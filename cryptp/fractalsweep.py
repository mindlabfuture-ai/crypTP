"""Fractal stop-hunt long strategy ("rownyel"), as pre-registered in docs/ROWNYEL_PREREG.md.

Buy the sweep of a confirmed Williams-fractal low: the bar wicks below the level and closes back above it in the upper half of its range.
Signals are computed at bar close, entries fill at the next bar's open, a bar that reaches both stop and target counts as the stop,
costs follow the project standard. A fractal is only used once it is confirmed (n bars after it), so nothing looks ahead.
`entry_bars` replaces the sweep signal with externally chosen entry bars (the random-entry control).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .backtest import Result, Trade
from .indicators import atr as atr_series


@dataclass
class FSParams:
    n: int = 2                        # Williams fractal: bars each side
    max_age: int = 100                # bars a fractal level stays active
    pen_atr: float = 0.1              # the wick must pierce the level by at least this x ATR
    sl_buf_atr: float = 0.1           # stop sits this x ATR below the wick low
    min_stop_pct: float = 2.0         # stop widened (never tightened) to at least this % below the signal close
    max_stop_pct: float = 15.0        # trade skipped if the stop would be further than this % below the signal close
    target_r: float = 5.0             # limit target at this multiple of the signal-close-to-stop distance
    be_at_r: float | None = None      # variant B: once the high reaches +this R, the stop moves to the entry price from the next bar
    max_hold: int = 480               # bars; exit at the close if neither stop nor target is hit
    control_lookback: int = 5         # control entries: stop under the lowest low of this many bars
    risk_pct: float = 1.0
    max_leverage: float = 3.0


def fractal_lows(low, n: int = 2) -> np.ndarray:
    """Bar j is a fractal low if its low is strictly below the n lows on each side. Needs bars up to j+n, so use it only from bar j+n+1 on."""
    L = np.asarray(low, float)
    N = len(L)
    out = np.zeros(N, bool)
    if N <= 2 * n:
        return out
    core = L[n:N - n]
    ok = np.ones(N - 2 * n, bool)
    for k in range(1, n + 1):
        ok &= core < L[n - k:N - n - k]
        ok &= core < L[n + k:N - n + k]
    out[n:N - n] = ok
    return out


def run_fractalsweep(df: pd.DataFrame, symbol: str, p: FSParams | None = None, fee_rate: float = 0.00055,
                     slippage_bps: float = 2.0, equity0: float = 1000.0, entry_bars=None) -> Result:
    p = p or FSParams()
    df = df.reset_index(drop=True)
    N, slip = len(df), slippage_bps / 10_000
    O, H, L, C = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    ATR = atr_series(df, 14).to_numpy(float)
    fl = fractal_lows(L, p.n)
    warm = max(30, 2 * p.n + 2, p.control_lookback)
    if entry_bars is not None and len(entry_bars) != N:
        raise ValueError("entry_bars must align with df")

    pos, qty, entry_px, stop, target, entry_i, risk_usd, init_stop = 0, 0.0, 0.0, 0.0, 0.0, 0, 0.0, 0.0
    realized, equity = 0.0, equity0
    be_trig, be_done, stop_next = None, False, None
    pending = None                         # (stop, target, be_trigger) decided at the last close, fills at this open
    active: list[list[float]] = []         # [level, fractal bar]
    res = Result(symbol, equity0, bars=N)
    curve = np.empty(N)

    for i in range(N):
        # 1. a break-even stop decided at the previous close takes effect now
        if pos != 0 and stop_next is not None:
            stop, stop_next = stop_next, None
        # 2. fill the order decided at the previous close, at this open
        if pending is not None and pos == 0:
            sl, tp, bt = pending
            fill = O[i] * (1 + slip)
            dist = fill - sl
            if dist > 0:
                qty = min(equity * p.risk_pct / 100.0 / dist, equity * p.max_leverage / fill)
                fee_in = fill * qty * fee_rate
                equity -= fee_in
                pos, entry_px, stop, target, entry_i = 1, fill, sl, tp, i
                init_stop, risk_usd, realized = sl, qty * dist, -fee_in
                be_trig, be_done, stop_next = bt, False, None
        pending = None
        # 3. exits during this bar (stop first if both are reachable; time stop at the close)
        if pos != 0:
            px = None
            if L[i] <= stop:
                px = min(stop, O[i]) * (1 - slip)
            elif H[i] >= target:
                px = target
            elif i - entry_i >= p.max_hold:
                px = C[i] * (1 - slip)
            if px is not None:
                gross = (px - entry_px) * qty
                fee_out = px * qty * fee_rate
                equity += gross - fee_out
                res.trades.append(Trade(symbol, df["ts"].iloc[entry_i], df["ts"].iloc[i], entry_px, init_stop,
                                        realized + gross - fee_out, risk_usd, i - entry_i, "buy"))
                pos, qty = 0, 0.0
            elif be_trig is not None and not be_done and H[i] >= be_trig:
                stop_next, be_done = entry_px, True
        curve[i] = equity + ((C[i] - entry_px) * qty if pos else 0.0)

        # 4. fractal state and signal at this close (state is updated on every bar; trades are only opened when flat)
        j = i - p.n - 1                                       # a fractal at bar j is confirmed at the close of bar j+n, usable from j+n+1
        if j >= p.n and fl[j]:
            active.append([L[j], j])
        if i < warm or np.isnan(ATR[i]) or i + 1 >= N:
            continue
        a, rng = ATR[i], H[i] - L[i]
        raw_stop = None
        if entry_bars is None:
            kept, best = [], None
            for lv in active:
                lvl, jj = lv
                if i - jj > p.max_age:
                    continue                                   # expired
                if L[i] < lvl:
                    if C[i] <= lvl:
                        continue                               # pierced without a close back above: a real breakdown, consumed
                    if rng > 0 and L[i] <= lvl - p.pen_atr * a and C[i] >= L[i] + 0.5 * rng:
                        if best is None or lvl > best:
                            best = lvl                         # qualifying sweep; the highest swept level is the one used
                        continue                               # a level is used up by its first qualifying sweep
                kept.append(lv)
            active = kept
            if best is not None:
                raw_stop = L[i] - p.sl_buf_atr * a
        elif entry_bars[i]:
            raw_stop = float(L[max(0, i - p.control_lookback + 1):i + 1].min()) - p.sl_buf_atr * a
        if raw_stop is None or pos != 0:
            continue
        sl = min(raw_stop, C[i] * (1 - p.min_stop_pct / 100.0))   # widen to the floor, never tighten
        if (C[i] - sl) / C[i] > p.max_stop_pct / 100.0 or sl >= C[i]:
            continue
        r_dist = C[i] - sl
        pending = (sl, C[i] + p.target_r * r_dist, C[i] + p.be_at_r * r_dist if p.be_at_r else None)

    if pos != 0:                                                     # mark an open trade at the last close
        gross = (C[-1] - entry_px) * qty
        res.trades.append(Trade(symbol, df["ts"].iloc[entry_i], df["ts"].iloc[-1], entry_px, init_stop,
                                realized + gross - C[-1] * qty * fee_rate, risk_usd, N - 1 - entry_i, "buy"))
    res.equity = pd.Series(curve, index=df["ts"])
    res.buy_hold_pct = (C[-1] / C[min(warm, N - 1)] - 1) * 100
    return res
