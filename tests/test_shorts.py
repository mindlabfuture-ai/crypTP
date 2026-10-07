import copy

import pandas as pd
import pytest

from cryptp.agent import TradeAgent
from cryptp.backtest import run_backtest, synthetic_ohlcv
from cryptp.config import load_config
from cryptp.dumbmoney import gate_long, gate_short
from cryptp.executor import PaperExecutor
from cryptp.planner import TradePlan, build_plan, build_plan_any
from cryptp.risk import RiskGate
from cryptp.signals import Signal, SignalBook
from cryptp.structure import MarketStructure

cfg = load_config("config.yaml")
SYM = "X/USDT:USDT"
T0 = 1_000_000.0


def down_ms(**kw):
    base = dict(trend="down", bos=None, last_swing_high=130.0, last_swing_low=100.0, resistance=130.0,
                support=None, swings=[])
    base.update(kw)
    return MarketStructure(**base)


def test_short_plan_is_exact_mirror_of_long():
    up = MarketStructure(trend="up", bos=None, last_swing_high=130.0, last_swing_low=124.7, resistance=None,
                         support=124.7, swings=[])
    longp = build_plan(SYM, 130.0, 2.0, up, "up", cfg.plan, "buy")
    shortp = build_plan(SYM, 70.0, 2.0, MarketStructure(trend="down", bos=None, last_swing_high=75.3,
                        last_swing_low=70.0, resistance=75.3, support=None, swings=[]), "down", cfg.plan, "sell")
    assert longp and shortp and shortp.side == "sell" and shortp.d == -1
    assert shortp.stop > shortp.entry and all(t < shortp.entry for t in shortp.targets)
    assert shortp.risk_per_unit == pytest.approx(longp.risk_per_unit)
    assert [shortp.entry - t for t in shortp.targets] == pytest.approx([t - longp.entry for t in longp.targets])


def test_short_rejected_in_htf_uptrend_and_long_in_htf_downtrend():
    assert build_plan(SYM, 70.0, 2.0, down_ms(), "up", cfg.plan, "sell") is None
    up = MarketStructure(trend="up", bos=None, last_swing_high=130.0, last_swing_low=124.7, resistance=None,
                         support=124.7, swings=[])
    assert build_plan(SYM, 130.0, 2.0, up, "down", cfg.plan, "buy") is None


def test_build_plan_any_respects_sides():
    ms = down_ms(last_swing_high=75.3, last_swing_low=70.0, resistance=75.3)
    assert build_plan_any(SYM, 70.0, 2.0, ms, "down", cfg.plan, "long") is None
    assert build_plan_any(SYM, 70.0, 2.0, ms, "down", cfg.plan, "short").side == "sell"
    assert build_plan_any(SYM, 70.0, 2.0, ms, "down", cfg.plan, "both").side == "sell"


def test_paper_short_ladder_breakeven_and_stop():
    plan = TradePlan(SYM, "sell", 100, 102, [98, 96, 94], [0.4, 0.3, 0.3], 2.0)
    ex = PaperExecutor(1000)
    ex.submit(plan, 10)
    assert ex.on_candle(SYM, 101, 97.5) == pytest.approx(8.0)           # TP1: 4 units * 2
    assert ex.positions[SYM].stop == 100                                # breakeven (moved down)
    ex.on_candle(SYM, 100.5, 99)                                        # tags breakeven stop
    assert SYM not in ex.positions and ex.equity == pytest.approx(1008.0)


def test_paper_short_gap_up_fills_at_open_and_slippage_is_adverse():
    plan = TradePlan(SYM, "sell", 100, 102, [98], [1.0], 2.0)
    ex = PaperExecutor(1000)
    ex.submit(plan, 10)
    assert ex.on_candle(SYM, 106, 104, open_=105) == pytest.approx(-50.0)   # (100-105)*10
    ex2 = PaperExecutor(1000, slippage=0.01)
    ex2.submit(plan, 10)
    assert ex2.on_candle(SYM, 103, 101) == pytest.approx((100 - 102 * 1.01) * 10)


def mirror(df, c=500.0):
    m = df.copy()
    m["open"], m["close"] = 2 * c - df["open"], 2 * c - df["close"]
    m["high"], m["low"] = 2 * c - df["low"], 2 * c - df["high"]
    return m


