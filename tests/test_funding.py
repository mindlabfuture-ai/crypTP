import numpy as np
import pandas as pd
import pytest

from cryptp.funding import daily_funding, perp_buy_and_hold
from cryptp.popular import run_reversal


def daily(closes):
    c = np.asarray(closes, float)
    return pd.DataFrame({"ts": pd.date_range("2024-01-01", periods=len(c), freq="1D", tz="UTC"), "open": c,
                         "high": c * 1.001, "low": c * 0.999, "close": c, "volume": 1.0})


def sig(n, at):
    s = pd.Series(False, index=range(n))
    s.iloc[list(at)] = True
    return s


def test_daily_funding_sums_the_three_settlements_of_each_day():
    df = daily([100] * 3)
    ts = pd.to_datetime(["2024-01-01 00:00", "2024-01-01 08:00", "2024-01-01 16:00", "2024-01-02 00:00"], utc=True)
    f, n = daily_funding(df, pd.DataFrame({"ts": ts, "rate": [0.0001, 0.0002, -0.00005, 0.0003]}))
    assert f.tolist() == pytest.approx([0.00025, 0.0003, 0.0]) and n.tolist() == [3, 1, 0]


def test_long_pays_positive_funding_while_held_and_flat_pays_nothing():
    df = daily([100.0] * 12)
    ls, ss = sig(12, [2]), sig(12, [7])                       # long signal at bar 2 -> in at open 3; flat signal at 7 -> out at open 8
    f = np.full(12, 0.001)
    free = run_reversal(df, ls, ss, long_only=True, fee_rate=0, slippage_bps=0, warmup=0, equity0=1000)
    paid = run_reversal(df, ls, ss, long_only=True, fee_rate=0, slippage_bps=0, warmup=0, equity0=1000, funding=f)
    assert free.trades[0].pnl == pytest.approx(0.0)
    assert paid.trades[0].pnl == pytest.approx(0.0, abs=1e-9) and paid.equity.iloc[-1] == pytest.approx(1000 - 5 * 0.001 * 1000)   # held bars 3..7
    assert paid.equity.iloc[2] == pytest.approx(1000.0)        # nothing charged before the position existed
    assert paid.equity.iloc[-1] == pytest.approx(995.0)        # nothing charged after it closed (bars 8..11)


def test_negative_funding_pays_longs_and_positive_funding_pays_shorts():
    df = daily([100.0] * 10)
    f = np.full(10, 0.001)
    long_ = run_reversal(df, sig(10, [1]), sig(10, []), fee_rate=0, slippage_bps=0, warmup=0, equity0=1000, funding=-f)
    short = run_reversal(df, sig(10, []), sig(10, [1]), fee_rate=0, slippage_bps=0, warmup=0, equity0=1000, funding=f)
    assert long_.equity.iloc[-1] > 1000 and short.equity.iloc[-1] > 1000


def test_perp_buy_and_hold_with_zero_funding_equals_price_return():
    c = pd.Series(100 * 1.01 ** np.arange(50))
    assert perp_buy_and_hold(c, np.zeros(50)).iloc[-1] == pytest.approx(c.iloc[-1] / c.iloc[0])
    assert perp_buy_and_hold(c, np.full(50, 0.001)).iloc[-1] < c.iloc[-1] / c.iloc[0]
