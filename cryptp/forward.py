"""Forward test of publicly posted trade setups (docs/MB_FORWARD_PREREG.md).

A setup is scored the way a follower could actually have traded it: a market order at the OPEN of the first 15m bar that starts
after the moment the setup was logged, the poster's own stop and target, stop-first if a bar reaches both, a time stop at the
horizon, project-standard costs. Leverage is not replicated: R is measured against the stop distance, 1R = fill-to-stop.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class Setup:
    id: str
    symbol: str                        # OKX instrument, e.g. DOGE-USDT-SWAP
    side: str                          # "long" or "short"
    logged_at: pd.Timestamp            # UTC; when the setup was seen/logged (never earlier than the post itself)
    stop: float
    target: float
    his_entry: float | None = None
    horizon_hours: float = 48.0


VALID = ("stop", "target", "expired")


def planned_rr(s: Setup) -> float | None:
    """The poster's own reward:risk from his drawn entry, or None if no entry was recorded."""
    if s.his_entry is None:
        return None
    d = 1 if s.side == "long" else -1
    risk, reward = d * (s.his_entry - s.stop), d * (s.target - s.his_entry)
    return reward / risk if risk > 0 else None


def score_setup(df: pd.DataFrame, s: Setup, fee_rate: float = 0.00055, slippage_bps: float = 2.0,
                min_rr: float = 1.0) -> dict:
    """df: CLOSED 15m bars with ts (bar open, UTC), open, high, low, close. Returns a result row.
    status: pending (no closed bar yet) | missed | stop | target | expired | open (still running inside its horizon)."""
    d = 1 if s.side == "long" else -1
    slip = slippage_bps / 10_000
    out = dict(id=s.id, symbol=s.symbol, side=s.side, status="pending", fill_ts=None, fill=None, exit_ts=None, exit=None,
               r_net=None, bars=None, planned_rr=planned_rr(s), note="")
    bars = df[df["ts"] > s.logged_at].reset_index(drop=True)
    if bars.empty:
        return out
    O, H, L, C = (bars[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    fill = O[0] * (1 + d * slip)
    risk, reward = d * (fill - s.stop), d * (s.target - fill)
    out.update(fill_ts=bars["ts"].iloc[0], fill=float(fill))
    if risk <= 0 or reward <= 0:
        out.update(status="missed", note="price already beyond the stop or the target at the first fill")
        return out
    if reward < min_rr * risk:
        out.update(status="missed", note=f"remaining reward:risk {reward / risk:.2f} below {min_rr:g} at the first fill")
        return out
    qty = 1.0 / risk                                           # 1R = 1 unit of risk
    horizon = max(1, int(round(s.horizon_hours * 4)))
    for i in range(len(bars)):
        hit_stop = L[i] <= s.stop if d > 0 else H[i] >= s.stop
        hit_tp = H[i] >= s.target if d > 0 else L[i] <= s.target
        px, status = None, None
        if hit_stop:
            px, status = (min(s.stop, O[i]) if d > 0 else max(s.stop, O[i])) * (1 - d * slip), "stop"
        elif hit_tp:
            px, status = s.target, "target"
        elif i + 1 >= horizon:
            px, status = C[i] * (1 - d * slip), "expired"
        if px is not None:
            pnl = (px - fill) * qty * d - (fill + px) * qty * fee_rate
            out.update(status=status, exit_ts=bars["ts"].iloc[i], exit=float(px), r_net=float(pnl), bars=i)
            return out
    mark = C[-1]
    pnl = (mark - fill) * qty * d - (fill + mark) * qty * fee_rate
    out.update(status="open", exit_ts=bars["ts"].iloc[-1], exit=float(mark), r_net=float(pnl), bars=len(bars) - 1,
               note="unrealized, marked at the last closed bar")
    return out


def summarize(rows: list[dict], n_boot: int = 10_000, seed: int = 1) -> dict:
    """Realized results only (open and missed are counted, not averaged)."""
    valid = [r["r_net"] for r in rows if r["status"] in VALID]
    n_all = sum(1 for r in rows if r["status"] != "pending")
    out = dict(scored=n_all, valid=len(valid), missed=sum(r["status"] == "missed" for r in rows),
               open=sum(r["status"] == "open" for r in rows), pending=sum(r["status"] == "pending" for r in rows))
    out["missed_rate"] = out["missed"] / n_all if n_all else None
    if valid:
        a = np.asarray(valid, float)
        rng = np.random.default_rng(seed)
        means = rng.choice(a, size=(n_boot, len(a)), replace=True).mean(axis=1) if len(a) > 1 else a
        out.update(mean_r=float(a.mean()), win_pct=float((a > 0).mean() * 100),
                   ci90_low=float(np.percentile(means, 5)), ci90_high=float(np.percentile(means, 95)))
    return out
