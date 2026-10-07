"""Paper-forward trade journal for the RS-pullback rules (docs/RS_PULLBACK_PREREG.md).

Each day the system proposes its candidates; you approve or skip each one. Every candidate's outcome is then tracked on CLOSED 1h candles at the
pre-registered costs: approved candidates are your paper trades; skipped (and undecided) ones are tracked as "shadow" trades, so you can measure
whether your judgement beats the unfiltered system. Nothing here places orders.
"""
from __future__ import annotations

import html
import math
import sqlite3
import threading
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from .rspullback import Plan, RSParams, plans_for_day, simulate

SCHEMA = """
CREATE TABLE IF NOT EXISTS jr_days (day TEXT PRIMARY KEY, risk_on INTEGER, notes TEXT, created TEXT);
CREATE TABLE IF NOT EXISTS jr_candidates (
  id INTEGER PRIMARY KEY AUTOINCREMENT, day TEXT, coin TEXT, level REAL, stop REAL, target REAL, rs REAL, floor INTEGER,
  created TEXT, decision TEXT DEFAULT 'pending', decided_at TEXT, note TEXT DEFAULT '',
  status TEXT DEFAULT 'pending', fill_ts TEXT, fill_px REAL, exit_ts TEXT, exit_px REAL, reason TEXT, r REAL, r_gross REAL,
  UNIQUE(day, coin));
"""
DONE = ("closed", "expired", "cancelled")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


class Journal:
    def __init__(self, path: str = ":memory:", params: RSParams | None = None):
        self.p = params or RSParams()
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._db.executescript(SCHEMA)

    # ---- writing ----
    def has_day(self, day: pd.Timestamp) -> bool:
        with self._lock:
            return self._db.execute("SELECT 1 FROM jr_days WHERE day=?", (str(day.date()),)).fetchone() is not None

    def propose(self, day: pd.Timestamp, plans: list[Plan], notes: dict) -> int:
        risk_on = (notes.get("regime") or {}).get("risk_on")
        with self._lock, self._db:
            self._db.execute("INSERT OR IGNORE INTO jr_days VALUES (?,?,?,?)",
                             (str(day.date()), None if risk_on is None else int(risk_on), repr(notes)[:4000], _now()))
            n = 0
            for pl in plans:
                cur = self._db.execute("INSERT OR IGNORE INTO jr_candidates (day, coin, level, stop, target, rs, floor, created) "
                                       "VALUES (?,?,?,?,?,?,?,?)", (str(day.date()), pl.coin, pl.level, pl.stop, pl.target, pl.rs,
                                                                    int(pl.floor_applied), _now()))
                n += cur.rowcount
            return n

    def decide(self, cid: int, action: str, note: str = "") -> tuple[bool, str]:
        if action not in ("approve", "skip"):
            return False, "action must be approve or skip"
        with self._lock, self._db:
            row = self._db.execute("SELECT status, decision FROM jr_candidates WHERE id=?", (cid,)).fetchone()
            if row is None:
                return False, "no such candidate"
            if row["status"] != "pending":                       # locked once the order filled or the day ended
                return False, f"locked: candidate is {row['status']}"
            self._db.execute("UPDATE jr_candidates SET decision=?, decided_at=?, note=? WHERE id=?",
                             ("approved" if action == "approve" else "skipped", _now(), note[:500], cid))
            return True, "ok"

    def open_candidates(self) -> list[sqlite3.Row]:
        with self._lock:
            return self._db.execute(f"SELECT * FROM jr_candidates WHERE status NOT IN {DONE}").fetchall()

    def update(self, hourlies: dict, now: pd.Timestamp, funding: dict | None = None) -> int:
        """Advance every unfinished candidate on closed 1h bars. funding: coin -> latest rate (per 8h) or None."""
        changed = 0
        for row in self.open_candidates():
            h1 = hourlies.get(row["coin"])
            if h1 is None:
                continue
            pl = Plan(pd.Timestamp(row["day"], tz="UTC"), row["coin"], row["level"], row["stop"], row["target"], row["rs"])
            rate = (funding or {}).get(row["coin"])
            out = simulate(pl, h1, self.p, (lambda t, r=rate: r) if rate is not None else None, now)
            with self._lock, self._db:
                self._db.execute("UPDATE jr_candidates SET status=?, fill_ts=?, fill_px=?, exit_ts=?, exit_px=?, reason=?, r=?, r_gross=? "
                                 "WHERE id=?", (out.status, str(out.fill_ts) if out.fill_ts is not None else None, out.fill_px,
                                                str(out.exit_ts) if out.exit_ts is not None else None, out.exit_px, out.reason,
                                                out.r, out.r_gross, row["id"]))
            changed += int(out.status != row["status"])
        return changed

    # ---- reading ----
    def rows(self, limit: int = 500) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._db.execute("SELECT * FROM jr_candidates ORDER BY day DESC, id DESC LIMIT ?", (limit,))]

    def days(self, limit: int = 30) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._db.execute("SELECT day, risk_on, created FROM jr_days ORDER BY day DESC LIMIT ?", (limit,))]

    def report(self) -> dict:
        rows = self.rows(100000)
        closed = [r for r in rows if r["status"] == "closed"]
        groups = {"approved": [r for r in closed if r["decision"] == "approved"],
                  "skipped (shadow)": [r for r in closed if r["decision"] == "skipped"],
                  "undecided (shadow)": [r for r in closed if r["decision"] == "pending"],
                  "all system picks": closed}
        rep = {"generated_at": _now(), "groups": {k: stats([r["r"] for r in v]) for k, v in groups.items()}}
        appr = sorted(groups["approved"], key=lambda r: r["exit_ts"])
        eq = 1000.0
        for r in appr:
            eq *= 1 + self.p.risk_pct / 100 * r["r"]
        rep["paper_equity"] = eq
        wk = pd.Timestamp.now(tz="UTC").isocalendar()
        week_r = sum(r["r"] for r in appr if pd.Timestamp(r["exit_ts"]).isocalendar()[:2] == wk[:2])
        rep["week_r"] = week_r
        rep["weekly_stop_hit"] = week_r <= self.p.weekly_stop_r
        by_coin = {}
        for r in appr:
            by_coin.setdefault(r["coin"], []).append(r["r"])
        rep["approved_by_coin"] = {c: stats(v) for c, v in sorted(by_coin.items())}
        rep["fill_rate_pct"] = (100 * sum(r["status"] in ("closed", "open") for r in rows) /
                                max(1, sum(r["status"] != "pending" for r in rows)))
        return rep


