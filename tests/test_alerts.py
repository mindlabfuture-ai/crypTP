import pandas as pd

from cryptp.alerts import AlertService


def coin(sym, state, dist, as_of="2026-10-06"):
    return dict(symbol=sym, coin=sym.split("/")[0], state=state, dist_pct=dist, as_of=as_of, close=100.0, sma=100.0 / (1 + dist / 100),
                days_in_state=5, funding_ann_pct=None)


class FakeDash:
    def __init__(self):
        self.rep = None

    def get(self, force=False):
        return self.rep


def run(svc, dash, coins, watch=(), day="2026-10-07 00:10"):
    dash.rep = {"coins": coins, "watch": list(watch)}
    return svc.tick(pd.Timestamp(day, tz="UTC"))


def test_first_run_summary_then_only_changes_once_per_day():
    sent, dash = [], FakeDash()
    svc = AlertService(dash, sent.append, near_pct=3.0)
    assert run(svc, dash, [coin("BTC/USDT:USDT", "LONG", 19.0)], day="2026-10-07 00:02") == ""     # before 00:05: nothing
    run(svc, dash, [coin("BTC/USDT:USDT", "LONG", 19.0), coin("SOL/USDT:USDT", "LONG", 2.0)])
    assert len(sent) == 1 and "currently near" in sent[0] and "SOL" in sent[0] and "BTC" not in sent[0]
    run(svc, dash, [coin("SOL/USDT:USDT", "LONG", 1.0)], day="2026-10-07 06:00")                   # same day: no repeat
    assert len(sent) == 1
    # next day: BTC enters the zone, SOL (already near) stays near -> one message for BTC only
    run(svc, dash, [coin("BTC/USDT:USDT", "LONG", 2.5, "2026-10-07"), coin("SOL/USDT:USDT", "LONG", 1.0, "2026-10-07")], day="2026-10-08 00:06")
    assert len(sent) == 2 and sent[1].startswith("BTC: now within 3%")


def test_flip_alert_and_watchlist_and_restart_dedupe(tmp_path):
    db = str(tmp_path / "a.db")
    sent, dash = [], FakeDash()
    svc = AlertService(dash, sent.append, db)
    run(svc, dash, [coin("ADA/USDT:USDT", "LONG", 1.0)], [coin("FET/USDT", "LONG", 10.0)])
    svc2 = AlertService(dash, sent.append, db)                    # restart: state survives, same day not re-sent
    run(svc2, dash, [coin("ADA/USDT:USDT", "LONG", 1.0)], [coin("FET/USDT", "LONG", 10.0)], day="2026-10-07 09:00")
    assert len(sent) == 1
    run(svc2, dash, [coin("ADA/USDT:USDT", "FLAT", -0.5, "2026-10-07")], [coin("FET/USDT", "LONG", 2.0, "2026-10-07")], day="2026-10-08 00:06")
    assert any(m.startswith("ADA: FLIPPED LONG -> FLAT") for m in sent) and any(m.startswith("FET: now within") for m in sent)


def test_send_failure_retries_next_tick():
    calls, dash = [], FakeDash()

    def bad(m):
        calls.append(m)
        raise RuntimeError("telegram down")
    svc = AlertService(dash, bad)
    assert "error" in run(svc, dash, [coin("SOL/USDT:USDT", "LONG", 1.0)])
    sent = []
    svc.send = sent.append
    run(svc, dash, [coin("SOL/USDT:USDT", "LONG", 1.0)], day="2026-10-07 00:20")
    assert len(sent) == 1
