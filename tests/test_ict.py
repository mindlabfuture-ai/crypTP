import numpy as np
import pandas as pd
import pytest

from cryptp.backtest import synthetic_ohlcv
from cryptp.ict import IctParams, Setup, detect_setups, in_killzone, prepare, run_ict, vwap_arrays
from cryptp.indicators import atr


def frame(rows, start="2025-03-03 08:00"):
    ts = pd.date_range(start, periods=len(rows), freq="15min", tz="UTC")
    o, h, l, c = zip(*rows)
    return pd.DataFrame({"ts": ts, "open": o, "high": h, "low": l, "close": c, "volume": 1.0})


def long_sweep_series():
    """Hand-built: a clear swing low at bar 10 (100), then a sweep to 99 closing back at 100.6, a shift above the prior highs with a bullish FVG."""
    rows = []
    px = 105.0
    for i in range(10):                                   # drift down into a swing low
        rows.append((px, px + 0.3, px - 0.5, px - 0.4)); px -= 0.5
    rows.append((100.2, 100.8, 99.9, 100.5))              # 10 swing low 99.9 (strictly below bar 9's 100.0)
    for i in range(6):                                    # 11..16: bounce, keeps the swing confirmed
        rows.append((100.5 + i * 0.2, 101.2 + i * 0.2, 100.4 + i * 0.2, 100.9 + i * 0.2))
    rows.append((101.5, 101.6, 99.0, 100.6))              # 17 sweep: low 99 < 100, close 100.6 > 100
    rows.append((100.6, 101.0, 100.5, 100.9))             # 18
    rows.append((101.7, 103.0, 101.7, 102.8))             # 19 displacement: closes above the 5-bar high; low 101.7 > high[17] 101.6 -> bullish FVG (17,18,19)
    rows.append((102.8, 104.5, 102.4, 104.0))             # 20 low 102.4 > high[18]=101.0 -> bullish FVG between 18 and 20
    return rows


def test_vwap_is_causal_and_anchored_at_midnight():
    df = synthetic_ohlcv(400, seed=2)
    prev, pos = vwap_arrays(df)
    d2 = df.copy()
    d2.loc[200:, "close"] *= 3.0
    d2.loc[200:, "high"] *= 3.0
    prev2, _ = vwap_arrays(d2)
    assert np.allclose(prev[:200], prev2[:200], equal_nan=True)            # future bars change nothing
    first_of_day = np.flatnonzero(pos == 0)
    assert np.isnan(prev[first_of_day]).all()                              # nothing before the anchor bar completes


def test_killzone_hours():
    assert in_killzone(7) and in_killzone(9) and in_killzone(12) and in_killzone(14)
    assert not in_killzone(10) and not in_killzone(11) and not in_killzone(15) and not in_killzone(3)


def test_detects_sweep_shift_fvg_long_only_after_completion():
    df = frame(long_sweep_series())
    p = IctParams()
    a = atr(df).to_numpy(float)
    setups, cnt = detect_setups(df, p, a)
    assert cnt["sweeps_long"] >= 1 and cnt["shifts_long"] >= 1
    longs = [s for v in setups.values() for s in v if s.d > 0]
    assert longs and all(s.m >= 19 for s in longs)                         # nothing exists before the shift bar closes
    s = longs[0]
    assert s.stop_raw < 99.0 and s.ce > 100.0 and s.d == 1


def test_setups_are_causal_prefix():
    df = synthetic_ohlcv(3000, seed=4)
    p = IctParams()
    a = atr(df).to_numpy(float)
    full, _ = detect_setups(df, p, a)
    cut = 2000
    part, _ = detect_setups(df.iloc[:cut].reset_index(drop=True), p, a[:cut])
    f = {m: [(s.d, round(s.ce, 8), round(s.stop_raw, 8)) for s in v] for m, v in full.items() if m < cut - 15}
    q = {m: [(s.d, round(s.ce, 8), round(s.stop_raw, 8)) for s in v] for m, v in part.items() if m < cut - 15}
    assert f == q and len(f) > 5


def test_short_is_exact_mirror_of_long():
    df = synthetic_ohlcv(30000, seed=5)
    C = 2 * df["high"].max()
    r = df.copy()
    r["open"], r["close"] = C - df["open"], C - df["close"]
    r["high"], r["low"] = C - df["low"], C - df["high"]
    p = IctParams(use_killzone=False, min_stop_pct=0.0, max_stop_pct=1e6, max_leverage=1e6)
    a = run_ict(df, "X", p, 0.0, 0.0, charge_funding=False).trades
    b = run_ict(r, "X", p, 0.0, 0.0, charge_funding=False).trades
    assert len(a) > 20
    assert [(t.entry_ts, t.side) for t in a] == [(t.entry_ts, "sell" if t.side == "buy" else "buy") for t in b]
    assert np.allclose([t.r for t in a], [t.r for t in b], atol=1e-6)
    assert {t.side for t in a} == {"buy", "sell"}


def run_manual(rows, setup, **kw):
    df = frame(rows)
    kw = dict(dict(trail_atr=100.0), **kw)                                  # trail never binds: only the +1.5R lock is tested
    p = IctParams(use_killzone=False, use_vwap=False, use_bias=False, min_stop_pct=0, max_stop_pct=1e6, cooldown_bars=0, **kw)
    prep = prepare(df, p)
    prep.setups = {setup.m: [setup]}
    return df, run_ict(df, "X", p, 0.0, 0.0, charge_funding=False, prep=prep)


