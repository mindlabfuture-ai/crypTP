import asyncio
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest
from aiohttp.test_utils import TestClient, TestServer

from cryptp.config import load_config
from cryptp.dashboard import (DashboardService, build_report, closed_candles, render_html, render_text, trend_state)
from cryptp.webhook import create_app

NOW = datetime(2026, 10, 7, 14, 0, tzinfo=timezone.utc)


def daily(closes, end="2026-10-07", opens=None):
    c = np.asarray(closes, float)
    o = c if opens is None else np.asarray(opens, float)
    ts = pd.date_range(end=end, periods=len(c), freq="1D", tz="UTC")
    return pd.DataFrame({"ts": ts, "open": o, "high": np.maximum(o, c) * 1.01, "low": np.minimum(o, c) * 0.99, "close": c, "volume": 1.0})


def closed(closes, opens=None):
    """Daily frame whose last row is YESTERDAY (a completed candle) relative to NOW."""
    return daily(closes, end="2026-10-06", opens=opens)


def test_forming_candle_is_dropped_but_closed_one_is_kept():
    assert len(closed_candles(daily(np.arange(100, 130)), NOW)) == 29                  # last row is 2026-10-07 = today -> forming
    assert len(closed_candles(closed(np.arange(100, 130)), NOW)) == 30


def test_a_wild_forming_candle_changes_nothing():
    base = closed(np.r_[np.full(250, 100.0), np.full(10, 110.0)])
    wild = pd.concat([base, daily([1.0], end="2026-10-07")], ignore_index=True)        # today's forming candle at price 1
    a = trend_state(base, "X/USDT:USDT", 200, now=NOW)
    b = trend_state(wild, "X/USDT:USDT", 200, now=NOW)
    assert a == b and b["close"] == 110.0 and b["as_of"] == "2026-10-06"


def test_long_state_days_in_state_and_move_since_flip_are_exact():
    closes = np.r_[np.full(250, 100.0), np.full(10, 110.0)]                            # flips above the average at index 250
    opens = closes.copy(); opens[251] = 111.0                                           # the open AFTER the flip bar
    s = trend_state(closed(closes, opens=opens), "X/USDT:USDT", 200, now=NOW)
    assert s["state"] == "LONG" and s["days_in_state"] == 10 and s["close"] == 110.0
    assert s["since_flip_pct"] == pytest.approx((110.0 / 111.0 - 1) * 100)


def test_flip_on_the_latest_closed_bar_has_unknown_move_not_a_guess():
    s = trend_state(closed(np.r_[np.full(250, 100.0), [130.0]]), "X/USDT:USDT", 200, now=NOW)
    assert s["state"] == "LONG" and s["days_in_state"] == 1 and s["since_flip_pct"] is None


def test_flat_state_when_below_the_average():
    up = 100 + 0.5 * np.arange(250)                                                    # a real uptrend: closes stay above their average
    s = trend_state(closed(np.r_[up, np.full(5, 120.0)]), "X/USDT:USDT", 200, now=NOW)
    assert s["state"] == "FLAT" and s["days_in_state"] == 5 and s["dist_pct"] < -15 and not s["run_truncated"]


def test_near_line_and_insufficient_history():
    assert trend_state(closed(np.r_[np.full(300, 100.0), [101.0]]), "X/USDT:USDT", 200, near_pct=3.0, now=NOW)["near_line"] is True
    assert trend_state(closed(np.arange(100, 150)), "X/USDT:USDT", 200, now=NOW)["state"] == "INSUFFICIENT_HISTORY"


def test_breadth_regime_thresholds():
    mk = lambda st: dict(state=st)
    assert build_report([mk("LONG")] * 4 + [mk("FLAT")])["breadth"]["regime"] == "RISK-ON"
    assert build_report([mk("LONG")] * 3 + [mk("FLAT")] * 2)["breadth"]["regime"] == "MIXED"
    assert build_report([mk("LONG")] + [mk("FLAT")] * 4)["breadth"]["regime"] == "RISK-OFF"
    assert build_report([])["breadth"]["regime"] is None


