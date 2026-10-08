"""Telegram alerts for the daily SMA dashboard (closed daily candles only).

Once per UTC day (after 00:05) the dashboard is rebuilt from CLOSED daily candles and compared with the previous day's state. A message is sent when
a coin ENTERS the near-the-line zone (|distance to SMA-200| < near_pct), or when it flips LONG <-> FLAT. The first run sends one summary of the coins
already near the line. State is kept in SQLite so restarts do not repeat alerts. Not a trading signal: near the line is where flips (whipsaws) happen.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import urllib.parse
import urllib.request

import pandas as pd

SCHEMA = "CREATE TABLE IF NOT EXISTS alert_state (symbol TEXT PRIMARY KEY, as_of TEXT, state TEXT, near INTEGER);" \
         "CREATE TABLE IF NOT EXISTS alert_log (day TEXT PRIMARY KEY, sent TEXT);"


def telegram_sender(token: str, chat_id: str, timeout: float = 20.0):
    def send(text: str) -> None:
        data = urllib.parse.urlencode({"chat_id": chat_id, "text": text, "disable_web_page_preview": "true"}).encode()
        with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", data=data, timeout=timeout) as r:
            body = json.loads(r.read().decode())
            if not body.get("ok"):
                raise RuntimeError(f"telegram: {body}")
    return send


def telegram_chat_ids(token: str) -> list[tuple[str, str]]:
    """(chat_id, name) of chats that have messaged the bot recently: send your bot any message, then call this."""
    with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/getUpdates", timeout=20) as r:
        upd = json.loads(r.read().decode()).get("result", [])
    out = {}
    for u in upd:
        chat = (u.get("message") or u.get("channel_post") or {}).get("chat") or {}
        if "id" in chat:
            out[str(chat["id"])] = chat.get("username") or chat.get("title") or chat.get("first_name") or ""
    return list(out.items())


def _px(v):
    return "-" if v is None else (f"{v:,.4f}" if v < 10 else f"{v:,.1f}")


def describe(s: dict, why: str) -> str:
    side = "above" if (s.get("dist_pct") or 0) > 0 else "below"
    fund = s.get("funding_ann_pct")
    f = f", perp funding {fund:+.1f}%/yr" if fund is not None else ""
    return (f"{s['coin']}: {why}. Close {_px(s.get('close'))} is {abs(s.get('dist_pct') or 0):.1f}% {side} its 200-day average "
            f"({_px(s.get('sma'))}); state {s['state']}, {s.get('days_in_state')} days{f}.")


class AlertService:
    def __init__(self, dashboard, send, path: str = ":memory:", near_pct: float = 3.0, page_url: str = ""):
        self.dash, self.send, self.near_pct, self.page_url = dashboard, send, near_pct, page_url
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock:
            self._db.executescript(SCHEMA)
        self.last_error = None

    def _prev(self) -> dict:
        with self._lock:
            return {r[0]: (r[1], r[2], bool(r[3])) for r in self._db.execute("SELECT symbol, as_of, state, near FROM alert_state")}

    def messages(self, rep: dict) -> list[str]:
        prev = self._prev()
        first = not prev
        msgs, near_now = [], []
        for s in rep.get("coins", []) + rep.get("watch", []):
            if s.get("state") not in ("LONG", "FLAT") or s.get("dist_pct") is None:
                continue
            near = abs(s["dist_pct"]) < self.near_pct
            if near:
                near_now.append(s)
            p = prev.get(s["symbol"])
            if first or p is None or p[0] == s.get("as_of"):
                continue                                          # first sight, or this close was already evaluated
            if p[1] != s["state"]:
                msgs.append(describe(s, f"FLIPPED {p[1]} -> {s['state']} on the {s['as_of']} close"))
            elif near and not p[2]:
                msgs.append(describe(s, f"now within {self.near_pct:g}% of its 200-day average"))
        if first and near_now:
            msgs.append("Coins currently near their 200-day average:\n" + "\n".join(describe(s, "near the line") for s in near_now))
        return msgs

    def _save(self, rep: dict) -> None:
        with self._lock, self._db:
            for s in rep.get("coins", []) + rep.get("watch", []):
                if s.get("state") in ("LONG", "FLAT") and s.get("dist_pct") is not None:
                    self._db.execute("INSERT OR REPLACE INTO alert_state VALUES (?,?,?,?)",
                                     (s["symbol"], s.get("as_of"), s["state"], int(abs(s["dist_pct"]) < self.near_pct)))

    def tick(self, now: pd.Timestamp | None = None) -> str:
        now = now or pd.Timestamp.now(tz="UTC")
        day = str(now.date())
        if now < now.normalize() + pd.Timedelta(minutes=5):
            return ""
        with self._lock:
            if self._db.execute("SELECT 1 FROM alert_log WHERE day=?", (day,)).fetchone():
                return ""
        try:
            rep = self.dash.get(force=True)
            msgs = self.messages(rep)
            footer = ("\n\nNot an entry signal by itself: near the line is where the filter whipsaws. Closed daily candles only."
                      + (f"\n{self.page_url}" if self.page_url else ""))
            for m in msgs:
                self.send(m + footer)
            self._save(rep)
            with self._lock, self._db:
                self._db.execute("INSERT OR REPLACE INTO alert_log VALUES (?,?)", (day, str(len(msgs))))
            self.last_error = None
            return f"alerts: {len(msgs)} sent for {day}"
        except Exception as e:                                    # retried on the next tick (the day is not logged)
            self.last_error = f"{type(e).__name__}: {str(e)[:200]}"
            return "alerts error " + self.last_error
