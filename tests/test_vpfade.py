import numpy as np
import pandas as pd
import pytest

from cryptp.indicators import atr
from cryptp.vpfade import VPParams, macro_bias, run_vpfade, volume_profile

SYM = "X/USDT:USDT"
W = 96
SIG = 100                                   # signal bar; its profile window is bars 4..99


def frame(o, h, l, c, v, start="2025-01-01 00:00"):
    ts = pd.date_range(start, periods=len(o), freq="15min", tz="UTC")
    return pd.DataFrame({"ts": ts, "open": o, "high": h, "low": l, "close": c, "volume": v})


def window(n=200):
    """Smooth path 98.8-101.2 for 100 bars with volume concentrated near 100 (POC ~100, wide value area), then flat 100."""
    k = np.arange(n)
    c = np.where(k < 100, 100 + 1.2 * np.sin(2 * np.pi * k / 96), 100.0)
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) + 0.03
    l = np.minimum(o, c) - 0.03
    v = np.exp(-(((c - 100) / 0.5) ** 2)) + 0.05
    return [x.astype(float).copy() for x in (o, h, l, c, v)]


def levels(arrs, i=SIG):
    o, h, l, c, v = arrs
    return volume_profile(h[i - W:i], l[i - W:i], v[i - W:i])


def put(arrs, i, o=None, h=None, l=None, c=None, v=None):
    for arr, val in zip(arrs, (o, h, l, c, v)):
        if val is not None:
            arr[i] = val
    arrs[0][i + 1:i + 2] = arrs[3][i]                  # keep the next open at this close unless overwritten later


def run(arrs, **kw):
    p = VPParams(**kw.pop("p", {}))
    return run_vpfade(frame(*arrs), SYM, p, fee_rate=kw.pop("fee_rate", 0.0), slippage_bps=kw.pop("slip", 0.0), **kw)


def a_short(arrs=None, wick=0.15):
    """Failed breakout above VAH: spike `wick` above it, close back just inside, then price flat at the close."""
    arrs = arrs or window()
    poc, vah, val = levels(arrs)
    c = vah - 0.05
    put(arrs, SIG, o=c - 0.03, h=vah + wick, l=c - 0.05, c=c, v=1.0)
    for b in range(SIG + 1, 200):                       # quiet around the close, ranges kept tiny
        arrs[0][b], arrs[1][b], arrs[2][b], arrs[3][b] = c, c + 0.01, c - 0.01, c
    return arrs, (poc, vah, val), c


def test_profile_poc_and_value_area():
    arrs = window()
    poc, vah, val = levels(arrs)
    assert poc == pytest.approx(100.0, abs=0.1)
    assert val < poc < vah
    o, h, l, c, v = arrs
    inside = np.array([(min(hi, vah) - max(lo, val)) / (hi - lo) for hi, lo in zip(h[4:100], l[4:100])]).clip(0, 1)
    assert (inside * v[4:100]).sum() / v[4:100].sum() >= 0.70 - 0.02          # value area holds ~70% of the volume


def test_profile_handles_zero_range_bars_and_flat_window():
    assert volume_profile([5.0] * 10, [5.0] * 10, [1.0] * 10) is None
    h = np.array([10.0, 10.0, 10.0, 12.0])
    l = np.array([10.0, 10.0, 10.0, 8.0])
    poc, vah, val = volume_profile(h, l, np.array([5.0, 5.0, 5.0, 1.0]))
    assert poc == pytest.approx(10.0, abs=0.05) and val <= poc <= vah


def test_fade_short_target_is_poc_and_r_matches_the_levels():
    arrs, (poc, vah, val), c = a_short()
    arrs[2][SIG + 1] = poc - 0.05                       # next bar reaches the POC
    df = frame(*arrs)
    r = run_vpfade(df, SYM, VPParams(), fee_rate=0, slippage_bps=0)
    assert len(r.trades) == 1
    t = r.trades[0]
    a = atr(df, 14).iloc[SIG]
    stop = vah + 0.15 + 0.1 * a
    assert t.side == "sell" and t.entry == pytest.approx(c) and t.bars == 0
    assert t.stop == pytest.approx(stop)
    assert t.r == pytest.approx((c - poc) / (stop - c), rel=1e-6)
    assert t.entry_ts == df["ts"].iloc[SIG + 1]


