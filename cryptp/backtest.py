"""Bar-by-bar backtester for crypTP's own structure strategy.

It reuses the live analyzer, planner, risk gate and paper executor. It does NOT replay the
TradingView Wyckoff/SMC indicator signals (Pine can't run here); it tests the structure rules.

No lookahead: a signal is computed from candles up to and including bar i, and filled at the
OPEN of bar i+1. Higher-timeframe trend uses only fully closed higher-timeframe candles.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .executor import PaperExecutor
from .indicators import atr
from .planner import build_plan
from .risk import RiskGate, position_size
from .structure import analyze

WINDOW = 300          # candles of context, same as the live agent
HTF_WINDOW = 200


@dataclass
class Trade:
    symbol: str
    entry_ts: pd.Timestamp
    exit_ts: pd.Timestamp
    entry: float
    stop: float
    pnl: float            # net of fees and slippage
    risk_usd: float
    bars: int

    @property
    def r(self) -> float:
        return self.pnl / self.risk_usd if self.risk_usd else 0.0


@dataclass
class Result:
    symbol: str
    equity0: float
    trades: list[Trade] = field(default_factory=list)
    equity: pd.Series | None = None       # mark-to-market, indexed by bar timestamp
    buy_hold_pct: float = 0.0
    bars: int = 0


def tf_to_pandas(tf: str) -> str:
    n, unit = int(tf[:-1]), tf[-1]
    return f"{n}{ {'m': 'min', 'h': 'h', 'd': 'D', 'w': 'W'}[unit] }"


def htf_trend_series(df: pd.DataFrame, htf: str, left: int, right: int):
    """Trend of each higher-timeframe candle plus the time at which that candle is complete."""
    hdf = (df.set_index("ts").resample(tf_to_pandas(htf))
           .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
           .dropna().reset_index())
    delta = pd.to_timedelta(tf_to_pandas(htf))
    trends = []
    for k in range(len(hdf)):
        w = hdf.iloc[max(0, k - HTF_WINDOW + 1): k + 1].reset_index(drop=True)
        trends.append(analyze(w, left, right).trend if len(w) >= 2 * (left + right) + 2 else "range")
    return np.array(trends), (hdf["ts"] + delta).to_numpy()


def run_backtest(df: pd.DataFrame, symbol: str, cfg, fee_rate: float = 0.00055,
                 slippage_bps: float = 2.0, cooldown_bars: int = 8, warmup: int = WINDOW) -> Result:
    df = df.reset_index(drop=True)
    n = len(df)
    s, pcfg = cfg.structure, cfg.plan
    entry_delta = df["ts"].diff().median()
    trends, htf_done = htf_trend_series(df, s.htf, s.swing_left, s.swing_right)
    close_times = (df["ts"] + entry_delta).to_numpy()
    htf_idx = np.searchsorted(htf_done, close_times, side="right") - 1      # last COMPLETED htf bar

    slip = slippage_bps / 10_000
    ex = PaperExecutor(cfg.risk.paper_equity, fee_rate=fee_rate, slippage=slip)
    gate = RiskGate(cfg.risk, kill_file="/nonexistent/KILL")
    res = Result(symbol, cfg.risk.paper_equity, bars=n)
    curve = np.full(n, np.nan)

    pending = None            # plan decided at close of bar i-1, to be filled at open of bar i
    prev_valid = False
    cooldown_until = -1
    open_meta = None          # (entry_bar, risk_usd)
    day = None

    for i in range(n):
        row = df.iloc[i]
        d = row["ts"].strftime("%Y-%m-%d")
        if d != day:
            gate.daily_pnl, day = 0.0, d

        # 1. fill the order decided on the previous close, at this bar's open
        if pending is not None and symbol not in ex.positions:
            fill = float(row["open"]) * (1 + slip)
            risk = fill - pending.stop
            if risk > 0 and fill < pending.targets[0]:
                plan = dataclasses.replace(pending, entry=fill, risk_per_unit=risk)
                ok, _ = gate.check(plan, ex.equity)
                qty = position_size(ex.equity, plan, cfg.risk.risk_per_trade_pct, cfg.risk.max_leverage)
                if ok and qty > 0:
                    ex.submit(plan, qty)
                    open_meta = (i, qty * risk)
        pending = None

        # 2. advance the open position through this bar
        if symbol in ex.positions:
            pos = ex.positions[symbol]
            gate.daily_pnl += ex.on_candle(symbol, float(row["high"]), float(row["low"]), float(row["open"]))
            if symbol not in ex.positions:                     # closed on this bar
                res.trades.append(Trade(symbol, df["ts"].iloc[open_meta[0]], row["ts"], pos.plan.entry,
                                        pos.plan.stop, ex.closed_pnl[-1], open_meta[1], i - open_meta[0]))
                cooldown_until = i + cooldown_bars
                open_meta = None

        mtm = ex.equity
        if symbol in ex.positions:
            p = ex.positions[symbol]
            mtm += p.remaining * (float(row["close"]) - p.plan.entry)
        curve[i] = mtm

        # 3. look for a new setup at this bar's close (edge-triggered: plan newly valid)
        if i < warmup or i >= n - 1:
            continue
        w = df.iloc[i - WINDOW + 1: i + 1].reset_index(drop=True) if i >= WINDOW else df.iloc[: i + 1]
        ms = analyze(w, s.swing_left, s.swing_right)
        a = float(atr(w).iloc[-1])
        htf_trend = trends[htf_idx[i]] if htf_idx[i] >= 0 else "range"
        plan = build_plan(symbol, float(row["close"]), a, ms, htf_trend, pcfg)
        valid = plan is not None
        if valid and not prev_valid and symbol not in ex.positions and i > cooldown_until:
            pending = plan
        prev_valid = valid

    res.equity = pd.Series(curve, index=df["ts"])
    res.buy_hold_pct = (df["close"].iloc[-1] / df["close"].iloc[warmup] - 1) * 100 if n > warmup else 0.0
    return res


def summarize(trades: list[Trade], equity0: float, equity: pd.Series | None = None) -> dict:
    n = len(trades)
    wins = [t for t in trades if t.pnl > 0]
    gross_win = sum(t.pnl for t in wins)
    gross_loss = -sum(t.pnl for t in trades if t.pnl <= 0)
    out = {
        "trades": n,
        "win_rate_pct": 100 * len(wins) / n if n else 0.0,
        "avg_r": float(np.mean([t.r for t in trades])) if n else 0.0,
        "profit_factor": gross_win / gross_loss if gross_loss > 0 else (float("inf") if gross_win > 0 else 0.0),
        "net_pnl": sum(t.pnl for t in trades),
        "return_pct": 100 * sum(t.pnl for t in trades) / equity0,
        "avg_bars": float(np.mean([t.bars for t in trades])) if n else 0.0,
    }
    if equity is not None and len(equity):
        peak = equity.cummax()
        out["max_drawdown_pct"] = float(((equity - peak) / peak).min() * 100)
    return out


def split_trades(trades: list[Trade], frac: float, df: pd.DataFrame):
    """In-sample / out-of-sample by time. Parameters are fixed, so this checks stability, not fit."""
    cut = df["ts"].iloc[int(len(df) * frac)]
    return [t for t in trades if t.entry_ts < cut], [t for t in trades if t.entry_ts >= cut], cut


def format_summary(name: str, m: dict) -> str:
    pf = "inf" if m["profit_factor"] == float("inf") else f"{m['profit_factor']:.2f}"
    dd = f"  maxDD {m['max_drawdown_pct']:.1f}%" if "max_drawdown_pct" in m else ""
    return (f"{name:<14} trades {m['trades']:>3}  win {m['win_rate_pct']:>5.1f}%  avgR {m['avg_r']:>+5.2f}  "
            f"PF {pf:>5}  net {m['return_pct']:>+6.1f}%{dd}")


def synthetic_ohlcv(n: int = 4000, seed: int = 1, tf_min: int = 15) -> pd.DataFrame:
    """Regime-switching random walk. For tests and dry runs ONLY: results mean nothing."""
    rng = np.random.default_rng(seed)
    drift = np.repeat(rng.choice([0.0004, -0.0003, 0.0], size=n // 200 + 1), 200)[:n]
    close = 100 * np.exp(np.cumsum(drift + rng.normal(0, 0.004, n)))
    open_ = np.r_[100.0, close[:-1]]
    wick = np.abs(rng.normal(0, 0.002, (2, n))) * close
    return pd.DataFrame({
        "ts": pd.date_range("2025-01-01", periods=n, freq=f"{tf_min}min", tz="UTC"),
        "open": open_, "high": np.maximum(open_, close) + wick[0],
        "low": np.minimum(open_, close) - wick[1], "close": close,
        "volume": rng.uniform(1, 2, n)})


def load_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    ts = df["ts"]
    df["ts"] = pd.to_datetime(ts, unit="ms", utc=True) if pd.api.types.is_numeric_dtype(ts) \
        else pd.to_datetime(ts, utc=True)
    return df[["ts", "open", "high", "low", "close", "volume"]].sort_values("ts").reset_index(drop=True)
