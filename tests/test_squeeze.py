import numpy as np
import pandas as pd
import pytest

from cryptp import squeeze as sq
from cryptp.squeeze import SqueezeParams, find_signals, run_squeeze, squeeze_features

SYM = "SUI/USDT:USDT"


def rand_df(n=4000, seed=1, start="2024-01-01"):
    """Random walk with volatility clustering, so quiet (squeeze) and active stretches both occur."""
    rng = np.random.default_rng(seed)
    vol = np.exp(np.cumsum(rng.normal(0, 0.15, n)) * 0.3 - 5.6)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 1, n) * vol))
    openp = np.r_[100.0, close[:-1]]
    w = np.abs(rng.normal(0, 1, (2, n))) * vol * close * 0.8
    return pd.DataFrame({"ts": pd.date_range(start, periods=n, freq="15min", tz="UTC"), "open": openp,
                         "high": np.maximum(openp, close) + w[0], "low": np.minimum(openp, close) - w[1],
                         "close": close, "volume": rng.lognormal(0, 0.6, n)})


def test_squeeze_flag_matches_an_independent_loop():
    df = rand_df(1500, seed=2)
    on, _ = squeeze_features(df)
    c, h, l = df.close.to_numpy(), df.high.to_numpy(), df.low.to_numpy()
    expect = np.zeros(len(df), bool)
    for i in range(20, len(df)):                                   # i has a full 20-bar window; true range needs a previous close
        w = c[i - 19:i + 1]
        basis, sd = w.mean(), w.std()                              # population std
        trs = [max(h[k] - l[k], abs(h[k] - c[k - 1]), abs(l[k] - c[k - 1])) for k in range(i - 19, i + 1)]
        kc = 1.5 * np.mean(trs)
        expect[i] = (basis - 2 * sd > basis - kc) and (basis + 2 * sd < basis + kc)
    assert (on[20:] == expect[20:]).all() and expect.any() and (~expect).any()


def test_momentum_matches_polyfit():
    df = rand_df(800, seed=3)
    _, mom = squeeze_features(df)
    c, h, l = df.close, df.high, df.low
    src = (c - ((h.rolling(20).max() + l.rolling(20).min()) / 2 + c.rolling(20).mean()) / 2).to_numpy()
    for i in (60, 200, 555, 799):
        y = src[i - 19:i + 1]
        b, a = np.polyfit(np.arange(20), y, 1)
        assert mom[i] == pytest.approx(a + b * 19, rel=1e-9, abs=1e-9)
    assert np.isnan(mom[:38]).all()


def scenario(monkeypatch, *, squeeze_len=8, break_close=100.9, break_off=0, volume=2.0, mom=1.0, hour0=9, n=140,
             after=None, release_closes=None):
    """Hand-built bars with a hand-fed squeeze flag: squeeze on for bars 30..30+squeeze_len-1, release bar b follows.
    Box = [99.5, 100.5]. `after` is {bar: (open, high, low, close)} for bars after the trigger."""
    b = 30 + squeeze_len
    on = np.zeros(n, bool); on[30:b] = True
    momentum = np.full(n, mom)
    ts = pd.date_range("2025-03-01 00:00", periods=n, freq="15min", tz="UTC") + pd.Timedelta(hours=hour0)
    close = np.full(n, 100.0); high = np.full(n, 100.5); low = np.full(n, 99.5); openp = np.full(n, 100.0); vol = np.ones(n)
    trig = b + break_off
    for k, cl in (release_closes or {}).items():
        close[k] = cl; high[k] = max(high[k], cl); low[k] = min(low[k], cl); openp[k] = 100.0
    close[trig] = break_close; high[trig] = max(100.5, break_close); low[trig] = 100.0; openp[trig] = 100.0; vol[trig] = volume
    quiet = slice(trig + 1, n)                                     # after the trigger: quiet around the entry price, so only `after` moves things
    openp[quiet] = close[quiet] = break_close
    high[quiet], low[quiet] = break_close + 0.1, break_close - 0.1
    for k, (o, h, l, c) in (after or {}).items():
        openp[k], high[k], low[k], close[k] = o, h, l, c
    df = pd.DataFrame({"ts": ts, "open": openp, "high": high, "low": low, "close": close, "volume": vol})
    monkeypatch.setattr(sq, "squeeze_features", lambda d: (on, momentum))
    return df, trig


