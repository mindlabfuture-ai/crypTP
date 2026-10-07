"""1h trend-continuation breakout, run-the-winner exit, midnight break-even (docs/HOURLY_PREREG.md, frozen pre-registration).

Long only, only in the daily LONG state (last CLOSED daily candle above its SMA-200). Signal: 1h close above the highest high of the previous
24 bars. Stop 2 x ATR under the fill. No profit-taking before +3R, then lock +1.5R and trail 3 x ATR under the highest high; at each UTC
midnight an open, profitable trade has its stop raised to break-even. Every stop change takes effect on the NEXT bar. Funding is charged
at the 00:00/08:00/16:00 UTC settlements a trade is open through.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .backtest import Result, Trade
from .bounce import funding_rates
from .daily15m import daily_allowed
from .indicators import atr


@dataclass
class HourlyParams:
    channel_bars: int = 24
    stop_atr: float = 2.0
    min_stop_pct: float = 0.9
    max_stop_pct: float = 5.0
    arm_r: float = 3.0
    lock_r: float = 1.5
    trail_atr: float = 3.0
    midnight: str = "be"                # "be" (frozen rule) | "flat" (secondary variant)
    exit_mode: str = "trail"            # "trail" (frozen) | "fixed3" (control: +3R target, no trail)
    cutoff_hour: int = 20
    risk_pct: float = 1.0
    max_leverage: float = 3.0
    cooldown_bars: int = 4
    max_trades_day: int = 2
    sma_days: int = 200
    default_funding: float = 0.0001


def to_hourly(df15: pd.DataFrame) -> pd.DataFrame:
    g = df15.set_index("ts").resample("1h")
    h = g.agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
    h["n"] = g["close"].count()
    return h[h["n"] == 4].drop(columns="n").reset_index()


def find_signals(df: pd.DataFrame, p: HourlyParams, daily: pd.DataFrame) -> dict[int, float]:
    """{signal_bar: ATR at that bar}. Uses only bars <= t and daily candles closed before the bar's UTC date."""
    allowed, _ = daily_allowed(df, daily, p.sma_days)
    prior_high = df["high"].rolling(p.channel_bars).max().shift(1)
    cond = df["close"] > prior_high
    edge = (cond & ~cond.shift(fill_value=False)).to_numpy()
    a = atr(df).to_numpy(float)
    sel = edge & allowed & ~np.isnan(a)
    return {int(i): float(a[i]) for i in np.flatnonzero(sel)}


