import asyncio

import numpy as np
import pandas as pd
import pytest
from aiohttp.test_utils import TestClient, TestServer

from cryptp.journal import Journal, JournalService, render_html
from cryptp.rspullback import Plan, RSParams, daily_state, plan_coin, plans_for_day, rank_rs, regime, simulate
from cryptp.webhook import create_app

DAY = pd.Timestamp("2026-03-10", tz="UTC")
P = RSParams()


def daily(closes, end=DAY):
    ts = pd.date_range(end=end, periods=len(closes), freq="D", tz="UTC")       # last row is TODAY's forming candle
    c = np.asarray(closes, float)
    return pd.DataFrame({"ts": ts, "open": c, "high": c * 1.01, "low": c * 0.99, "close": c, "volume": 1.0})


def hourly(rows, start):
    ts = pd.date_range(start, periods=len(rows), freq="1h", tz="UTC")
    o, h, l, c = zip(*rows)
    return pd.DataFrame({"ts": ts, "open": o, "high": h, "low": l, "close": c, "volume": 1.0})


def flat(px, n, spread=0.2):
    return [(px, px + spread, px - spread, px)] * n


def test_daily_state_uses_closed_candles_only():
    closes = [100.0] * 210 + [50.0]                       # today's forming candle crashes: must be ignored
    closes[-2] = 120.0                                    # yesterday closed above the average
    assert daily_state(daily(closes), DAY, 200) is True


def test_regime_and_relative_strength_ranking():
    up = daily(list(np.linspace(50, 100, 220)))           # rising: above SMA
    dn = daily(list(np.linspace(100, 50, 220)))           # falling: below SMA
    d = {"BTC": up, "ETH": up, "SOL": up, "ADA": up, "SUI": dn}
    ok, states = regime(d, ["BTC", "ETH", "SOL", "ADA", "SUI"], DAY, P)
    assert ok and sum(states.values()) == 4
    fast = daily(list(np.linspace(20, 100, 220)))         # stronger 7d return than BTC
    d.update(FAST=fast, SEI=dn)
    ranked = rank_rs(d, ["ETH", "FAST", "SEI"], "BTC", DAY, P)
    assert [c for c, _ in ranked] == ["FAST"]             # ETH has RS 0 (same series as BTC); SEI not eligible


def test_plan_floor_cap_and_open_rules():
    h = hourly(flat(100.0, 24), DAY - pd.Timedelta(days=1))           # yesterday: VWAP 100, low 99.8
    pl, why = plan_coin("X", 0.05, DAY, h, 101.0, P)
    assert pl and pl.floor_applied and pl.stop == pytest.approx(98.5) and pl.target == pytest.approx(104.5)
    assert plan_coin("X", 0.05, DAY, h, 100.05, P) == (None, "open not above the level")
    wide = hourly(flat(100.0, 23) + [(100, 100.2, 95.0, 100)], DAY - pd.Timedelta(days=1))
    assert plan_coin("X", 0.05, DAY, wide, 101.0, P)[1] == "stop wider than 3%"


PL = Plan(DAY, "X", 100.0, 98.5, 104.5, 0.05)


def test_fill_needs_trade_through_and_target_is_maker():
    rows = [(101, 101.2, 100.0, 100.5),                   # touches the level but does not trade through: no fill
            (100.5, 100.6, 99.9, 100.2),                  # trades through: fill at 100
            (100.2, 104.6, 100.1, 104.0)]                 # target
    o = simulate(PL, hourly(rows, DAY), P)
    assert o.status == "closed" and o.reason == "target" and o.fill_ts == DAY + pd.Timedelta(hours=1)
    cost = (100 * 0.0002 + 104.5 * 0.0002) / 1.5
    assert o.r_gross == pytest.approx(3.0) and o.r == pytest.approx(3.0 - cost)


def test_stop_first_when_a_bar_touches_both_and_cancel_below_stop():
    rows = [(100.5, 100.6, 99.9, 100.2), (100.2, 105, 98.0, 101)]
    o = simulate(PL, hourly(rows, DAY), P)
    assert o.reason == "stop" and o.r < -1.0
    assert simulate(PL, hourly([(98.0, 98.4, 97.0, 98.2)], DAY), P).status == "cancelled"
    assert simulate(PL, hourly(flat(101.0, 30), DAY), P).status == "expired"


def test_time_stop_after_72_hours_and_closed_bars_only():
    rows = [(100.5, 100.6, 99.9, 100.2)] + flat(101.0, 80)
    o = simulate(PL, hourly(rows, DAY), P)
    assert o.reason == "time" and o.exit_ts + pd.Timedelta(hours=1) == DAY + pd.Timedelta(hours=72)   # the bar that CLOSES 72h after the fill bar opened
    late = flat(101.0, 1) + rows                          # the fill happens in the 01:00 bar
    now = DAY + pd.Timedelta(hours=1, minutes=30)         # ... which has not closed yet: ignored
    assert simulate(PL, hourly(late, DAY), P, now=now).status == "pending"
    assert simulate(PL, hourly(late, DAY), P, now=now + pd.Timedelta(minutes=30)).status == "open"