P0 = dict(vol_mult=1.5)


def go(df, **kw):
    return run_squeeze(df, SYM, SqueezeParams(**{**P0, **kw}), fee_rate=0.0, slippage_bps=0.0, equity0=1000.0)


def test_target_pays_exactly_five_r_and_risks_one_percent(monkeypatch):
    df, t = scenario(monkeypatch)
    df.loc[t + 2, ["open", "high", "low", "close"]] = [100.9, 106.0, 100.7, 105.8]                 # target is 100.9 + 5*0.9 = 105.4
    r = go(df)
    assert len(r.trades) == 1
    tr = r.trades[0]
    assert tr.side == "buy" and tr.entry == pytest.approx(100.9) and tr.stop == pytest.approx(100.0)
    assert tr.r == pytest.approx(5.0, rel=1e-9) and tr.risk_usd == pytest.approx(10.0, rel=1e-9)   # 1% of $1,000


def test_stop_at_the_box_midpoint_loses_one_r(monkeypatch):
    df, t = scenario(monkeypatch)
    df.loc[t + 2, ["open", "high", "low", "close"]] = [100.9, 101.0, 99.8, 100.0]
    tr = go(df).trades[0]
    assert tr.r == pytest.approx(-1.0, rel=1e-9) and tr.bars == 1


def test_stop_is_assumed_first_when_a_bar_reaches_both(monkeypatch):
    df, t = scenario(monkeypatch)
    df.loc[t + 2, ["open", "high", "low", "close"]] = [100.9, 110.0, 99.0, 105.0]
    assert go(df).trades[0].r == pytest.approx(-1.0, rel=1e-9)


def test_time_exit_at_midnight_open(monkeypatch):
    df, t = scenario(monkeypatch, hour0=20)                       # trigger at ~22:00 UTC... but cutoff: allow it for this test
    r = go(df, cutoff_hour=24)
    tr = r.trades[0]
    mid = df.index[(df.ts.dt.hour == 0) & (df.ts.dt.minute == 0) & (df.index > t)][0]
    assert tr.exit_ts == df.ts[mid] and tr.bars == mid - (t + 1)
    assert tr.r == pytest.approx((df.open[mid] - 100.9) / 0.9)    # exits at that bar's open


@pytest.mark.parametrize("kw", [dict(volume=1.0), dict(mom=-1.0), dict(hour0=11)])
def test_filters_block_the_trade(monkeypatch, kw):
    # hour0=11 puts the trigger bar (38 bars x 15 min = 9.5 h after the start) at 20:30 UTC, past the 20:00 cutoff
    df, t = scenario(monkeypatch, **kw)
    assert go(df).trades == []
    ok, _ = scenario(monkeypatch)                                  # the same scenario without the offending filter trades
    assert len(go(ok).trades) == 1


def test_squeeze_must_last_the_minimum_number_of_bars(monkeypatch):
    short, _ = scenario(monkeypatch, squeeze_len=5)
    assert go(short).trades == []
    ok, _ = scenario(monkeypatch, squeeze_len=6)
    assert len(go(ok).trades) == 1


def test_breakout_window_is_four_bars_from_the_release(monkeypatch):
    inside = {38: 100.0, 39: 100.0, 40: 100.0}                    # release bar and the next two close inside the box
    df, t = scenario(monkeypatch, break_off=3, release_closes=inside)
    assert len(go(df).trades) == 1                                # 4th bar of the window: allowed
    df, t = scenario(monkeypatch, break_off=4, release_closes={38: 100.0, 39: 100.0, 40: 100.0, 41: 100.0})
    assert go(df).trades == []                                    # 5th bar: too late


