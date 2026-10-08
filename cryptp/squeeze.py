"""Intraday squeeze-breakout (docs/SQUEEZE_PROPOSAL.md, frozen pre-registration).

Squeeze = Bollinger Bands (20, 2 sigma) fully inside Keltner Channels (SMA20 +/- 1.5 x SMA20(true range)), the public TTM/LazyBear
formulation, implemented independently from the formula. Trade the first close outside the squeeze box, with momentum and volume
agreeing, stop at the box midpoint, single +5R target, flat by 00:00 UTC. Signals use only data up to the trigger bar; fills are at
the next bar's open.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .backtest import Result, Trade


@dataclass
class SqueezeParams:
    min_squeeze_bars: int = 6
    window_bars: int = 4
    vol_mult: float = 1.5               # 0 disables the volume filter
    use_momentum: bool = True
    cutoff_hour: int = 20               # no triggers on bars opening at or after this UTC hour
    min_stop_pct: float = 0.45
    max_stop_pct: float = 3.0
    stop_mode: str = "mid"              # "mid" (box midpoint) | "far" (opposite side of the box)
    rr: float = 5.0
    risk_pct: float = 1.0
    max_leverage: float = 3.0
    flat_at_midnight: bool = True


def squeeze_features(df: pd.DataFrame):
    """(squeeze_on, momentum) as numpy arrays, aligned to df."""
    h, l, c = df["high"].astype(float), df["low"].astype(float), df["close"].astype(float)
    basis = c.rolling(20).mean()
    dev = 2.0 * c.rolling(20).std(ddof=0)
    prev = c.shift()
    tr = pd.concat([h - l, (h - prev).abs(), (l - prev).abs()], axis=1).max(axis=1)
    kc = 1.5 * tr.rolling(20).mean()
    on = ((basis - dev) > (basis - kc)) & ((basis + dev) < (basis + kc))
    mid = (h.rolling(20).max() + l.rolling(20).min()) / 2
    src = (c - (mid + basis) / 2).to_numpy()
    n = 20
    x = np.arange(n) - (n - 1) / 2.0
    sxx = (x ** 2).sum()
    win = np.lib.stride_tricks.sliding_window_view(np.nan_to_num(src), n)
    slope = (win * x).sum(axis=1) / sxx
    last = win.mean(axis=1) + slope * ((n - 1) - (n - 1) / 2.0)             # regression value at the newest bar
    mom = np.full(len(src), np.nan)
    mom[n - 1:] = last
    mom[np.isnan(src.astype(float))] = np.nan
    first_valid = int(np.argmax(~np.isnan(src))) if (~np.isnan(src)).any() else len(src)
    mom[: first_valid + n - 1] = np.nan                                      # need a full window of real values
    return on.fillna(False).to_numpy(), mom


def find_signals(df: pd.DataFrame, p: SqueezeParams):
    """{trigger_bar: (direction, box_high, box_low)}. Uses only bars up to the trigger bar."""
    h, l, c, v = (df[k].to_numpy(float) for k in ("high", "low", "close", "volume"))
    on, mom = squeeze_features(df)
    vsma = df["volume"].rolling(20).mean().to_numpy()
    hours = df["ts"].dt.hour.to_numpy()
    n = len(df)
    sig: dict[int, tuple[int, float, float]] = {}
    i = 0
    while i < n:
        if not on[i]:
            i += 1
            continue
        j = i
        while j < n and on[j]:
            j += 1
        a, b = i, j                                              # squeeze bars a..b-1; release bar is b
        i = j
        if b - a < p.min_squeeze_bars or b >= n:
            continue
        bh, bl = h[a:b].max(), l[a:b].min()
        for k in range(b, min(b + p.window_bars, n)):
            up, dn = c[k] > bh, c[k] < bl
            if not (up or dn):
                continue
            ok = hours[k] < p.cutoff_hour
            if p.use_momentum:
                ok = ok and not np.isnan(mom[k]) and ((mom[k] > 0) if up else (mom[k] < 0))
            if p.vol_mult:
                ok = ok and not np.isnan(vsma[k]) and v[k] >= p.vol_mult * vsma[k]
            if ok:
                sig[k] = (1 if up else -1, bh, bl)
            break                                                # the first close outside the box ends the setup
    return sig


def run_squeeze(df: pd.DataFrame, symbol: str, p: SqueezeParams | None = None, fee_rate: float = 0.00055,
                slippage_bps: float = 2.0, equity0: float = 1000.0) -> Result:
    p = p or SqueezeParams()
    df = df.reset_index(drop=True)
    n, slip = len(df), slippage_bps / 10_000
    O, H, L, C = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    ts = df["ts"]
    midnight = ((ts.dt.hour == 0) & (ts.dt.minute == 0)).to_numpy()
    sig = find_signals(df, p)
    equity = equity0
    pos, qty, entry_px, stop, target, entry_i, risk_usd, fee_in = 0, 0.0, 0.0, 0.0, 0.0, 0, 0.0, 0.0
    pending = None
    res = Result(symbol, equity0, bars=n)
    curve = np.empty(n)

    def close_trade(i: int, px: float):
        nonlocal equity, pos, qty
        gross = (px - entry_px) * qty * pos
        fee_out = px * qty * fee_rate
        equity += gross - fee_out
        res.trades.append(Trade(symbol, ts.iloc[entry_i], ts.iloc[i], entry_px, stop, -fee_in + gross - fee_out, risk_usd,
                                i - entry_i, "buy" if pos > 0 else "sell"))
        pos, qty = 0, 0.0

    for i in range(n):
        # 1. fill the order decided at the previous close, at this open
        if pending is not None and pos == 0:
            d, st = pending
            fill = O[i] * (1 + d * slip)
            risk = d * (fill - st)
            if risk > 0:
                dist = risk
                q = min(equity * p.risk_pct / 100.0 / dist, equity * p.max_leverage / fill)
                if q > 0:
                    qty, pos, entry_px, stop, entry_i, risk_usd = q, d, fill, st, i, q * dist
                    target = fill + d * p.rr * dist
                    fee_in = fill * q * fee_rate
                    equity -= fee_in
        pending = None
        # 2. exits: 00:00 UTC time exit at the open, else stop (first) / target during the bar
        if pos != 0:
            if p.flat_at_midnight and midnight[i] and i > entry_i:
                close_trade(i, O[i] * (1 - pos * slip))
            else:
                hit_stop = L[i] <= stop if pos > 0 else H[i] >= stop
                hit_tp = H[i] >= target if pos > 0 else L[i] <= target
                if hit_stop:
                    px = (min(stop, O[i]) if pos > 0 else max(stop, O[i])) * (1 - pos * slip)
                    close_trade(i, px)
                elif hit_tp:
                    close_trade(i, target)
        curve[i] = equity + ((C[i] - entry_px) * qty * pos if pos else 0.0)
        # 3. a trigger at this bar's close becomes an order for the next open (only when flat)
        if pos == 0 and i in sig and i + 1 < n:
            d, bh, bl = sig[i]
            mid = (bh + bl) / 2.0
            st = mid if p.stop_mode == "mid" else (bl if d > 0 else bh)
            dist_pct = abs(C[i] - st) / C[i] * 100.0
            if (d > 0 and st < C[i] or d < 0 and st > C[i]) and p.min_stop_pct <= dist_pct <= p.max_stop_pct:
                pending = (d, st)

    if pos != 0:                                                  # mark an open trade at the last close
        close_trade(n - 1, C[-1])
    res.equity = pd.Series(curve, index=ts)
    res.buy_hold_pct = (C[-1] / C[0] - 1) * 100
    return res