def test_fade_needs_a_close_back_inside_value():
    arrs, (poc, vah, val), c = a_short()
    arrs[3][SIG] = vah + 0.1                            # closes ABOVE VAH: accepted, not failed
    arrs[1][SIG] = vah + 0.3
    arrs[0][SIG + 1] = vah + 0.1
    assert run(arrs).trades == []


def test_fade_needs_a_rejection_wick():
    arrs, (poc, vah, val), c = a_short()
    put(arrs, SIG, o=vah - 0.45, h=vah + 0.2, l=vah - 0.5, c=vah - 0.02, v=1.0)   # pokes, but the upper wick is only ~30% of the range
    for b in range(SIG + 1, 200):
        arrs[0][b], arrs[1][b], arrs[2][b], arrs[3][b] = vah - 0.02, vah - 0.01, vah - 0.03, vah - 0.02
    assert run(arrs).trades == []


def test_fade_reward_to_risk_gate_blocks_a_long_wick():
    arrs, *_ = a_short(wick=3.0)                         # stop 3 above VAH: reward no longer 1.5x the risk
    assert run(arrs).trades == []
    ts = frame(*arrs)["ts"]
    assert any(t.entry_ts == ts.iloc[SIG + 1] for t in run(arrs, p={"min_rr": 0.1}).trades)


def test_stop_is_assumed_first_when_a_bar_reaches_both():
    arrs, (poc, vah, val), c = a_short()
    arrs[1][SIG + 1], arrs[2][SIG + 1] = vah + 5.0, poc - 5.0      # reaches both stop and target
    t = run(arrs).trades[0]
    assert t.r < -0.9 and t.bars == 0


def test_time_stop_exits_at_the_close():
    arrs, *_ = a_short()
    t = run(arrs, p={"max_hold": 10}).trades[0]
    assert t.bars == 10 and abs(t.r) < 0.2                # flat market, so about zero R


def test_costs_reduce_pnl():
    arrs, (poc, vah, val), c = a_short()
    arrs[2][SIG + 1] = poc - 0.05
    free = run(arrs).trades[0].pnl
    paid = run(arrs, fee_rate=0.001, slip=10).trades[0].pnl
    assert paid < free


def test_risk_sizing_risks_the_chosen_percent_and_leverage_cap_binds():
    arrs, (poc, vah, val), c = a_short()
    arrs[2][SIG + 1] = poc - 0.05
    t = run(arrs, p={"max_leverage": 100.0}).trades[0]
    assert t.risk_usd == pytest.approx(10.0, rel=1e-6)                 # 1% of $1,000
    capped = run(arrs, p={"max_leverage": 0.5}).trades[0]
    assert capped.risk_usd < 10.0


def test_fade_long_is_the_mirror_of_short():
    arrs, (poc, vah, val), c = a_short()
    arrs[2][SIG + 1] = poc - 0.05
    short = run(arrs).trades[0]
    m = [x.copy() for x in arrs]
    m[0], m[3] = 200 - arrs[0], 200 - arrs[3]
    m[1], m[2] = 200 - arrs[2], 200 - arrs[1]
    long_ = run(m).trades[0]
    assert long_.side == "buy" and short.side == "sell"
    assert long_.entry_ts == short.entry_ts
    assert long_.r == pytest.approx(short.r, rel=0.12)         # POC/VA tie-breaks prefer the upper side: levels may differ by a row


# ---- B: discount + pressure ------------------------------------------------------------------

def b_long_b1(arrs=None):
    arrs = arrs or window()
    poc, vah, val = levels(arrs)
    c = val + 0.22
    put(arrs, SIG, o=val + 0.05, h=c, l=val - 0.01, c=c, v=5.0)          # bullish pressure candle low in the discount zone
    for b in range(SIG + 1, 200):
        arrs[0][b], arrs[1][b], arrs[2][b], arrs[3][b] = c, c + 0.01, c - 0.01, c
    return arrs, (poc, vah, val), c


