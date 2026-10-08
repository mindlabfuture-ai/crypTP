import numpy as np
import pandas as pd
import pytest

from cryptp.fractalsweep import FSParams, fractal_lows, run_fractalsweep
from cryptp.indicators import atr

SYM = "X/USDT:USDT"
LVL_BAR, SIG = 40, 60                      # a fractal low at bar 40 (95.0); the sweep bar is 60


def base(n=130):
    """Strictly rising, so the only fractal low is the one planted at bar 40. The dip is a single-bar wick (close stays ~100.4)."""
    k = np.arange(n)
    c = 100 + 0.01 * k
    o = np.r_[c[0], c[:-1]]
    h, l, v = c + 0.05, c - 0.05, np.ones(n)
    l[LVL_BAR] = 95.0
    return [x.astype(float).copy() for x in (o, h, l, c, v)]


def frame(arrs):
    o, h, l, c, v = arrs
    ts = pd.date_range("2025-01-01", periods=len(o), freq="1h", tz="UTC")
    return pd.DataFrame({"ts": ts, "open": o, "high": h, "low": l, "close": c, "volume": v})


def sweep_bar(arrs, low=94.0, high=101.0, close=100.9, i=SIG):
    arrs[0][i], arrs[1][i], arrs[2][i], arrs[3][i] = arrs[3][i - 1], high, low, close
    for b in range(i + 1, len(arrs[0])):            # quiet at the close afterwards
        arrs[0][b], arrs[1][b], arrs[2][b], arrs[3][b] = close, close + 0.05, close - 0.05, close
    return arrs


def run(arrs, fee=0.0, slip=0.0, **kw):
    return run_fractalsweep(frame(arrs), SYM, FSParams(**kw), fee_rate=fee, slippage_bps=slip)


def test_fractal_lows_need_n_strictly_higher_lows_each_side_and_are_confirmed_late():
    low = np.array([5, 4, 3, 4, 5, 6, 5, 5.0, 6, 7])
    assert fractal_lows(low, 2).nonzero()[0].tolist() == [2]
    assert fractal_lows(np.array([5, 4, 3, 3, 5, 6.0]), 2).nonzero()[0].tolist() == []        # an equal neighbour is not a fractal
    assert not fractal_lows(low[:4], 2).any()                                                   # needs 2 bars after the candidate


def test_clean_sweep_enters_next_open_and_target_pays_five_r():
    arrs = sweep_bar(base())
    arrs[1][SIG + 3] = 140.0                                         # a later bar runs far past the target
    df = frame(arrs)
    r = run_fractalsweep(df, SYM, FSParams(), fee_rate=0, slippage_bps=0)
    assert len(r.trades) == 1
    t = r.trades[0]
    a = atr(df, 14).iloc[SIG]
    assert t.side == "buy" and t.entry == pytest.approx(100.9) and t.entry_ts == df["ts"].iloc[SIG + 1]
    assert t.stop == pytest.approx(94.0 - 0.1 * a)
    assert t.r == pytest.approx(5.0, rel=1e-6)


def test_no_signal_when_the_bar_does_not_close_back_above_the_level_and_the_level_is_consumed():
    arrs = sweep_bar(base(), low=94.0, high=95.4, close=94.5)        # closes below 95.0: a breakdown
    assert run(arrs).trades == []
    arrs = sweep_bar(arrs, i=SIG + 5, low=94.0, high=101.0, close=100.9)   # a later "reclaim" of the same level must not fire
    assert run(arrs).trades == []


def test_shallow_pierce_and_lower_half_close_do_not_qualify():
    assert run(sweep_bar(base(), low=94.995, high=101.0, close=100.9)).trades == []              # pierces by < 0.1 ATR
    assert run(sweep_bar(base(), low=94.0, high=101.0, close=95.5)).trades == []                 # closes in the lower half of the bar


def test_stop_floor_never_tightens_and_cap_skips_wide_stops():
    arrs = sweep_bar(base(), low=99.7, high=101.0, close=100.9)
    arrs[2][LVL_BAR] = 100.0                                          # level at 100.0: a 0.3-wide wick is a tiny natural stop
    arrs[1][SIG + 2] = 150.0
    t = run(arrs).trades[0]
    assert t.stop == pytest.approx(100.9 * 0.98)                       # widened to the 2% floor
    wide = sweep_bar(base(), low=80.0, high=101.0, close=100.9)        # natural stop ~20% away: skipped
    assert run(wide).trades == []
    assert len(run(wide, max_stop_pct=30.0).trades) == 1


def test_stop_is_assumed_first_when_a_bar_reaches_both():
    arrs = sweep_bar(base())
    arrs[1][SIG + 2], arrs[2][SIG + 2] = 150.0, 90.0
    t = run(arrs).trades[0]
    assert t.r == pytest.approx(-1.0, abs=0.02) and t.bars == 1


def test_break_even_variant_turns_a_round_trip_into_zero_r():
    arrs = sweep_bar(base())
    arrs[0][SIG + 3], arrs[1][SIG + 3], arrs[2][SIG + 3], arrs[3][SIG + 3] = 100.9, 108.2, 100.8, 108.0      # reaches +1R (~107.8)
    arrs[0][SIG + 4], arrs[1][SIG + 4], arrs[2][SIG + 4], arrs[3][SIG + 4] = 108.0, 108.2, 93.0, 94.0         # then collapses
    fixed = run(arrs).trades[0]
    be = run(arrs, be_at_r=1.0).trades[0]
    assert fixed.r == pytest.approx(-1.0, abs=0.02)
    assert be.r == pytest.approx(0.0, abs=0.02)


