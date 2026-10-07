"""Regime + relative strength + maker pullback, fixed 1:3 (docs/RS_PULLBACK_PREREG.md).

Pure rule functions shared by the backtest and the live paper journal, so both trade exactly the same rules.
Daily inputs are CLOSED daily candles only (dated before `day`); hourly inputs used for the plan are the bars of the previous UTC day.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .indicators import atr

DAY = pd.Timedelta(days=1)
HOUR = pd.Timedelta(hours=1)


@dataclass
class RSParams:
    breadth_min: int = 4
    sma: int = 200
    rs_days: int = 7
    top_n: int = 2
    min_gap_above: float = 0.001        # today's open must be >= 0.1% above the level
    stop_atr: float = 0.25
    min_stop: float = 0.015
    max_stop: float = 0.03
    rr: float = 3.0
    trade_through: float = 0.0005       # a maker fill needs low < level x (1 - 0.05%)
    maker_fee: float = 0.0002
    taker_fee: float = 0.00055
    slip_bps: float = 2.0
    time_stop_h: int = 72
    risk_pct: float = 1.0
    max_leverage: float = 3.0
    max_open: int = 2
    daily_stop_r: float = -2.0
    weekly_stop_r: float = -5.0
    default_funding: float = 0.0001
    use_regime: bool = True
    taker_entry: bool = False           # sensitivity only


@dataclass
class Plan:
    day: pd.Timestamp
    coin: str
    level: float
    stop: float
    target: float
    rs: float
    floor_applied: bool = False


@dataclass
class Outcome:
    status: str                          # pending | expired | cancelled | open | closed
    fill_ts: pd.Timestamp | None = None
    fill_px: float | None = None
    exit_ts: pd.Timestamp | None = None
    exit_px: float | None = None
    reason: str | None = None            # stop | target | time
    r: float | None = None               # net of fees, slippage and funding
    r_gross: float | None = None
    funding_r: float = 0.0


def closed_daily(df: pd.DataFrame, day: pd.Timestamp) -> pd.DataFrame:
    return df[df["ts"] < day]


def daily_state(df: pd.DataFrame, day: pd.Timestamp, n: int = 200) -> bool | None:
    """True/False = closed above/below its SMA-n yesterday; None = not enough history."""
    c = closed_daily(df, day)["close"]
    if len(c) < n:
        return None
    return bool(c.iloc[-1] > c.iloc[-n:].mean())


def regime(dailies: dict, breadth: list[str], day: pd.Timestamp, p: RSParams) -> tuple[bool | None, dict]:
    states = {c: daily_state(dailies[c], day, p.sma) for c in breadth if c in dailies}
    if any(v is None for v in states.values()) or len(states) < len(breadth):
        return None, states
    return sum(states.values()) >= p.breadth_min, states


def ret(df: pd.DataFrame, day: pd.Timestamp, k: int) -> float | None:
    c = closed_daily(df, day)["close"]
    return None if len(c) < k + 1 else float(c.iloc[-1] / c.iloc[-1 - k] - 1)


def rank_rs(dailies: dict, coins: list[str], bench: str, day: pd.Timestamp, p: RSParams) -> list[tuple[str, float]]:
    """Eligible coins (own state LONG) with RS > 0, strongest first."""
    rb = ret(dailies[bench], day, p.rs_days)
    out = []
    for c in coins:
        if c not in dailies or daily_state(dailies[c], day, p.sma) is not True:
            continue
        rc = ret(dailies[c], day, p.rs_days)
        if rc is None or rb is None:
            continue
        if rc - rb > 0:
            out.append((c, rc - rb))
    return sorted(out, key=lambda x: -x[1])


def eligible(dailies: dict, coins: list[str], day: pd.Timestamp, p: RSParams) -> list[str]:
    return [c for c in coins if c in dailies and daily_state(dailies[c], day, p.sma) is True]


def prior_day(h1: pd.DataFrame, day: pd.Timestamp):
    """(vwap, low, atr14) of the UTC day before `day`, from its 1h bars; None if the day is incomplete."""
    y = h1[(h1["ts"] >= day - DAY) & (h1["ts"] < day)]
    if len(y) < 24:
        return None
    tp = (y["high"] + y["low"] + y["close"]) / 3
    v = float((tp * y["volume"]).sum() / y["volume"].sum()) if y["volume"].sum() > 0 else float(tp.mean())
    a = atr(h1[h1["ts"] < day].tail(300)).iloc[-1]
    return v, float(y["low"].min()), float(a)


def plan_coin(coin: str, rs: float, day: pd.Timestamp, h1: pd.DataFrame, day_open: float, p: RSParams):
    """(Plan, None) or (None, reason skipped)."""
    pdy = prior_day(h1, day)
    if pdy is None:
        return None, "incomplete prior day"
    level, low, a = pdy
    if not day_open >= level * (1 + p.min_gap_above):
        return None, "open not above the level"
    stop = low - p.stop_atr * a
    floor = False
    if stop > level * (1 - p.min_stop):
        stop, floor = level * (1 - p.min_stop), True
    if stop < level * (1 - p.max_stop):
        return None, "stop wider than 3%"
    return Plan(day, coin, level, stop, level + p.rr * (level - stop), rs, floor), None


def plans_for_day(day: pd.Timestamp, dailies: dict, hourlies: dict, tradable: list[str], breadth: list[str], bench: str,
                  p: RSParams, day_opens: dict, picks: list[tuple[str, float]] | None = None):
    """The day's orders. `picks` overrides the RS choice (random-coin control)."""
    notes = {}
    if p.use_regime:
        ok, states = regime(dailies, breadth, day, p)
        notes["regime"] = {"risk_on": ok, "states": states}
        if not ok:
            return [], notes
    ranked = rank_rs(dailies, tradable, bench, day, p) if picks is None else picks
    notes["ranked"] = ranked
    plans, skipped = [], {}
    for coin, rs in ranked[: p.top_n]:
        if coin not in hourlies or coin not in day_opens:
            skipped[coin] = "no data"
            continue
        pl, why = plan_coin(coin, rs, day, hourlies[coin], day_opens[coin], p)
        if pl:
            plans.append(pl)
        else:
            skipped[coin] = why
    notes["skipped"] = skipped
    return plans, notes