def run_hourly(df: pd.DataFrame, symbol: str, p: HourlyParams | None = None, fee_rate: float = 0.00055,
               slippage_bps: float = 2.0, equity0: float = 1000.0, funding: pd.DataFrame | None = None,
               charge_funding: bool = True, signals: dict | None = None, daily: pd.DataFrame | None = None,
               start_i: int = 0, end_i: int | None = None) -> Result:
    p = p or HourlyParams()
    df = df.reset_index(drop=True)
    n = len(df)
    end_i = n if end_i is None else end_i
    slip = slippage_bps / 10_000
    O, H, L, C = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    a_np = atr(df).to_numpy(float)
    ts = df["ts"]
    day = ts.dt.strftime("%Y-%m-%d").to_numpy()
    hours, mins = ts.dt.hour.to_numpy(), ts.dt.minute.to_numpy()
    frate = funding_rates(df, funding, p.default_funding)
    if signals is None:
        signals = find_signals(df, p, daily)

    equity = equity0
    pos = False
    qty = entry_px = stop = next_stop = risk_unit = risk_usd = fee_in = fund_paid = hh = init_stop = 0.0
    armed = be_moved = False
    entry_i = 0
    cool = -1
    pending = None
    trades_today, cur_day = 0, None
    res = Result(symbol, equity0, bars=end_i - start_i)
    res.funding_paid = res.funding_received = 0.0
    res.armed_trades = res.be_moved_trades = res.be_stopped = res.flat_cut_above_1r = res.skipped_busy = 0
    res.trade_notes = []
    curve = np.full(n, np.nan)

    def close_trade(i: int, px: float, reason: str):
        nonlocal equity, pos, qty, cool
        gross = (px - entry_px) * qty
        fee_out = px * qty * fee_rate
        equity += gross - fee_out
        pnl = -fee_in + gross - fee_out - fund_paid
        res.trades.append(Trade(symbol, ts.iloc[entry_i], ts.iloc[i], entry_px, init_stop, pnl, risk_usd, i - entry_i, "buy"))
        res.armed_trades += int(armed)
        res.be_moved_trades += int(be_moved)
        res.be_stopped += int(reason == "be_stop")
        if reason == "flat" and (px - entry_px) / risk_unit > 1.0:
            res.flat_cut_above_1r += 1
        res.trade_notes.append(reason)
        pos, qty, cool = False, 0.0, i + p.cooldown_bars

    for i in range(start_i, end_i):
        if day[i] != cur_day:
            cur_day, trades_today = day[i], 0
        if pending is not None and not pos:
            a_sig = pending
            fill = O[i] * (1 + slip)
            st = fill - p.stop_atr * a_sig
            dist_pct = (fill - st) / fill * 100.0
            if hours[i] < p.cutoff_hour and p.min_stop_pct <= dist_pct <= p.max_stop_pct:
                ru = fill - st
                q = min(equity * p.risk_pct / 100.0 / ru, equity * p.max_leverage / fill)
                if q > 0:
                    pos, qty, entry_px, stop, init_stop, next_stop, entry_i = True, q, fill, st, st, st, i
                    risk_unit, risk_usd, armed, be_moved, hh, fund_paid = ru, q * ru, False, False, fill, 0.0
                    fee_in = fill * q * fee_rate
                    equity -= fee_in
                    trades_today += 1
        pending = None
        if pos:
            if charge_funding and mins[i] == 0 and hours[i] in (0, 8, 16) and entry_i < i:
                f = qty * O[i] * frate[i]
                fund_paid += f
                equity -= f
                res.funding_paid += max(f, 0.0)
                res.funding_received += max(-f, 0.0)
            last_bar = i + 1 >= end_i or day[i + 1] != day[i]
            if L[i] <= stop:                                                    # (a) stop, gap-aware
                px = min(stop, O[i]) * (1 - slip)
                close_trade(i, px, "be_stop" if be_moved and abs(stop - entry_px) < 1e-12 else "stop")
            elif p.exit_mode == "fixed3" and H[i] >= entry_px + p.arm_r * risk_unit:
                close_trade(i, entry_px + p.arm_r * risk_unit, "target")
            else:
                if p.exit_mode == "trail":
                    if not armed and H[i] >= entry_px + p.arm_r * risk_unit:     # (b) arm: lock effective next bar
                        armed = True
                        next_stop = max(next_stop, entry_px + p.lock_r * risk_unit)
                    hh = max(hh, H[i])
                    if armed and not np.isnan(a_np[i]):                         # (c) trail, effective next bar
                        next_stop = max(next_stop, hh - p.trail_atr * a_np[i])
                if last_bar:                                                    # (d) midnight
                    if p.midnight == "flat":
                        close_trade(i, C[i] * (1 - slip), "flat")
                    elif C[i] > entry_px and next_stop < entry_px:
                        next_stop, be_moved = entry_px, True
                if pos:
                    stop = next_stop
        curve[i] = equity + ((C[i] - entry_px) * qty if pos else 0.0)
        if i in signals and i + 1 < end_i:
            if pos:
                res.skipped_busy += 1
            elif i > cool and trades_today < p.max_trades_day and hours[i + 1] < p.cutoff_hour:
                pending = signals[i]
    if pos:
        close_trade(end_i - 1, C[end_i - 1] * (1 - slip), "end")
    res.equity = pd.Series(curve[start_i:end_i], index=ts.iloc[start_i:end_i])
    res.buy_hold_pct = (C[end_i - 1] / C[start_i] - 1) * 100
    return res
