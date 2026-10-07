"""Market structure: swing points, trend (HH/HL vs LH/LL), break of structure, nearby levels."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class Swing:
    pos: int          # integer position in the frame
    price: float
    kind: str         # "high" | "low"


@dataclass
class MarketStructure:
    trend: str                      # "up" | "down" | "range"
    bos: str | None                 # "bullish" | "bearish" | None (close beyond last swing)
    last_swing_high: float | None
    last_swing_low: float | None
    resistance: float | None        # nearest swing high above price
    support: float | None           # nearest swing low below price
    swings: list[Swing]


def find_swings(df: pd.DataFrame, left: int = 3, right: int = 3) -> list[Swing]:
    """Fractal swings. A swing is only confirmed `right` bars later, so no lookahead."""
    out: list[Swing] = []
    h, l = df["high"].to_numpy(), df["low"].to_numpy()
    for i in range(left, len(df) - right):
        if h[i] == h[i - left : i + right + 1].max() and h[i] > h[i - 1]:
            out.append(Swing(i, float(h[i]), "high"))
        if l[i] == l[i - left : i + right + 1].min() and l[i] < l[i - 1]:
            out.append(Swing(i, float(l[i]), "low"))
    return sorted(out, key=lambda s: s.pos)


def analyze(df: pd.DataFrame, left: int = 3, right: int = 3) -> MarketStructure:
    swings = find_swings(df, left, right)
    highs = [s for s in swings if s.kind == "high"]
    lows = [s for s in swings if s.kind == "low"]
    price = float(df["close"].iloc[-1])

    trend = "range"
    if len(highs) >= 2 and len(lows) >= 2:
        hh, hl = highs[-1].price > highs[-2].price, lows[-1].price > lows[-2].price
        lh, ll = highs[-1].price < highs[-2].price, lows[-1].price < lows[-2].price
        trend = "up" if hh and hl else "down" if lh and ll else "range"

    lsh = highs[-1].price if highs else None
    lsl = lows[-1].price if lows else None
    bos = None
    if lsh is not None and price > lsh:
        bos = "bullish"
    elif lsl is not None and price < lsl:
        bos = "bearish"

    above = [s.price for s in highs if s.price > price]
    below = [s.price for s in lows if s.price < price]
    return MarketStructure(
        trend=trend,
        bos=bos,
        last_swing_high=lsh,
        last_swing_low=lsl,
        resistance=min(above) if above else None,
        support=max(below) if below else None,
        swings=swings,
    )
