"""Perpetual funding helpers for daily backtests (see docs/FUNDING_PREREG.md)."""
from __future__ import annotations

import numpy as np
import pandas as pd


def daily_funding(df: pd.DataFrame, rates: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Per daily bar: (sum of funding rates settling in [bar open, next open), number of settlements).
    `rates` has columns ts (UTC) and rate (fraction of notional per interval)."""
    day = rates["ts"].dt.floor("D")
    total = rates.groupby(day)["rate"].sum()
    count = rates.groupby(day)["rate"].count()
    opens = df["ts"].dt.floor("D")
    return total.reindex(opens).fillna(0.0).to_numpy(), count.reindex(opens).fillna(0).to_numpy()


def perp_buy_and_hold(close: pd.Series, funding: np.ndarray) -> pd.Series:
    """Equity (start 1.0) of a 1x long held on a perpetual from the first bar: price P&L minus funding paid."""
    p = close.to_numpy(float)
    paid = np.cumsum((p / p[0]) * funding)
    return pd.Series(1.0 + (p - p[0]) / p[0] - paid, index=close.index)
