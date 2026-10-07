"""SUI own-drop bounce with a run-the-winner exit (docs/BOUNCE_PREREG.md, frozen pre-registration).

Signal: the 4-bar (1h) return falls to its causal 5th percentile (previous 30 days, current bar excluded), edge-triggered, long only.
Exit: no profit-taking before +3R; after +3R the stop locks +1.5R and then trails 2.5 x ATR below the highest high (each stop change
takes effect on the NEXT bar); forced flat at the close of the UTC day. Fills at the next bar's open. Funding is charged at the 08:00 and
16:00 UTC settlements a trade is open through.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .backtest import Result, Trade
from .indicators import atr


@dataclass
class BounceParams:
    drop_bars: int = 4
    quantile: float = 0.05
    lookback_bars: int = 2880
    stop_bars: int = 4
    stop_atr: float = 0.1
    min_stop_pct: float = 0.45
    max_stop_pct: float = 3.0
    arm_r: float = 3.0
    lock_r: float = 1.5
    trail_atr: float = 2.5
    exit_mode: str = "trail"            # "trail" (frozen rule) | "fixed3" (control: fixed +3R target, no trail)
    cutoff_hour: int = 20
    risk_pct: float = 1.0
    max_leverage: float = 3.0
    cooldown_bars: int = 8
    max_trades_day: int = 3
    default_funding: float = 0.0001


def find_signals(df: pd.DataFrame, p: BounceParams) -> np.ndarray:
    """Boolean array: True at bars where the (edge-triggered) drop signal fires. Uses only bars <= t."""
    c = df["close"].astype(float)
    r = np.log(c / c.shift(p.drop_bars))
    thr = r.shift(1).rolling(p.lookback_bars).quantile(p.quantile)       # previous bars only
    on = (r <= thr).fillna(False)
    return (on & ~on.shift(fill_value=False)).to_numpy()


def stop_price(df: pd.DataFrame, p: BounceParams, a: pd.Series) -> np.ndarray:
    return (df["low"].rolling(p.stop_bars).min() - p.stop_atr * a).to_numpy()


def funding_rates(df: pd.DataFrame, funding: pd.DataFrame | None, default: float) -> np.ndarray:
    """Latest known funding rate at or before each bar (default where none)."""
    if funding is None or not len(funding):
        return np.full(len(df), default)
    f = funding.sort_values("ts")[["ts", "rate"]].copy()
    f["ts"] = pd.to_datetime(f["ts"], utc=True).astype(df["ts"].dtype)
    m = pd.merge_asof(df[["ts"]], f, on="ts")
    return m["rate"].fillna(default).to_numpy(float)


def run_bounce(df: pd.DataFrame, symbol: str, p: BounceParams | None = None, fee_rate: float = 0.00055,
               slippage_bps: float = 2.0, equity0: float = 1000.0, funding: pd.DataFrame | None = None,
               charge_funding: bool = True, start_i: int = 0, end_i: int | None = None,
               signals: dict | None = None) -> Result:
    """Simulate bars start_i..end_i-1 (indicators may read earlier bars). `signals` {bar: stop} overrides the signal (tests/controls)."""
    p = p or BounceParams()
    df = df.reset_index(drop=True)
    n = len(df)
    end_i = n if end_i is None else end_i
    slip = slippage_bps / 10_000
    O, H, L, C = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    A = atr(df)
    a_np = A.to_numpy(float)
    ts = df["ts"]
    day = ts.dt.strftime("%Y-%m-%d").to_numpy()
    hours, mins = ts.dt.hour.to_numpy(), ts.dt.minute.to_numpy()
    frate = funding_rates(df, funding, p.default_funding)
    if signals is None:
        sig_bar = find_signals(df, p)
        stops = stop_price(df, p, A)
        signals = {int(i): float(stops[i]) for i in np.flatnonzero(sig_bar) if not np.isnan(stops[i])}

    equity = equity0
    pos = False
    qty = entry_px = stop = next_stop = risk_unit = risk_usd = fee_in = fund_paid = hh = 0.0
    armed = False
    entry_i = 0
    cool = -1
    pending = None
    trades_today, cur_day = 0, None
    res = Result(symbol, equity0, bars=end_i - start_i)
    res.funding_paid, res.midnight_cut_above_1r, res.armed_trades = 0.0, 0, 0
    curve = np.full(n, np.nan)

    def close_trade(i: int, px: float, midnight: bool = False):
        nonlocal equity, pos, qty, cool
        gross = (px - entry_px) * qty
        fee_out = px * qty * fee_rate
        equity += gross - fee_out
        pnl = -fee_in + gross - fee_out - fund_paid
        res.trades.append(Trade(symbol, ts.iloc[entry_i], ts.iloc[i], entry_px, init_stop, pnl, risk_usd, i - entry_i, "buy"))
        res.funding_paid += fund_paid
        res.armed_trades += int(armed)
        if midnight and (px - entry_px) / risk_unit > 1.0:
            res.midnight_cut_above_1r += 1
        pos, qty, cool = False, 0.0, i + p.cooldown_bars

    init_stop = 0.0
    for i in range(start_i, end_i):
        if day[i] != cur_day:
            cur_day, trades_today = day[i], 0
        if pending is not None and not pos:
            st = pending
            fill = O[i] * (1 + slip)
            ru = fill - st
            if ru > 0 and hours[i] < p.cutoff_hour:
                q = min(equity * p.risk_pct / 100.0 / ru, equity * p.max_leverage / fill)
                if q > 0:
                    pos, qty, entry_px, stop, init_stop, next_stop, entry_i = True, q, fill, st, st, st, i
                    risk_unit, risk_usd, armed, hh, fund_paid = ru, q * ru, False, fill, 0.0
                    fee_in = fill * q * fee_rate
                    equity -= fee_in
                    trades_today += 1
        pending = None
        if pos:
            if charge_funding and mins[i] == 0 and hours[i] in (8, 16) and entry_i < i:
                f = qty * O[i] * frate[i]
                fund_paid += f
                equity -= f
            last_bar = i + 1 >= end_i or day[i + 1] != day[i]
            if L[i] <= stop:                                              # (a) stop, gap-aware
                close_trade(i, min(stop, O[i]) * (1 - slip))
            elif p.exit_mode == "fixed3" and H[i] >= entry_px + p.arm_r * risk_unit:
                close_trade(i, entry_px + p.arm_r * risk_unit)
            else:
                if p.exit_mode == "trail":
                    if not armed and H[i] >= entry_px + p.arm_r * risk_unit:   # (b) arm: lock takes effect next bar
                        armed = True
                        next_stop = max(next_stop, entry_px + p.lock_r * risk_unit)
                    hh = max(hh, H[i])
                    if armed and not np.isnan(a_np[i]):                       # (c) trail from this close, effective next bar
                        next_stop = max(next_stop, hh - p.trail_atr * a_np[i])
                    stop = next_stop
                if last_bar:                                                  # (d) flat at the day's last close
                    close_trade(i, C[i] * (1 - slip), midnight=True)
        curve[i] = equity + ((C[i] - entry_px) * qty if pos else 0.0)
        if (not pos and i in signals and i + 1 < end_i and i > cool and trades_today < p.max_trades_day
                and hours[i + 1] < p.cutoff_hour):
            st = signals[i]
            dist = (C[i] - st) / C[i] * 100.0
            if st < C[i] and p.min_stop_pct <= dist <= p.max_stop_pct:
                pending = st
    if pos:                                                                   # segment ended with an open trade
        close_trade(end_i - 1, C[end_i - 1] * (1 - slip))
    res.equity = pd.Series(curve[start_i:end_i], index=ts.iloc[start_i:end_i])
    res.buy_hold_pct = (C[end_i - 1] / C[start_i] - 1) * 100
    return res
