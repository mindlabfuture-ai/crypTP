import numpy as np
import pandas as pd
import pytest

from cryptp.confirmed import CParams, resample_ohlc, run_confirmed
from cryptp.indicators import atr

SYM = "X/USDT:USDT"
N = 400                                    # 15m bars (100 hours)
SWEEP_HOUR_LAST_BAR = 163                  # the HTF (1h) sweep bar is bars 160-163; it completes with bar 163
CHOCH, IDM_SWEEP = 172, 180


def scene(n=N, spike=130.0):
    """Strictly rising base (no accidental pivots), a 1h fractal HIGH spike at hour 10 (the HTF target), a 1h fractal LOW at hour 20 (95),
    then a hand-built 15m sequence: sweep of that low in hour 40, a pivot high at bar 166, a CHoCH close at bar 172, an inducement low at bar 175
    and its sweep at bar 180."""
    k = np.arange(n)
    c = 100 + 0.002 * k
    o = np.r_[c[0], c[:-1]]
    h, l, v = c + 0.03, c - 0.03, np.ones(n)
    h[41] = spike                                    # hour 10: fractal high
    l[82] = 95.0                                     # hour 20: fractal low
    explicit = {
        160: (100.80, 100.85, 100.70, 100.75), 161: (100.75, 100.90, 100.60, 100.65),      # bar 161's high keeps bar 160 from being a pivot
        162: (100.65, 100.70, 94.00, 100.00), 163: (100.00, 101.00, 99.90, 100.90),      # sweep wick, HTF bar closes in its upper half
        164: (100.90, 101.00, 100.80, 100.85), 165: (100.85, 100.90, 100.70, 100.75),
        166: (100.75, 101.30, 100.70, 101.00),                                           # pivot high 101.30
        167: (101.00, 101.20, 100.80, 100.90), 168: (100.90, 101.10, 100.70, 100.85),
        169: (100.85, 101.05, 100.60, 100.80), 170: (100.80, 101.00, 100.50, 100.75),
        171: (100.75, 100.95, 100.40, 100.45),
        172: (100.45, 101.60, 100.44, 101.50),                                           # CHoCH: closes above 101.30
        173: (101.50, 101.55, 101.20, 101.25), 174: (101.25, 101.35, 101.10, 101.15),
        175: (101.15, 101.30, 100.90, 101.00),                                           # pivot low 100.90 = the inducement
        176: (101.00, 101.30, 101.00, 101.25), 177: (101.25, 101.40, 101.20, 101.35),
        178: (101.35, 101.45, 101.25, 101.40), 179: (101.40, 101.45, 101.30, 101.35),
        180: (101.35, 101.50, 100.50, 101.40),                                           # sweeps the inducement and closes back above it
    }
    for b, (ob, hb, lb, cb) in explicit.items():
        o[b], h[b], l[b], c[b] = ob, hb, lb, cb
    for b in range(181, n):                          # quiet afterwards, identical bars so no pivots appear
        o[b], h[b], l[b], c[b] = 101.40, 101.45, 101.35, 101.40
    return [x.astype(float).copy() for x in (o, h, l, c, v)]


def frame(arrs):
    o, h, l, c, v = arrs
    ts = pd.date_range("2025-01-01 00:00", periods=len(o), freq="15min", tz="UTC")
    return pd.DataFrame({"ts": ts, "open": o, "high": h, "low": l, "close": c, "volume": v})


def run(arrs, fee=0.0, slip=0.0, **kw):
    return run_confirmed(frame(arrs), SYM, CParams(**kw), fee_rate=fee, slippage_bps=slip)


def mirror(arrs, c=200.0):
    o, h, l, cl, v = arrs
    return [c - o, c - l, c - h, c - cl, v.copy()]


def expected_stop(arrs):
    df = frame(arrs)
    hdf = resample_ohlc(df, "1h")
    ha = atr(hdf, 14)
    return hdf["low"].iloc[40] - 0.1 * ha.iloc[40]


def test_resample_uses_complete_buckets_only():
    df = frame(scene()).iloc[:-3]
    hdf = resample_ohlc(df, "1h")
    assert len(hdf) == (N - 4) // 4 and hdf["ts"].iloc[-1] == df["ts"].iloc[N - 8]
    assert hdf["high"].iloc[10] == pytest.approx(130.0)


def test_m2_enters_at_the_open_after_the_choch_close_with_the_htf_stop_and_target():
    arrs = scene()
    arrs[1][190] = 131.0                                       # a later bar runs through the HTF target (130)
    df = frame(arrs)
    r = run_confirmed(df, SYM, CParams(model="M2"), fee_rate=0, slippage_bps=0)
    assert len(r.trades) == 1
    t = r.trades[0]
    stop = expected_stop(arrs)
    assert t.side == "buy" and t.entry_ts == df["ts"].iloc[CHOCH + 1] and t.entry == pytest.approx(101.50)
    assert t.stop == pytest.approx(stop)
    assert t.r == pytest.approx((130.0 - 101.5) / (101.5 - stop), rel=1e-6)


