import pandas as pd
import pytest

from cryptp.config import load_config
from cryptp.executor import LiveExecutor, PaperExecutor
from cryptp.planner import TradePlan, build_plan
from cryptp.risk import RiskGate, position_size
from cryptp.screener import rank
from cryptp.structure import analyze

cfg = load_config("config.yaml")


def zigzag(n_waves=6, up=True):
    """Synthetic trend: each wave rises 10 then retraces 5 (HH/HL)."""
    closes, p = [], 100.0
    for _ in range(n_waves):
        for _ in range(8):
            p += 1.25 if up else -1.25
            closes.append(p)
        for _ in range(8):
            p -= 0.625 if up else -0.625
            closes.append(p)
    c = pd.Series(closes)
    return pd.DataFrame({"open": c.shift().fillna(c[0]), "high": c + 0.3, "low": c - 0.3,
                         "close": c, "volume": 1.0})


def test_uptrend_detected():
    assert analyze(zigzag(up=True)).trend == "up"


def test_downtrend_detected():
    assert analyze(zigzag(up=False)).trend == "down"


def test_plan_rejected_when_htf_down():
    ms = analyze(zigzag())
    assert build_plan("X", 100, 1, ms, "down", cfg.plan) is None


def test_plan_geometry():
    df = zigzag()
    ms = analyze(df)
    price = float(df["close"].iloc[-1])
    ms.resistance = None
    plan = build_plan("X", price, 2.0, ms, "up", cfg.plan)
    assert plan and plan.stop < plan.entry
    assert plan.targets[0] == pytest.approx(plan.entry + plan.risk_per_unit)
    assert sum(plan.fractions) == pytest.approx(1.0)


def test_position_size_risks_expected_amount():
    plan = TradePlan("X", "buy", 100, 98, [102], [1.0], 2.0)
    qty = position_size(1000, plan, 0.5, 10)
    assert qty * plan.risk_per_unit == pytest.approx(5.0)


def test_position_size_leverage_cap():
    plan = TradePlan("X", "buy", 100, 99.99, [102], [1.0], 0.01)
    assert position_size(1000, plan, 0.5, 3) == pytest.approx(30.0)


def test_risk_gate(tmp_path):
    gate = RiskGate(cfg.risk, kill_file=str(tmp_path / "KILL"))
    plan = TradePlan("X", "buy", 100, 98, [102], [1.0], 2.0)
    assert gate.check(plan, 1000)[0]
    gate.daily_pnl = -25
    assert not gate.check(plan, 1000)[0]
    gate.daily_pnl = 0
    (tmp_path / "KILL").write_text("")
    assert not gate.check(plan, 1000)[0]


def test_paper_tp_ladder_and_breakeven():
    plan = TradePlan("X", "buy", 100, 98, [102, 104, 106], [0.4, 0.3, 0.3], 2.0)
    ex = PaperExecutor(1000)
    ex.submit(plan, 10)
    assert ex.on_candle("X", 102.5, 99) == pytest.approx(8.0)
    assert ex.positions["X"].stop == 100
    assert ex.on_candle("X", 101, 99.5) == 0.0
    ex.on_candle("X", 101, 99.9)
    assert "X" not in ex.positions and ex.equity == pytest.approx(1008.0)


def test_paper_stop_first():
    plan = TradePlan("X", "buy", 100, 98, [102], [1.0], 2.0)
    ex = PaperExecutor(1000)
    ex.submit(plan, 10)
    assert ex.on_candle("X", 103, 97) == pytest.approx(-20.0)


def test_live_disabled_by_default(monkeypatch):
    monkeypatch.delenv("CRYPTP_ALLOW_LIVE", raising=False)
    with pytest.raises(RuntimeError):
        LiveExecutor(object())


def test_rank_prefers_strong_coin():
    rows = [
        {"symbol": "A", "rs_vs_btc": 5, "vol_surge": 3, "near_high": 0.99, "uptrend": True, "rsi": 65},
        {"symbol": "B", "rs_vs_btc": -3, "vol_surge": 0.8, "near_high": 0.7, "uptrend": False, "rsi": 40},
    ]
    assert rank(rows).iloc[0]["symbol"] == "A"
