# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Python port of the logic of the "SuperTrend STRATEGY" TradingView script by KivancOzbilgic (Pine v4, MPL 2.0).
# Only the signal logic is ported (no drawing). See docs/SUPERTREND_PREREG.md.
"""SuperTrend: ratcheting ATR bands around hl2; the trend flips when close crosses the opposite band."""
from __future__ import annotations

import numpy as np
import pandas as pd


def rma(x: np.ndarray, n: int) -> np.ndarray:
    """Pine's rma: seeded with the SMA of the first n values, then (prev*(n-1)+x)/n."""
    out = np.full(len(x), np.nan)
    if len(x) < n:
        return out
    out[n - 1] = x[:n].mean()
    for i in range(n, len(x)):
        out[i] = (out[i - 1] * (n - 1) + x[i]) / n
    return out


def supertrend(df: pd.DataFrame, period: int = 10, mult: float = 3.0):
    """Returns (buy, sell, trend, up, dn). buy/sell are one-bar events on the bar where the trend flips."""
    h, l, c = (df[k].to_numpy(float) for k in ("high", "low", "close"))
    n = len(c)
    src = (h + l) / 2.0
    prev_c = np.r_[np.nan, c[:-1]]
    tr = np.maximum.reduce([h - l, np.abs(h - prev_c), np.abs(l - prev_c)])
    tr[0] = h[0] - l[0]                                       # Pine: tr is high-low on the first bar
    atr = rma(tr, period)
    up, dn = np.full(n, np.nan), np.full(n, np.nan)
    trend = np.ones(n, dtype=int)
    buy, sell = np.zeros(n, dtype=bool), np.zeros(n, dtype=bool)
    i0 = period - 1                                           # first bar with a valid ATR
    for i in range(i0, n):
        up_raw, dn_raw = src[i] - mult * atr[i], src[i] + mult * atr[i]
        up1 = up[i - 1] if i > i0 else up_raw                 # nz(up[1], up): the PREVIOUS bar's final band
        dn1 = dn[i - 1] if i > i0 else dn_raw
        up[i] = max(up_raw, up1) if (i > 0 and c[i - 1] > up1) else up_raw
        dn[i] = min(dn_raw, dn1) if (i > 0 and c[i - 1] < dn1) else dn_raw
        prev = trend[i - 1] if i > 0 else 1
        t = prev
        if prev == -1 and c[i] > dn1:
            t = 1
        elif prev == 1 and c[i] < up1:
            t = -1
        trend[i] = t
        buy[i], sell[i] = (t == 1 and prev == -1), (t == -1 and prev == 1)
    idx = df.index
    return (pd.Series(buy, index=idx), pd.Series(sell, index=idx), pd.Series(trend, index=idx),
            pd.Series(up, index=idx), pd.Series(dn, index=idx))
