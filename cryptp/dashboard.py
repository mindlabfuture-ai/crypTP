"""Daily trend dashboard: where each coin sits against its 200-day average (spot-style assumptions).

EVERYTHING here comes from CLOSED daily candles only: the strategy decides on completed closes, so today's forming candle
is dropped before anything is computed (no live price, no intraday "provisional" flips). Perp funding is a rate, not a
candle, and is shown as the latest value. This is a trend STATE, not a forecast.
See docs/TREND_PREREG.md and docs/FUNDING_PREREG.md for what the backtests did and did not show.
"""
from __future__ import annotations

import html
import threading
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd

LIMITS = [
    "A trend state, not a forecast: the filter lags, whipsaws near the line, and lost money in fast crashes (e.g. 2025).",
    "Backtest (docs/TREND_PREREG.md): improved return per unit of drawdown on 5 of 5 coins but missed the pre-registered "
    "drawdown-reduction and robustness bars. Treat it as risk management, not an edge.",
    "Spot-style: no funding. Held on a perpetual, longs paid roughly 19-43% a year in the periods the filter was long "
    "(docs/FUNDING_PREREG.md), which removed 37-79% of the return.",
]


def closed_candles(df: pd.DataFrame, now: datetime | None = None) -> pd.DataFrame:
    """Drop the last candle if it is today's (still forming) UTC day."""
    now = now or datetime.now(timezone.utc)
    if len(df) and df["ts"].iloc[-1].date() >= now.date():
        return df.iloc[:-1].reset_index(drop=True)
    return df.reset_index(drop=True)


def trend_state(df: pd.DataFrame, symbol: str, n: int = 200, near_pct: float = 3.0,
                now: datetime | None = None, funding_ann_pct: float | None = None) -> dict:
    closed = closed_candles(df, now)                              # today's forming candle never gets past this line
    out = dict(symbol=symbol, coin=symbol.split("/")[0], n=n, funding_ann_pct=funding_ann_pct,
               as_of=str(closed["ts"].iloc[-1].date()) if len(closed) else None,
               close=float(closed["close"].iloc[-1]) if len(closed) else None)
    if len(closed) < n + 1:
        out.update(state="INSUFFICIENT_HISTORY", sma=None, dist_pct=None, days_in_state=None, since_flip_pct=None,
                   near_line=False, sma_slope_30d_pct=None, flips_1y=None, from_1y_high_pct=None, run_truncated=False)
        return out
    c = closed["close"].astype(float).reset_index(drop=True)
    sma = c.rolling(n).mean()
    above = (c > sma).to_numpy()
    valid = sma.notna().to_numpy()
    last = len(c) - 1
    k = last
    while k - 1 >= 0 and valid[k - 1] and above[k - 1] == above[k]:
        k -= 1
    truncated = k == 0 or not valid[k - 1]                      # the run began at the start of usable data
    days = last - k + 1
    # The backtests fill at the OPEN after the flip bar. If the flip is the latest closed bar, that open is not a
    # closed candle yet, so the move since the flip is unknown (None) rather than guessed.
    since = (float(c.iloc[-1]) / float(closed["open"].iloc[k + 1]) - 1) * 100 if k < last else None
    sma_last = float(sma.iloc[-1])
    dist = (float(c.iloc[-1]) / sma_last - 1) * 100
    recent = above[-365:][valid[-365:]]
    flips = int((recent[1:] != recent[:-1]).sum()) if len(recent) > 1 else 0
    out.update(
        state="LONG" if above[last] else "FLAT", sma=sma_last, dist_pct=dist, days_in_state=days,
        run_truncated=bool(truncated), since_flip_pct=since, near_line=bool(abs(dist) < near_pct),
        sma_slope_30d_pct=float((sma.iloc[-1] / sma.iloc[-31] - 1) * 100) if len(sma.dropna()) > 31 else None,
        flips_1y=flips, from_1y_high_pct=float((float(c.iloc[-1]) / c.tail(365).max() - 1) * 100))
    return out


def build_report(states: list[dict], n: int = 200) -> dict:
    ok = [s for s in states if s["state"] in ("LONG", "FLAT")]
    longs = sum(s["state"] == "LONG" for s in ok)
    share = longs / len(ok) if ok else None
    regime = None if share is None else ("RISK-ON" if share >= 0.8 else "RISK-OFF" if share <= 0.2 else "MIXED")
    return dict(generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), sma=n, coins=states,
                breadth=dict(long=longs, total=len(ok), regime=regime), limits=LIMITS)


