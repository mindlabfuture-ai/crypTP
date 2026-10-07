"""TradingView alert signals (Wyckoff + Smart Money Concepts) and confluence rules."""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

# Event names used in the alert JSON ("event" field). One alert per event per symbol.
WY_LONG = {"wy_long_entry", "wy_spring", "wy_sos", "wy_lps", "wy_ctest"}
WY_EXIT = {"wy_short_entry", "wy_sow", "wy_utad", "wy_lpsy"}
SMC_BULL = {"smc_bull_choch", "smc_bull_bos"}
SMC_BEAR = {"smc_bear_choch", "smc_bear_bos"}
ALL_EVENTS = WY_LONG | WY_EXIT | SMC_BULL | SMC_BEAR

_SYM = re.compile(r"^(?:[A-Z]+:)?(.+?)USDT(?:\.P)?$")


def to_ccxt_symbol(tv: str) -> str:
    """BYBIT:BTCUSDT.P / BTCUSDT.P / BTCUSDT -> BTC/USDT:USDT"""
    m = _SYM.match(tv.strip().upper())
    if not m:
        raise ValueError(f"unsupported symbol: {tv}")
    return f"{m.group(1)}/USDT:USDT"


@dataclass
class Signal:
    event: str
    symbol: str
    tf: str = ""
    price: float | None = None
    ts: float = field(default_factory=time.time)


def parse_signal(payload: dict, now: float | None = None) -> Signal:
    event = str(payload.get("event", "")).lower()
    if event not in ALL_EVENTS:
        raise ValueError(f"unknown event: {event!r}")
    price = payload.get("price")
    return Signal(event, to_ccxt_symbol(str(payload.get("symbol", ""))), str(payload.get("tf", "")),
                  float(price) if price not in (None, "") else None,
                  now if now is not None else time.time())


class SignalBook:
    def __init__(self, cfg):
        self.cfg = cfg
        self.last: dict[str, dict[str, float]] = {}

    def record(self, sig: Signal) -> None:
        self.last.setdefault(sig.symbol, {})[sig.event] = sig.ts

    def _latest(self, symbol: str, events: set[str], now: float, ttl_min: float):
        ev = self.last.get(symbol, {})
        hits = [(t, e) for e, t in ev.items() if e in events and now - t <= ttl_min * 60]
        return max(hits) if hits else None

    def smc_bias(self, symbol: str, now: float) -> int:
        bull = self._latest(symbol, SMC_BULL, now, self.cfg.smc_ttl_min)
        bear = self._latest(symbol, SMC_BEAR, now, self.cfg.smc_ttl_min)
        if bull and (not bear or bull[0] > bear[0]):
            return 1
        if bear and (not bull or bear[0] >= bull[0]):
            return -1
        return 0

    def armed_long(self, symbol: str, now: float) -> tuple[bool, str]:
        trig = self._latest(symbol, WY_LONG, now, self.cfg.wy_ttl_min)
        if not trig:
            return False, "no recent Wyckoff long trigger"
        bad = self._latest(symbol, WY_EXIT, now, self.cfg.wy_ttl_min)
        if bad and bad[0] > trig[0]:
            return False, f"{bad[1]} after {trig[1]}"
        bias = self.smc_bias(symbol, now)
        if bias == -1 or (self.cfg.require_smc and bias != 1):
            return False, "SMC swing bias not bullish"
        return True, f"{trig[1]} + smc_bias={bias}"

    def exit_signal(self, symbol: str, since: float, now: float) -> str | None:
        """A bearish Wyckoff event or bearish SMC swing break that arrived after the entry."""
        for events in (WY_EXIT, SMC_BEAR):
            hit = self._latest(symbol, events, now, 1e9)
            if hit and hit[0] > since:
                return hit[1]
        return None
