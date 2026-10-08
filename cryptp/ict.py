"""ICT + SMC + VWAP model (docs/ICT_SMC_VWAP_PREREG.md, frozen pre-registration).

Liquidity sweep of a confirmed swing -> market-structure shift -> fair-value-gap retrace (limit at the gap midpoint), inside a session
window, on the discount (long) / premium (short) side of the daily-anchored VWAP, with the 4h structure not against the trade. Short is the
exact mirror. Exit: no profit-taking before +3R, then lock +1.5R and trail 3 x ATR, midnight break-even; every stop change takes effect on the
NEXT bar. Signals use data up to the bar that completes them; the order fills later.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .backtest import Result, Trade, htf_trend_series
from .bounce import funding_rates
from .indicators import atr


@dataclass
class IctParams:
    swing: int = 3
    sweep_shift_bars: int = 6            # shift must come within this many bars after the sweep
    shift_lookback: int = 5              # shift = close beyond the extreme of the 5 bars before the sweep
    fill_bars: int = 12                  # limit order lives this many bars after the shift
    stop_atr: float = 0.1
    min_stop_pct: float = 0.45
    max_stop_pct: float = 3.0
    arm_r: float = 3.0
    lock_r: float = 1.5
    trail_atr: float = 3.0
    vwap_min_bars: int = 8
    risk_pct: float = 1.0
    max_leverage: float = 3.0
    cooldown_bars: int = 8
    max_trades_day: int = 3
    default_funding: float = 0.0001
    # toggles (frozen = all on, both sides); the ablations flip one at a time
    use_killzone: bool = True
    use_vwap: bool = True
    use_bias: bool = True
    use_fvg: bool = True
    sides: str = "both"                  # both | long | short
    htf: str = "4h"
    # SMC order-block model (docs/SMC_VWAP_PREREG.md): model="smc"
    model: str = "ict"                   # ict | smc
    impulse_atr: float = 1.2             # BOS bar true range >= this x ATR(14) ...
    impulse_close_frac: float = 0.25     # ... and it closes in the top (bottom for shorts) 25% of its range
    use_impulse: bool = True
    ob_lookback: int = 10
    ob_fill_bars: int = 16
    ob_entry: str = "mid"                # mid | edge


KZ = ((7, 10), (12, 15))


@dataclass
class Setup:
    d: int                # +1 long, -1 short
    m: int                # bar that completes the shift (order live from m+1)
    ce: float             # limit price (gap midpoint); +/-inf means "next open"
    stop_raw: float       # extreme of the sweep..shift bars +/- 0.1 ATR(m)
    end: int              # last bar the order may fill (expiry or void)


@dataclass
class Prep:
    setups: dict = field(default_factory=dict)          # m -> [Setup]
    vwap_prev: np.ndarray | None = None
    day_pos: np.ndarray | None = None
    bias: np.ndarray | None = None                      # +1 up, -1 down, 0 range, per bar open
    atr: np.ndarray | None = None
    counts: dict = field(default_factory=dict)


def vwap_arrays(df: pd.DataFrame):
    """VWAP anchored at 00:00 UTC through the PREVIOUS bar, and the number of bars since the anchor."""
    day = df["ts"].dt.strftime("%Y-%m-%d")
    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    pv = (tp * df["volume"]).groupby(day).cumsum()
    vv = df["volume"].groupby(day).cumsum()
    cum = (pv / vv.replace(0, np.nan)).to_numpy()
    same = (day == day.shift()).to_numpy()
    prev = np.r_[np.nan, cum[:-1]]
    prev[~same] = np.nan
    pos = df.groupby(day).cumcount().to_numpy()
    return prev, pos


def _last_confirmed(df: pd.DataFrame, p: IctParams):
    """Most recent CONFIRMED swing low/high (price and bar) as seen at each bar s: swing bar b <= s - (swing+1)."""
    h, l = df["high"].to_numpy(float), df["low"].to_numpy(float)
    n, k = len(df), p.swing
    is_h, is_l = np.zeros(n, bool), np.zeros(n, bool)
    for i in range(k, n - k):
        if h[i] == h[i - k: i + k + 1].max() and h[i] > h[i - 1]:
            is_h[i] = True
        if l[i] == l[i - k: i + k + 1].min() and l[i] < l[i - 1]:
            is_l[i] = True
    idx = np.arange(n)

    def ffill(mask, vals):
        pos = np.where(mask, idx, -1)
        pos = np.maximum.accumulate(pos)
        price = np.where(pos >= 0, vals[np.clip(pos, 0, None)], np.nan)
        return price, pos

    lp, lb = ffill(is_l, l)
    hp, hb = ffill(is_h, h)
    sh = k + 1                                            # a swing is usable `swing + 1` bars after it forms
    shift = lambda a, fill: np.r_[np.full(sh, fill), a[:-sh]]
    return shift(lp, np.nan), shift(lb, -1), shift(hp, np.nan), shift(hb, -1)


def detect_setups(df: pd.DataFrame, p: IctParams, a: np.ndarray) -> tuple[dict, dict]:
    """Causal scan for sweep -> shift -> FVG setups of both sides. {m: [Setup]} plus step counts."""
    o, h, l, c = (df[x].to_numpy(float) for x in ("open", "high", "low", "close"))
    n = len(df)
    Lp, Lb, Hp, Hb = _last_confirmed(df, p)
    out: dict[int, list[Setup]] = {}
    cnt = dict(sweeps_long=0, sweeps_short=0, shifts_long=0, shifts_short=0, setups_long=0, setups_short=0)
    used_l, used_h = set(), set()
    back = p.shift_lookback
    for s in range(max(back, 2 * p.swing + 2), n - 1):
        for d in (1, -1):
            if p.sides == "long" and d < 0 or p.sides == "short" and d > 0:
                continue
            if d > 0:
                lvl, lb = Lp[s], int(Lb[s])
                if lb < 0 or np.isnan(lvl) or lb in used_l or not (l[s] < lvl and c[s] > lvl):
                    continue
                used_l.add(lb)
                cnt["sweeps_long"] += 1
                thresh = h[s - back: s].max()
            else:
                lvl, lb = Hp[s], int(Hb[s])
                if lb < 0 or np.isnan(lvl) or lb in used_h or not (h[s] > lvl and c[s] < lvl):
                    continue
                used_h.add(lb)
                cnt["sweeps_short"] += 1
                thresh = l[s - back: s].min()
            m = None
            for t in range(s + 1, min(s + p.sweep_shift_bars, n - 1) + 1):
                if d * (c[t] - lvl) < 0:                                      # closed back through the swept level: void
                    break
                if d * (c[t] - thresh) > 0:
                    m = t
                    break
            if m is None:
                continue
            cnt["shifts_long" if d > 0 else "shifts_short"] += 1
            ce = None
            if p.use_fvg:
                for k in range(m, s + 1, -1):
                    if d > 0 and l[k] > h[k - 2]:
                        ce = (h[k - 2] + l[k]) / 2.0
                        break
                    if d < 0 and h[k] < l[k - 2]:
                        ce = (l[k - 2] + h[k]) / 2.0
                        break
                if ce is None:
                    continue
                end = m + p.fill_bars
            else:
                ce, end = (np.inf if d > 0 else -np.inf), m + 1
            if np.isnan(a[m]):
                continue
            stop = (l[s: m + 1].min() - p.stop_atr * a[m]) if d > 0 else (h[s: m + 1].max() + p.stop_atr * a[m])
            for t in range(m + 1, min(end, n - 1) + 1):                       # void: any close beyond the swept level
                if d * (c[t] - lvl) < 0:
                    end = t
                    break
            end = min(end, n - 1)
            out.setdefault(m, []).append(Setup(d, m, ce, float(stop), end))
            cnt["setups_long" if d > 0 else "setups_short"] += 1
    return out, cnt


def detect_setups_smc(df: pd.DataFrame, p: IctParams, a: np.ndarray) -> tuple[dict, dict]:
    """Causal scan: break of the last confirmed swing (first break only) by an impulse bar -> order block (last opposite candle) retest."""
    o, h, l, c = (df[x].to_numpy(float) for x in ("open", "high", "low", "close"))
    n = len(df)
    Lp, Lb, Hp, Hb = _last_confirmed(df, p)
    pc = np.r_[np.nan, c[:-1]]
    tr = np.maximum.reduce([h - l, np.abs(h - pc), np.abs(l - pc)])
    out: dict[int, list[Setup]] = {}
    cnt = dict(bos_long=0, bos_short=0, impulse_long=0, impulse_short=0, setups_long=0, setups_short=0)
    used_up, used_dn = set(), set()
    for b in range(max(p.ob_lookback, 2 * p.swing + 2), n - 1):
        for d in (1, -1):
            if p.sides == "long" and d < 0 or p.sides == "short" and d > 0:
                continue
            if d > 0:
                lvl, sb = Hp[b], int(Hb[b])
                if sb < 0 or np.isnan(lvl) or sb in used_up or not c[b] > lvl:
                    continue
                used_up.add(sb)
            else:
                lvl, sb = Lp[b], int(Lb[b])
                if sb < 0 or np.isnan(lvl) or sb in used_dn or not c[b] < lvl:
                    continue
                used_dn.add(sb)
            cnt["bos_long" if d > 0 else "bos_short"] += 1
            if np.isnan(a[b]):
                continue
            if p.use_impulse:
                rng = h[b] - l[b]
                top = (c[b] - l[b]) >= (1 - p.impulse_close_frac) * rng if d > 0 else (h[b] - c[b]) >= (1 - p.impulse_close_frac) * rng
                if not (tr[b] >= p.impulse_atr * a[b] and top and rng > 0):
                    continue
            cnt["impulse_long" if d > 0 else "impulse_short"] += 1
            ob = None
            for j in range(b - 1, b - p.ob_lookback - 1, -1):
                if (c[j] < o[j]) if d > 0 else (c[j] > o[j]):
                    ob = j
                    break
            if ob is None:
                continue
            lo, hi = l[ob], h[ob]
            ce = (lo + hi) / 2.0 if p.ob_entry == "mid" else (hi if d > 0 else lo)
            stop = (lo - p.stop_atr * a[b]) if d > 0 else (hi + p.stop_atr * a[b])
            end = b + p.ob_fill_bars
            for t in range(b + 1, min(end, n - 1) + 1):                         # void: a close through the far edge of the block
                if (c[t] < lo) if d > 0 else (c[t] > hi):
                    end = t
                    break
            out.setdefault(b, []).append(Setup(d, b, float(ce), float(stop), min(end, n - 1)))
            cnt["setups_long" if d > 0 else "setups_short"] += 1
    return out, cnt


def prepare(df: pd.DataFrame, p: IctParams | None = None) -> Prep:
    p = p or IctParams()
    df = df.reset_index(drop=True)
    a = atr(df).to_numpy(float)
    setups, cnt = (detect_setups_smc if p.model == "smc" else detect_setups)(df, p, a)
    prev, pos = vwap_arrays(df)
    trends, htf_done = htf_trend_series(df, p.htf, p.swing, p.swing)
    code = np.array([{"up": 1, "down": -1}.get(t, 0) for t in trends])
    idx = np.searchsorted(htf_done, df["ts"].to_numpy(), side="right") - 1        # last COMPLETED 4h candle as of the bar's open
    bias = np.where(idx >= 0, code[np.clip(idx, 0, None)], 0)
    return Prep(setups, prev, pos, bias, a, cnt)


def in_killzone(hour: int) -> bool:
    return any(a <= hour < b for a, b in KZ)


def run_ict(df: pd.DataFrame, symbol: str, p: IctParams | None = None, fee_rate: float = 0.00055, slippage_bps: float = 2.0,
            equity0: float = 1000.0, funding: pd.DataFrame | None = None, charge_funding: bool = True,
            prep: Prep | None = None, fee_entry: float | None = None, setups: dict | None = None,
            skip_filters: bool = False, start_i: int = 0, end_i: int | None = None) -> Result:
    p = p or IctParams()
    df = df.reset_index(drop=True)
    n = len(df)
    end_i = n if end_i is None else end_i
    prep = prep or prepare(df, p)
    sdict = prep.setups if setups is None else setups
    fee_in_rate = fee_rate if fee_entry is None else fee_entry
    slip = slippage_bps / 10_000
    O, H, L, C = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    A, vw, dpos, bias = prep.atr, prep.vwap_prev, prep.day_pos, prep.bias
    ts = df["ts"]
    day = ts.dt.strftime("%Y-%m-%d").to_numpy()
    hours, mins = ts.dt.hour.to_numpy(), ts.dt.minute.to_numpy()
    frate = funding_rates(df, funding, p.default_funding)

    equity = equity0
    pos, d = False, 0
    qty = entry_px = stop = next_stop = risk_unit = risk_usd = fee_in = fund_paid = hh = init_stop = 0.0
    armed = be_moved = False
    entry_i = 0
    cool = -1
    act: list[Setup] = []
    trades_today, cur_day = 0, None
    res = Result(symbol, equity0, bars=end_i - start_i)
    res.funding_paid = res.funding_received = 0.0
    res.armed_trades = res.be_moved_trades = res.be_stopped = 0
    res.trade_notes = []
    res.filtered = dict(killzone=0, vwap=0, bias=0, stop_size=0, busy_or_limit=0, filled=0)
    curve = np.full(n, np.nan)

    def close_trade(i: int, px: float, reason: str):
        nonlocal equity, pos, qty, cool
        gross = (px - entry_px) * qty * d
        fee_out = px * qty * fee_rate
        equity += gross - fee_out
        pnl = -fee_in + gross - fee_out - fund_paid
        res.trades.append(Trade(symbol, ts.iloc[entry_i], ts.iloc[i], entry_px, init_stop, pnl, risk_usd, i - entry_i,
                                "buy" if d > 0 else "sell"))
        res.armed_trades += int(armed)
        res.be_moved_trades += int(be_moved)
        res.be_stopped += int(reason == "be_stop")
        res.trade_notes.append(reason)
        pos, qty, cool = False, 0.0, i + p.cooldown_bars

    for i in range(start_i, end_i):
        if day[i] != cur_day:
            cur_day, trades_today = day[i], 0
        # 1. orders: setups completed at bar i-1 go live now; expired ones drop out
        for s in sdict.get(i - 1, ()):
            act.append(s)
        act = [s for s in act if s.end >= i]
        if not pos and act and i > cool and trades_today < p.max_trades_day:
            for s in list(act):
                touched = (L[i] <= s.ce) if s.d > 0 else (H[i] >= s.ce)
                if not touched:
                    continue
                act.remove(s)                                                    # consumed whether or not it passes the filters
                fill_px = min(O[i], s.ce) if s.d > 0 else max(O[i], s.ce)
                ref = s.ce if np.isfinite(s.ce) else fill_px
                if not skip_filters:
                    if p.use_killzone and not in_killzone(hours[i]):
                        res.filtered["killzone"] += 1
                        continue
                    if p.use_vwap and not (dpos[i] >= p.vwap_min_bars and not np.isnan(vw[i])
                                           and (ref <= vw[i] if s.d > 0 else ref >= vw[i])):
                        res.filtered["vwap"] += 1
                        continue
                    if p.use_bias and bias[i] == -s.d:
                        res.filtered["bias"] += 1
                        continue
                fill = fill_px * (1 + s.d * slip)
                ru = s.d * (fill - s.stop_raw)
                dist_pct = ru / fill * 100.0
                if ru <= 0 or not (p.min_stop_pct <= dist_pct <= p.max_stop_pct):
                    res.filtered["stop_size"] += 1
                    continue
                q = min(equity * p.risk_pct / 100.0 / ru, equity * p.max_leverage / fill)
                if q <= 0:
                    continue
                pos, d, qty, entry_px, stop, init_stop, next_stop, entry_i = True, s.d, q, fill, s.stop_raw, s.stop_raw, s.stop_raw, i
                risk_unit, risk_usd, armed, be_moved, hh, fund_paid = ru, q * ru, False, False, fill, 0.0
                fee_in = fill * q * fee_in_rate
                equity -= fee_in
                trades_today += 1
                res.filtered["filled"] += 1
                act.clear()
                break
        # 2. manage the position through this bar (the entry bar included: stop first, conservative)
        if pos:
            if charge_funding and mins[i] == 0 and hours[i] in (0, 8, 16) and entry_i < i:
                f = d * qty * O[i] * frate[i]
                fund_paid += f
                equity -= f
                res.funding_paid += max(f, 0.0)
                res.funding_received += max(-f, 0.0)
            last_bar = i + 1 >= end_i or day[i + 1] != day[i]
            hit = (L[i] <= stop) if d > 0 else (H[i] >= stop)
            if hit:
                px = (min(stop, O[i]) if d > 0 else max(stop, O[i])) * (1 - d * slip)
                close_trade(i, px, "be_stop" if be_moved and abs(stop - entry_px) < 1e-12 else "stop")
            else:
                if not armed and d * (((H[i] if d > 0 else L[i])) - entry_px) >= p.arm_r * risk_unit:
                    armed = True
                    lock = entry_px + d * p.lock_r * risk_unit
                    next_stop = max(next_stop, lock) if d > 0 else min(next_stop, lock)
                hh = max(hh, H[i]) if d > 0 else min(hh, L[i])
                if armed and not np.isnan(A[i]):
                    tr = hh - d * p.trail_atr * A[i]
                    next_stop = max(next_stop, tr) if d > 0 else min(next_stop, tr)
                if last_bar and d * (C[i] - entry_px) > 0 and d * (entry_px - next_stop) > 0:
                    next_stop, be_moved = entry_px, True
                stop = next_stop
        curve[i] = equity + ((C[i] - entry_px) * qty * d if pos else 0.0)
    if pos:
        close_trade(end_i - 1, C[end_i - 1] * (1 - d * slip), "end")
    res.equity = pd.Series(curve[start_i:end_i], index=ts.iloc[start_i:end_i])
    res.buy_hold_pct = (C[end_i - 1] / C[start_i] - 1) * 100
    return res