def test_b1_long_enters_on_pressure_in_the_discount_zone_and_targets_vah():
    arrs, (poc, vah, val), c = b_long_b1()
    arrs[1][SIG + 1] = vah + 0.05                                        # next bar runs to VAH
    df = frame(*arrs)
    t = run_vpfade(df, SYM, VPParams(mode="discount"), fee_rate=0, slippage_bps=0).trades[0]
    a = atr(df, 14).iloc[SIG]
    stop = val - 0.01 - 0.1 * a                                          # min(VAL, bar low) - 0.1 ATR
    assert t.side == "buy" and t.entry == pytest.approx(c) and t.stop == pytest.approx(stop)
    assert t.r == pytest.approx((vah - c) / (c - stop), rel=1e-6) and t.r >= 2.0


def test_b1_needs_pressure_no_pressure_no_entry():
    arrs, (poc, vah, val), c = b_long_b1()
    arrs[3][SIG] = val + 0.04                                            # a tiny-body candle: no pressure
    arrs[0][SIG] = val + 0.05
    assert run(arrs, p={"mode": "discount"}).trades == []
    weak_vol = b_long_b1()[0]
    weak_vol[4][SIG] = 0.001                                             # strong candle on no volume
    assert run(weak_vol, p={"mode": "discount"}).trades == []


def test_b1_needs_the_discount_zone():
    arrs = window()
    poc, vah, val = levels(arrs)
    c = poc + 0.3                                                         # premium side: no long
    put(arrs, SIG, o=c - 0.2, h=c, l=c - 0.21, c=c, v=5.0)
    assert [t for t in run(arrs, p={"mode": "discount"}).trades if t.side == "buy" and t.entry_ts == frame(*arrs)["ts"].iloc[SIG + 1]] == []


def test_b1_short_is_the_mirror():
    arrs, (poc, vah, val), c = b_long_b1()
    arrs[1][SIG + 1] = vah + 0.05
    long_ = run(arrs, p={"mode": "discount"}).trades[0]
    m = [x.copy() for x in arrs]
    m[0], m[3] = 200 - arrs[0], 200 - arrs[3]
    m[1], m[2] = 200 - arrs[2], 200 - arrs[1]
    short = run(m, p={"mode": "discount"}).trades
    assert short and short[0].side == "sell" and short[0].r == pytest.approx(long_.r, rel=0.15)


def test_b2_poc_reclaim_then_retest_enters_long_with_stop_below_poc():
    arrs = window()
    poc0 = levels(arrs)[0]
    for b in range(SIG - 12, SIG):                                       # recently below the POC, on negligible volume
        arrs[0][b], arrs[3][b] = poc0 - 0.4, poc0 - 0.4
        arrs[1][b], arrs[2][b] = poc0 - 0.38, poc0 - 0.42
        arrs[4][b] = 0.001
    poc, vah, val = levels(arrs, SIG)                                    # the POC the engine sees at the reclaim bar
    put(arrs, SIG, o=poc - 0.4, h=poc + 0.25, l=poc - 0.42, c=poc + 0.2, v=1.0)        # reclaim: closes above the POC
    put(arrs, SIG + 1, o=poc + 0.2, h=poc + 0.22, l=poc + 0.15, c=poc + 0.18, v=1.0)    # drifts
    put(arrs, SIG + 2, o=poc + 0.18, h=poc + 0.19, l=poc + 0.14, c=poc + 0.15, v=1.0)
    c = poc + 0.1
    put(arrs, SIG + 3, o=poc + 0.01, h=c, l=poc - 0.01, c=c, v=5.0)                    # retest holds with a pressure candle
    for b in range(SIG + 4, 200):
        arrs[0][b], arrs[1][b], arrs[2][b], arrs[3][b] = c, c + 0.01, c - 0.01, c
    df = frame(*arrs)
    r = run_vpfade(df, SYM, VPParams(mode="discount"), fee_rate=0, slippage_bps=0)
    longs = [t for t in r.trades if t.side == "buy"]
    assert longs and longs[0].entry_ts == df["ts"].iloc[SIG + 4]
    assert longs[0].stop < poc


