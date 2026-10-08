# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Python port of the logic of the "Liquidity Sweep Reversal Strategy" TradingView script (Pine v6, MPL 2.0).
# Only the trading logic is ported (no drawing). See docs/SWEEP_PREREG.md for the deliberate differences.
"""Liquidity sweep reversal: fade a wick through a swing high/low that closes back inside, with filters.

Signals are computed at bar close; entries fill at the next bar's open. If a bar reaches both stop and
target the stop is assumed first. Costs follow the project standard (fee per side + slippage on market/stop fills).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .backtest import Result, Trade
from .indicators import atr as atr_series


@dataclass
class SweepParams:
    pivot_len: int = 7
    max_age: int = 150
    min_gap_atr: float = 0.25
    sl_atr: float = 1.2
    min_risk_atr: float = 0.5
    rr: float = 1.5
    use_be: bool = True
    be_pct: float = 50.0
    allow_long: bool = True
    allow_short: bool = True
    use_vol: bool = True
    vol_mult: float = 1.3
    use_wick: bool = True
    min_wick_ratio: float = 1.5
    use_confirm: bool = True
    use_session: bool = True
    sess_start_min: int = 12 * 60          # 12:00 UTC
    sess_end_min: int = 16 * 60            # 16:00 UTC (exclusive)
    size_pct: float = 10.0                 # % of equity per trade (notional), used when risk_pct is None
    risk_pct: float | None = None          # if set: risk this % of equity per trade (stop distance sets the size)
    max_leverage: float = 3.0              # notional cap when sizing by risk


def _pivots(df: pd.DataFrame, n: int):
    """Confirmed pivots, flagged on the bar that confirms them (n bars after the pivot bar).
    High: strictly above the n bars on the left, >= the n bars on the right; mirrored for lows."""
    h, l = df["high"].astype(float), df["low"].astype(float)
    ph = (h.shift(n) > h.shift(n + 1).rolling(n).max()) & (h.shift(n) >= h.rolling(n).max())
    pl = (l.shift(n) < l.shift(n + 1).rolling(n).min()) & (l.shift(n) <= l.rolling(n).min())
    return ph.fillna(False).to_numpy(), pl.fillna(False).to_numpy()


def run_sweep(df: pd.DataFrame, symbol: str, p: SweepParams | None = None, fee_rate: float = 0.00055,
              slippage_bps: float = 2.0, equity0: float = 1000.0) -> Result:
    p = p or SweepParams()
    df = df.reset_index(drop=True)
    n, slip = len(df), slippage_bps / 10_000
    O, H, L, C = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    V = df["volume"].to_numpy(float)
    ATR = atr_series(df, 14).to_numpy(float)
    VSMA = df["volume"].rolling(20).mean().to_numpy(float)
    piv_h, piv_l = _pivots(df, p.pivot_len)
    mins = (df["ts"].dt.hour * 60 + df["ts"].dt.minute).to_numpy()
    in_sess = (mins >= p.sess_start_min) & (mins < p.sess_end_min)
    R = p.pivot_len
    warm = max(20, 2 * R + 2)

    highs: list[list[float]] = []          # [price, bar]
    lows: list[list[float]] = []
    pend_long = pend_short = False
    pend_wick = pend_mid = np.nan
    pending = None                          # (dir, sl, tp, close_at_signal) decided at last close, fills at next open
    pos, qty, entry_px, stop, target, entry_i, risk_usd, init_stop = 0, 0.0, 0.0, 0.0, 0.0, 0, 0.0, 0.0
    realized, active_entry, be_done, stop_next = 0.0, np.nan, False, None
    equity = equity0
    res = Result(symbol, equity0, bars=n)
    curve = np.empty(n)

    def too_close(arr, px, a):
        return any(abs(lv[0] - px) < a * p.min_gap_atr for lv in arr)

    for i in range(n):
        # 1. a breakeven stop decided at the previous close takes effect now
        if pos != 0 and stop_next is not None:
            stop, stop_next = stop_next, None
        # 2. fill the order decided at the previous close, at this open
        if pending is not None and pos == 0:
            d, sl, tp, ec = pending
            fill = O[i] * (1 + d * slip)
            if p.risk_pct is not None:
                dist = abs(fill - sl)
                qty = min(equity * p.risk_pct / 100.0 / dist if dist > 0 else 0.0, equity * p.max_leverage / fill)
            else:
                qty = equity * p.size_pct / 100.0 / fill
            fee_in = fill * qty * fee_rate
            equity -= fee_in
            pos, entry_px, stop, target, entry_i = d, fill, sl, tp, i
            init_stop, risk_usd, realized = sl, qty * abs(fill - sl), -fee_in
            active_entry, be_done, stop_next = ec, False, None
        pending = None
        # 3. exits during this bar (stop first if both are reachable)
        if pos != 0:
            d = pos
            hit_stop = L[i] <= stop if d > 0 else H[i] >= stop
            hit_tp = H[i] >= target if d > 0 else L[i] <= target
            px = None
            if hit_stop:
                px = (min(stop, O[i]) if d > 0 else max(stop, O[i])) * (1 - d * slip)
            elif hit_tp:
                px = target
            if px is not None:
                gross = (px - entry_px) * qty * d
                fee_out = px * qty * fee_rate
                equity += gross - fee_out
                res.trades.append(Trade(symbol, df["ts"].iloc[entry_i], df["ts"].iloc[i], entry_px, init_stop,
                                        realized + gross - fee_out, risk_usd, i - entry_i,
                                        "buy" if d > 0 else "sell"))
                pos, qty = 0, 0.0
        curve[i] = equity + ((C[i] - entry_px) * qty * pos if pos else 0.0)

        if i < warm or np.isnan(ATR[i]) or np.isnan(VSMA[i]):
            continue
        a = ATR[i]

        # 4. new swing levels (confirmed R bars after the pivot)
        if piv_h[i]:
            px = H[i - R]
            if not too_close(highs, px, a):
                highs.append([px, i - R])
        if piv_l[i]:
            px = L[i - R]
            if not too_close(lows, px, a):
                lows.append([px, i - R])

        body = abs(C[i] - O[i])
        vol_ok = (not p.use_vol) or V[i] > VSMA[i] * p.vol_mult
        sweep_high = sweep_low = False
        sweep_high_wick = sweep_low_wick = np.nan
        k = 0
        while k < len(highs):
            lv = highs[k]
            wick_sz = H[i] - max(C[i], O[i])
            wick_ok = (not p.use_wick) or (body > 0 and wick_sz / body >= p.min_wick_ratio) or (body == 0 and wick_sz > 0)
            if H[i] > lv[0] and C[i] < lv[0] and vol_ok and wick_ok:
                sweep_high, sweep_high_wick = True, H[i]
                highs.pop(k)
            elif i - lv[1] > p.max_age:
                highs.pop(k)
            else:
                k += 1
        k = 0
        while k < len(lows):
            lv = lows[k]
            wick_sz = min(C[i], O[i]) - L[i]
            wick_ok = (not p.use_wick) or (body > 0 and wick_sz / body >= p.min_wick_ratio) or (body == 0 and wick_sz > 0)
            if L[i] < lv[0] and C[i] > lv[0] and vol_ok and wick_ok:
                sweep_low, sweep_low_wick = True, L[i]
                lows.pop(k)
            elif i - lv[1] > p.max_age:
                lows.pop(k)
            else:
                k += 1

        # 5. entry decision (only when flat), exactly as the script orders it
        do_long = do_short = False
        wick_lvl = np.nan
        sess_ok = (not p.use_session) or bool(in_sess[i])
        if pos == 0:
            if p.use_confirm:
                if pend_long and C[i] > pend_mid and p.allow_long and sess_ok:
                    do_long, wick_lvl = True, pend_wick
                if pend_short and C[i] < pend_mid and p.allow_short and sess_ok:
                    do_short, wick_lvl = True, pend_wick
                pend_long = pend_short = False
                if sweep_low:
                    pend_long, pend_wick, pend_mid = True, sweep_low_wick, (sweep_low_wick + C[i]) / 2
                if sweep_high:
                    pend_short, pend_wick, pend_mid = True, sweep_high_wick, (sweep_high_wick + C[i]) / 2
            else:
                if sweep_low and p.allow_long and sess_ok:
                    do_long, wick_lvl = True, sweep_low_wick
                if sweep_high and p.allow_short and sess_ok:
                    do_short, wick_lvl = True, sweep_high_wick
        if do_long or do_short:
            is_long = do_long
            sl = wick_lvl - a * p.sl_atr if is_long else wick_lvl + a * p.sl_atr
            risk = C[i] - sl if is_long else sl - C[i]
            if risk >= a * p.min_risk_atr and i + 1 < n:
                tp = C[i] + risk * p.rr if is_long else C[i] - risk * p.rr
                pending = (1 if is_long else -1, sl, tp, C[i])

        # 6. breakeven: once price covers be_pct of the way to target, the stop moves to the signal close
        if pos != 0 and p.use_be and not be_done and not np.isnan(active_entry):
            if pos > 0:
                trig = active_entry + (target - active_entry) * p.be_pct / 100.0
                hit = H[i] >= trig
            else:
                trig = active_entry - (active_entry - target) * p.be_pct / 100.0
                hit = L[i] <= trig
            if hit:
                stop_next, be_done = active_entry, True

    if pos != 0:                                                     # mark an open trade at the last close
        gross = (C[-1] - entry_px) * qty * pos
        res.trades.append(Trade(symbol, df["ts"].iloc[entry_i], df["ts"].iloc[-1], entry_px, init_stop,
                                realized + gross - C[-1] * qty * fee_rate, risk_usd, n - 1 - entry_i,
                                "buy" if pos > 0 else "sell"))
    res.equity = pd.Series(curve, index=df["ts"])
    res.buy_hold_pct = (C[-1] / C[min(warm, n - 1)] - 1) * 100
    return res
