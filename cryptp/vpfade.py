"""Volume-profile fade (A) and discount + pressure entries (B), as pre-registered in docs/MB_FADE_PREREG.md.

The profile is built from the trailing `window` bars that END BEFORE the signal bar, so a signal bar never sees its own volume.
Signals are computed at bar close; entries fill at the next bar's open. If a bar reaches both stop and target the stop is
assumed first. Costs follow the project standard (fee per side + slippage on market and stop fills).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .backtest import Result, Trade
from .indicators import atr as atr_series


@dataclass
class VPParams:
    mode: str = "fade"                 # "fade" (A) or "discount" (B)
    window: int = 96                   # bars in the profile (24h of 15m)
    rows: int = 100                    # price rows in the profile
    va_pct: float = 0.70               # value area share of volume
    ext_atr: float = 0.25              # A: how far beyond VAH/VAL the bar must poke, in ATR
    wick_frac: float = 0.40            # A: rejection wick as a fraction of the bar range
    body_frac: float = 0.50            # B: pressure candle body as a fraction of range
    close_frac: float = 0.30           # B: pressure candle closes in the outer 30% of its range
    vol_mult: float = 1.0              # B: pressure candle volume > vol_mult * 20-bar average
    zone_frac: float = 0.25            # B1: low must reach the outer 25% of the discount (premium) zone
    reclaim_back: int = 12             # B2: a close on the other side of the POC within this many bars
    retest_bars: int = 12              # B2: retest must come within this many bars of the reclaim
    sl_buf_atr: float = 0.1
    min_stop_pct: float = 0.0          # stop is widened (never tightened) to at least this % from the signal close; 0 = off
    a_vol_mult: float = 0.0            # A: signal-bar volume must exceed this x its 20-bar average; 0 = off
    min_rr: float | None = None        # None = 1.5 for "fade", 2.0 for "discount"
    max_hold: int = 96                 # bars; exit at the close if neither stop nor target is hit
    allow_long: bool = True
    allow_short: bool = True
    risk_pct: float = 1.0              # % of equity risked per trade (stop distance sets the size)
    max_leverage: float = 3.0          # notional cap
    macro: bool = False                # "+F": trade only with the BTC / coin-vs-BTC bias
    macro_len: int = 672               # 7 days of 15m bars


def volume_profile(h, l, v, rows: int = 100, va_pct: float = 0.70):
    """(poc, vah, val) of the bars, or None. Each bar's volume is spread uniformly over the rows its high-low covers."""
    h, l, v = np.asarray(h, float), np.asarray(l, float), np.asarray(v, float)
    lo, hi = float(l.min()), float(h.max())
    if not hi > lo:
        return None
    edges = np.linspace(lo, hi, rows + 1)
    bl, bh = edges[:-1], edges[1:]
    rng = h - l
    prof = np.zeros(rows)
    wide = rng > 0
    if wide.any():
        ov = np.clip(np.minimum(h[wide, None], bh[None, :]) - np.maximum(l[wide, None], bl[None, :]), 0.0, None)
        prof += (ov / rng[wide, None] * v[wide, None]).sum(axis=0)
    if (~wide).any():                                         # zero-range bars land in the row containing the price
        idx = np.clip(np.searchsorted(edges, l[~wide], side="right") - 1, 0, rows - 1)
        np.add.at(prof, idx, v[~wide])
    tot = prof.sum()
    if tot <= 0:
        return None
    p = int(np.argmax(prof))
    lo_i = hi_i = p
    acc, target = prof[p], va_pct * tot
    while acc < target and (lo_i > 0 or hi_i < rows - 1):
        up = (prof[hi_i + 1] + (prof[hi_i + 2] if hi_i + 2 < rows else 0.0)) if hi_i < rows - 1 else -1.0
        dn = (prof[lo_i - 1] + (prof[lo_i - 2] if lo_i - 2 >= 0 else 0.0)) if lo_i > 0 else -1.0
        if up >= dn:
            new_hi = min(hi_i + 2, rows - 1)
            acc += prof[hi_i + 1:new_hi + 1].sum()
            hi_i = new_hi
        else:
            new_lo = max(lo_i - 2, 0)
            acc += prof[new_lo:lo_i].sum()
            lo_i = new_lo
    return float((edges[p] + edges[p + 1]) / 2), float(edges[hi_i + 1]), float(edges[lo_i])


