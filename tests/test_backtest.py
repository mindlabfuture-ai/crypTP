import numpy as np
import pandas as pd
import pytest

from cryptp.backtest import (Trade, load_csv, run_backtest, split_trades, summarize,
                             synthetic_ohlcv, tf_to_pandas)
from cryptp.config import load_config
from cryptp.executor import PaperExecutor
from cryptp.planner import TradePlan

cfg = load_config("config.yaml")
SYM = "X/USDT:USDT"


def test_tf_to_pandas():
    assert tf_to_pandas("15m") == "15min" and tf_to_pandas("4h") == "4h" and tf_to_pandas("1d") == "1D"


def test_stop_gap_fills_at_open_not_stop():
    plan = TradePlan(SYM, "buy", 100, 98, [102], [1.0], 2.0)
    ex = PaperExecutor(1000)
    ex.submit(plan, 10)
    assert ex.on_candle(SYM, 96, 94, open_=95) == pytest.approx(-50.0)     # (95-100)*10, not -20


def test_fees_and_slippage_reduce_pnl():
    plan = TradePlan(SYM, "buy", 100, 98, [102], [1.0], 2.0)
    ex = PaperExecutor(1000, fee_rate=0.001, slippage=0.001)
    ex.submit(plan, 10)                                                    # entry fee 1.0
    pnl = ex.on_candle(SYM, 99, 97)                                        # stop 98 -> 97.902
    assert pnl == pytest.approx((98 * 0.999 - 100) * 10 - 98 * 0.999 * 10 * 0.001)
    assert ex.closed_pnl[-1] == pytest.approx(pnl - 1.0)                   # trade net includes entry fee


def test_summarize_hand_computed():
    ts = pd.Timestamp("2025-01-01", tz="UTC")
    t = [Trade(SYM, ts, ts, 100, 98, 20.0, 10.0, 5), Trade(SYM, ts, ts, 100, 98, -10.0, 10.0, 3),
         Trade(SYM, ts, ts, 100, 98, -10.0, 10.0, 4)]
    m = summarize(t, 1000.0)
    assert m["trades"] == 3 and m["win_rate_pct"] == pytest.approx(100 / 3)
    assert m["profit_factor"] == pytest.approx(1.0) and m["net_pnl"] == 0.0
    assert m["avg_r"] == pytest.approx(0.0)


def test_csv_roundtrip(tmp_path):
    df = synthetic_ohlcv(50)
    p = tmp_path / "x.csv"
    df.to_csv(p, index=False)
    back = load_csv(str(p))
    assert len(back) == 50 and np.allclose(back["close"], df["close"])
    ms = df.assign(ts=df["ts"].dt.as_unit("ms").astype("int64"))
    ms.to_csv(p, index=False)
    assert load_csv(str(p))["ts"].iloc[0] == df["ts"].iloc[0]


@pytest.fixture(scope="module")
def full():
    df = synthetic_ohlcv(2500, seed=3)
    return df, run_backtest(df, SYM, cfg)


def test_runs_and_produces_sane_trades(full):
    df, res = full
    assert res.trades, "synthetic trending regimes should yield at least one trade"
    for t in res.trades:
        assert t.exit_ts >= t.entry_ts and t.risk_usd > 0
        assert t.entry_ts > df["ts"].iloc[0]                               # nothing before the data
    assert res.equity.notna().all()


def test_no_lookahead_truncated_run_matches_prefix(full):
    df, res = full
    cut = 1800
    short = run_backtest(df.iloc[:cut], SYM, cfg)
    cut_ts = df["ts"].iloc[cut - 2]
    expect = [(t.entry_ts, round(t.pnl, 6)) for t in res.trades if t.exit_ts < cut_ts]
    got = [(t.entry_ts, round(t.pnl, 6)) for t in short.trades if t.exit_ts < cut_ts]
    assert expect and expect == got


def test_costs_lower_returns(full):
    df, base = full
    free = run_backtest(df, SYM, cfg, fee_rate=0.0, slippage_bps=0.0)
    assert summarize(free.trades, 1000.0)["net_pnl"] > summarize(base.trades, 1000.0)["net_pnl"]


def test_split_partitions_trades(full):
    df, res = full
    a, b, cut = split_trades(res.trades, 0.7, df)
    assert len(a) + len(b) == len(res.trades)
    assert all(t.entry_ts < cut for t in a) and all(t.entry_ts >= cut for t in b)