def test_journal_decisions_shadow_tracking_and_locking():
    j = Journal()
    plans = [Plan(DAY, "A", 100.0, 98.5, 104.5, 0.05), Plan(DAY, "B", 100.0, 98.5, 104.5, 0.03)]
    assert j.propose(DAY, plans, {"regime": {"risk_on": True}}) == 2
    assert j.propose(DAY, plans, {}) == 0                 # idempotent
    ids = {r["coin"]: r["id"] for r in j.rows()}
    assert j.decide(ids["A"], "approve")[0] and j.decide(ids["B"], "skip")[0]
    win = hourly([(100.5, 100.6, 99.9, 100.2), (100.2, 104.6, 100.1, 104.0)], DAY)
    lose = hourly([(100.5, 100.6, 99.9, 100.2), (100.2, 100.3, 98.0, 98.2)], DAY)
    j.update({"A": win, "B": lose}, DAY + pd.Timedelta(hours=5))
    rep = j.report()
    assert rep["groups"]["approved"]["n"] == 1 and rep["groups"]["approved"]["avg_r"] > 2.9
    assert rep["groups"]["skipped (shadow)"]["n"] == 1 and rep["groups"]["skipped (shadow)"]["avg_r"] < -1.0
    assert rep["paper_equity"] > 1000
    assert j.decide(ids["A"], "skip")[0] is False         # locked after the outcome
    assert "Approve" not in render_html(j, "", False)


def test_service_proposes_once_per_day_after_0005():
    up = daily(list(np.linspace(50, 100, 220)))
    fast = daily(list(np.linspace(20, 100, 220)))
    h = hourly(flat(100.0, 24) + [(101.0, 101.2, 100.9, 101.1)], DAY - pd.Timedelta(days=1))
    fd = lambda c: fast if c == "SOL" else up
    j = Journal()
    svc = JournalService(j, fd, lambda c: h, ["ETH", "SOL"], ["BTC", "ETH", "SOL", "ADA", "SUI"], "BTC")
    assert "proposed" not in svc.tick(DAY + pd.Timedelta(minutes=2))
    assert "proposed 1" in svc.tick(DAY + pd.Timedelta(minutes=6))
    assert "proposed" not in svc.tick(DAY + pd.Timedelta(minutes=12))
    assert [r["coin"] for r in j.rows()] == ["SOL"]


def test_webhook_journal_routes_and_token():
    j = Journal()
    j.propose(DAY, [Plan(DAY, "SOL/USDT:USDT", 100.0, 98.5, 104.5, 0.05)], {"regime": {"risk_on": True}})
    cid = j.rows()[0]["id"]

    async def go():
        async with TestClient(TestServer(create_app(None, "s", journal=j, journal_token="jt"))) as c:
            r = await c.get("/journal")
            assert r.status == 200 and "Read-only" in await r.text()
            r = await c.get("/journal?jtoken=jt")
            assert "Approve" in await r.text()
            r = await c.post("/journal/decide", data={"id": cid, "action": "approve", "token": "bad"})
            assert r.status == 403
            r = await c.post("/journal/decide", data={"id": cid, "action": "approve", "token": "jt"}, allow_redirects=False)
            assert r.status == 303
            assert (await (await c.get("/api/journal")).json())["candidates"][0]["decision"] == "approved"
        async with TestClient(TestServer(create_app(None, "s", journal=j))) as c:              # no JOURNAL_TOKEN: decisions disabled
            r = await c.post("/journal/decide", data={"id": cid, "action": "skip", "token": ""})
            assert r.status == 403
        async with TestClient(TestServer(create_app(None, "s"))) as c:
            assert (await c.get("/journal")).status == 404
    asyncio.run(go())


def test_journal_decisions_work_behind_the_dashboard_token():
    j = Journal()
    j.propose(DAY, [Plan(DAY, "SOL/USDT:USDT", 100.0, 98.5, 104.5, 0.05)], {"regime": {"risk_on": True}})
    cid = j.rows()[0]["id"]

    async def go():
        async with TestClient(TestServer(create_app(None, "s", dashboard_token="dt", journal=j, journal_token="jt"))) as c:
            assert (await c.get("/journal?jtoken=jt")).status == 403                     # dashboard token missing
            page = await (await c.get("/journal?token=dt&jtoken=jt")).text()
            assert 'action="/journal/decide?token=dt"' in page
            r = await c.post("/journal/decide", data={"id": cid, "action": "approve", "token": "jt"}, allow_redirects=False)
            assert r.status == 403                                                       # no dashboard token on the POST
            r = await c.post("/journal/decide?token=dt", data={"id": cid, "action": "approve", "token": "jt"}, allow_redirects=False)
            assert r.status == 303 and "token=dt" in r.headers["Location"]
            assert (await c.get(r.headers["Location"])).status == 200
    asyncio.run(go())
