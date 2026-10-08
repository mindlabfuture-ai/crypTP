import numpy as np
import pandas as pd
import pytest

from cryptp.trend import evaluate, sma_trend_signals


def daily(closes, opens=None):
    c = np.asarray(closes, float)
    o = c if opens is None else np.asarray(opens, float)
    return pd.DataFrame({"ts": pd.date_range("2022-01-01", periods=len(c), freq="1D", tz="UTC"), "open": o,
                         "high": np.maximum(o, c) * 1.01, "low": np.minimum(o, c) * 0.99, "close": c, "volume": 1.0})


def test_signal_is_close_vs_sma_and_causal():
    rng = np.random.default_rng(0)
    df = daily(100 * np.exp(np.cumsum(rng.normal(0, 0.02, 600))))
    ls, ss = sma_trend_signals(df, 50)
    assert not (ls & ss).any() and not ls.iloc[:49].any() and not ss.iloc[:49].any()
    ls2, _ = sma_trend_signals(df.iloc[:400], 50)
    assert (ls.iloc[:400].to_numpy() == ls2.to_numpy()).all()                    # no lookahead


def test_steady_uptrend_tracks_buy_and_hold_with_one_trade():
    df = daily(100 * 1.002 ** np.arange(600))
    r = evaluate(df, 50, fee_rate=0.00055, slippage_bps=2)
    assert r["trades"] == 1 and r["time_in_market_pct"] > 95
    assert r["strat"]["total_pct"] == pytest.approx(r["hold"]["total_pct"], rel=0.05)
    assert r["strat"]["total_pct"] < r["hold"]["total_pct"]                       # costs and the first-bar lag


def test_downtrend_stays_flat_and_loses_nothing_long_only():
    df = daily(100 * 0.998 ** np.arange(600))
    r = evaluate(df, 50)
    assert r["trades"] == 0 and r["strat"]["total_pct"] == pytest.approx(0.0, abs=1e-9)
    assert r["hold"]["total_pct"] < -20 and r["strat"]["max_dd_pct"] == pytest.approx(0.0, abs=1e-9)


def test_long_short_profits_in_downtrend_and_costs_reduce_it():
    df = daily(100 * 0.998 ** np.arange(600))
    free = evaluate(df, 50, long_only=False, fee_rate=0, slippage_bps=0)
    paid = evaluate(df, 50, long_only=False, fee_rate=0.001, slippage_bps=10)
    assert free["strat"]["total_pct"] > 0 and paid["strat"]["total_pct"] < free["strat"]["total_pct"]


def test_fills_at_next_open_not_signal_close():
    base = 100 * 1.001 ** np.arange(300)
    opens = base.copy()
    opens[-1] = opens[-1] * 5                                   # absurd last open must not matter for earlier fills
    df = daily(base, opens)
    r = evaluate(df, 50, fee_rate=0, slippage_bps=0)
    assert r["trades"] == 1
