"""The SMC e-book's confirmed-entry model, as pre-registered in docs/EBOOK_CONFIRMED_PREREG.md.

HTF liquidity sweep (a fractal high/low taken and closed back inside) arms a setup; on 15m the setup then waits for a structure shift (CHoCH: a body close
beyond the most recent confirmed 15m fractal) and, for model M1, for the first pullback extreme after it (the inducement, IDM) to be swept and reclaimed.
Model C0 is the unconfirmed control: it enters at the first 15m open after the HTF sweep bar closes.
HTF bars are only used once complete; 15m fractals are used from the third bar after the pivot. Signals fill at the next 15m open; stop-first; project-standard costs.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .backtest import Result, Trade
from .fractalsweep import fractal_lows
from .indicators import atr as atr_series

TF_MIN = {"1h": 60, "4h": 240}
LTF_MIN = 15


@dataclass
class CParams:
    tf: str = "1h"                    # HTF
    model: str = "M2"                 # "M1" CHoCH with IDM, "M2" CHoCH without IDM, "C0" unconfirmed control
    n: int = 2                        # Williams fractal bars each side (HTF and 15m)
    max_age: int = 100                # HTF bars an HTF fractal level stays active
    pen_atr: float = 0.1
    sl_buf_atr: float = 0.1
    window_htf: int = 12              # HTF bars an armed setup stays alive
    min_stop_pct: float = 1.0
    max_stop_pct: float = 12.0
    min_rr: float = 3.0
    be_at_r: float | None = 1.0
    max_hold: int = 1920              # 15m bars (20 days)
    risk_pct: float = 1.0
    max_leverage: float = 3.0


def resample_ohlc(df15: pd.DataFrame, tf: str) -> pd.DataFrame:
    """Complete HTF buckets only. ts is the bucket start."""
    d = df15.set_index("ts")
    agg = d.resample(f"{TF_MIN[tf]}min", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
    cnt = d["open"].resample(f"{TF_MIN[tf]}min", label="left", closed="left").count()
    return agg[cnt == TF_MIN[tf] // LTF_MIN].dropna().reset_index()


def run_confirmed(df15: pd.DataFrame, symbol: str, p: CParams | None = None, fee_rate: float = 0.00055,
                  slippage_bps: float = 2.0, equity0: float = 1000.0) -> Result:
    p = p or CParams()
    df = df15.reset_index(drop=True)
    N, slip = len(df), slippage_bps / 10_000
    O, H, L, C = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    A15 = atr_series(df, 14).to_numpy(float)
    ts = df["ts"].to_numpy("datetime64[ns]").astype("int64")
    end15 = ts + LTF_MIN * 60 * 10**9
    fl_lo, fl_hi = fractal_lows(L, p.n), fractal_lows(-H, p.n)

    hdf = resample_ohlc(df, p.tf)
    NH = len(hdf)
    hO, hH, hL, hC = (hdf[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    hA = atr_series(hdf, 14).to_numpy(float) if NH else np.array([])
    hend = hdf["ts"].to_numpy("datetime64[ns]").astype("int64") + TF_MIN[p.tf] * 60 * 10**9 if NH else np.array([], dtype=np.int64)
    hfl_lo, hfl_hi = (fractal_lows(hL, p.n), fractal_lows(-hH, p.n)) if NH else (np.zeros(0, bool), np.zeros(0, bool))
    window_ltf = p.window_htf * (TF_MIN[p.tf] // LTF_MIN)

    act_lo: list[list[float]] = []         # active HTF fractal lows [level, bar]
    act_hi: list[list[float]] = []
    arms: dict[int, dict | None] = {1: None, -1: None}
    last_fh = last_fl = None               # most recent confirmed 15m fractal high / low [level, bar]
    hp = 0

    pos, qty, entry_px, stop, target, entry_i, risk_usd, init_stop = 0, 0.0, 0.0, 0.0, 0.0, 0, 0.0, 0.0
    realized, equity = 0.0, equity0
    be_trig, be_done, stop_next = None, False, None
    pending = None                         # (dir, stop, target, be_trigger)
    res = Result(symbol, equity0, bars=N)
    curve = np.empty(N)

    def try_signal(d: int, i: int, sl: float):
        """Gates, HTF target and break-even trigger for a signal at the close of 15m bar i; sets `pending`. Returns True if a trade was queued."""
        nonlocal pending
        c = C[i]
        risk = d * (c - sl)
        if risk <= 0 or not (p.min_stop_pct / 100.0 <= risk / c <= p.max_stop_pct / 100.0):
            return False
        lv = [x[0] for x in (act_hi if d > 0 else act_lo) if (x[0] > c if d > 0 else x[0] < c)]
        if not lv:
            return False
        tgt = min(lv) if d > 0 else max(lv)
        if d * (tgt - c) < p.min_rr * risk:
            return False
        pending = (d, sl, tgt, c + d * p.be_at_r * risk if p.be_at_r else None)
        return True

    for i in range(N):
        # 1. a break-even stop decided at the previous bar takes effect now
        if pos != 0 and stop_next is not None:
            stop, stop_next = stop_next, None
        # 2. fill the order decided at the previous close, at this open
        if pending is not None and pos == 0:
            d, sl, tp, bt = pending
            fill = O[i] * (1 + d * slip)
            dist = d * (fill - sl)
            if dist > 0:
                qty = min(equity * p.risk_pct / 100.0 / dist, equity * p.max_leverage / fill)
                fee_in = fill * qty * fee_rate
                equity -= fee_in
                pos, entry_px, stop, target, entry_i = d, fill, sl, tp, i
                init_stop, risk_usd, realized = sl, qty * dist, -fee_in
                be_trig, be_done, stop_next = bt, False, None
        pending = None
        # 3. exits during this bar (stop first if both are reachable; time stop at the close)
        if pos != 0:
            d = pos
            px = None
            if (L[i] <= stop) if d > 0 else (H[i] >= stop):
                px = (min(stop, O[i]) if d > 0 else max(stop, O[i])) * (1 - d * slip)
            elif (H[i] >= target) if d > 0 else (L[i] <= target):
                px = target
            elif i - entry_i >= p.max_hold:
                px = C[i] * (1 - d * slip)
            if px is not None:
                gross = (px - entry_px) * qty * d
                fee_out = px * qty * fee_rate
                equity += gross - fee_out
                res.trades.append(Trade(symbol, df["ts"].iloc[entry_i], df["ts"].iloc[i], entry_px, init_stop,
                                        realized + gross - fee_out, risk_usd, i - entry_i, "buy" if d > 0 else "sell"))
                pos, qty = 0, 0.0
            elif be_trig is not None and not be_done and ((H[i] >= be_trig) if d > 0 else (L[i] <= be_trig)):
                stop_next, be_done = entry_px, True
        curve[i] = equity + ((C[i] - entry_px) * qty * pos if pos else 0.0)

        # 4. 15m fractals confirmed by the close of bar i-1 (usable from the third bar after the pivot)
        j = i - p.n - 1
        if j >= p.n:
            if fl_hi[j]:
                last_fh = [H[j], j]
            if fl_lo[j]:
                last_fl = [L[j], j]
        # 5. HTF bars that completed with this 15m bar: confirm fractals, look for sweeps, arm setups
        while hp < NH and hend[hp] <= end15[i]:
            h = hp
            hp += 1
            jh = h - p.n - 1
            if jh >= p.n:
                if hfl_lo[jh]:
                    act_lo.append([hL[jh], jh])
                if hfl_hi[jh]:
                    act_hi.append([hH[jh], jh])
            if np.isnan(hA[h]):
                continue
            ha, hrng = hA[h], hH[h] - hL[h]
            c0: dict[int, float] = {}
            kept, best = [], None
            for lv in act_lo:
                lvl, jj = lv
                if h - jj > p.max_age:
                    continue
                if hL[h] < lvl:
                    if hC[h] <= lvl:
                        continue
                    if hrng > 0 and hL[h] <= lvl - p.pen_atr * ha and hC[h] >= hL[h] + 0.5 * hrng:
                        best = lvl if best is None else max(best, lvl)
                        continue
                kept.append(lv)
            act_lo = kept
            if best is not None:
                if p.model == "C0":
                    c0[1] = hL[h] - p.sl_buf_atr * ha
                else:
                    arms[1] = dict(start=i + 1, expiry=i + window_ltf, stop_ref=hL[h] - p.sl_buf_atr * ha, stage="choch", choch_i=None, idm=None)
            kept, best = [], None
            for lv in act_hi:
                lvl, jj = lv
                if h - jj > p.max_age:
                    continue
                if hH[h] > lvl:
                    if hC[h] >= lvl:
                        continue
                    if hrng > 0 and hH[h] >= lvl + p.pen_atr * ha and hC[h] <= hL[h] + 0.5 * hrng:
                        best = lvl if best is None else min(best, lvl)
                        continue
                kept.append(lv)
            act_hi = kept
            if best is not None:
                if p.model == "C0":
                    c0[-1] = hH[h] + p.sl_buf_atr * ha
                else:
                    arms[-1] = dict(start=i + 1, expiry=i + window_ltf, stop_ref=hH[h] + p.sl_buf_atr * ha, stage="choch", choch_i=None, idm=None)
            if c0 and pos == 0 and pending is None and not np.isnan(A15[i]) and len(c0) == 1:
                (d0, sl0), = c0.items()
                try_signal(d0, i, sl0)                        # control: enter at the next open, no confirmation; a double sweep on one bar is skipped
            c0 = {}
        # 6. LTF confirmation of armed setups (M1 / M2). Signals are only acted on when flat.
        if p.model == "C0" or i + 1 >= N or np.isnan(A15[i]):
            continue
        a15 = A15[i]
        sigs = {}
        for d in (1, -1):
            arm = arms[d]
            if arm is None or i < arm["start"]:
                continue
            if i > arm["expiry"] or ((L[i] < arm["stop_ref"]) if d > 0 else (H[i] > arm["stop_ref"])):
                arms[d] = None                               # window over, or the structure extreme was broken
                continue
            if arm["stage"] == "choch":
                ref = last_fh if d > 0 else last_fl
                if ref is not None and ((C[i] > ref[0]) if d > 0 else (C[i] < ref[0])):      # a body close beyond the recent fractal
                    if p.model == "M2":
                        sigs[d] = arm["stop_ref"]
                        arms[d] = None
                    else:
                        arm["stage"], arm["choch_i"] = "idm", i
                continue
            # stage "idm": first pullback extreme confirmed after the CHoCH bar, then swept and reclaimed
            jj = i - p.n - 1
            if arm["idm"] is None and jj > arm["choch_i"] and ((fl_lo[jj]) if d > 0 else (fl_hi[jj])):
                arm["idm"] = L[jj] if d > 0 else H[jj]
            if arm["idm"] is not None:
                idm = arm["idm"]
                if (L[i] <= idm - p.pen_atr * a15 and C[i] > idm) if d > 0 else (H[i] >= idm + p.pen_atr * a15 and C[i] < idm):
                    sigs[d] = min(arm["stop_ref"], L[i] - p.sl_buf_atr * a15) if d > 0 else max(arm["stop_ref"], H[i] + p.sl_buf_atr * a15)
                    arms[d] = None
        if pos == 0 and pending is None and len(sigs) == 1:
            (d, sl), = sigs.items()
            try_signal(d, i, sl)

    if pos != 0:                                                     # mark an open trade at the last close
        gross = (C[-1] - entry_px) * qty * pos
        res.trades.append(Trade(symbol, df["ts"].iloc[entry_i], df["ts"].iloc[-1], entry_px, init_stop,
                                realized + gross - C[-1] * qty * fee_rate, risk_usd, N - 1 - entry_i, "buy" if pos > 0 else "sell"))
    res.equity = pd.Series(curve, index=df["ts"])
    res.buy_hold_pct = (C[-1] / C[min(30, N - 1)] - 1) * 100
    return res
