"""Executors. PaperExecutor simulates fills; LiveExecutor places Bybit orders via ccxt."""
from __future__ import annotations

import os
from pathlib import Path
from dataclasses import dataclass, field

from .planner import TradePlan
from .safety import SafetyError, check_perp_order, isolated_leverage, safety_cfg, verify_exchange_stop


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
    """Real orders. UNTESTED against live Bybit from this repo's CI: use testnet first.

    Every entry passes cryptp.safety first (leverage cap, stop-vs-liquidation distance, price drift, adverse funding, exchange
    minimums), is placed on ISOLATED margin with the stop attached to the entry order, and is then verified: if the exchange does
    not hold the stop, the position is flattened and the KILL file is written so nothing else trades until a human clears it."""

    def __init__(self, exchange, safety=None, max_leverage: float = 3.0, kill_file: str = "KILL"):
        if os.getenv("CRYPTP_ALLOW_LIVE", "no").lower() != "yes":
            raise RuntimeError("Live trading disabled. Set CRYPTP_ALLOW_LIVE=yes to enable.")
        self.ex = exchange
        self.safety = safety_cfg(safety)
        self.max_leverage = max_leverage
        self.kill_file = Path(kill_file)

    def _pre_trade(self, plan: TradePlan, qty: float) -> int:
        sym = plan.symbol
        equity = float(self.ex.fetch_balance()["USDT"]["total"])
        last = float(self.ex.fetch_ticker(sym)["last"])
        fr = None
        try:
            fr = float(self.ex.fetch_funding_rate(sym)["fundingRate"]) * 100
        except Exception:
            pass                                          # funding unavailable: the other checks still apply
        limits = (self.ex.market(sym) or {}).get("limits") or {}
        ok, why = check_perp_order(plan, qty, equity, self.max_leverage, self.safety, last, fr,
                                   (limits.get("amount") or {}).get("min"), (limits.get("cost") or {}).get("min"))
        if not ok:
            raise SafetyError(f"{sym}: " + "; ".join(why))
        return isolated_leverage(qty * plan.entry, equity, self.max_leverage)

    def submit(self, plan: TradePlan, qty: float) -> str:
        sym = plan.symbol
        qty = float(self.ex.amount_to_precision(sym, qty))
        if self.kill_file.exists():
            raise SafetyError("kill switch file present")
        lev = self._pre_trade(plan, qty)
        if self.safety.isolated:
            try:
                self.ex.set_margin_mode("isolated", sym, params={"leverage": lev})
            except Exception as e:                        # Bybit errors when the mode is already set: only that is fine
                if "not modified" not in str(e).lower() and "already" not in str(e).lower():
                    raise SafetyError(f"{sym}: could not set isolated margin: {e}")
        try:
            self.ex.set_leverage(lev, sym)
        except Exception as e:
            if "not modified" not in str(e).lower():
                raise SafetyError(f"{sym}: could not set leverage {lev}x: {e}")
        exit_side = "sell" if plan.side == "buy" else "buy"
        order = self.ex.create_order(
            sym, "market", plan.side, qty, params={"stopLoss": self.ex.price_to_precision(sym, plan.stop)}
        )
        if self.safety.require_exchange_stop:
            ok, why = verify_exchange_stop(self.ex, sym, plan.side, float(self.ex.price_to_precision(sym, plan.stop)))
            if not ok:
                self._emergency_flatten(sym)
                raise SafetyError(f"{sym}: stop not confirmed on exchange ({why}); position flattened, KILL written")
        for tp, frac in zip(plan.targets, plan.fractions):
            q = float(self.ex.amount_to_precision(sym, qty * frac))
            if q > 0:
                self.ex.create_order(sym, "limit", exit_side, q, float(self.ex.price_to_precision(sym, tp)),
                                     params={"reduceOnly": True})
        return str(order.get("id"))

    def _emergency_flatten(self, symbol: str) -> None:
        try:
            self.close(symbol, None)
        finally:
            self.kill_file.write_text("stop not confirmed on exchange; flattened automatically\n")

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