def test_backtest_exact_mirror_symmetry():
    c = copy.deepcopy(cfg)
    c.plan.min_stop_cost_mult = 0.0            # fee filter is price-relative, so switch it off for the test
    c.risk.max_leverage = 1e9                  # leverage cap is price-relative too
    df = synthetic_ohlcv(2500, seed=3)
    longs = run_backtest(df, SYM, c, fee_rate=0, slippage_bps=0, sides="long")
    shorts = run_backtest(mirror(df), SYM, c, fee_rate=0, slippage_bps=0, sides="short")
    assert len(longs.trades) >= 3
    assert [t.entry_ts for t in longs.trades] == [t.entry_ts for t in shorts.trades]
    assert [t.pnl for t in longs.trades] == pytest.approx([t.pnl for t in shorts.trades], rel=1e-6)
    assert {t.side for t in shorts.trades} == {"sell"}


def test_backtest_both_is_causal_and_uses_both_sides():
    df = synthetic_ohlcv(3000, seed=11)
    full = run_backtest(df, SYM, cfg, sides="both")
    part = run_backtest(df.iloc[:2300], SYM, cfg, sides="both")
    cut = df["ts"].iloc[2300 - 2]
    a = [(t.entry_ts, round(t.pnl, 6), t.side) for t in full.trades if t.exit_ts < cut]
    b = [(t.entry_ts, round(t.pnl, 6), t.side) for t in part.trades if t.exit_ts < cut]
    assert a and a == b
    assert {t.side for t in full.trades} == {"buy", "sell"}


def test_dumbmoney_short_gate_mirrors_long_gate():
    calm = {"euphoric": False, "capitulation": False}
    euph = {"euphoric": True, "capitulation": False}
    cap = {"euphoric": False, "capitulation": True}
    assert not gate_short(cap, "veto")[0] and gate_short(euph, "veto")[0] and gate_short(calm, "veto")[0]
    assert gate_short(euph, "require")[0] and not gate_short(calm, "require")[0] and not gate_short(cap, "require")[0]
    assert not gate_long(euph, "veto")[0]          # long gate unchanged


def test_signalbook_short_confluence_and_exit():
    book = SignalBook(cfg.signals)
    book.record(Signal("wy_utad", SYM, ts=T0))
    assert not book.armed_short(SYM, T0 + 60)[0]                    # no SMC bias yet
    book.record(Signal("smc_bear_choch", SYM, ts=T0 + 60))
    assert book.armed_short(SYM, T0 + 120)[0] and not book.armed_long(SYM, T0 + 120)[0]
    book.record(Signal("wy_spring", SYM, ts=T0 + 180))              # bullish Wyckoff after the trigger
    assert not book.armed_short(SYM, T0 + 240)[0]
    assert book.exit_signal(SYM, T0 + 100, T0 + 300, side="sell") == "wy_spring"
    assert book.exit_signal(SYM, T0 + 100, T0 + 300, side="buy") is None


def test_agent_enters_short_then_exits_on_bullish_event():
    c = copy.deepcopy(cfg)
    c.plan.sides = "both"
    ms = down_ms(last_swing_high=75.3, last_swing_low=70.0, resistance=75.3)
    ex = PaperExecutor(1000)
    agent = TradeAgent(c, SignalBook(c.signals), RiskGate(c.risk, kill_file="/nonexistent/KILL"), ex,
                       lambda s: (70.0, 2.0, ms, "down"), lambda: ex.equity)
    agent.on_signal(Signal("smc_bear_bos", SYM, ts=T0))
    msg = agent.on_signal(Signal("wy_lpsy", SYM, price=70.0, ts=T0 + 60))
    assert "ENTER SHORT" in msg and ex.positions[SYM].plan.side == "sell"
    assert "ignored" in agent.on_signal(Signal("wy_sow", SYM, ts=T0 + 120))     # bearish while short: ignore
    assert "EXIT short" in agent.on_signal(Signal("wy_sos", SYM, price=72.0, ts=T0 + 180))
    assert not ex.positions and ex.equity < 1000                                 # covered above entry


def test_agent_long_only_ignores_bearish_triggers():
    ms = down_ms(last_swing_high=75.3, last_swing_low=70.0, resistance=75.3)
    ex = PaperExecutor(1000)
    agent = TradeAgent(cfg, SignalBook(cfg.signals), RiskGate(cfg.risk, kill_file="/nonexistent/KILL"), ex,
                       lambda s: (70.0, 2.0, ms, "down"), lambda: ex.equity)
    agent.on_signal(Signal("smc_bear_bos", SYM, ts=T0))
    assert "noted" in agent.on_signal(Signal("wy_lpsy", SYM, ts=T0 + 60)) and not ex.positions
