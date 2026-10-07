import numpy as np
import pandas as pd
import pytest

from cryptp.backtest import synthetic_ohlcv
from cryptp.hourly import HourlyParams, find_signals, run_hourly, to_hourly


def hb(rows, start="2025-03-03 20:00"):
    ts = pd.date_range(start, periods=len(rows), freq="1h", tz="UTC")
    o, h, l, c = zip(*rows)
    return pd.DataFrame({"ts": ts, "open": o, "high": h, "low": l, "close": c, "volume": 1.0})


def run(rows, start="2025-03-03 18:00", p=None, **kw):
    df = hb(rows, start)
    p = p or HourlyParams(min_stop_pct=0, max_stop_pct=100, cooldown_bars=0, cutoff_hour=24)
    sig = {0: 1.0}                                   # ATR 1.0 -> stop = fill - 2.0, R = 2.0
    return df, run_hourly(df, "X", p, fee_rate=0.0, slippage_bps=0.0, signals=sig, charge_funding=False, **kw)


def flatbar(px):
    return (px, px + 0.1, px - 0.1, px)


def test_midnight_moves_stop_to_breakeven_only_when_in_profit():
    # entry bar 19:00 open 100 (stop 98). Midnight bar (23:00) closes 101 > entry -> stop to 100 effective next bar.
    rows = [(100, 100.2, 99.9, 100), (100, 101.2, 99.8, 100.5), flatbar(100.5), flatbar(100.6), (100.6, 101.2, 100.5, 101.0),
            (101.0, 101.2, 99.9, 100.2), (100.2, 100.3, 99.9, 100.0)]
    df, r = run(rows, "2025-03-03 18:00")
    t = r.trades[0]
    assert t.exit_ts == pd.Timestamp("2025-03-04 00:00", tz="UTC")           # next bar: low 99.9 <= BE stop 100
    assert t.r == pytest.approx(0.0) and r.be_stopped == 1 and r.be_moved_trades == 1


def test_midnight_leaves_stop_alone_when_not_in_profit():
    rows = [(100, 100.2, 99.9, 100), (100, 100.3, 99.5, 99.7), flatbar(99.7), flatbar(99.7), (99.7, 99.8, 99.0, 99.6),
            (99.6, 99.7, 98.5, 99.0), flatbar(99.0)]
    df, r = run(rows, "2025-03-03 18:00")
    t = r.trades[0]
    assert r.be_moved_trades == 0 and r.trade_notes == ["end"]              # still open at the end: the stop was never raised
    assert t.r == pytest.approx(-0.5)


def test_midnight_flat_variant_closes_the_trade():
    rows = [(100, 100.2, 99.9, 100), (100, 101.2, 99.8, 100.5), flatbar(100.5), flatbar(100.6), (100.6, 101.2, 100.5, 101.0),
            (101.0, 101.2, 100.9, 101.0), flatbar(101.0)]
    p = HourlyParams(min_stop_pct=0, max_stop_pct=100, cooldown_bars=0, cutoff_hour=24, midnight="flat")
    df, r = run(rows, "2025-03-03 18:00", p=p)
    assert r.trades[0].exit_ts == pd.Timestamp("2025-03-03 23:00", tz="UTC") and r.trade_notes == ["flat"]


def test_signals_are_causal_and_use_closed_daily_state_only():
    df15 = synthetic_ohlcv(24 * 4 * 40, seed=11)
    h = to_hourly(df15)
    daily = h.set_index("ts").resample("1D").agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna().reset_index()
    p = HourlyParams(sma_days=5)
    full = find_signals(h, p, daily)
    cut = 600
    part = find_signals(h.iloc[:cut].reset_index(drop=True), p, daily)
    assert {k: v for k, v in full.items() if k < cut - 1} == {k: v for k, v in part.items() if k < cut - 1}
    assert len(full) > 3


def test_no_profit_taking_before_3r_then_lock_effective_next_bar():
    # R = 2.0: +3R = 106, lock = 103.  Bar 2 hits 106.5 and trades down to 99 the same bar: initial stop 98 still protects, no exit.
    rows = [(100, 100.2, 99.9, 100), (100, 100.5, 99.5, 100.2), (100.2, 106.5, 99.0, 105.0), (105.0, 105.5, 102.0, 104.0),
            (104.0, 104.1, 102.5, 103.0), flatbar(103.0)]
    df, r = run(rows, "2025-03-03 08:00", p=HourlyParams(min_stop_pct=0, max_stop_pct=100, cooldown_bars=0, cutoff_hour=24, trail_atr=100.0))
    t = r.trades[0]
    assert t.exit_ts == df["ts"].iloc[3] and t.r == pytest.approx(1.5)         # bar 3 low 102 <= lock 103: stopped there, not in bar 2
