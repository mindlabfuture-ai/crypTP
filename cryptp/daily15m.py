"""Daily direction + 15m pullback-resume entries (docs/DAILY15M_PREREG.md, frozen pre-registration).

The daily state (last CLOSED daily close vs SMA-200) permits longs; a 15m pullback to EMA(20) that resumes above the prior bar's
high is the trigger. Stop under the 12-bar low, single +3R target, flat by the end of the UTC day. Signals use data up to the trigger
bar only; fills are at the next bar's open.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .backtest import Result, Trade
from .indicators import atr, ema


@dataclass
class DailyParams:
    sma_days: int = 200
    ema_trend: int = 50
    ema_pull: int = 20
    pull_bars: int = 12
    stop_atr: float = 0.1
    cutoff_hour: int = 20
    min_stop_pct: float = 0.45
    max_stop_pct: float = 3.0
    rr: float = 3.0
    risk_pct: float = 1.0
    max_leverage: float = 3.0
    cooldown_bars: int = 8
    max_trades_day: int = 3
    side: str = "long"                  # "long" | "short" (exact mirror, docs/FLATSHORT_PREREG.md)
    daily_filter: str = "regime"        # "regime" (long in LONG state, short in FLAT) | "off" | "opposite" (controls)


def daily_allowed(df15: pd.DataFrame, daily: pd.DataFrame, sma_days: int = 200) -> np.ndarray:
    """True where the last daily candle CLOSED BEFORE the bar's UTC date has close > SMA(sma_days). NaN history -> False."""
    d = daily.sort_values("ts").reset_index(drop=True)
    sma = d["close"].rolling(sma_days).mean()
    state = (d["close"] > sma) & sma.notna()
    valid = sma.notna()
    # state of candle dated D becomes usable on date D+1
    key = pd.DataFrame({"day": d["ts"].dt.normalize() + pd.Timedelta(days=1), "state": state.to_numpy(), "valid": valid.to_numpy()})
    bars = pd.DataFrame({"day": df15["ts"].dt.normalize()})
    m = pd.merge_asof(bars.reset_index().sort_values("day"), key.sort_values("day"), on="day").sort_values("index")
    return m["state"].fillna(False).to_numpy(bool), m["valid"].fillna(False).to_numpy(bool)


def find_signals(df: pd.DataFrame, p: DailyParams, allowed: np.ndarray, valid: np.ndarray):
    """{trigger_bar: stop_price}. Uses only bars up to the trigger bar."""
    c, h, l = (df[k].astype(float) for k in ("close", "high", "low"))
    e50, e20 = ema(c, p.ema_trend), ema(c, p.ema_pull)
    a = atr(df)
    if p.side == "long":
        pulled = (l <= e20).rolling(p.pull_bars).max().fillna(0).astype(bool)
        cond = (c > e50) & pulled & (c > e20) & (c > h.shift())
        stop = l.rolling(p.pull_bars).min() - p.stop_atr * a
        regime = allowed
    else:
        pulled = (h >= e20).rolling(p.pull_bars).max().fillna(0).astype(bool)
        cond = (c < e50) & pulled & (c < e20) & (c < l.shift())
        stop = h.rolling(p.pull_bars).max() + p.stop_atr * a
        regime = (~allowed) & valid
    edge = cond & ~cond.shift(fill_value=False)
    if p.daily_filter == "regime":
        ok = regime
    elif p.daily_filter == "opposite":
        ok = (allowed if p.side == "short" else ((~allowed) & valid))
    else:
        ok = np.ones(len(df), bool)
    ok = ok & (df["ts"].dt.hour.to_numpy() < p.cutoff_hour)
    sel = edge.to_numpy() & ok & stop.notna().to_numpy()
    return {int(i): float(stop.iloc[i]) for i in np.flatnonzero(sel)}


def run_daily15m(df: pd.DataFrame, daily: pd.DataFrame, symbol: str, p: DailyParams | None = None,
                 fee_rate: float = 0.00055, slippage_bps: float = 2.0, equity0: float = 1000.0) -> Result:
    p = p or DailyParams()
    df = df.reset_index(drop=True)
    n, slip = len(df), slippage_bps / 10_000
    O, H, L, C = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    ts = df["ts"]
    day = ts.dt.strftime("%Y-%m-%d").to_numpy()
    allowed, valid = daily_allowed(df, daily, p.sma_days)
    sig = find_signals(df, p, allowed, valid)
    equity = equity0
    d = 1 if p.side == "long" else -1
    pos = 0
    qty = entry_px = stop = target = risk_usd = fee_in = 0.0
    entry_i = cool = 0
    pending = None
    trades_today, cur_day = 0, None
    res = Result(symbol, equity0, bars=n)
    curve = np.empty(n)

    def close_trade(i: int, px: float):
        nonlocal equity, pos, qty, cool
        gross = (px - entry_px) * qty * d
        equity += gross - px * qty * fee_rate
        res.trades.append(Trade(symbol, ts.iloc[entry_i], ts.iloc[i], entry_px, stop,
                                -fee_in + gross - px * qty * fee_rate, risk_usd, i - entry_i, "buy" if d > 0 else "sell"))
        pos, qty, cool = 0, 0.0, i + p.cooldown_bars

    for i in range(n):
        if day[i] != cur_day:
            cur_day, trades_today = day[i], 0
        if pending is not None and pos == 0:
            fill = O[i] * (1 + d * slip)
            dist = d * (fill - pending)
            if dist > 0:
                q = min(equity * p.risk_pct / 100.0 / dist, equity * p.max_leverage / fill)
                if q > 0:
                    qty, pos, entry_px, stop, entry_i, risk_usd = q, d, fill, pending, i, q * dist
                    target = fill + d * p.rr * dist
                    fee_in = fill * q * fee_rate
                    equity -= fee_in
                    trades_today += 1
        pending = None
        if pos:
            if (L[i] <= stop) if d > 0 else (H[i] >= stop):
                close_trade(i, (min(stop, O[i]) if d > 0 else max(stop, O[i])) * (1 - d * slip))
            elif (H[i] >= target) if d > 0 else (L[i] <= target):
                close_trade(i, target)
            elif i + 1 >= n or day[i + 1] != day[i]:                      # last bar of the UTC day: flat at its close
                close_trade(i, C[i] * (1 - d * slip))
        curve[i] = equity + ((C[i] - entry_px) * qty * d if pos else 0.0)
        if pos == 0 and i in sig and i + 1 < n and i > cool and trades_today < p.max_trades_day:
            st = sig[i]
            dist_pct = d * (C[i] - st) / C[i] * 100.0
            if d * (C[i] - st) > 0 and p.min_stop_pct <= dist_pct <= p.max_stop_pct:
                pending = st

    res.equity = pd.Series(curve, index=ts)
    res.buy_hold_pct = (C[-1] / C[0] - 1) * 100
    return res
