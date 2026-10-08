"""Pre-trade and post-trade safety checks for Bybit USDT perpetuals. Pure functions plus one exchange verifier.

Nothing here is smart: each check is a deterministic rule that can only BLOCK an order or flatten a position, never create one.
Defaults are conservative; Bybit's real maintenance-margin tiers vary by symbol and size, so `mmr_pct` is a configured
assumption (check it per symbol before going live). Untested against live Bybit from this repo's CI.
"""
from __future__ import annotations

import math
from types import SimpleNamespace

from .planner import TradePlan

DEFAULTS = dict(
    isolated=True,                     # isolated margin only: a liquidation can lose at most this position's margin
    liq_buffer=0.5,                    # stop distance must be <= this fraction of the distance to liquidation
    mmr_pct=0.5,                       # assumed maintenance margin rate, % of notional
    max_entry_drift_pct=0.5,           # block if the live price has moved this far from the planned entry
    max_adverse_funding_8h_pct=0.05,   # block if the side pays more than this per 8h (0.01% is the usual baseline)
    require_exchange_stop=True,        # a stop must exist ON THE EXCHANGE after the entry, else flatten
)


class SafetyError(RuntimeError):
    pass


def safety_cfg(cfg=None) -> SimpleNamespace:
    vals = dict(DEFAULTS)
    if cfg is not None:
        vals.update({k: v for k, v in vars(cfg).items() if k in DEFAULTS})
    return SimpleNamespace(**vals)


def isolated_leverage(notional: float, equity: float, cap: float) -> int:
    """Smallest whole leverage that carries `notional` on `equity`, never above `cap` (>= 1)."""
    return int(min(max(1, math.ceil(notional / max(equity, 1e-9))), max(1, math.floor(cap))))


def liquidation_price(side: str, entry: float, leverage: float, mmr_pct: float) -> float:
    """Isolated-margin liquidation estimate (ignores fees and funding): entry*(1 -/+ (1/lev - mmr))."""
    gap = 1.0 / leverage - mmr_pct / 100.0
    return entry * (1 - gap) if side == "buy" else entry * (1 + gap)


def check_perp_order(plan: TradePlan, qty: float, equity: float, max_leverage: float, scfg, last_price: float | None = None,
                     funding_rate_8h_pct: float | None = None, min_qty: float | None = None,
                     min_notional: float | None = None) -> tuple[bool, list[str]]:
    """All reasons the order must be blocked (empty list = ok)."""
    why: list[str] = []
    d = plan.d
    notional = qty * plan.entry
    if qty <= 0 or equity <= 0:
        return False, ["non-positive size or equity"]
    if notional > equity * max_leverage * 1.0001:
        why.append(f"leverage {notional / equity:.2f}x exceeds cap {max_leverage}x")
    if d * (plan.entry - plan.stop) <= 0:
        why.append("stop is not on the losing side of entry")
    lev = isolated_leverage(notional, equity, max_leverage)
    liq = liquidation_price(plan.side, plan.entry, lev, scfg.mmr_pct)
    stop_dist, liq_dist = abs(plan.entry - plan.stop), abs(plan.entry - liq)
    if stop_dist > scfg.liq_buffer * liq_dist:
        why.append(f"stop {stop_dist / plan.entry * 100:.2f}% away is too close to liquidation "
                   f"({liq_dist / plan.entry * 100:.2f}% at {lev}x); limit is {scfg.liq_buffer:.0%} of that")
    if last_price is not None:
        if abs(last_price / plan.entry - 1) * 100 > scfg.max_entry_drift_pct:
            why.append(f"price drifted {abs(last_price / plan.entry - 1) * 100:.2f}% from the planned entry")
        if d * (last_price - plan.stop) <= 0:
            why.append("last price is already beyond the stop")
    if funding_rate_8h_pct is not None and d * funding_rate_8h_pct > scfg.max_adverse_funding_8h_pct:
        why.append(f"this side pays {d * funding_rate_8h_pct:.3f}% funding per 8h (limit {scfg.max_adverse_funding_8h_pct}%)")
    if min_qty is not None and qty < min_qty:
        why.append(f"size {qty} below exchange minimum {min_qty}")
    if min_notional is not None and notional < min_notional:
        why.append(f"notional {notional:.2f} below exchange minimum {min_notional}")
    return not why, why


def verify_exchange_stop(exchange, symbol: str, side: str, expected_stop: float, tol_pct: float = 0.2) -> tuple[bool, str]:
    """After entry: the exchange must hold a stop-loss on the right side, near the stop we asked for."""
    for p in exchange.fetch_positions([symbol]):
        if float(p.get("contracts") or 0) <= 0:
            continue
        sl = p.get("stopLossPrice") or (p.get("info") or {}).get("stopLoss")
        try:
            sl = float(sl)
        except (TypeError, ValueError):
            sl = 0.0
        if sl <= 0:
            return False, "no stop-loss on the exchange position"
        if abs(sl / expected_stop - 1) * 100 > tol_pct:
            return False, f"exchange stop {sl} differs from expected {expected_stop}"
        return True, "ok"
    return False, "position not found after entry"