def test_b2_cancelled_when_the_poc_is_lost_again():
    arrs = window()
    poc0 = levels(arrs)[0]
    for b in range(SIG - 12, SIG):                                       # recently below the POC, on negligible volume
        arrs[0][b], arrs[3][b] = poc0 - 0.4, poc0 - 0.4
        arrs[1][b], arrs[2][b] = poc0 - 0.38, poc0 - 0.42
        arrs[4][b] = 0.001
    poc, vah, val = levels(arrs, SIG)                                    # the POC the engine sees at the reclaim bar
    put(arrs, SIG, o=poc - 0.4, h=poc + 0.25, l=poc - 0.42, c=poc + 0.2, v=1.0)
    put(arrs, SIG + 1, o=poc + 0.2, h=poc + 0.21, l=poc - 0.6, c=poc - 0.5, v=1.0)     # falls back through the POC
    c = poc + 0.1
    put(arrs, SIG + 3, o=poc + 0.01, h=c, l=poc - 0.01, c=c, v=5.0)                    # a later "retest" no longer counts
    for b in range(SIG + 4, 200):
        arrs[0][b], arrs[1][b], arrs[2][b], arrs[3][b] = c, c + 0.01, c - 0.01, c
    r = run(arrs, p={"mode": "discount"})
    assert not [t for t in r.trades if t.entry_ts == frame(*arrs)["ts"].iloc[SIG + 4]]


# ---- macro filter and structural guarantees -------------------------------------------------

def test_macro_bias_is_causal_and_directional():
    n = 2000
    btc = pd.Series(100 + np.cumsum(np.full(n, -0.01)))            # BTC steadily down
    coin = pd.Series(50 + np.cumsum(np.full(n, -0.02)))            # coin falls faster: ratio down too
    up, dn = macro_bias(coin, btc, 672)
    assert dn[1500] and not up[1500] and not dn[100]
    up2, dn2 = macro_bias(coin.iloc[:1600], btc.iloc[:1600], 672)
    assert (dn[:1600] == dn2).all()                                 # truncating the future changes nothing


def test_macro_filter_blocks_shorts_without_bias_down_and_needs_btc():
    arrs, (poc, vah, val), c = a_short()
    arrs[2][SIG + 1] = poc - 0.05
    df = frame(*arrs)
    with pytest.raises(ValueError):
        run_vpfade(df, SYM, VPParams(macro=True, macro_len=50), fee_rate=0, slippage_bps=0)
    flat_btc = np.full(len(df), 30000.0)                             # no bias at all
    assert run_vpfade(df, SYM, VPParams(macro=True, macro_len=50), fee_rate=0, slippage_bps=0, btc_close=flat_btc).trades == []
    falling = 30000.0 * np.exp(-0.002 * np.arange(len(df)))          # BTC falling...
    c = df["close"].to_numpy()
    coin_weaker = c * np.exp(-0.002 * np.arange(len(df)))            # ...coin falling faster -> ratio falling
    df2 = df.copy()
    df2["close"], df2["open"], df2["high"], df2["low"] = coin_weaker, df["open"] * np.exp(-0.002 * np.arange(len(df))), df["high"] * np.exp(-0.002 * np.arange(len(df))), df["low"] * np.exp(-0.002 * np.arange(len(df)))
    _ = run_vpfade(df2, SYM, VPParams(macro=True, macro_len=50), fee_rate=0, slippage_bps=0, btc_close=falling)   # runs, no crash