class DashboardService:
    """Fetches daily candles per symbol, caches the report for `ttl` seconds."""

    def __init__(self, fetch, symbols, n: int = 200, near_pct: float = 3.0, ttl: int = 600, funding_fn=None):
        self.fetch, self.symbols, self.n, self.near_pct, self.ttl, self.funding_fn = fetch, list(symbols), n, near_pct, ttl, funding_fn
        self._lock, self._cache, self._at = threading.Lock(), None, 0.0

    def get(self, force: bool = False) -> dict:
        with self._lock:
            if force or self._cache is None or time.time() - self._at > self.ttl:
                states = []
                for sym in self.symbols:
                    try:
                        df = self.fetch(sym)
                        fund = None
                        if self.funding_fn:
                            try:
                                fund = self.funding_fn(sym)
                            except Exception:
                                fund = None
                        states.append(trend_state(df, sym, self.n, self.near_pct, funding_ann_pct=fund))
                    except Exception as e:                             # one bad symbol must not blank the page
                        states.append(dict(symbol=sym, coin=sym.split("/")[0], state="ERROR", error=f"{type(e).__name__}: {str(e)[:120]}",
                                           close=None, sma=None, dist_pct=None, days_in_state=None, since_flip_pct=None,
                                           near_line=False, sma_slope_30d_pct=None, flips_1y=None,
                                           from_1y_high_pct=None, funding_ann_pct=None, as_of=None, run_truncated=False, n=self.n))
                self._cache, self._at = build_report(states, self.n), time.time()
            return self._cache


def _f(v, fmt="{:+.1f}%", none="-"):
    return none if v is None or (isinstance(v, float) and np.isnan(v)) else fmt.format(v)


def render_text(rep: dict) -> str:
    b = rep["breadth"]
    lines = [f"Daily trend dashboard (SMA{rep['sma']}, closed daily candles)  {rep['generated_at']}",
             f"Breadth: {b['long']}/{b['total']} above their SMA  ->  {b['regime']}", "",
             f"{'coin':<5}{'state':<8}{'last close':>12}{'SMA':>12}{'dist':>8}{'days':>6}{'since flip':>12}{'30d SMA':>9}{'flips/1y':>9}{'funding/yr':>11}  flags"]
    for s in rep["coins"]:
        flags = [x for x, on in (("NEAR LINE", s.get("near_line")), ("RUN>=DATA", s.get("run_truncated"))) if on]
        price = _f(s["close"], "{:,.4f}") if s["close"] is not None and s["close"] < 10 else _f(s["close"], "{:,.1f}")
        sma = _f(s["sma"], "{:,.4f}") if s["sma"] is not None and s["sma"] < 10 else _f(s["sma"], "{:,.1f}")
        lines.append(f"{s['coin']:<5}{s['state']:<8}{price:>12}{sma:>12}{_f(s['dist_pct']):>8}{_f(s['days_in_state'], '{:d}'):>6}"
                     f"{_f(s['since_flip_pct']):>12}{_f(s['sma_slope_30d_pct']):>9}{_f(s['flips_1y'], '{:d}'):>9}"
                     f"{_f(s.get('funding_ann_pct'), '{:+.0f}%'):>11}  {' '.join(flags)}")
    lines += [""] + ["- " + t for t in rep["limits"]]
    return "\n".join(lines)


