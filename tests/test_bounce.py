import numpy as np
import pandas as pd
import pytest

from cryptp.backtest import synthetic_ohlcv
from cryptp.bounce import BounceParams, find_signals, run_bounce


def bars(rows, start="2025-03-03 09:00"):
    """rows: (open, high, low, close) per 15m bar."""
    ts = pd.date_range(start, periods=len(rows), freq="15min", tz="UTC")
    o, h, l, c = zip(*rows)
    return pd.DataFrame({"ts": ts, "open": o, "high": h, "low": l, "close": c, "volume": 1.0})


P = BounceParams(min_stop_pct=0.0, max_stop_pct=100.0, cooldown_bars=0)


def run(df, sig=None, **kw):
    return run_bounce(df, "X", P, fee_rate=0.0, slippage_bps=0.0, signals=sig or {0: 99.0}, charge_funding=False, **kw)


def test_signal_is_causal_and_ignores_current_bar():
    df = synthetic_ohlcv(6000, seed=7)
    p = BounceParams(lookback_bars=500)
    full = find_signals(df, p)
    cut = 3500
    assert (full[:cut] == find_signals(df.iloc[:cut], p)).all()          # truncating the future changes nothing
    d2 = df.copy()
    d2.loc[cut:, "close"] *= 0.5                                          # wreck the future
    assert (find_signals(d2, p)[:cut] == full[:cut]).all()
    assert full.sum() > 20


def test_stop_before_target_loses_one_r():
    # entry at bar1 open 100, stop 99 (R=1); bar1 drops to 98.9 -> stopped at 99
    df = bars([(100, 100.2, 99.9, 100), (100, 100.3, 98.9, 99.5), (99.5, 99.6, 99.4, 99.5)])
    t = run(df).trades
    assert len(t) == 1 and t[0].r == pytest.approx(-1.0)


def _p(**kw):
    return BounceParams(min_stop_pct=0, max_stop_pct=100, cooldown_bars=0, **kw)


def _go(df, p, **kw):
    return run_bounce(df, "X", p, fee_rate=0.0, slippage_bps=0.0, signals={0: 99.0}, charge_funding=False, **kw).trades


RUN = [(100, 100.1, 99.9, 100),                  # 0 signal bar
       (100, 100.5, 99.8, 100.2),                # 1 entry at 100 (stop 99, R=1)
       (100.2, 103.5, 100.0, 103.2),             # 2 reaches +3R this bar; not exited
       (103.2, 104.0, 102.0, 103.8),             # 3 low 102 is above the 101.5 lock
       (103.8, 104.0, 101.0, 101.2),             # 4 low 101 is below the lock
       (101.2, 101.3, 101.0, 101.1)]


def test_no_profit_taking_before_3r_then_lock():
    df = bars(RUN)
    t = _go(df, _p(trail_atr=100.0))                                      # trail never binds: only the +1.5R lock is active
    assert len(t) == 1 and t[0].exit_ts == df["ts"].iloc[4]               # survived bar 3, stopped on bar 4 at the lock
    assert t[0].r == pytest.approx(1.5)


def test_trail_follows_highest_high_and_is_gap_aware():
    df = bars(RUN)
    t = _go(df, _p(trail_atr=0.0))                                        # stop = highest high (103.5) from bar 3 on
    assert len(t) == 1 and t[0].exit_ts == df["ts"].iloc[3]
    assert t[0].r == pytest.approx(3.2)                                   # bar 3 opens 103.2 below the stop: filled at the open


def test_lock_applies_next_bar_not_same_bar():
    # bar 2 reaches +3R and ALSO trades down to 99.5 (below the 101.5 lock). The lock is not yet effective, so no stop-out in bar 2.
    rows = [(100, 100.1, 99.9, 100), (100, 100.5, 99.8, 100.2), (100.2, 103.5, 99.5, 103.0), (103.0, 103.1, 101.0, 101.2),
            (101.2, 101.3, 101.0, 101.1)]
    df = bars(rows)
    t = run(df).trades
    assert len(t) == 1 and t[0].exit_ts == df["ts"].iloc[3]               # stopped on bar 3 by the lock (101.5)
    assert t[0].r >= 1.4                                                  # locked at least ~+1.5R before slippage-free exit


def test_flat_at_end_of_utc_day_and_funding_only_when_held_through_settlement():
    rows = [(100, 100.1, 99.9, 100), (100, 100.5, 99.8, 100.2)] + [(100.2, 100.4, 100.0, 100.2)] * 100
    df = bars(rows, start="2025-03-03 22:45")                             # crosses midnight
    t = run_bounce(df, "X", BounceParams(min_stop_pct=0, max_stop_pct=100, cooldown_bars=0, cutoff_hour=24), fee_rate=0.0,
                   slippage_bps=0.0, signals={0: 99.0}, charge_funding=False).trades
    assert len(t) == 1 and t[0].exit_ts == pd.Timestamp("2025-03-03 23:45", tz="UTC")
    # held through 08:00 and 16:00? use a day-long stretch starting 07:00 so one trade crosses 08:00 and 16:00 before the day ends
    rows2 = [(100, 100.1, 99.9, 100), (100, 100.5, 99.8, 100.2)] + [(100.2, 100.4, 100.0, 100.2)] * 120
    df2 = bars(rows2, start="2025-03-03 06:45")
    f = pd.DataFrame({"ts": [pd.Timestamp("2025-03-01", tz="UTC")], "rate": [0.001]})
    r = run_bounce(df2, "X", P, fee_rate=0.0, slippage_bps=0.0, signals={0: 99.0}, funding=f, charge_funding=True)
    assert r.funding_paid > 0
    notional = r.trades[0].risk_usd / (100.0 - 99.0) * 100.0
    assert r.funding_paid == pytest.approx(2 * 0.001 * notional, rel=0.02)   # 08:00 and 16:00, not 00:00
    r0 = run_bounce(df2, "X", P, fee_rate=0.0, slippage_bps=0.0, signals={0: 99.0}, funding=f, charge_funding=False)
    assert r0.funding_paid == 0.0 and r0.trades[0].pnl > r.trades[0].pnl


def test_fixed3_control_takes_profit_at_3r():
    rows = [(100, 100.1, 99.9, 100), (100, 100.5, 99.8, 100.2), (100.2, 103.5, 100.0, 103.2), (103.2, 110, 103.0, 109)]
    t = run_bounce(bars(rows), "X", BounceParams(min_stop_pct=0, max_stop_pct=100, exit_mode="fixed3"), fee_rate=0.0,
                   slippage_bps=0.0, signals={0: 99.0}, charge_funding=False).trades
    assert len(t) == 1 and t[0].r == pytest.approx(3.0)
