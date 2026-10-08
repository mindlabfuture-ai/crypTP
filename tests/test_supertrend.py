import numpy as np
import pandas as pd
import pytest

from cryptp.backtest import synthetic_ohlcv
from cryptp.supertrend import rma, supertrend
from cryptp.trend import evaluate_signals


def frame(closes, spread=0.5):
    c = np.asarray(closes, float)
    o = np.r_[c[0], c[:-1]]
    return pd.DataFrame({"ts": pd.date_range("2022-01-01", periods=len(c), freq="1D", tz="UTC"), "open": o,
                         "high": np.maximum(o, c) + spread, "low": np.minimum(o, c) - spread, "close": c, "volume": 1.0})


def test_rma_seed_and_recursion():
    x = np.array([1.0, 2, 3, 4, 5, 6])
    out = rma(x, 3)
    assert np.isnan(out[:2]).all() and out[2] == pytest.approx(2.0)                 # SMA seed
    assert out[3] == pytest.approx((2.0 * 2 + 4) / 3) and out[4] == pytest.approx((out[3] * 2 + 5) / 3)


def test_flips_down_on_a_crash_and_back_up_on_a_rally():
    closes = np.r_[np.linspace(100, 140, 60), np.linspace(140, 80, 40), np.linspace(80, 150, 60)]
    buy, sell, trend, up, dn = supertrend(frame(closes))
    assert sell.any() and buy.any()
    first_sell, first_buy_after = sell.idxmax(), None
    after = buy[first_sell:]
    assert after.any()
    assert closes[first_sell] < 140 and closes[after.idxmax()] > 80                 # sell during the fall, buy during the rally
    assert not (buy & sell).any()


def test_signals_alternate_and_band_ratchets_in_a_trend():
    df = synthetic_ohlcv(3000, seed=5)
    buy, sell, trend, up, dn = supertrend(df)
    events = [("b" if b else "s") for b, s in zip(buy, sell) if b or s]
    assert len(events) > 6 and all(a != b for a, b in zip(events, events[1:]))      # strictly alternating
    run_up = (trend == 1) & (trend.shift() == 1)
    d = up.diff()[run_up].dropna()
    assert (d >= -1e-12).all()                                                       # lower band never falls inside an uptrend
    run_dn = (trend == -1) & (trend.shift() == -1)
    assert (dn.diff()[run_dn].dropna() <= 1e-12).all()                               # upper band never rises inside a downtrend


def test_causal():
    df = synthetic_ohlcv(2000, seed=8)
    b1, s1, *_ = supertrend(df)
    b2, s2, *_ = supertrend(df.iloc[:1300])
    assert (b1.iloc[:1300].to_numpy() == b2.to_numpy()).all() and (s1.iloc[:1300].to_numpy() == s2.to_numpy()).all()


def test_engine_goes_long_then_short_on_flips_and_long_only_goes_flat():
    closes = np.r_[np.linspace(100, 140, 80), np.linspace(140, 70, 60), np.linspace(70, 150, 80)]
    df = frame(closes)
    buy, sell, *_ = supertrend(df)
    both = evaluate_signals(df, buy, sell, long_only=False, fee_rate=0, slippage_bps=0, warmup=20)
    flat = evaluate_signals(df, buy, sell, long_only=True, fee_rate=0, slippage_bps=0, warmup=20)
    assert both["trades"] >= 2 and flat["time_in_market_pct"] < both["time_in_market_pct"]
    assert both["strat"]["total_pct"] != flat["strat"]["total_pct"]
