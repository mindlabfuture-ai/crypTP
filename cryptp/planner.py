"""Turns market structure into a concrete trade plan (long or short) with a TP ladder.

The short side is the exact mirror of the long side: same ATR rules, same fee filter, same R ladder.
No short-only parameters exist, so there is nothing extra to overfit.
"""
from __future__ import annotations

from dataclasses import dataclass

from .structure import MarketStructure


@dataclass
class TradePlan:
    symbol: str
    side: str                     # "buy" (long) | "sell" (short)
    entry: float
    stop: float
    targets: list[float]
    fractions: list[float]
    risk_per_unit: float
    note: str = ""

    @property
    def d(self) -> int:
        """+1 for long, -1 for short."""
        return 1 if self.side == "buy" else -1


def build_plan(symbol: str, price: float, atr_val: float, ms: MarketStructure,
               htf_trend: str, cfg, side: str = "buy") -> TradePlan | None:
    """Long: HTF not down, and an uptrend or bullish BOS. Short: the mirror image."""
    d = 1 if side == "buy" else -1
    if d > 0:
        if htf_trend == "down" or not (ms.trend == "up" or ms.bos == "bullish"):
            return None
        anchor, far = ms.last_swing_low, ms.resistance
    else:
        if htf_trend == "up" or not (ms.trend == "down" or ms.bos == "bearish"):
            return None
        anchor, far = ms.last_swing_high, ms.support
    if anchor is None or atr_val <= 0:
        return None

    stop = anchor - d * 0.25 * atr_val
    risk = d * (price - stop)
    if risk > cfg.max_stop_atr * atr_val:
        return None                              # structure stop too far; skip
    if risk < cfg.min_stop_atr * atr_val:
        stop = price - d * cfg.min_stop_atr * atr_val
        risk = d * (price - stop)
    if risk <= 0:
        return None

    # Fee-aware filter: a stop tighter than a few round-trip costs can't pay for itself
    # (at 0.23% of price a 0.11% round trip costs ~0.5R). Skip, don't widen the structure stop.
    stop_pct = risk / price * 100
    if stop_pct < getattr(cfg, "min_stop_cost_mult", 0.0) * getattr(cfg, "round_trip_cost_pct", 0.0):
        return None

    if far is not None and d * (far - price) < cfg.min_room_r * risk:
        return None                              # not enough room to run

    targets = [price + d * r * risk for r in cfg.r_multiples]
    return TradePlan(symbol, side, price, stop, targets, list(cfg.tp_fractions), risk,
                     note=f"trend={ms.trend} bos={ms.bos} htf={htf_trend}")


SIDES = {"long": ("buy",), "short": ("sell",), "both": ("buy", "sell")}


def build_plan_any(symbol: str, price: float, atr_val: float, ms: MarketStructure,
                   htf_trend: str, cfg, sides: str | None = None) -> TradePlan | None:
    """First valid plan among the allowed sides (cfg.sides: long | short | both; default long)."""
    for side in SIDES[sides or getattr(cfg, "sides", "long")]:
        plan = build_plan(symbol, price, atr_val, ms, htf_trend, cfg, side)
        if plan:
            return plan
    return None
