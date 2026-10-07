import numpy as np
import pandas as pd
import pytest

from cryptp.sweep import SweepParams, _pivots, run_sweep

SYM = "X/USDT:USDT"


def scenario(start="2025-01-01 00:00", confirm_close=100.8, tail=None):
    """Flat noisy market; a swing low at bar 40 (95); a sweep of it at bar 60 (low 94, big volume, close back
    above); a confirming bar 61; then whatever the `tail` dict says for bars 62+."""
    n = 130
    k = np.arange(n)
    close = 100 + 0.3 * np.sin(0.9 * k)
    openp = np.r_[close[0], close[:-1]]
    high = np.maximum(openp, close) + 0.15
    low = np.minimum(openp, close) - 0.15
    vol = np.ones(n)
    low[40] = 95.0
    # sweep bar 60
    openp[60], close[60], low[60], high[60], vol[60] = close[59], 100.0, 94.0, max(close[59], 100.0) + 0.15, 3.0
    # confirmation bar 61 (signal at its close), entry fills at the open of bar 62 = close of bar 61
    openp[61], close[61] = 100.0, confirm_close
    high[61], low[61] = max(100.0, confirm_close) + 0.1, min(100.0, confirm_close) - 0.1
    for b in range(62, n):                                  # quiet around the entry price
        openp[b] = close[b] = confirm_close
        high[b], low[b] = confirm_close + 0.2, confirm_close - 0.2
    for b, (o, h, l, c) in (tail or {}).items():
        openp[b], high[b], low[b], close[b] = o, h, l, c
    ts = pd.date_range(start, periods=n, freq="1h", tz="UTC")
    return pd.DataFrame({"ts": ts, "open": openp, "high": high, "low": low, "close": close, "volume": vol})


def go(df, **kw):
    return run_sweep(df, SYM, SweepParams(**kw.pop("p", {})), fee_rate=0, slippage_bps=0, **kw)


def test_pivot_tie_rules():
    h = pd.Series([1, 2, 3, 9, 3, 2, 1, 1, 1, 1], dtype=float)
    df = pd.DataFrame({"high": h, "low": -h})
    ph, pl = _pivots(df, 3)
    assert ph.nonzero()[0].tolist() == [6] and pl.nonzero()[0].tolist() == [6]       # confirmed 3 bars after bar 3
    tie = pd.DataFrame({"high": [1, 2, 3, 9, 9, 2, 1, 1, 1, 1.0], "low": [0] * 10})
    assert _pivots(tie, 3)[0].nonzero()[0].tolist() == [6]                            # equal on the RIGHT still counts
    tie_left = pd.DataFrame({"high": [1, 2, 9, 9, 3, 2, 1, 1, 1, 1.0], "low": [0] * 10})
    assert not _pivots(tie_left, 3)[0][:7].any() or _pivots(tie_left, 3)[0].nonzero()[0].tolist() == [6]


def test_sweep_confirm_entry_and_target_gives_exactly_1_5_R():
    df = scenario(tail={64: (100.8, 113.0, 100.6, 112.9)})
    r = go(df)
    assert len(r.trades) == 1
    t = r.trades[0]
    assert t.side == "buy" and t.entry == pytest.approx(100.8) and t.bars == 2          # filled bar 62, exited bar 64
    assert t.r == pytest.approx(1.5, rel=1e-6)


def test_no_trade_without_confirmation():
    assert go(scenario(confirm_close=96.0)).trades == []                                # 96 < sweep midpoint 97


def test_trade_without_confirmation_requirement_enters_on_the_sweep_bar():
    df = scenario(confirm_close=96.0, tail={})
    r = go(df, p={"use_confirm": False})
    assert r.trades and r.trades[0].entry_ts == df["ts"].iloc[61]                      # filled at open of bar 61


def test_session_filter_blocks_outside_12_to_16_utc():
    off = scenario(start="2025-01-01 14:00", tail={64: (100.8, 113.0, 100.6, 112.9)})   # bar 61 is 03:00 UTC
    assert go(off).trades == []
    assert len(go(off, p={"use_session": False}).trades) == 1


def test_breakeven_moves_stop_to_signal_close_and_exits_flat():
    df = scenario(tail={63: (100.8, 107.0, 100.7, 101.0), 64: (101.0, 101.2, 99.0, 99.5)})
    t = go(df).trades[0]
    assert t.r == pytest.approx(0.0, abs=1e-9) and t.bars == 2                          # BE at 100.8, no loss
    no_be = go(df, p={"use_be": False}).trades[0]
    assert no_be.r < -0.5 or no_be.bars > 2                                              # without BE it keeps running


