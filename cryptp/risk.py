"""Deterministic risk controls. Never delegated to an LLM."""
from __future__ import annotations

from pathlib import Path

from .planner import TradePlan


def position_size(equity: float, plan: TradePlan, risk_pct: float, max_leverage: float) -> float:
    qty = equity * risk_pct / 100 / plan.risk_per_unit
    max_qty = equity * max_leverage / plan.entry
    return min(qty, max_qty)


class RiskGate:
    def __init__(self, cfg, kill_file: str = "KILL"):
        self.cfg = cfg
        self.kill_file = Path(kill_file)
        self.daily_pnl = 0.0
        self.open_symbols: set[str] = set()

    def check(self, plan: TradePlan, equity: float) -> tuple[bool, str]:
        if self.kill_file.exists():
            return False, "kill switch file present"
        if self.daily_pnl <= -equity * self.cfg.max_daily_loss_pct / 100:
            return False, "daily loss limit hit"
        if plan.symbol in self.open_symbols:
            return False, "already in position"
        if len(self.open_symbols) >= self.cfg.max_open_positions:
            return False, "max open positions"
        return True, "ok"
