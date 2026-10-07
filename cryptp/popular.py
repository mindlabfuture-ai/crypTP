"""Benchmarks: two popular TradingView strategies (ChartArt, 2015) re-implemented for comparison.

Both are always-in-the-market reversal systems: hold until the opposite signal, no stop, no target.
Signals use candles up to bar i; the fill is at the OPEN of bar i+1 (TradingView fills those
stop orders at the next open because the stop price is already behind the market).
Sized at 100% of equity, 1x. The original "max intraday loss 50%" guard is not modelled.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .indicators import rsi


def _cross_over(x: pd.Series, y) -> pd.Series:
    y_prev = y.shift() if isinstance(y, pd.Series) else y
    return (x > y) & (x.shift() <= y_prev)


def _cross_under(x: pd.Series, y) -> pd.Series:
    y_prev = y.shift() if isinstance(y, pd.Series) else y
    return (x < y) & (x.shift() >= y_prev)


def bb_rsi_signals(df: pd.DataFrame, rsi_len: int = 6, bb_len: int = 200, mult: float = 2.0):
    """Returns (long_signal, short_signal). RSI must cross 50 on the same bar price crosses the band."""
    c = df["close"].astype(float)
    basis = c.rolling(bb_len).mean()
    dev = mult * c.rolling(bb_len).std(ddof=0)
    v = rsi(c, rsi_len)
    long_ = _cross_over(v, 50) & _cross_over(c, basis - dev)
    short = _cross_under(v, 50) & _cross_under(c, basis + dev)
    return long_.fillna(False), short.fillna(False)


def macd_sma_signals(df: pd.DataFrame, fast: int = 12, slow: int = 26, sig: int = 9, very_slow: int = 200):
    c = df["close"].astype(float)
    f, s, vs = c.rolling(fast).mean(), c.rolling(slow).mean(), c.rolling(very_slow).mean()
    macd = f - s
    hist = macd - macd.rolling(sig).mean()
    long_ = _cross_over(hist, 0.0) & (macd > 0) & (f > s) & (c.shift(slow) > vs)
    short = _cross_under(hist, 0.0) & (macd < 0) & (f < s) & (c.shift(slow) < vs)
    return long_.fillna(False), short.fillna(False)


STRATEGIES = {"bb_rsi": bb_rsi_signals, "macd_sma": macd_sma_signals}


@dataclass
class Fill:
    side: str                 # "long" | "short"
    entry_ts: pd.Timestamp
    exit_ts: pd.Timestamp
    entry: float
    exit: float
    pnl: float                # net of fees and slippage
    ret_pct: float


@dataclass
class PopResult:
    name: str
    equity0: float
    trades: list[Fill] = field(default_factory=list)
    equity: pd.Series | None = None
    buy_hold_pct: float = 0.0


def run_reversal(df: pd.DataFrame, long_sig: pd.Series, short_sig: pd.Series, name: str = "",
                 long_only: bool = False, fee_rate: float = 0.00055, slippage_bps: float = 2.0,
                 equity0: float = 1000.0, warmup: int = 250) -> PopResult:
    """Target-position engine: a signal at the close of bar i sets the target; the position moves
    to the target at the open of bar i+1. long_only: a short signal means 'go flat'."""
    df = df.reset_index(drop=True)
    n, slip = len(df), slippage_bps / 10_000
    ls, ss = long_sig.reset_index(drop=True), short_sig.reset_index(drop=True)
    opens, closes = df["open"].to_numpy(float), df["close"].to_numpy(float)
    equity, pos, qty, entry_px, entry_i, entry_fee, target = equity0, 0, 0.0, 0.0, 0, 0.0, 0
    res = PopResult(name, equity0)
    curve = np.empty(n)

    for i in range(n):
        o = opens[i]
        if i >= warmup and target != pos:
            if pos != 0:                                                       # exit at the open, adverse fill
                px = o * (1 - slip) if pos > 0 else o * (1 + slip)
                fee = px * qty * fee_rate
                gross = (px - entry_px) * qty * pos
                equity += gross - fee
                pnl = gross - fee - entry_fee
                res.trades.append(Fill("long" if pos > 0 else "short", df["ts"].iloc[entry_i], df["ts"].iloc[i],
                                       entry_px, px, pnl, pnl / (entry_px * qty) * 100))
                pos, qty = 0, 0.0
            if target != 0:
                px = o * (1 + slip) if target > 0 else o * (1 - slip)
                qty = equity / px                                              # 100% of equity, 1x
                entry_fee = px * qty * fee_rate
                equity -= entry_fee
                pos, entry_px, entry_i = target, px, i
        curve[i] = equity + ((closes[i] - entry_px) * qty * pos if pos else 0.0)
        if ls.iloc[i]:
            target = 1
        elif ss.iloc[i]:
            target = 0 if long_only else -1

    if pos != 0:                                                               # mark the open trade at the last close
        px = closes[-1]
        gross = (px - entry_px) * qty * pos
        pnl = gross - px * qty * fee_rate - entry_fee
        res.trades.append(Fill("long" if pos > 0 else "short", df["ts"].iloc[entry_i], df["ts"].iloc[-1],
                               entry_px, px, pnl, pnl / (entry_px * qty) * 100))
    res.equity = pd.Series(curve, index=df["ts"])
    res.buy_hold_pct = (closes[-1] / closes[warmup] - 1) * 100 if n > warmup else 0.0
    return res


def summarize_fills(trades: list[Fill], equity0: float, equity: pd.Series | None = None) -> dict:
    n = len(trades)
    wins = [t for t in trades if t.pnl > 0]
    gl = -sum(t.pnl for t in trades if t.pnl <= 0)
    out = {"trades": n, "win_rate_pct": 100 * len(wins) / n if n else 0.0,
           "avg_trade_pct": float(np.mean([t.ret_pct for t in trades])) if n else 0.0,
           "profit_factor": sum(t.pnl for t in wins) / gl if gl > 0 else (float("inf") if wins else 0.0),
           "return_pct": 100 * sum(t.pnl for t in trades) / equity0}
    if equity is not None and len(equity):
        out["max_drawdown_pct"] = float(((equity - equity.cummax()) / equity.cummax()).min() * 100)
    return out


def format_fills(name: str, m: dict) -> str:
    pf = "inf" if m["profit_factor"] == float("inf") else f"{m['profit_factor']:.2f}"
    dd = f"  maxDD {m['max_drawdown_pct']:.1f}%" if "max_drawdown_pct" in m else ""
    return (f"{name:<14} trades {m['trades']:>3}  win {m['win_rate_pct']:>5.1f}%  avg {m['avg_trade_pct']:>+6.2f}%/trade  "
            f"PF {pf:>5}  net {m['return_pct']:>+7.1f}%{dd}")