def test_stop_is_assumed_first_when_a_bar_reaches_both():
    df = scenario(tail={62: (100.8, 113.0, 91.0, 100.8)})
    t = go(df).trades[0]
    assert t.r < -0.9 and t.bars == 0


def test_costs_reduce_pnl():
    df = scenario(tail={64: (100.8, 113.0, 100.6, 112.9)})
    free = run_sweep(df, SYM, fee_rate=0, slippage_bps=0).trades[0].pnl
    paid = run_sweep(df, SYM, fee_rate=0.001, slippage_bps=10).trades[0].pnl
    assert paid < free


def fat(n=9000, seed=4):
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.006, n)))
    openp = np.r_[100.0, close[:-1]]
    w = np.abs(rng.standard_t(3, (2, n))) * 0.004 * close
    return pd.DataFrame({"ts": pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC"), "open": openp,
                         "high": np.maximum(openp, close) + w[0], "low": np.minimum(openp, close) - w[1],
                         "close": close, "volume": rng.lognormal(0, 0.8, n)})


RELAXED = dict(use_session=False)


def test_causality_prefix_run_reproduces_earlier_trades():
    df = fat()
    full = run_sweep(df, SYM, SweepParams(**RELAXED))
    part = run_sweep(df.iloc[:6000], SYM, SweepParams(**RELAXED))
    cut = df["ts"].iloc[6000 - 3]
    a = [(t.entry_ts, round(t.pnl, 8), t.side) for t in full.trades if t.exit_ts < cut]
    b = [(t.entry_ts, round(t.pnl, 8), t.side) for t in part.trades if t.exit_ts < cut]
    assert len(a) >= 10 and a == b


def test_exact_mirror_symmetry_long_short():
    df = fat(seed=6)
    m = df.copy()
    c = 1000.0
    m["open"], m["close"] = 2 * c - df["open"], 2 * c - df["close"]
    m["high"], m["low"] = 2 * c - df["low"], 2 * c - df["high"]
    a = run_sweep(df, SYM, SweepParams(**RELAXED), fee_rate=0, slippage_bps=0)
    b = run_sweep(m, SYM, SweepParams(**RELAXED), fee_rate=0, slippage_bps=0)
    assert len(a.trades) >= 10 and len(a.trades) == len(b.trades)
    assert [t.entry_ts for t in a.trades] == [t.entry_ts for t in b.trades]
    flip = {"buy": "sell", "sell": "buy"}
    mismatch = [k for k, (x, y) in enumerate(zip(a.trades, b.trades))
                if flip[x.side] != y.side or abs(x.r - y.r) > 1e-6]
    # The Pine script is itself NOT perfectly symmetric on a bar that sweeps both a swing high and a swing low:
    # the short sweep overwrites the pending state, while the long wins the entry priority. The port reproduces
    # that, so a rare double-sweep bar may differ; every other trade must mirror exactly.
    assert len(mismatch) <= max(1, len(a.trades) // 50)


def test_risk_based_sizing_risks_exactly_the_chosen_percent_and_caps_leverage():
    df = scenario(tail={64: (100.8, 113.0, 100.6, 112.9)})
    r = run_sweep(df, SYM, SweepParams(risk_pct=1.0, max_leverage=100.0, use_be=False), fee_rate=0, slippage_bps=0, equity0=1000.0)
    t = r.trades[0]
    assert t.risk_usd == pytest.approx(10.0, rel=1e-6)                    # 1% of $1,000
    assert t.pnl == pytest.approx(10.0 * 1.5, rel=1e-6)                   # 1.5R at the default 1.5:1
    capped = run_sweep(df, SYM, SweepParams(risk_pct=1.0, max_leverage=0.05, use_be=False), fee_rate=0, slippage_bps=0, equity0=1000.0).trades[0]
    assert capped.risk_usd < 10.0                                         # the cap (5% of equity as notional) binds, so less than 1% is risked


def test_five_to_one_target_pays_five_r():
    df = scenario(tail={64: (100.8, 150.0, 100.6, 149.0)})
    t = run_sweep(df, SYM, SweepParams(rr=5.0, use_be=False, risk_pct=1.0, max_leverage=100.0), fee_rate=0, slippage_bps=0).trades[0]
    assert t.r == pytest.approx(5.0, rel=1e-6)
