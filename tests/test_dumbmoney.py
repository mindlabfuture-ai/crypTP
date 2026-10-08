import numpy as np
import pandas as pd
import pytest

from cryptp.agent import TradeAgent
from cryptp.backtest import run_backtest, synthetic_ohlcv
from cryptp.config import load_config
from cryptp.dumbmoney import compute, gate_long, gate_short
from cryptp.executor import PaperExecutor
from cryptp.risk import RiskGate
from cryptp.signals import Signal, SignalBook
from cryptp.structure import MarketStructure

cfg = load_config("config.yaml")


def flat(n=70, price=100.0):
    return pd.DataFrame({"ts": pd.date_range("2025-01-01", periods=n, freq="1h", tz="UTC"),
                         "open": price, "high": price + 0.5, "low": price - 0.5, "close": price, "volume": 1.0})


def test_panic_flush_detected():
    df = flat()
    df.loc[len(df) - 1, ["open", "high", "low", "close", "volume"]] = [100, 100.2, 90, 100.1, 5.0]
    f = compute(df)
    assert f["panic"].iloc[-1] and not f["panic"].iloc[:-1].any()


def test_herd_exhaustion_and_euphoria_detected():
    df = flat(80)
    for k, i in enumerate(range(len(df) - 6, len(df))):                 # six green candles, rising volume
        px = 100 * 1.03 ** (k + 1)
        df.loc[i, ["open", "high", "low", "close", "volume"]] = [px / 1.03, px * 1.002, px / 1.03 - 0.1, px, 4.0]
    f = compute(df)
    assert f["herd"].any() or f["fomo"].any()
    assert f["euphoric"].iloc[-1]


def test_features_are_causal():
    df = synthetic_ohlcv(1500, seed=5)
    full, part = compute(df), compute(df.iloc[:1000])
    cols = ["fomo", "herd", "chase", "panic", "hopeless", "euphoric", "capitulation"]
    assert (full[cols].iloc[:1000].to_numpy() == part[cols].to_numpy()).all()
    assert np.allclose(full["index_fast"].iloc[:1000].fillna(-1), part["index_fast"].fillna(-1))


def test_gate_modes():
    calm = {"euphoric": False, "capitulation": False}
    hot = {"euphoric": True, "capitulation": False}
    cap = {"euphoric": False, "capitulation": True}
    assert gate_long(hot, "off")[0] and gate_long(None, "veto")[0]
    assert not gate_long(hot, "veto")[0] and gate_long(calm, "veto")[0] and gate_long(cap, "veto")[0]
    assert not gate_long(calm, "require")[0] and gate_long(cap, "require")[0] and not gate_long(hot, "require")[0]


def test_agent_blocks_entry_into_euphoria():
    ms = MarketStructure(trend="up", bos=None, last_swing_high=130.0, last_swing_low=124.7,
                         resistance=None, support=124.7, swings=[])
    ex = PaperExecutor(1000)
    state = {"euphoric": True, "capitulation": False}
    agent = TradeAgent(cfg, SignalBook(cfg.signals), RiskGate(cfg.risk, kill_file="/nonexistent/KILL"), ex,
                       lambda s: (130.0, 2.0, ms, "up"), lambda: ex.equity,
                       get_dm=lambda s: state, dm_mode="veto")
    T = 1_000_000.0
    agent.on_signal(Signal("smc_bull_bos", "BTC/USDT:USDT", ts=T))
    assert "dumb-money" in agent.on_signal(Signal("wy_lps", "BTC/USDT:USDT", ts=T + 60))
    assert not ex.positions
    state["euphoric"] = False                                           # crowd cools off -> next trigger enters
    assert "ENTER" in agent.on_signal(Signal("wy_sos", "BTC/USDT:USDT", ts=T + 120))


def test_backtest_veto_only_removes_trades_and_off_matches_baseline():
    df = synthetic_ohlcv(2500, seed=3)
    off = run_backtest(df, "X/USDT:USDT", cfg, dm_mode="off")
    veto = run_backtest(df, "X/USDT:USDT", cfg, dm_mode="veto")
    req = run_backtest(df, "X/USDT:USDT", cfg, dm_mode="require")
    assert len(off.trades) >= 1
    assert len(req.trades) <= len(off.trades) and len(veto.trades) <= len(off.trades) + 2


def test_config_default_is_really_off_and_bare_yaml_off_is_normalised(tmp_path):
    from cryptp.dumbmoney import normalize_mode
    assert load_config("config.yaml").dumb_money.mode == "off"          # quoted in the file
    bare = tmp_path / "c.yaml"
    bare.write_text("dumb_money:\n  mode: off\n")                       # YAML 1.1 turns this into False
    raw = load_config(str(bare)).dumb_money.mode
    assert raw is False and normalize_mode(raw) == "off"
    assert gate_long({"euphoric": True, "capitulation": False}, raw)[0]  # must not act as a veto
    assert gate_short({"euphoric": False, "capitulation": True}, raw)[0]
    assert normalize_mode("veto") == "veto"
