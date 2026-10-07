# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
#
# Python port of the signal logic of "Dumb Money Concepts" by theUltimator5 (MPL 2.0),
# https://www.tradingview.com/ (Pine v6). Only the computations are ported (no drawing).
# Not byte-identical: indicator warm-up/seeding differs slightly from Pine's built-ins.
"""Crowd-behaviour ("dumb money") features, used as a contrarian filter on long entries.

Euphoria  (FOMO breakout, herd exhaustion, chase-the-pullback, index in the hot zone):
          retail is buying the top  -> do not buy here.
Capitulation (panic flush, hopelessness, index in the cold zone):
          retail is selling the low -> contrarian support for a long.
Everything is causal: values at bar i use only candles up to and including bar i.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .indicators import atr, ema, rsi

RSI_LEN, EMA_LEN, ATR_LEN, VOL_LEN, HH_LEN = 14, 20, 14, 30, 50
DI_LEN, ADX_LEN, DI_MIN = 14, 14, 20
ADX_LOW, ADX_HIGH = 14, 40


def _rma(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(alpha=1 / n, adjust=False).mean()


def _normalize(s: pd.Series, n: int) -> pd.Series:
    lo, hi = s.rolling(n).min(), s.rolling(n).max()
    rng = hi - lo
    return (100 * (s - lo) / rng.where(rng != 0)).fillna(50.0)


def compute(df: pd.DataFrame, euphoria_bars: int = 6, capitulation_bars: int = 12,
            index_hot: float = 70, index_cold: float = 30, index_lookback: int = 100,
            fast_len: int = 5, slow_len: int = 12) -> pd.DataFrame:
    o, h, l, c, v = (df[k].astype(float) for k in ("open", "high", "low", "close", "volume"))
    r, e, a = rsi(c, RSI_LEN), ema(c, EMA_LEN), atr(df, ATR_LEN)
    vol_ma = v.rolling(VOL_LEN).mean()
    hh, ll = h.rolling(HH_LEN).max(), l.rolling(HH_LEN).min()

    fomo = (c > hh.shift()) & (r > 80) & ((c - e).abs() > 2 * a)
    panic = (l < ll.shift()) & (c > ll.shift()) & (v > 2 * vol_ma)
    green5 = (c.diff() > 0).rolling(5).sum() == 5
    herd = green5 & (v > 2 * vol_ma) & (r > 75)

    # crowd-sentiment pseudo-candle -> directional index (DDX / "DMX")
    bull = (((r - 70) / 30).where(r > 70, 0.0) + ((c - e) / a).where(c > e, 0.0)
            + (v / vol_ma - 1).where(v > vol_ma, 0.0))
    bear = (((30 - r) / 30).where(r < 30, 0.0) + ((e - c) / a).where(c < e, 0.0)
            + (v / vol_ma - 1).where(v > vol_ma, 0.0))
    d_close = (bull - bear) * a
    d_open = d_close.shift().fillna(0.0)
    d_rng = (bull - bear).abs() * a * 0.3
    d_hi, d_lo = np.maximum(d_close, d_open) + d_rng, np.minimum(d_close, d_open) - d_rng
    pc = d_close.shift()
    tr = pd.concat([d_hi - d_lo, (d_hi - pc).abs(), (d_lo - pc).abs()], axis=1).max(axis=1)
    up, dn = d_hi.diff(), -d_lo.diff()
    vf = (0.85 + 0.30 * np.minimum(v / np.maximum(vol_ma, 1), 1.0)).clip(0.85, 1.15)
    pos = pd.Series(np.where((up > dn) & (up > 0), up * vf, 0.0), index=df.index)
    neg = pd.Series(np.where((dn > up) & (dn > 0), dn * vf, 0.0), index=df.index)
    str_ = _rma(tr, DI_LEN)
    di_p, di_m = 100 * _rma(pos, DI_LEN) / str_, 100 * _rma(neg, DI_LEN) / str_
    dx = 100 * (di_p - di_m).abs() / (di_p + di_m).replace(0, np.nan)
    adx = _rma(dx.fillna(0.0), ADX_LEN)

    strong = adx >= ADX_HIGH
    weak = (adx < ADX_LOW) & (di_p < DI_MIN) & (di_m < DI_MIN)
    peak_turn = (adx < adx.shift()) & (adx.shift() > adx.shift(2))
    chase = strong & (di_p > di_m) & peak_turn & (adx > ADX_HIGH)
    hopeless = strong & (di_p < di_m) & peak_turn & (adx > ADX_HIGH)
    bored = weak & ((di_p.shift() - di_m.shift()).abs() < 5)

    # Dumb Money Index: mean of five 0-100 normalised components
    sma20, sd20 = c.rolling(20).mean(), c.rolling(20).std(ddof=0)
    up_b, lo_b = sma20 + 2 * sd20, sma20 - 2 * sd20
    bb_pos = (100 * (c - lo_b) / (up_b - lo_b).where(up_b != lo_b)).fillna(50.0)
    macd_line = ema(c, 12) - ema(c, 26)
    macd_hist = macd_line - ema(macd_line, 9)
    vol_signed = v / vol_ma * np.where(c >= o, 1.0, -1.0)
    raw = (_normalize(r, index_lookback) + _normalize(macd_hist, index_lookback)
           + _normalize(bb_pos, index_lookback) + _normalize(vol_signed, index_lookback)
           + _normalize(bull - bear, index_lookback)) / 5.0
    fast, slow = raw.rolling(fast_len).mean(), raw.rolling(slow_len).mean()

    def recent(flag: pd.Series, n: int) -> pd.Series:
        return flag.astype(float).rolling(n, min_periods=1).max() > 0

    euphoric = recent(fomo | herd | chase, euphoria_bars) | (fast >= index_hot)
    capitulation = recent(panic | hopeless, capitulation_bars) | recent(fast <= index_cold, euphoria_bars)
    out = pd.DataFrame({"fomo": fomo, "herd": herd, "chase": chase, "panic": panic,
                        "hopeless": hopeless, "bored": bored, "ddx": adx, "index_fast": fast,
                        "index_slow": slow, "euphoric": euphoric, "capitulation": capitulation})
    out.loc[out["index_fast"].isna(), ["euphoric", "capitulation"]] = False       # warm-up: no opinion
    return out


def gate_long(row, mode: str) -> tuple[bool, str]:
    """mode: off | veto (block euphoria) | require (also demand recent capitulation)."""
    if mode == "off" or row is None:
        return True, "dumb-money filter off"
    if bool(row["euphoric"]):
        return False, "crowd euphoric (FOMO/herd/chase or index hot)"
    if mode == "require" and not bool(row["capitulation"]):
        return False, "no recent crowd capitulation"
    return True, "ok"
