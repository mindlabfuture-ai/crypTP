"""Executors. PaperExecutor simulates fills; LiveExecutor places Bybit orders via ccxt."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from .planner import TradePlan


@dataclass
class Position:
    plan: TradePlan
    qty: float
    remaining: float
    stop: float
    next_tp: int = 0
    realized: float = 0.0


class PaperExecutor:
    def __init__(self, equity: float):
        self.equity = equity
        self.positions: dict[str, Position] = {}
        self.closed_pnl: list[float] = []

    def submit(self, plan: TradePlan, qty: float) -> str:
        self.positions[plan.symbol] = Position(plan, qty, qty, plan.stop)
        return f"paper-{plan.symbol}"

    def on_candle(self, symbol: str, high: float, low: float) -> float:
        """Advance a position through one candle. Stop is checked first (conservative)."""
        pos = self.positions.get(symbol)
        if not pos:
            return 0.0
        p = pos.plan
        pnl = 0.0
        if low <= pos.stop:
            pnl += (pos.stop - p.entry) * pos.remaining
            pos.remaining = 0.0
        else:
            while pos.next_tp < len(p.targets) and high >= p.targets[pos.next_tp]:
                frac = p.fractions[pos.next_tp]
                q = min(pos.qty * frac, pos.remaining)
                pnl += (p.targets[pos.next_tp] - p.entry) * q
                pos.remaining -= q
                if pos.next_tp == 0:
                    pos.stop = max(pos.stop, p.entry)   # TP1 hit -> stop to breakeven
                pos.next_tp += 1
        pos.realized += pnl
        self.equity += pnl
        if pos.remaining <= 1e-12:
            self.closed_pnl.append(pos.realized)
            del self.positions[symbol]
        return pnl


class LiveExecutor:
    """Real orders. UNTESTED against live Bybit from this repo's CI: use testnet first."""

    def __init__(self, exchange):
        if os.getenv("CRYPTP_ALLOW_LIVE", "no").lower() != "yes":
            raise RuntimeError("Live trading disabled. Set CRYPTP_ALLOW_LIVE=yes to enable.")
        self.ex = exchange

    def submit(self, plan: TradePlan, qty: float) -> str:
        sym = plan.symbol
        qty = float(self.ex.amount_to_precision(sym, qty))
        order = self.ex.create_order(
            sym, "market", "buy", qty, params={"stopLoss": self.ex.price_to_precision(sym, plan.stop)}
        )
        for tp, frac in zip(plan.targets, plan.fractions):
            q = float(self.ex.amount_to_precision(sym, qty * frac))
            if q > 0:
                self.ex.create_order(sym, "limit", "sell", q, float(self.ex.price_to_precision(sym, tp)),
                                     params={"reduceOnly": True})
        return str(order.get("id"))
