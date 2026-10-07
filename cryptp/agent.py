"""Decision layer: turns TradingView signals into entries/exits, always through the risk gate."""
from __future__ import annotations

import time

from .dumbmoney import gate_long
from .planner import build_plan
from .risk import RiskGate, position_size
from .signals import SMC_BULL, WY_LONG, Signal, SignalBook


class TradeAgent:
    def __init__(self, cfg, book: SignalBook, gate: RiskGate, executor, get_market, get_equity,
                 get_candle=None, live: bool = False, get_dm=None, dm_mode: str = "off"):
        self.cfg, self.book, self.gate, self.executor = cfg, book, gate, executor
        self.get_market, self.get_equity, self.get_candle, self.live = get_market, get_equity, get_candle, live
        self.get_dm, self.dm_mode = get_dm, dm_mode
        self.entry_ts: dict[str, float] = {}
        self.log: list[str] = []
        self._day = None

    def _say(self, msg: str) -> str:
        self.log.append(msg)
        print(msg)
        return msg

    def on_signal(self, sig: Signal) -> str:
        self.book.record(sig)
        held = self.executor.open_symbols()
        self.gate.open_symbols = held
        if sig.symbol in held:
            why = self.book.exit_signal(sig.symbol, self.entry_ts.get(sig.symbol, 0.0), sig.ts)
            if not why:
                return self._say(f"{sig.symbol}: {sig.event} ignored (in position)")
            pnl = self.executor.close(sig.symbol, sig.price)
            self.gate.daily_pnl += pnl or 0.0
            self.entry_ts.pop(sig.symbol, None)
            return self._say(f"{sig.symbol}: EXIT on {why}")
        if sig.event not in WY_LONG | SMC_BULL:
            return self._say(f"{sig.symbol}: {sig.event} noted")
        ok, why = self.book.armed_long(sig.symbol, sig.ts)
        if not ok:
            return self._say(f"{sig.symbol}: not armed ({why})")
        price, atr_val, ms, htf_trend = self.get_market(sig.symbol)
        plan = build_plan(sig.symbol, price, atr_val, ms, htf_trend, self.cfg.plan)
        if not plan:
            return self._say(f"{sig.symbol}: armed but no valid plan (structure/stop/room)")
        if self.get_dm and self.dm_mode != "off":
            ok, why_dm = gate_long(self.get_dm(sig.symbol), self.dm_mode)
            if not ok:
                return self._say(f"{sig.symbol}: armed but blocked by dumb-money filter ({why_dm})")
        equity = self.get_equity()
        ok, why2 = self.gate.check(plan, equity)
        if not ok:
            return self._say(f"{sig.symbol}: blocked by risk gate ({why2})")
        qty = position_size(equity, plan, self.cfg.risk.risk_per_trade_pct, self.cfg.risk.max_leverage)
        self.executor.submit(plan, qty)
        self.entry_ts[sig.symbol] = sig.ts
        return self._say(f"{sig.symbol}: ENTER qty={qty:.4f} entry={plan.entry} sl={plan.stop} "
                         f"tps={plan.targets} [{why}]")

    def tick(self) -> None:
        """Paper mode: advance simulated positions; both modes: roll the daily loss counter."""
        today = time.strftime("%Y-%m-%d", time.gmtime())
        if today != self._day:
            self.gate.daily_pnl, self._day = 0.0, today
        if not self.live and self.get_candle:
            for sym in list(self.executor.positions):
                hi, lo = self.get_candle(sym)
                self.gate.daily_pnl += self.executor.on_candle(sym, hi, lo)