_CSS = """
:root{--bg:#f7f7f5;--card:#fff;--ink:#1c1c1a;--mute:#6b6b66;--line:#e4e4df;--long:#0f7b4a;--longbg:#e3f4ea;--flat:#8a5a00;--flatbg:#fbf0d9;--warn:#b3261e}
@media (prefers-color-scheme:dark){:root{--bg:#141413;--card:#1e1e1c;--ink:#ecece8;--mute:#9a9a93;--line:#2e2e2b;--long:#5fd49b;--longbg:#15301f;--flat:#e8b64c;--flatbg:#33290f;--warn:#ff8a80}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
main{max-width:980px;margin:0 auto;padding:20px 16px 40px}h1{font-size:20px;margin:0 0 4px}.sub{color:var(--mute);font-size:13px;margin-bottom:16px}
.regime{display:flex;gap:12px;align-items:center;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px;margin-bottom:16px}
.regime b{font-size:18px}.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px}.top{display:flex;justify-content:space-between;align-items:baseline}
.coin{font-weight:650;font-size:17px}.chip{font-size:12px;font-weight:650;padding:2px 10px;border-radius:99px}.LONG{background:var(--longbg);color:var(--long)}.FLAT{background:var(--flatbg);color:var(--flat)}
.ERROR,.INSUFFICIENT_HISTORY{background:var(--line);color:var(--mute)}.price{font-size:22px;margin:6px 0 2px}dl{display:grid;grid-template-columns:auto 1fr;gap:2px 12px;margin:8px 0 0;font-size:13px}
dt{color:var(--mute)}dd{margin:0;text-align:right}.flags{margin-top:8px;font-size:12px;color:var(--warn)}.flags span{margin-right:8px}
.limits{margin-top:20px;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 16px;font-size:13px;color:var(--mute)}.limits li{margin:4px 0}
footer{margin-top:14px;font-size:12px;color:var(--mute)}
"""


def render_html(rep: dict) -> str:
    e = html.escape
    b = rep["breadth"]
    cards = []
    for s in rep["coins"]:
        flags = []
        if s.get("near_line"):
            flags.append("Near the line: flips (whipsaws) are most likely here.")
        if s.get("run_truncated"):
            flags.append("This state began before the available data.")
        if s["state"] == "ERROR":
            flags.append("Data error: " + s.get("error", ""))
        rows = [("Distance to SMA", _f(s["dist_pct"])), (f"Days in state", _f(s["days_in_state"], "{:d}")),
                ("Move since flip", _f(s["since_flip_pct"], "{:+.1f}%", "n/a (fills at next open)" if s.get("days_in_state") == 1 else "-")), ("SMA slope (30d)", _f(s["sma_slope_30d_pct"])),
                ("Flips in last year", _f(s["flips_1y"], "{:d}")), ("From 1y high", _f(s["from_1y_high_pct"])),
                ("Perp funding (latest)", _f(s.get("funding_ann_pct"), "{:+.0f}%/yr"))]
        price = "-" if s["close"] is None else (f"{s['close']:,.4f}" if s["close"] < 10 else f"{s['close']:,.1f}")
        sma = "-" if s["sma"] is None else (f"{s['sma']:,.4f}" if s["sma"] < 10 else f"{s['sma']:,.1f}")
        cards.append(
            f'<section class="card"><div class="top"><span class="coin">{e(s["coin"])}</span>'
            f'<span class="chip {e(s["state"])}">{e(s["state"].replace("_", " "))}</span></div>'
            f'<div class="price">{e(price)}</div><div class="sub" style="margin:0">last close</div><div class="sub" style="margin:0">SMA{rep["sma"]}: {e(sma)}</div>'
            f'<dl>{"".join(f"<dt>{e(k)}</dt><dd>{e(v)}</dd>" for k, v in rows)}</dl>'
            f'<div class="flags">{"".join(f"<span>{e(x)}</span><br>" for x in flags)}</div></section>')
    regime = e(b["regime"] or "n/a")
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<meta http-equiv="refresh" content="600"><title>Daily Trend Dashboard</title><style>{_CSS}</style></head><body><main>'
            f'<h1>Daily trend dashboard</h1><div class="sub">Last completed daily close vs {rep["sma"]}-day average (closed candles only), spot-style. Data as of {e(rep["coins"][0]["as_of"] or "n/a") if rep["coins"] else "n/a"} close; page built {e(rep["generated_at"])}</div>'
            f'<div class="regime"><div><div class="sub" style="margin:0">Breadth</div><b>{b["long"]}/{b["total"]} above their average</b></div>'
            f'<span class="chip {"LONG" if regime=="RISK-ON" else "FLAT" if regime=="RISK-OFF" else "ERROR"}">{regime}</span></div>'
            f'<div class="grid">{"".join(cards)}</div>'
            f'<div class="limits"><b>Read this first</b><ul>{"".join(f"<li>{e(t)}</li>" for t in rep["limits"])}</ul></div>'
            f'<footer>Not financial advice. Data: exchange daily candles (UTC). JSON: /api/trend</footer></main></body></html>')
