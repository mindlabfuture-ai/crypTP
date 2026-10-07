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
    def __init__(self, equity: float, fee_rate: float = 0.0, slippage: float = 0.0):
        self.equity = equity
        self.fee_rate = fee_rate          # per side, fraction of notional (taker)
        self.slippage = slippage          # applied against stop-market exits, fraction of price
        self.positions: dict[str, Position] = {}
        self.closed_pnl: list[float] = []

    def submit(self, plan: TradePlan, qty: float) -> str:
        fee = plan.entry * qty * self.fee_rate
        self.equity -= fee
        self.positions[plan.symbol] = Position(plan, qty, qty, plan.stop, realized=-fee)
        return f"paper-{plan.symbol}"

    def open_symbols(self) -> set[str]:
        return set(self.positions)

    def close(self, symbol: str, price: float | None) -> float:
        pos = self.positions.pop(symbol, None)
        if not pos or price is None:
            return 0.0
        pnl = (price - pos.plan.entry) * pos.remaining * pos.plan.d
        pos.realized += pnl
        self.equity += pnl
        self.closed_pnl.append(pos.realized)
        return pnl

    def on_candle(self, symbol: str, high: float, low: float, open_: float | None = None) -> float:
        """Advance a position through one candle. Stop is checked first (conservative).
        If the candle opens through the stop, the stop fills at the open (gap risk).
        Works for longs (stop below, targets above) and shorts (the mirror)."""
        pos = self.positions.get(symbol)
        if not pos:
            return 0.0
        p, d = pos.plan, pos.plan.d
        stopped = low <= pos.stop if d > 0 else high >= pos.stop
        pnl = 0.0
        if stopped:
            if d > 0:
                px = (pos.stop if open_ is None else min(pos.stop, open_)) * (1 - self.slippage)
            else:
                px = (pos.stop if open_ is None else max(pos.stop, open_)) * (1 + self.slippage)
            pnl += (px - p.entry) * pos.remaining * d - px * pos.remaining * self.fee_rate
            pos.remaining = 0.0
        else:
            while pos.next_tp < len(p.targets) and (high >= p.targets[pos.next_tp] if d > 0
                                                    else low <= p.targets[pos.next_tp]):
                tp = p.targets[pos.next_tp]
                q = min(pos.qty * p.fractions[pos.next_tp], pos.remaining)
                pnl += (tp - p.entry) * q * d - tp * q * self.fee_rate
                pos.remaining -= q
                if pos.next_tp == 0:                    # TP1 hit -> stop to breakeven
                    pos.stop = max(pos.stop, p.entry) if d > 0 else min(pos.stop, p.entry)
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
        exit_side = "sell" if plan.side == "buy" else "buy"
        order = self.ex.create_order(
            sym, "market", plan.side, qty, params={"stopLoss": self.ex.price_to_precision(sym, plan.stop)}
        )
        for tp, frac in zip(plan.targets, plan.fractions):
            q = float(self.ex.amount_to_precision(sym, qty * frac))
            if q > 0:
                self.ex.create_order(sym, "limit", exit_side, q, float(self.ex.price_to_precision(sym, tp)),
                                     params={"reduceOnly": True})
        return str(order.get("id"))

    def open_symbols(self) -> set[str]:
        return {p["symbol"] for p in self.ex.fetch_positions() if float(p.get("contracts") or 0) > 0}

    def close(self, symbol: str, price: float | None) -> float:
        for p in self.ex.fetch_positions([symbol]):
            qty = float(p.get("contracts") or 0)
            if qty > 0:
                self.ex.cancel_all_orders(symbol)
                closing = "buy" if str(p.get("side")).lower() == "short" else "sell"
                self.ex.create_order(symbol, "market", closing, qty, params={"reduceOnly": True})
        return 0.0      # realized PnL is tracked by the exchange; daily limit uses balance in live mode