def test_break_even_is_not_applied_on_the_same_bar_it_is_triggered():
    arrs = sweep_bar(base())
    arrs[0][SIG + 3], arrs[1][SIG + 3], arrs[2][SIG + 3], arrs[3][SIG + 3] = 100.9, 108.2, 93.0, 94.0         # +1R and the stop in one bar
    assert run(arrs, be_at_r=1.0).trades[0].r == pytest.approx(-1.0, abs=0.02)                                  # stop-first, the break-even is not retroactive


def test_time_stop_exits_at_the_close():
    t = run(sweep_bar(base()), max_hold=10).trades[0]
    assert t.bars == 10 and abs(t.r) < 0.1


def test_costs_reduce_pnl():
    arrs = sweep_bar(base())
    arrs[1][SIG + 3] = 140.0
    free = run(arrs).trades[0].pnl
    paid = run(arrs, fee=0.001, slip=10).trades[0].pnl
    assert paid < free


def test_levels_expire_after_max_age():
    arrs = sweep_bar(base(n=200), i=LVL_BAR + 120)
    assert run(arrs, max_age=100).trades == []
    assert len(run(arrs, max_age=200).trades) == 1


def test_control_entries_use_the_lowest_low_of_the_last_five_bars():
    arrs = base()
    df = frame(arrs)
    eb = np.zeros(len(df), bool)
    eb[70] = True
    r = run_fractalsweep(df, SYM, FSParams(), fee_rate=0, slippage_bps=0, entry_bars=eb)
    assert len(r.trades) == 1
    t = r.trades[0]
    a = atr(df, 14).iloc[70]
    natural = arrs[2][66:71].min() - 0.1 * a
    assert t.stop == pytest.approx(min(natural, arrs[3][70] * 0.98)) and t.entry_ts == df["ts"].iloc[71]
    with pytest.raises(ValueError):
        run_fractalsweep(df, SYM, FSParams(), entry_bars=np.zeros(5, bool))


def fat(n=9000, seed=4):
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.012, n)))
    openp = np.r_[100.0, close[:-1]]
    w = np.abs(rng.standard_t(3, (2, n))) * 0.008 * close
    return pd.DataFrame({"ts": pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC"), "open": openp,
                         "high": np.maximum(openp, close) + w[0], "low": np.minimum(openp, close) - w[1],
                         "close": close, "volume": rng.lognormal(0, 0.8, n)})


@pytest.mark.parametrize("be", [None, 1.0])
def test_causality_prefix_run_reproduces_earlier_trades(be):
    df = fat()
    full = run_fractalsweep(df, SYM, FSParams(be_at_r=be))
    part = run_fractalsweep(df.iloc[:6000], SYM, FSParams(be_at_r=be))
    cut = df["ts"].iloc[6000 - 3]
    a = [(t.entry_ts, round(t.pnl, 8)) for t in full.trades if t.exit_ts < cut]
    b = [(t.entry_ts, round(t.pnl, 8)) for t in part.trades if t.exit_ts < cut]
    assert len(a) >= 5 and a == b


def test_every_trade_respects_the_stop_floor_and_cap():
    r = run_fractalsweep(fat(), SYM, FSParams())
    pct = np.array([(t.entry - t.stop) / t.entry * 100 for t in r.trades])
    assert len(pct) >= 5 and pct.min() >= 1.9 and pct.max() <= 15.5      # entry is the next open, so allow a hair either way


@pytest.mark.parametrize("be", [None, 1.0])
def test_scrambling_the_future_never_changes_earlier_entries(be):
    """Stronger than the prefix test: replace every bar after K with a different random walk; every entry stamped at or before bar K+1
    (a signal at bar <= K, which may only use data up to K) must be unchanged. Catches even a one-bar look-ahead."""
    df = fat(n=3000, seed=11)
    rng = np.random.default_rng(5)
    base_entries = [t.entry_ts for t in run_fractalsweep(df, SYM, FSParams(be_at_r=be)).trades]
    assert len(base_entries) >= 10
    checked = 0
    for K in rng.integers(200, 2900, size=60):
        alt = df.copy()
        m = len(df) - (K + 1)
        close = alt["close"].iloc[K] * np.exp(np.cumsum(rng.normal(0, 0.012, m)))
        openp = np.r_[alt["close"].iloc[K], close[:-1]]
        w = np.abs(rng.standard_t(3, (2, m))) * 0.008 * close
        alt.loc[K + 1:, "open"], alt.loc[K + 1:, "close"] = openp, close
        alt.loc[K + 1:, "high"], alt.loc[K + 1:, "low"] = np.maximum(openp, close) + w[0], np.minimum(openp, close) - w[1]
        stamp = df["ts"].iloc[K + 1]
        a = sorted(t for t in base_entries if t <= stamp)
        b = sorted(t.entry_ts for t in run_fractalsweep(alt, SYM, FSParams(be_at_r=be)).trades if t.entry_ts <= stamp)
        assert a == b, f"entries up to bar {K + 1} changed when only later bars were replaced"
        checked += 1
    assert checked == 60


def test_a_fractal_cannot_be_pierced_by_the_bars_that_confirm_it():
    """Why `usable from bar j+n+1` is the earliest meaningful moment: the n bars after a fractal low all have strictly higher lows."""
    df = fat(n=4000, seed=3)
    fl = fractal_lows(df["low"].to_numpy(), 2)
    low = df["low"].to_numpy()
    for j in np.flatnonzero(fl):
        assert (low[j + 1:j + 3] > low[j]).all()