def stats(rs: list[float]) -> dict:
    n = len(rs)
    if n == 0:
        return dict(n=0)
    a = np.array(rs, float)
    se = float(a.std(ddof=1) / math.sqrt(n)) if n > 1 else float("nan")
    win, loss = a[a > 0].sum(), -a[a <= 0].sum()
    return dict(n=n, win_pct=float((a > 0).mean() * 100), avg_r=float(a.mean()), se=se,
                ci95=(float(a.mean() - 1.96 * se), float(a.mean() + 1.96 * se)) if n > 1 else None,
                total_r=float(a.sum()), pf=float(win / loss) if loss > 0 else (float("inf") if win > 0 else 0.0))


class JournalService:
    """Live wiring: propose once per UTC day (after 00:05) and update outcomes on every tick. Fetchers return OHLCV DataFrames."""

    def __init__(self, journal: Journal, fetch_daily, fetch_hourly, tradable: list[str], breadth: list[str], bench: str,
                 funding_fn=None):
        self.j, self.fd, self.fh, self.tradable, self.breadth, self.bench = journal, fetch_daily, fetch_hourly, tradable, breadth, bench
        self.funding_fn = funding_fn
        self.last_error = None

    def tick(self, now: pd.Timestamp | None = None) -> str:
        now = now or pd.Timestamp.now(tz="UTC")
        day = now.normalize()
        msg = []
        try:
            if now >= day + pd.Timedelta(minutes=5) and not self.j.has_day(day):
                coins = sorted(set(self.tradable) | set(self.breadth) | {self.bench})
                dailies = {c: self.fd(c) for c in coins}
                hourlies = {c: self.fh(c) for c in self.tradable}
                opens = {}
                for c, h in hourlies.items():
                    t = h[h["ts"] == day]
                    if len(t):
                        opens[c] = float(t["open"].iloc[0])
                plans, notes = plans_for_day(day, dailies, hourlies, self.tradable, self.breadth, self.bench, self.j.p, opens)
                msg.append(f"proposed {self.j.propose(day, plans, notes)} for {day.date()}")
            open_coins = {r["coin"] for r in self.j.open_candidates()}
            if open_coins:
                hourlies = {c: self.fh(c) for c in open_coins}
                funding = {}
                if self.funding_fn:
                    for c in open_coins:
                        try:
                            funding[c] = self.funding_fn(c)
                        except Exception:
                            pass
                msg.append(f"updated {self.j.update(hourlies, now, funding)}")
            self.last_error = None
        except Exception as e:                                   # a data hiccup must not kill the loop
            self.last_error = f"{type(e).__name__}: {str(e)[:200]}"
            msg.append("error " + self.last_error)
        return "; ".join(msg)


def _fmt(v, f="{:+.2f}"):
    return "-" if v is None or (isinstance(v, float) and (math.isnan(v))) else f.format(v)