def fat(n=9000, seed=4):
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.003, n)))
    openp = np.r_[100.0, close[:-1]]
    w = np.abs(rng.standard_t(3, (2, n))) * 0.002 * close
    return pd.DataFrame({"ts": pd.date_range("2024-01-01", periods=n, freq="15min", tz="UTC"), "open": openp,
                         "high": np.maximum(openp, close) + w[0], "low": np.minimum(openp, close) - w[1],
                         "close": close, "volume": rng.lognormal(0, 0.8, n)})


@pytest.mark.parametrize("mode", ["fade", "discount"])
def test_causality_prefix_run_reproduces_earlier_trades(mode):
    df = fat()
    full = run_vpfade(df, SYM, VPParams(mode=mode))
    part = run_vpfade(df.iloc[:6000], SYM, VPParams(mode=mode))
    cut = df["ts"].iloc[6000 - 3]
    a = [(t.entry_ts, round(t.pnl, 8), t.side) for t in full.trades if t.exit_ts < cut]
    b = [(t.entry_ts, round(t.pnl, 8), t.side) for t in part.trades if t.exit_ts < cut]
    assert len(a) >= 5 and a == b


def test_mirror_symmetry_on_random_data():
    df = fat(seed=6)
    m = df.copy()
    c = 400.0
    m["open"], m["close"] = 2 * c - df["open"], 2 * c - df["close"]
    m["high"], m["low"] = 2 * c - df["low"], 2 * c - df["high"]
    a = run_vpfade(df, SYM, VPParams(), fee_rate=0, slippage_bps=0)
    b = run_vpfade(m, SYM, VPParams(), fee_rate=0, slippage_bps=0)
    assert len(a.trades) >= 5
    flip = {"buy": "sell", "sell": "buy"}
    same = sum(1 for x, y in zip(a.trades, b.trades) if x.entry_ts == y.entry_ts and flip[x.side] == y.side)
    # not bit-exact: the profile's POC tie-break and the value-area growth prefer the upper side, so near-ties can differ
    assert abs(len(a.trades) - len(b.trades)) <= max(2, len(a.trades) // 10) and same >= 0.8 * len(a.trades)


# ---- exploratory knobs: stop floor and A volume filter --------------------------------------

def test_stop_floor_widens_the_stop_and_the_reward_gate_then_filters():
    arrs, (poc, vah, val), c = a_short()
    arrs[2][SIG + 1] = poc - 0.05
    base = run(arrs).trades[0]
    assert run(arrs, p={"min_stop_pct": 0.1}).trades[0].stop == pytest.approx(base.stop)   # a floor tighter than the natural stop changes nothing
    assert run(arrs, p={"min_stop_pct": 2.0}).trades == []                                  # stop 2% away: reward is no longer 1.5x the risk
    wide = run(arrs, p={"min_stop_pct": 2.0, "min_rr": 0.1}).trades[0]
    assert wide.stop == pytest.approx(c * 1.02) and wide.side == "sell"
    assert wide.r == pytest.approx((c - poc) / (c * 1.02 - c), rel=1e-6)                     # R shrinks because risk is larger


def test_stop_floor_applies_to_longs_and_never_tightens():
    arrs, (poc, vah, val), c = b_long_b1()
    arrs[1][SIG + 1] = vah + 0.05
    t = run(arrs, p={"mode": "discount", "min_stop_pct": 0.8, "min_rr": 0.1}).trades[0]
    assert t.side == "buy" and t.stop == pytest.approx(c * (1 - 0.008))
    base = run(arrs, p={"mode": "discount"}).trades[0]
    assert t.stop < base.stop                                          # wider: further below the entry


def test_a_volume_filter_requires_a_volume_spike_on_the_signal_bar():
    arrs, (poc, vah, val), c = a_short()
    arrs[2][SIG + 1] = poc - 0.05
    assert len(run(arrs, p={"a_vol_mult": 0.5}).trades) == 1
    assert run(arrs, p={"a_vol_mult": 5.0}).trades == []                # the signal bar's volume is ~1.5x the average, not 5x


def test_defaults_leave_the_exploratory_knobs_off():
    p = VPParams()
    assert p.min_stop_pct == 0.0 and p.a_vol_mult == 0.0
