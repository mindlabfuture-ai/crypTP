"""Turns market structure into a concrete long trade plan with a TP ladder."""
from __future__ import annotations

from dataclasses import dataclass

from .structure import MarketStructure


@dataclass
class TradePlan:
    symbol: str
    side: str                     # "buy"
    entry: float
    stop: float
    targets: list[float]
    fractions: list[float]
    risk_per_unit: float
    note: str = ""


def build_plan(symbol: str, price: float, atr_val: float, ms: MarketStructure,
               htf_trend: str, cfg) -> TradePlan | None:
    """Long-only plan. Requires HTF not down and either an uptrend or a bullish BOS."""
    if htf_trend == "down":
        return None
    if not (ms.trend == "up" or ms.bos == "bullish"):
        return None
    if ms.last_swing_low is None or atr_val <= 0:
        return None

    stop = ms.last_swing_low - 0.25 * atr_val
    risk = price - stop
    if risk > cfg.max_stop_atr * atr_val:
        return None                              # structure stop too far; skip
    if risk < cfg.min_stop_atr * atr_val:
        stop = price - cfg.min_stop_atr * atr_val
        risk = price - stop
    if risk <= 0:
        return None

    # Fee-aware filter: a stop tighter than a few round-trip costs can't pay for itself
    # (at 0.23% of price a 0.11% round trip costs ~0.5R). Skip, don't widen the structure stop.
    stop_pct = risk / price * 100
    if stop_pct < getattr(cfg, "min_stop_cost_mult", 0.0) * getattr(cfg, "round_trip_cost_pct", 0.0):
        return None

    if ms.resistance is not None and (ms.resistance - price) < cfg.min_room_r * risk:
        return None                              # not enough room to run

    targets = [price + r * risk for r in cfg.r_multiples]
    return TradePlan(symbol, "buy", price, stop, targets, list(cfg.tp_fractions), risk,
                     note=f"trend={ms.trend} bos={ms.bos} htf={htf_trend}")
