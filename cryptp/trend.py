"""Daily SMA trend-regime strategy (see docs/TREND_PREREG.md). Low turnover, so costs matter little.

Long when close > SMA(n), flat (or short) when close < SMA(n). Signal at the daily close, fill at the
next daily open, via the same target-position engine and cost model as the other backtests.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .popular import run_reversal


def sma_trend_signals(df: pd.DataFrame, n: int = 200):
    c = df["close"].astype(float)
    sma = c.rolling(n).mean()
    return (c > sma).fillna(False), (c < sma).fillna(False)


def _curve_metrics(eq: pd.Series) -> dict:
    years = max((eq.index[-1] - eq.index[0]).days / 365.25, 1e-9)
    total = eq.iloc[-1] / eq.iloc[0] - 1
    cagr = (1 + total) ** (1 / years) - 1 if total > -1 else -1.0
    dd = float((eq / eq.cummax() - 1).min())
    return dict(total_pct=100 * total, cagr_pct=100 * cagr, max_dd_pct=100 * dd,
                calmar=(cagr / abs(dd)) if dd < 0 else float("inf"),
                years={int(y): round(100 * (g.iloc[-1] / g.iloc[0] - 1), 1) for y, g in eq.groupby(eq.index.year)})


def evaluate_signals(df: pd.DataFrame, ls: pd.Series, ss: pd.Series, long_only: bool = True,
                     fee_rate: float = 0.00055, slippage_bps: float = 2.0, equity0: float = 1000.0,
                     warmup: int = 50, funding: np.ndarray | None = None) -> dict:
    """Run any (long_signal, short_signal) pair through the target-position engine and compare to buy and hold.
    Both curves start at the close BEFORE the first possible fill, so the first trade's costs are counted."""
    df = df.reset_index(drop=True)
    r = run_reversal(df, ls, ss, "", long_only, fee_rate, slippage_bps, equity0, warmup=warmup, funding=funding)
    eq = r.equity.iloc[warmup - 1:]
    bh = pd.Series(df["close"].to_numpy(float), index=df["ts"]).iloc[warmup - 1:]
    strat, hold = _curve_metrics(eq), _curve_metrics(bh)
    span = (eq.index[-1] - eq.index[0]).total_seconds()
    held = sum((t.exit_ts - t.entry_ts).total_seconds() for t in r.trades)
    wins = [t for t in r.trades if t.pnl > 0]
    return dict(long_only=long_only, start=str(eq.index[0].date()), end=str(eq.index[-1].date()),
                trades=len(r.trades), win_rate_pct=100 * len(wins) / len(r.trades) if r.trades else 0.0,
                time_in_market_pct=100 * held / span if span else 0.0, ruined=bool((r.equity <= 0).any()),
                strat=strat, hold=hold, last_close=float(df["close"].iloc[-1]))


def evaluate(df: pd.DataFrame, n: int = 200, long_only: bool = True, fee_rate: float = 0.00055,
             slippage_bps: float = 2.0, equity0: float = 1000.0) -> dict:
    df = df.reset_index(drop=True)
    ls, ss = sma_trend_signals(df, n)
    out = evaluate_signals(df, ls, ss, long_only, fee_rate, slippage_bps, equity0, warmup=n)
    out.update(n=n, last_sma=float(df["close"].rolling(n).mean().iloc[-1]))
    return out