def simulate(plan: Plan, h1: pd.DataFrame, p: RSParams, funding_rate=None, now: pd.Timestamp | None = None) -> Outcome:
    """Per-unit outcome on CLOSED 1h bars (bars ending after `now` are ignored). funding_rate: callable(ts)->rate or None."""
    bars = h1[h1["ts"] >= plan.day]
    if now is not None:
        bars = bars[bars["ts"] + HOUR <= now]
    slip = p.slip_bps / 10_000
    fee_in = p.taker_fee if p.taker_entry else p.maker_fee
    end_day = plan.day + DAY
    fill_i = None
    O, H, L, C, T = (bars[k].to_numpy() for k in ("open", "high", "low", "close", "ts"))
    for i in range(len(bars)):
        if T[i] >= end_day:
            return Outcome("expired")
        if O[i] <= plan.stop:
            return Outcome("cancelled")
        if L[i] < plan.level * (1 - p.trade_through):
            fill_i = i
            break
    if fill_i is None:
        return Outcome("pending")
    fill = min(float(O[fill_i]), plan.level)
    if p.taker_entry:
        fill *= 1 + slip
    risk = fill - plan.stop
    fts = pd.Timestamp(T[fill_i])
    fund = 0.0
    for i in range(fill_i, len(bars)):
        t = pd.Timestamp(T[i])
        if i > fill_i and t.minute == 0 and t.hour in (0, 8, 16):
            rate = funding_rate(t) if funding_rate else p.default_funding
            fund += rate * float(O[i])
        exit_px = reason = None
        if L[i] <= plan.stop:
            exit_px, reason, fee_out = min(plan.stop, float(O[i])) * (1 - slip), "stop", p.taker_fee
        elif i > fill_i and H[i] >= plan.target:
            exit_px, reason, fee_out = plan.target, "target", p.maker_fee
        elif t + HOUR >= fts + pd.Timedelta(hours=p.time_stop_h):
            exit_px, reason, fee_out = float(C[i]) * (1 - slip), "time", p.taker_fee
        if exit_px is not None:
            gross = exit_px - fill
            net = gross - fill * fee_in - exit_px * fee_out - fund
            return Outcome("closed", fts, fill, t, exit_px, reason, net / risk, gross / risk, fund / risk)
    return Outcome("open", fts, fill)