def macro_bias(close, btc_close, n: int):
    """(bias_up, bias_down) boolean arrays. Up: BTC above its n-bar EMA AND coin/BTC above its own EMA. Causal."""
    c = pd.Series(np.asarray(close, float))
    b = pd.Series(np.asarray(btc_close, float))
    ratio = c / b
    eb, er = b.ewm(span=n, adjust=False).mean(), ratio.ewm(span=n, adjust=False).mean()
    up = ((b > eb) & (ratio > er)).to_numpy().copy()
    dn = ((b < eb) & (ratio < er)).to_numpy().copy()
    up[:n], dn[:n] = False, False                               # EMA still warming up
    return up, dn


def run_vpfade(df: pd.DataFrame, symbol: str, p: VPParams | None = None, fee_rate: float = 0.00055,
               slippage_bps: float = 2.0, equity0: float = 1000.0, btc_close=None) -> Result:
    p = p or VPParams()
    min_rr = p.min_rr if p.min_rr is not None else (1.5 if p.mode == "fade" else 2.0)
    df = df.reset_index(drop=True)
    n, slip = len(df), slippage_bps / 10_000
    O, H, L, C = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    V = df["volume"].to_numpy(float)
    ATR = atr_series(df, 14).to_numpy(float)
    VSMA = df["volume"].rolling(20).mean().to_numpy(float)
    W, buf = p.window, p.sl_buf_atr
    warm = max(W + 1, 21, p.reclaim_back + 1)
    if p.macro:
        if btc_close is None or len(btc_close) != n:
            raise ValueError("macro filter needs btc_close aligned to df")
        bias_up, bias_dn = macro_bias(C, btc_close, p.macro_len)
        warm = max(warm, p.macro_len)

    pos, qty, entry_px, stop, target, entry_i, risk_usd, init_stop = 0, 0.0, 0.0, 0.0, 0.0, 0, 0.0, 0.0
    realized = 0.0
    equity = equity0
    pending = None                       # (dir, stop, target) decided at the last close, fills at this open
    r_long = r_short = None              # B2 state: (frozen POC level, last bar of the retest window)
    res = Result(symbol, equity0, bars=n)
    curve = np.empty(n)

    def widen(side, a_stop, close):
        floor = close * p.min_stop_pct / 100.0
        return min(a_stop, close - floor) if side > 0 else max(a_stop, close + floor)

    def gate(side, a_stop, a_target, close):
        risk = (close - a_stop) if side > 0 else (a_stop - close)
        reward = (a_target - close) if side > 0 else (close - a_target)
        return risk > 0 and reward >= min_rr * risk

    for i in range(n):
        # 1. fill the order decided at the previous close, at this open
        if pending is not None and pos == 0:
            d, sl, tp = pending
            fill = O[i] * (1 + d * slip)
            dist = abs(fill - sl)
            qty = min(equity * p.risk_pct / 100.0 / dist if dist > 0 else 0.0, equity * p.max_leverage / fill)
            if qty > 0:
                fee_in = fill * qty * fee_rate
                equity -= fee_in
                pos, entry_px, stop, target, entry_i = d, fill, sl, tp, i
                init_stop, risk_usd, realized = sl, qty * dist, -fee_in
        pending = None
        # 2. exits during this bar (stop first if both are reachable; time stop at the close)
        if pos != 0:
            d = pos
            hit_stop = L[i] <= stop if d > 0 else H[i] >= stop
            hit_tp = H[i] >= target if d > 0 else L[i] <= target
            px = None
            if hit_stop:
                px = (min(stop, O[i]) if d > 0 else max(stop, O[i])) * (1 - d * slip)
            elif hit_tp:
                px = target
            elif i - entry_i >= p.max_hold:
                px = C[i] * (1 - d * slip)
            if px is not None:
                gross = (px - entry_px) * qty * d
                fee_out = px * qty * fee_rate
                equity += gross - fee_out
                res.trades.append(Trade(symbol, df["ts"].iloc[entry_i], df["ts"].iloc[i], entry_px, init_stop,
                                        realized + gross - fee_out, risk_usd, i - entry_i,
                                        "buy" if d > 0 else "sell"))
                pos, qty = 0, 0.0
        curve[i] = equity + ((C[i] - entry_px) * qty * pos if pos else 0.0)

        if i < warm or np.isnan(ATR[i]) or np.isnan(VSMA[i]) or i + 1 >= n or pos != 0:
            continue
        a, rng = ATR[i], H[i] - L[i]
        up_ok = p.allow_long and (not p.macro or bool(bias_up[i]))
        dn_ok = p.allow_short and (not p.macro or bool(bias_dn[i]))
        cands: list[tuple[int, float, float]] = []

        if p.mode == "fade":
            if rng > 0:
                upper, lower = H[i] - max(O[i], C[i]), min(O[i], C[i]) - L[i]
                s_c, l_c = upper >= p.wick_frac * rng, lower >= p.wick_frac * rng
                if s_c or l_c:                                  # necessary condition, so the profile is built only when needed
                    lv = volume_profile(H[i - W:i], L[i - W:i], V[i - W:i], p.rows, p.va_pct)
                    if lv:
                        poc, vah, val = lv
                        vol_a = p.a_vol_mult <= 0 or V[i] > p.a_vol_mult * VSMA[i]
                        if dn_ok and vol_a and s_c and H[i] > vah + p.ext_atr * a and C[i] < vah:
                            sl = widen(-1, H[i] + buf * a, C[i])
                            if gate(-1, sl, poc, C[i]):
                                cands.append((-1, sl, poc))
                        if up_ok and vol_a and l_c and L[i] < val - p.ext_atr * a and C[i] > val:
                            sl = widen(1, L[i] - buf * a, C[i])
                            if gate(1, sl, poc, C[i]):
                                cands.append((1, sl, poc))
        else:
            lv = volume_profile(H[i - W:i], L[i - W:i], V[i - W:i], p.rows, p.va_pct)
            if lv and rng > 0:
                poc, vah, val = lv
                vol_ok = V[i] > p.vol_mult * VSMA[i]
                bull = C[i] > O[i] and (C[i] - O[i]) >= p.body_frac * rng and (C[i] - L[i]) >= (1 - p.close_frac) * rng and vol_ok
                bear = C[i] < O[i] and (O[i] - C[i]) >= p.body_frac * rng and (H[i] - C[i]) >= (1 - p.close_frac) * rng and vol_ok
                # B2: retests of a reclaimed POC (checked against state set on EARLIER bars, then state is refreshed)
                if r_long is not None:
                    lvl, exp = r_long
                    if i > exp or C[i] < lvl - buf * a:
                        r_long = None
                    elif bull and L[i] <= lvl + buf * a and C[i] > lvl:
                        sl = widen(1, min(lvl, L[i]) - buf * a, C[i])
                        if up_ok and gate(1, sl, vah, C[i]):
                            cands.append((1, sl, vah))
                        r_long = None
                if r_short is not None:
                    lvl, exp = r_short
                    if i > exp or C[i] > lvl + buf * a:
                        r_short = None
                    elif bear and H[i] >= lvl - buf * a and C[i] < lvl:
                        sl = widen(-1, max(lvl, H[i]) + buf * a, C[i])
                        if dn_ok and gate(-1, sl, val, C[i]):
                            cands.append((-1, sl, val))
                        r_short = None
                if C[i] > poc and C[i - 1] <= poc and C[i - p.reclaim_back:i].min() < poc:
                    r_long = (poc, i + p.retest_bars)
                if C[i] < poc and C[i - 1] >= poc and C[i - p.reclaim_back:i].max() > poc:
                    r_short = (poc, i + p.retest_bars)
                # B1: pressure candle inside the discount (premium) zone, reaching its outer quarter
                if bull and val < C[i] < poc and L[i] <= val + p.zone_frac * (poc - val):
                    sl = widen(1, min(val, L[i]) - buf * a, C[i])
                    if up_ok and gate(1, sl, vah, C[i]):
                        cands.append((1, sl, vah))
                if bear and poc < C[i] < vah and H[i] >= vah - p.zone_frac * (vah - poc):
                    sl = widen(-1, max(vah, H[i]) + buf * a, C[i])
                    if dn_ok and gate(-1, sl, val, C[i]):
                        cands.append((-1, sl, val))

        sides = {c[0] for c in cands}
        if len(sides) == 1:
            pending = cands[0]

    if pos != 0:                                                     # mark an open trade at the last close
        gross = (C[-1] - entry_px) * qty * pos
        res.trades.append(Trade(symbol, df["ts"].iloc[entry_i], df["ts"].iloc[-1], entry_px, init_stop,
                                realized + gross - C[-1] * qty * fee_rate, risk_usd, n - 1 - entry_i,
                                "buy" if pos > 0 else "sell"))
    res.equity = pd.Series(curve, index=df["ts"])
    res.buy_hold_pct = (C[-1] / C[min(warm, n - 1)] - 1) * 100
    return res