def test_m1_waits_for_the_inducement_sweep_and_enters_after_it():
    arrs = scene()
    arrs[1][190] = 131.0
    df = frame(arrs)
    r = run_confirmed(df, SYM, CParams(model="M1"), fee_rate=0, slippage_bps=0)
    assert len(r.trades) == 1
    t = r.trades[0]
    assert t.entry_ts == df["ts"].iloc[IDM_SWEEP + 1] and t.entry == pytest.approx(101.40)
    assert t.stop == pytest.approx(expected_stop(arrs))        # the HTF extreme is lower than the inducement-sweep wick, so it is the stop


def test_control_c0_enters_at_the_first_open_after_the_htf_bar_completes_not_before():
    arrs = scene()
    arrs[1][190] = 131.0
    df = frame(arrs)
    t = run_confirmed(df, SYM, CParams(model="C0"), fee_rate=0, slippage_bps=0).trades[0]
    assert t.entry_ts == df["ts"].iloc[SWEEP_HOUR_LAST_BAR + 1]       # bar 162 already shows the wick, but the 1h bar is not complete until 163
    assert t.entry == pytest.approx(100.90)                            # the open of bar 164 equals the close of bar 163
    assert t.stop == pytest.approx(expected_stop(arrs))


def test_no_confirmation_means_no_m1_m2_trade_but_the_control_still_trades():
    arrs = scene()
    for b in range(172, N):                                    # price never closes above the pivot high (101.30)
        arrs[0][b], arrs[1][b], arrs[2][b], arrs[3][b] = 100.90, 100.95, 100.85, 100.90
    assert run(arrs, model="M2").trades == []
    assert run(arrs, model="M1").trades == []
    assert len(run(arrs, model="C0").trades) == 1


def test_wick_only_break_is_not_a_choch():
    arrs = scene()
    arrs[0][172], arrs[1][172], arrs[2][172], arrs[3][172] = 100.45, 101.60, 100.44, 101.20     # wicks above 101.30, closes below it
    for b in range(173, N):
        arrs[0][b], arrs[1][b], arrs[2][b], arrs[3][b] = 101.20, 101.25, 101.15, 101.20
    assert run(arrs, model="M2").trades == []


def test_window_expiry_cancels_the_setup():
    arrs = scene()
    arrs[3][172], arrs[1][172] = 100.45, 100.50                # no CHoCH here ...
    arrs[0][172] = 100.45
    for b in range(173, 230):
        arrs[0][b], arrs[1][b], arrs[2][b], arrs[3][b] = 100.45, 100.50, 100.40, 100.45
    arrs[0][230], arrs[1][230], arrs[2][230], arrs[3][230] = 100.45, 101.60, 100.44, 101.50    # ... and the break comes 67 bars after the sweep (> 48)
    for b in range(231, N):
        arrs[0][b], arrs[1][b], arrs[2][b], arrs[3][b] = 101.50, 101.55, 101.45, 101.50
    assert run(arrs, model="M2").trades == []
    assert len(run(arrs, model="M2", window_htf=24).trades) == 1


def test_breaking_the_htf_extreme_before_entry_cancels_the_setup():
    arrs = scene()
    arrs[2][168] = 93.0                                        # a 15m low beyond the HTF sweep low (93.66) before the CHoCH
    assert run(arrs, model="M2").trades == []


def test_stop_distance_gates():
    deep = scene()
    deep[2][162] = 80.0                                        # stop ~22% away
    assert run(deep, model="M2", min_rr=0.5).trades == []      # skipped by the 12% cap (reward:risk relaxed so only the cap can block it)
    assert len(run(deep, model="M2", min_rr=0.5, max_stop_pct=30.0).trades) == 1
    assert run(scene(), model="M2", min_stop_pct=9.0).trades == []        # natural stop ~7.7%: below a 9% minimum


def test_reward_to_risk_gate_uses_the_nearest_htf_target():
    near = scene(spike=105.0)                                  # target only ~3.5 away vs ~7.8 of risk
    assert run(near, model="M2").trades == []
    assert len(run(near, model="M2", min_rr=0.3).trades) == 1


def test_short_is_the_exact_mirror_of_long():
    arrs = scene()
    arrs[1][190] = 131.0
    up = run(arrs, model="M2").trades[0]
    m = mirror(arrs)
    m[2][190] = 200 - 131.0
    dn = run(m, model="M2").trades[0]
    assert up.side == "buy" and dn.side == "sell"
    assert up.entry_ts == dn.entry_ts and up.r == pytest.approx(dn.r, rel=1e-6)
    assert run(mirror(arrs), model="M1").trades[0].side == "sell"
    assert run(mirror(arrs), model="C0").trades[0].side == "sell"