def test_first_close_outside_the_box_ends_the_setup_even_if_filters_fail(monkeypatch):
    df, t = scenario(monkeypatch, volume=1.0)                     # first outside close has weak volume -> no trade
    df.loc[t + 1, ["high", "close", "volume"]] = [102.0, 101.8, 5.0]   # a strong follow-up bar must NOT be scanned
    assert go(df).trades == []


def test_stop_distance_limits(monkeypatch):
    df, t = scenario(monkeypatch)
    assert go(df, min_stop_pct=2.0).trades == []                  # stop is ~0.9% away: closer than the minimum
    assert go(df, max_stop_pct=0.5).trades == []                  # ... and farther than a 0.5% cap
    assert len(go(df).trades) == 1


def test_far_side_stop_option(monkeypatch):
    df, t = scenario(monkeypatch)
    df.loc[t + 2, ["open", "high", "low", "close"]] = [100.9, 101.0, 99.4, 99.6]
    tr = go(df, stop_mode="far").trades[0]
    assert tr.stop == pytest.approx(99.5) and tr.r == pytest.approx(-1.0, rel=1e-9)


def test_short_is_the_mirror_of_the_long(monkeypatch):
    df, t = scenario(monkeypatch, break_close=99.1, mom=-1.0)
    df.loc[t, ["low", "high"]] = [99.1, 100.0]
    df.loc[t + 2, ["open", "high", "low", "close"]] = [99.1, 99.3, 94.0, 94.2]                       # target 99.1 - 5*0.9 = 94.6
    tr = go(df).trades[0]
    assert tr.side == "sell" and tr.stop == pytest.approx(100.0) and tr.r == pytest.approx(5.0, rel=1e-9)


def test_costs_reduce_pnl(monkeypatch):
    df, t = scenario(monkeypatch)
    df.loc[t + 2, ["open", "high", "low", "close"]] = [100.9, 106.0, 100.7, 105.8]
    free = go(df).trades[0].pnl
    paid = run_squeeze(df, SYM, SqueezeParams(**P0), fee_rate=0.001, slippage_bps=10).trades[0].pnl
    assert paid < free


def test_signals_are_causal():
    df = rand_df(6000, seed=5)
    p = SqueezeParams(vol_mult=0, cutoff_hour=24)
    full, part = find_signals(df, p), find_signals(df.iloc[:4000], p)
    cut = 4000 - 10
    assert len([k for k in full if k < cut]) >= 5
    assert {k: v for k, v in full.items() if k < cut} == {k: v for k, v in part.items() if k < cut}
    a = run_squeeze(df, SYM, p, 0.0, 0.0).trades
    b = run_squeeze(df.iloc[:4000], SYM, p, 0.0, 0.0).trades
    cutoff_ts = df.ts[cut - 100]
    assert [(t.entry_ts, round(t.pnl, 8)) for t in a if t.exit_ts < cutoff_ts] == [(t.entry_ts, round(t.pnl, 8)) for t in b if t.exit_ts < cutoff_ts]


def test_exact_mirror_symmetry_on_random_data():
    df = rand_df(8000, seed=7)
    m = df.copy(); c = 1000.0
    m["open"], m["close"], m["high"], m["low"] = 2 * c - df.open, 2 * c - df.close, 2 * c - df.low, 2 * c - df.high
    p = SqueezeParams(vol_mult=0, cutoff_hour=24, min_stop_pct=0.0, max_stop_pct=1e9, max_leverage=1e9)
    a = run_squeeze(df, SYM, p, 0.0, 0.0).trades
    b = run_squeeze(m, SYM, p, 0.0, 0.0).trades
    assert len(a) >= 10 and len(a) == len(b)
    assert [t.entry_ts for t in a] == [t.entry_ts for t in b]
    assert [t.r for t in a] == pytest.approx([t.r for t in b], abs=1e-6)
    assert all({"buy": "sell", "sell": "buy"}[x.side] == y.side for x, y in zip(a, b))