def render_html(j: Journal, token: str = "", can_decide: bool = False, last_error: str | None = None, dash_token: str = "") -> str:
    e = html.escape
    rep, rows = j.report(), j.rows(200)
    css = ("body{font:15px/1.5 system-ui,sans-serif;margin:0;background:#f7f7f5;color:#1c1c1a}main{max-width:1100px;margin:0 auto;padding:20px 16px}"
           "@media (prefers-color-scheme:dark){body{background:#141413;color:#ecece8}.card,table{background:#1e1e1c!important}td,th{border-color:#2e2e2b!important}}"
           "h1{font-size:20px;margin:0}h2{font-size:16px;margin:22px 0 6px}.sub{color:#6b6b66;font-size:13px}.card{background:#fff;border:1px solid #e4e4df;"
           "border-radius:12px;padding:12px 16px;margin:10px 0}table{border-collapse:collapse;width:100%;background:#fff;font-size:13px}"
           "td,th{border-bottom:1px solid #e4e4df;padding:6px 8px;text-align:right}td:first-child,th:first-child{text-align:left}"
           ".wrap{overflow-x:auto}button{font:inherit;padding:2px 10px;border-radius:8px;border:1px solid #999;background:none;color:inherit;cursor:pointer}"
           ".warn{color:#b3261e}")
    g = rep["groups"]
    stat_rows = "".join(
        f"<tr><td>{e(k)}</td><td>{v.get('n', 0)}</td><td>{_fmt(v.get('win_pct'), '{:.0f}%')}</td><td>{_fmt(v.get('avg_r'))}</td>"
        f"<td>{'-' if not v.get('ci95') else e(f'{v['ci95'][0]:+.2f} .. {v['ci95'][1]:+.2f}')}</td><td>{_fmt(v.get('total_r'), '{:+.1f}')}</td>"
        f"<td>{_fmt(v.get('pf'), '{:.2f}')}</td></tr>" for k, v in g.items())
    def act(r):
        if r["status"] != "pending" or not can_decide:
            return e(r["decision"])
        action = "/journal/decide" + (f"?token={html.escape(dash_token)}" if dash_token else "")
        return (f'<form method="post" action="{action}" style="display:inline"><input type="hidden" name="id" value="{r["id"]}">'
                f'<input type="hidden" name="token" value="{e(token)}"><button name="action" value="approve">Approve</button> '
                f'<button name="action" value="skip">Skip</button></form> <span class="sub">{e(r["decision"])}</span>')
    cand = "".join(
        f"<tr><td>{e(r['day'])}</td><td>{e(r['coin'].split('/')[0])}</td><td>{r['level']:.5g}</td><td>{r['stop']:.5g}"
        f"{' (1.5% floor)' if r['floor'] else ''}</td><td>{r['target']:.5g}</td><td>{_fmt(r['rs'] * 100, '{:+.1f}%')}</td>"
        f"<td>{act(r)}</td><td>{e(r['status'])}{(' / ' + e(r['reason'])) if r['reason'] else ''}</td><td>{_fmt(r['r'])}</td></tr>"
        for r in rows)
    days = "".join(f"<tr><td>{e(d['day'])}</td><td>{'RISK-ON' if d['risk_on'] == 1 else 'no trade (not risk-on)' if d['risk_on'] == 0 else 'n/a'}</td>"
                   f"<td>{e(d['created'])}</td></tr>" for d in j.days(14))
    warn = '<p class="warn">Weekly stop reached (-5R): no new approvals until Monday.</p>' if rep["weekly_stop_hit"] else ""
    err = f'<p class="warn">Last data error: {e(last_error)}</p>' if last_error else ""
    decide_note = "" if can_decide else '<p class="sub">Read-only: open this page with ?token=JOURNAL_TOKEN to approve or skip.</p>'
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<meta http-equiv="refresh" content="300"><title>Paper Trade Journal</title><style>{css}</style></head><body><main>'
            f'<h1>Paper trade journal</h1><div class="sub">RS pullback rules (docs/RS_PULLBACK_PREREG.md): maker limit at yesterday\'s VWAP, stop 1.5-3%, '
            f'fixed 1:3, 72h time stop. Paper only, no orders are placed. Updated {e(rep["generated_at"])}</div>{warn}{err}{decide_note}'
            f'<div class="card">Paper equity (approved trades, 1% risk each): <b>${rep["paper_equity"]:,.2f}</b> &nbsp; This week: '
            f'<b>{rep["week_r"]:+.1f} R</b> &nbsp; Fill rate: {rep["fill_rate_pct"]:.0f}%</div>'
            f'<h2>Results (closed trades, net R)</h2><div class="wrap"><table><tr><th>group</th><th>trades</th><th>win</th><th>avg R</th>'
            f'<th>95% range of avg R</th><th>total R</th><th>PF</th></tr>{stat_rows}</table></div>'
            f'<p class="sub">Your edge = approved vs skipped. Until a group has ~60 trades its 95% range will be wide: do not size up on a lucky streak.</p>'
            f'<h2>Candidates</h2><div class="wrap"><table><tr><th>day</th><th>coin</th><th>limit buy</th><th>stop</th><th>target (3R)</th>'
            f'<th>RS vs BTC</th><th>decision</th><th>status</th><th>R</th></tr>{cand}</table></div>'
            f'<h2>Days</h2><div class="wrap"><table><tr><th>day</th><th>regime</th><th>proposed at</th></tr>{days}</table></div>'
            f'</main></body></html>')