def test_service_caches_and_isolates_errors():
    calls = {"n": 0}

    def fetch(sym):
        calls["n"] += 1
        if sym.startswith("BAD"):
            raise RuntimeError("geo-blocked <script>alert(1)</script>")
        return closed(np.r_[np.full(300, 100.0), [105.0]])

    svc = DashboardService(fetch, ["OK/USDT:USDT", "BAD/USDT:USDT"], ttl=600)
    rep = svc.get()
    states = {c["coin"]: c["state"] for c in rep["coins"]}
    assert states == {"OK": "LONG", "BAD": "ERROR"} and rep["breadth"]["total"] == 1
    n = calls["n"]
    svc.get()
    assert calls["n"] == n                                                              # served from cache
    svc.get(force=True)
    assert calls["n"] == 2 * n
    page = render_html(rep)
    assert "<script>alert(1)</script>" not in page and "&lt;script&gt;" in page         # error text is escaped


def test_renderers_include_state_and_the_limits():
    svc = DashboardService(lambda s: closed(np.r_[np.full(300, 100.0), [130.0]]), ["BTC/USDT:USDT"], funding_fn=lambda s: 21.0)
    rep = svc.get()
    txt, page = render_text(rep), render_html(rep)
    for needle in ("BTC", "LONG", "+21%", "last close"):
        assert needle in txt
    assert "Read this first" in page and "not a forecast" in page and "+21%/yr" in page and "viewport" in page
    assert "closed candles only" in page and "rovisional" not in page and "live" not in page.lower().replace("deliver", "")


def test_webhook_serves_dashboard_json_and_enforces_token():
    svc = DashboardService(lambda s: closed(np.r_[np.full(300, 100.0), [130.0]]), ["BTC/USDT:USDT"])

    async def go():
        async with TestClient(TestServer(create_app(None, "s", svc, dashboard_token="t0k"))) as c:
            assert (await c.get("/dashboard")).status == 403 and (await c.get("/api/trend")).status == 403
            assert (await c.get("/dashboard?token=wrong")).status == 403
            r = await c.get("/dashboard?token=t0k")
            assert r.status == 200 and "text/html" in r.headers["Content-Type"] and "BTC" in await r.text()
            j = await (await c.get("/api/trend?token=t0k")).json()
            assert j["coins"][0]["coin"] == "BTC" and j["breadth"]["total"] == 1
            assert (await c.get("/health")).status == 200
        async with TestClient(TestServer(create_app(None, "s", svc))) as c:             # no token configured -> open
            assert (await c.get("/dashboard")).status == 200
            r = await c.get("/", allow_redirects=False)
            assert r.status == 302 and r.headers["Location"] == "/dashboard"
        async with TestClient(TestServer(create_app(None, "s"))) as c:                  # dashboard disabled
            assert (await c.get("/dashboard")).status == 404

    asyncio.run(go())


def test_watchlist_is_shown_but_never_counted_in_breadth():
    svc = DashboardService(lambda s: closed(np.r_[np.full(300, 100.0), [130.0]]) if s.startswith("BTC") else closed(np.r_[np.full(300, 100.0), [60.0]]),
                           ["BTC/USDT:USDT"], watch=["NEAR/USDT", "FET/USDT"])
    rep = svc.get()
    assert [c["coin"] for c in rep["coins"]] == ["BTC"] and [c["coin"] for c in rep["watch"]] == ["NEAR", "FET"]
    assert rep["breadth"] == {"long": 1, "total": 1, "regime": "RISK-ON"}              # two FLAT watch coins change nothing
    page, txt = render_html(rep), render_text(rep)
    assert "Watchlist" in page and "NOT counted in breadth" in page and "NEAR" in page and "Watchlist" in txt and "FET" in txt


def test_extended_flag_when_far_above_the_average():
    s = trend_state(closed(np.r_[np.full(300, 100.0), [300.0]]), "NEAR/USDT", 200, now=NOW)
    assert s["state"] == "LONG" and s["dist_pct"] > 50
    rep = build_report([s])
    assert "Far above the average" in render_html(rep) and "EXTENDED" in render_text(rep)


def test_a_watchlist_symbol_that_fails_does_not_blank_the_page():
    def fetch(sym):
        if sym.startswith("FET"):
            raise RuntimeError("no such market")
        return closed(np.r_[np.full(300, 100.0), [130.0]])
    rep = DashboardService(fetch, ["BTC/USDT:USDT"], watch=["NEAR/USDT", "FET/USDT"]).get()
    assert {c["coin"]: c["state"] for c in rep["watch"]} == {"NEAR": "LONG", "FET": "ERROR"}