def test_break_even_turns_a_round_trip_into_zero_r_and_is_not_retroactive():
    arrs = scene()
    stop = expected_stop(arrs)
    r1 = 101.5 - stop                                         # 1R above the signal close
    arrs[0][185], arrs[1][185], arrs[2][185], arrs[3][185] = 101.4, 101.5 + r1 + 0.1, 101.3, 101.4 + r1
    arrs[0][186], arrs[1][186], arrs[2][186], arrs[3][186] = 101.4 + r1, 101.4 + r1 + 0.1, 90.0, 91.0
    for b in range(187, N):
        arrs[0][b], arrs[1][b], arrs[2][b], arrs[3][b] = 91.0, 91.1, 90.9, 91.0
    assert run(arrs, model="M2", be_at_r=1.0).trades[0].r == pytest.approx(0.0, abs=0.03)
    assert run(arrs, model="M2", be_at_r=None).trades[0].r == pytest.approx(-1.0, abs=0.02)
    same_bar = scene()
    same_bar[0][185], same_bar[1][185], same_bar[2][185], same_bar[3][185] = 101.4, 101.5 + r1 + 0.1, 90.0, 91.0   # +1R and the stop in one bar
    for b in range(186, N):
        same_bar[0][b], same_bar[1][b], same_bar[2][b], same_bar[3][b] = 91.0, 91.1, 90.9, 91.0
    assert run(same_bar, model="M2", be_at_r=1.0).trades[0].r == pytest.approx(-1.0, abs=0.02)


def test_costs_reduce_pnl():
    arrs = scene()
    arrs[1][190] = 131.0
    free = run(arrs, model="M2").trades[0].pnl
    paid = run(arrs, model="M2", fee=0.001, slip=10).trades[0].pnl
    assert paid < free


def fat15(n=8000, seed=4):
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.004, n)))
    openp = np.r_[100.0, close[:-1]]
    w = np.abs(rng.standard_t(3, (2, n))) * 0.0025 * close
    return pd.DataFrame({"ts": pd.date_range("2024-01-01", periods=n, freq="15min", tz="UTC"), "open": openp,
                         "high": np.maximum(openp, close) + w[0], "low": np.minimum(openp, close) - w[1],
                         "close": close, "volume": rng.lognormal(0, 0.8, n)})


PERMISSIVE = dict(min_stop_pct=0.1, max_stop_pct=60.0, min_rr=0.5)


@pytest.mark.parametrize("model,tf", [("M1", "1h"), ("M2", "1h"), ("C0", "1h"), ("M2", "4h")])
def test_scrambling_the_future_never_changes_earlier_entries(model, tf):
    """Replace every 15m bar after K with a different random walk; every entry stamped at or before bar K+1 (a signal at bar <= K) must be unchanged.
    This also guards the HTF alignment: a 1h/4h bar that has not completed by bar K must never be used."""
    df = fat15(n=6000, seed=11)
    kw = dict(model=model, tf=tf, **PERMISSIVE)
    base = [t.entry_ts for t in run_confirmed(df, SYM, CParams(**kw)).trades]
    assert len(base) >= 10, len(base)
    rng = np.random.default_rng(5)
    for K in rng.integers(300, 5900, size=40):
        alt = df.copy()
        m = len(df) - (K + 1)
        close = alt["close"].iloc[K] * np.exp(np.cumsum(rng.normal(0, 0.004, m)))
        openp = np.r_[alt["close"].iloc[K], close[:-1]]
        w = np.abs(rng.standard_t(3, (2, m))) * 0.0025 * close
        alt.loc[K + 1:, "open"], alt.loc[K + 1:, "close"] = openp, close
        alt.loc[K + 1:, "high"], alt.loc[K + 1:, "low"] = np.maximum(openp, close) + w[0], np.minimum(openp, close) - w[1]
        stamp = df["ts"].iloc[K + 1]
        a = sorted(t for t in base if t <= stamp)
        b = sorted(t.entry_ts for t in run_confirmed(alt, SYM, CParams(**kw)).trades if t.entry_ts <= stamp)
        assert a == b, f"{model}/{tf}: entries up to bar {K + 1} changed when only later bars were replaced"


def test_random_data_produces_both_sides_and_respects_the_gates():
    r = run_confirmed(fat15(), SYM, CParams(model="M2", **PERMISSIVE))
    sides = {t.side for t in r.trades}
    assert sides == {"buy", "sell"}
    r2 = run_confirmed(fat15(), SYM, CParams(model="C0"))
    pct = np.array([abs(t.entry - t.stop) / t.entry * 100 for t in r2.trades])
    assert len(pct) >= 5 and pct.min() >= 0.9 and pct.max() <= 12.6          # entry is the next open, so allow a hair either way


def test_target_is_the_nearest_htf_level_above_the_entry_not_the_farthest():
    arrs = scene()                                             # HTF high at 130 (hour 10) ...
    arrs[1][61] = 126.0                                        # ... and a nearer one at 126 (hour 15)
    arrs[1][190] = 131.0                                       # a later bar trades through both
    t = run(arrs, model="M2").trades[0]
    stop = expected_stop(arrs)
    assert t.r == pytest.approx((126.0 - 101.5) / (101.5 - stop), rel=1e-6)
    m = mirror(arrs)                                           # and the mirror picks the nearest HTF low below for a short
    assert run(m, model="M2").trades[0].r == pytest.approx(t.r, rel=1e-6)