def test_limit_fill_stop_lock_and_midnight_breakeven():
    # long: CE 100, stop 98 (R=2). Bar 3 trades down to 100 -> fills at 100. Bar 4 reaches +3R (106): arm; lock 103 effective NEXT bar.
    rows = [(101, 101.2, 100.8, 101)] * 3 + [(101, 101.1, 99.9, 100.5), (100.5, 106.5, 99.0, 105.5), (105.5, 105.8, 102.5, 103.0),
                                              (103, 103.2, 102.0, 102.5)]
    df, r = run_manual(rows, Setup(1, 2, 100.0, 98.0, 6))
    t = r.trades[0]
    assert t.entry == pytest.approx(100.0) and t.exit_ts == df["ts"].iloc[5] and t.r == pytest.approx(1.5)


def test_filters_block_when_killzone_required():
    rows = [(101, 101.2, 100.8, 101)] * 3 + [(101, 101.1, 99.9, 100.5)] + [(100.5, 100.7, 100.2, 100.4)] * 4   # bar 3 is 08:45, outside the zones
    df = frame(rows, "2025-03-03 10:15")
    p = IctParams(use_vwap=False, use_bias=False, min_stop_pct=0, max_stop_pct=1e6)
    prep = prepare(df, p)
    prep.setups = {2: [Setup(1, 2, 100.0, 98.0, 6)]}
    r = run_ict(df, "X", p, 0.0, 0.0, charge_funding=False, prep=prep)
    assert not r.trades and r.filtered["killzone"] == 1


# ---- SMC order-block model ----
from cryptp.ict import detect_setups_smc


def smc_series():
    """Down-drift forming a swing high at bar 12 (105), a bearish candle (the order block) at bar 18, then an impulse that closes above 105."""
    rows, px = [], 100.0
    for i in range(12):
        rows.append((px, px + 0.5, px - 0.3, px + 0.3)); px += 0.4
    rows.append((104.6, 105.0, 104.2, 104.4))             # 12 swing high 105.0
    for i in range(5):                                     # 13..17 fall back (confirms the swing), small candles
        rows.append((104.4 - i * 0.4, 104.6 - i * 0.4, 103.9 - i * 0.4, 104.0 - i * 0.4))
    rows.append((102.6, 102.7, 101.8, 102.0))             # 18 bearish candle = order block [101.8, 102.7]
    rows.append((102.0, 102.4, 101.9, 102.3))             # 19
    rows.append((102.3, 106.0, 102.2, 105.9))             # 20 impulse: closes above 105, near its high, large range
    rows.append((105.9, 106.1, 105.5, 105.8))
    return rows


def test_smc_detects_bos_impulse_order_block_and_stop():
    df = frame(smc_series())
    p = IctParams(model="smc")
    a = atr(df).to_numpy(float)
    setups, cnt = detect_setups_smc(df, p, a)
    longs = [s for v in setups.values() for s in v if s.d > 0]
    assert cnt["bos_long"] >= 1 and cnt["impulse_long"] >= 1 and len(longs) == 1
    s = longs[0]
    assert s.m == 20 and s.ce == pytest.approx((101.8 + 102.7) / 2) and s.stop_raw < 101.8


def test_smc_requires_an_impulse():
    rows = smc_series()
    rows[20] = (102.3, 105.1, 102.2, 105.05)               # breaks 105 but with a small range relative to ATR? keep range small
    df = frame(rows)
    a = atr(df).to_numpy(float)
    on, _ = detect_setups_smc(df, IctParams(model="smc", impulse_atr=50.0), a)
    off, _ = detect_setups_smc(df, IctParams(model="smc", use_impulse=False), a)
    assert not [s for v in on.values() for s in v if s.d > 0]
    assert [s for v in off.values() for s in v if s.d > 0]


def test_smc_setups_are_causal_prefix():
    df = synthetic_ohlcv(4000, seed=9)
    p = IctParams(model="smc")
    a = atr(df).to_numpy(float)
    full, _ = detect_setups_smc(df, p, a)
    cut = 2500
    part, _ = detect_setups_smc(df.iloc[:cut].reset_index(drop=True), p, a[:cut])
    f = {m: [(s.d, round(s.ce, 8), round(s.stop_raw, 8)) for s in v] for m, v in full.items() if m < cut - 25}
    q = {m: [(s.d, round(s.ce, 8), round(s.stop_raw, 8)) for s in v] for m, v in part.items() if m < cut - 25}
    assert f == q and len(f) > 5


def test_smc_short_is_exact_mirror_of_long():
    df = synthetic_ohlcv(30000, seed=6)
    C = 2 * df["high"].max()
    r = df.copy()
    r["open"], r["close"] = C - df["open"], C - df["close"]
    r["high"], r["low"] = C - df["low"], C - df["high"]
    p = IctParams(model="smc", use_killzone=False, min_stop_pct=0.0, max_stop_pct=1e6, max_leverage=1e6)
    a = run_ict(df, "X", p, 0.0, 0.0, charge_funding=False).trades
    b = run_ict(r, "X", p, 0.0, 0.0, charge_funding=False).trades
    assert len(a) > 20
    assert [(t.entry_ts, t.side) for t in a] == [(t.entry_ts, "sell" if t.side == "buy" else "buy") for t in b]
    assert np.allclose([t.r for t in a], [t.r for t in b], atol=1e-6)
    assert {t.side for t in a} == {"buy", "sell"}
