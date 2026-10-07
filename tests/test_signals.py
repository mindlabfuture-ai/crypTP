import asyncio
from types import SimpleNamespace

import pytest
from aiohttp.test_utils import TestClient, TestServer

from cryptp.agent import TradeAgent
from cryptp.config import load_config
from cryptp.executor import PaperExecutor
from cryptp.risk import RiskGate
from cryptp.signals import Signal, SignalBook, parse_signal, to_ccxt_symbol
from cryptp.structure import MarketStructure
from cryptp.webhook import create_app

cfg = load_config("config.yaml")
T0 = 1_000_000.0


def S(event, t, sym="BTC/USDT:USDT", price=100.0):
    return Signal(event, sym, "60", price, T0 + t * 60)


def test_symbol_mapping():
    assert to_ccxt_symbol("BYBIT:BTCUSDT.P") == "BTC/USDT:USDT"
    assert to_ccxt_symbol("1000PEPEUSDT.P") == "1000PEPE/USDT:USDT"
    assert to_ccxt_symbol("ETHUSDT") == "ETH/USDT:USDT"
    with pytest.raises(ValueError):
        to_ccxt_symbol("AAPL")


def test_parse_rejects_unknown_event():
    with pytest.raises(ValueError):
        parse_signal({"event": "nope", "symbol": "BTCUSDT.P"})


def test_confluence_needs_both():
    book = SignalBook(cfg.signals)
    book.record(S("wy_spring", 0))
    assert not book.armed_long("BTC/USDT:USDT", T0 + 60)[0]           # no SMC bias yet
    book.record(S("smc_bull_choch", 1))
    assert book.armed_long("BTC/USDT:USDT", T0 + 120)[0]


def test_bearish_smc_after_blocks_and_ttl_expires():
    book = SignalBook(cfg.signals)
    book.record(S("smc_bull_choch", 0))
    book.record(S("wy_sos", 1))
    book.record(S("smc_bear_choch", 2))
    assert not book.armed_long("BTC/USDT:USDT", T0 + 180)[0]
    book2 = SignalBook(cfg.signals)
    book2.record(S("smc_bull_choch", 0))
    book2.record(S("wy_sos", 1))
    assert not book2.armed_long("BTC/USDT:USDT", T0 + 60 + cfg.signals.wy_ttl_min * 60 + 1)[0]


def make_agent():
    ms = MarketStructure(trend="up", bos=None, last_swing_high=130.0, last_swing_low=124.7, resistance=None, support=124.7, swings=[])
    book = SignalBook(cfg.signals)
    ex = PaperExecutor(1000)
    agent = TradeAgent(cfg, book, RiskGate(cfg.risk, kill_file="/nonexistent/KILL"), ex,
                       lambda s: (130.0, 2.0, ms, "up"), lambda: ex.equity)
    return agent, ex


def test_agent_enters_then_exits_on_bearish():
    agent, ex = make_agent()
    agent.on_signal(S("smc_bull_bos", 0))
    assert "ENTER" in agent.on_signal(S("wy_lps", 1))
    assert "BTC/USDT:USDT" in ex.positions
    assert "ignored" in agent.on_signal(S("wy_sos", 2))               # bullish while holding: ignored
    assert "EXIT" in agent.on_signal(S("wy_sow", 3, price=128.0))
    assert not ex.positions and ex.equity < 1000                      # exited below entry


def test_agent_respects_kill_switch(tmp_path):
    agent, ex = make_agent()
    (tmp_path / "KILL").write_text("")
    agent.gate.kill_file = tmp_path / "KILL"
    agent.on_signal(S("smc_bull_bos", 0))
    assert "blocked" in agent.on_signal(S("wy_lps", 1))
    assert not ex.positions


def test_webhook_auth_and_flow():
    agent, ex = make_agent()

    async def go():
        async with TestClient(TestServer(create_app(agent, "s3cret"))) as c:
            bad = await c.post("/tv", data='{"secret":"x","event":"wy_lps","symbol":"BTCUSDT.P"}')
            assert bad.status == 403
            junk = await c.post("/tv", data="not json")
            assert junk.status == 400
            ev = await c.post("/tv", data='{"secret":"s3cret","event":"nope","symbol":"BTCUSDT.P"}')
            assert ev.status == 400
            ok = await c.post("/tv", data='{"secret":"s3cret","event":"smc_bull_bos","symbol":"BYBIT:BTCUSDT.P","tf":"60"}')
            assert ok.status == 200
            ok = await c.post("/tv", data='{"secret":"s3cret","event":"wy_lps","symbol":"BYBIT:BTCUSDT.P","tf":"60","price":130}')
            assert "ENTER" in (await ok.json())["result"]

    asyncio.run(go())
    assert "BTC/USDT:USDT" in ex.positions


def test_webhook_requires_secret():
    with pytest.raises(ValueError):
        create_app(None, "")
