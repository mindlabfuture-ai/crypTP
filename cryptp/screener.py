"""Coin screener: relative strength vs BTC, volume surge, trend and breakout proximity."""
from __future__ import annotations

import pandas as pd

from .indicators import atr, ema, rsi

BTC = "BTC/USDT:USDT"


def metrics(df: pd.DataFrame, btc: pd.DataFrame, rs_bars: int) -> dict:
    c = df["close"]
    ret = c.iloc[-1] / c.iloc[-1 - rs_bars] - 1
    btc_ret = btc["close"].iloc[-1] / btc["close"].iloc[-1 - rs_bars] - 1
    vol_base = df["volume"].iloc[-50:-3].mean()
    return {
        "ret_pct": ret * 100,
        "rs_vs_btc": (ret - btc_ret) * 100,
        "vol_surge": df["volume"].iloc[-3:].mean() / vol_base if vol_base else 0.0,
        "near_high": c.iloc[-1] / df["high"].iloc[-50:].max(),
        "uptrend": bool(ema(c, 20).iloc[-1] > ema(c, 50).iloc[-1] and c.iloc[-1] > ema(c, 50).iloc[-1]),
        "rsi": float(rsi(c).iloc[-1]),
        "atr_pct": float(atr(df).iloc[-1] / c.iloc[-1] * 100),
    }


def rank(rows: list[dict]) -> pd.DataFrame:
    t = pd.DataFrame(rows)
    if t.empty:
        return t
    r = lambda col: t[col].rank(pct=True)
    t["score"] = (0.35 * r("rs_vs_btc") + 0.25 * r("vol_surge") + 0.25 * r("near_high")
                  + 0.15 * t["uptrend"].astype(float))
    t.loc[t["rsi"] > 80, "score"] *= 0.7           # overheated, chase risk
    return t.sort_values("score", ascending=False).reset_index(drop=True)


def scan(ex, cfg) -> pd.DataFrame:
    from .exchange import fetch_ohlcv_df, fetch_universe

    s = cfg.screener
    universe = fetch_universe(ex, s.min_quote_volume_usd, s.exclude, s.max_universe)
    btc = fetch_ohlcv_df(ex, BTC, s.timeframe, s.lookback_bars)
    rows = []
    for sym in universe:
        if sym == BTC:
            continue
        try:
            df = fetch_ohlcv_df(ex, sym, s.timeframe, s.lookback_bars)
            if len(df) < 60:
                continue
            rows.append({"symbol": sym, **metrics(df, btc, s.rs_bars)})
        except Exception as e:                       # one bad symbol must not kill a scan
            print(f"skip {sym}: {e}")
    return rank(rows).head(s.top_n)
