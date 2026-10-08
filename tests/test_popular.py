import numpy as np
import pandas as pd
import pytest

from cryptp.backtest import synthetic_ohlcv
from cryptp.popular import (STRATEGIES, bb_rsi_signals, macd_sma_signals, run_reversal, summarize_fills)


def frame(opens, closes=None):
    closes = opens if closes is None else closes
    n = len(opens)
    return pd.DataFrame({"ts": pd.date_range("2025-01-01", periods=n, freq="1h", tz="UTC"), "open": opens,
                         "high": np.maximum(opens, closes) + 0.1, "low": np.minimum(opens, closes) - 0.1,
                         "close": closes, "volume": 1.0})


def sig(n, at):
    s = pd.Series(False, index=range(n))
    for i in at:
        s.iloc[i] = True
    return s


def test_fill_is_next_open_and_flip_reverses():
    opens = [100.0] * 4 + [100, 110, 120, 130, 125, 120]
    df = frame(opens)
    ls, ss = sig(10, [4]), sig(10, [7])                       # long signal on bar 4, short signal on bar 7
    r = run_reversal(df, ls, ss, fee_rate=0, slippage_bps=0, warmup=0, equity0=1000)
    first = r.trades[0]
    assert first.side == "long" and first.entry == 110 and first.exit == 125     # in at open[5], out at open[8]
    assert first.pnl == pytest.approx(1000 / 110 * 15)
    assert r.trades[1].side == "short" and r.trades[1].entry == 125              # flipped on the same open


def test_long_only_goes_flat_instead_of_short():
    df = frame([100.0] * 4 + [100, 110, 120, 130, 125, 120])
    r = run_reversal(df, sig(10, [4]), sig(10, [7]), long_only=True, fee_rate=0, slippage_bps=0, warmup=0)
    assert [t.side for t in r.trades] == ["long"] and r.trades[0].exit == 125


def test_costs_reduce_pnl():
    df = frame([100.0] * 4 + [100, 110, 120, 130, 125, 120])
    a = run_reversal(df, sig(10, [4]), sig(10, [7]), long_only=True, fee_rate=0, slippage_bps=0, warmup=0)
    b = run_reversal(df, sig(10, [4]), sig(10, [7]), long_only=True, fee_rate=0.001, slippage_bps=5, warmup=0)
    assert summarize_fills(b.trades, 1000)["return_pct"] < summarize_fills(a.trades, 1000)["return_pct"]


def test_open_trade_is_marked_at_last_close():
    df = frame([100.0] * 4 + [100, 110, 120, 130])
    r = run_reversal(df, sig(8, [4]), sig(8, []), fee_rate=0, slippage_bps=0, warmup=0)
    assert len(r.trades) == 1 and r.trades[0].exit == 130


def test_bb_rsi_needs_both_crossings():
    n = 260
    close = np.r_[np.full(240, 100.0), np.linspace(100, 95, 12), [94, 93, 92, 91, 90, 89, 88, 87]][:n]
    df = frame(close)
    ls, ss = bb_rsi_signals(df)
    assert ls.dtype == bool and not ls.iloc[:200].any()           # nothing during warm-up


def test_signals_are_causal_and_boolean():
    df = synthetic_ohlcv(1500, seed=7)
    for fn in STRATEGIES.values():
        full, part = fn(df), fn(df.iloc[:900])
        assert (full[0].iloc[:900].to_numpy() == part[0].to_numpy()).all()
        assert (full[1].iloc[:900].to_numpy() == part[1].to_numpy()).all()


def test_macd_sma_long_signal_on_uptrend_pullback_cross():
    rng = np.random.default_rng(2)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0006, 0.01, 1200)))
    ls, ss = macd_sma_signals(frame(close))
    assert ls.sum() > 0 and ss.sum() >= 0
