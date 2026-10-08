import numpy as np
import pandas as pd
import pytest

from cryptp.forward import Setup, planned_rr, score_setup, summarize

T0 = pd.Timestamp("2026-10-08 00:00", tz="UTC")


def bars(rows, start=T0):
    """rows: list of (open, high, low, close) 15m bars starting at `start`."""
    ts = pd.date_range(start, periods=len(rows), freq="15min", tz="UTC")
    return pd.DataFrame([dict(ts=t, open=o, high=h, low=l, close=c) for t, (o, h, l, c) in zip(ts, rows)])


def flat(n, px=100.0):
    return [(px, px + 0.1, px - 0.1, px)] * n


def long_setup(**kw):
    return Setup(id="t1", symbol="X-USDT-SWAP", side="long", logged_at=T0, stop=99.0, target=103.0, **kw)


def short_setup(**kw):
    return Setup(id="t2", symbol="X-USDT-SWAP", side="short", logged_at=T0, stop=101.0, target=97.0, **kw)


def score(df, s, **kw):
    return score_setup(df, s, fee_rate=kw.pop("fee_rate", 0.0), slippage_bps=kw.pop("slip", 0.0), **kw)


def test_fill_is_the_open_of_the_first_bar_after_logging_and_target_pays_planned_r():
    df = bars(flat(1) + flat(3) + [(100.0, 103.5, 99.9, 103.0)])      # bar at 00:00 is NOT usable; fills at the 00:15 open
    r = score(df, long_setup())
    assert r["fill_ts"] == T0 + pd.Timedelta(minutes=15) and r["fill"] == pytest.approx(100.0)
    assert r["status"] == "target" and r["r_net"] == pytest.approx(3.0)       # (103-100)/(100-99)


def test_stop_costs_exactly_one_r_without_costs():
    df = bars(flat(1) + flat(2) + [(100.0, 100.2, 98.5, 98.8)])
    r = score(df, long_setup())
    assert r["status"] == "stop" and r["r_net"] == pytest.approx(-1.0)


def test_stop_is_assumed_first_when_a_bar_reaches_both():
    df = bars(flat(1) + [(100.0, 104.0, 98.0, 100.0)])
    assert score(df, long_setup())["status"] == "stop"


def test_short_is_the_mirror_of_long():
    up = bars(flat(2) + [(100.0, 103.5, 99.9, 103.0)])
    dn = bars([(200 - o, 200 - l, 200 - h, 200 - c) for o, h, l, c in [(100.0, 100.1, 99.9, 100.0)] * 2 + [(100.0, 103.5, 99.9, 103.0)]])
    a = score(up, long_setup())
    b = score(dn, Setup(id="m", symbol="X-USDT-SWAP", side="short", logged_at=T0, stop=101.0, target=97.0))
    assert a["status"] == "target" and b["status"] == "target" and a["r_net"] == pytest.approx(b["r_net"])


def test_missed_when_price_already_past_the_target():
    r = score(bars(flat(1) + [(103.5, 104.0, 103.2, 103.8)]), long_setup())
    assert r["status"] == "missed" and r["r_net"] is None


def test_missed_when_the_remaining_reward_is_too_small():
    r = score(bars(flat(1) + [(102.8, 103.0, 102.7, 102.9)]), long_setup())        # 0.2 reward vs 3.8 risk at the fill
    assert r["status"] == "missed" and "reward:risk" in r["note"]
    assert score(bars(flat(1) + [(102.8, 103.2, 102.7, 103.1)]), long_setup(), min_rr=0.01)["status"] == "target"


def test_missed_when_the_first_open_is_beyond_the_stop():
    assert score(bars(flat(1) + [(98.5, 98.9, 98.0, 98.2)]), long_setup())["status"] == "missed"


def test_time_stop_exits_at_the_close_of_the_last_horizon_bar():
    df = bars(flat(1) + [(100.0, 100.3, 99.8, 100.2)] * 12)
    r = score(df, long_setup(horizon_hours=1.0))                                  # 4 bars
    assert r["status"] == "expired" and r["bars"] == 3 and r["exit"] == pytest.approx(100.2)
    assert r["r_net"] == pytest.approx(0.2)


def test_open_while_inside_the_horizon_and_pending_without_data():
    df = bars(flat(1) + [(100.0, 100.3, 99.8, 100.4)] * 2)
    r = score(df, long_setup())
    assert r["status"] == "open" and r["r_net"] == pytest.approx(0.4) and "unrealized" in r["note"]
    assert score(bars(flat(1)), long_setup())["status"] == "pending"


def test_costs_reduce_r():
    df = bars(flat(1) + [(100.0, 103.5, 99.9, 103.0)])
    free = score(df, long_setup())["r_net"]
    paid = score_setup(df, long_setup(), fee_rate=0.001, slippage_bps=10)["r_net"]
    assert paid < free


def test_planned_rr_uses_his_own_entry():
    assert planned_rr(long_setup(his_entry=100.0)) == pytest.approx(3.0)
    assert planned_rr(long_setup()) is None
    assert planned_rr(Setup("x", "X", "short", T0, stop=101.0, target=97.0, his_entry=100.0)) == pytest.approx(3.0)


def test_summarize_counts_and_ci():
    rows = [dict(status="target", r_net=3.0), dict(status="stop", r_net=-1.0), dict(status="stop", r_net=-1.0),
            dict(status="missed", r_net=None), dict(status="open", r_net=0.5), dict(status="pending", r_net=None)]
    s = summarize(rows)
    assert (s["valid"], s["missed"], s["open"], s["pending"], s["scored"]) == (3, 1, 1, 1, 5)
    assert s["mean_r"] == pytest.approx(1 / 3) and s["missed_rate"] == pytest.approx(0.2)
    assert s["ci90_low"] <= s["mean_r"] <= s["ci90_high"]
    assert summarize([dict(status="pending", r_net=None)])["valid"] == 0
