from __future__ import annotations

import os

import ccxt
import pandas as pd


def make_exchange(cfg, authed: bool = False):
    params = {"enableRateLimit": True, "options": {"defaultType": "swap"}}
    if authed:
        params["apiKey"] = os.environ["BYBIT_API_KEY"]
        params["secret"] = os.environ["BYBIT_API_SECRET"]
    ex = ccxt.bybit(params)
    if cfg.exchange.testnet:
        ex.set_sandbox_mode(True)
    return ex


def make_public_exchange():
    """Bybit MAINNET, public data only: no keys, never testnet (testnet history is unreliable).
    Used for read-only market views such as the trend dashboard, independent of the trading agent's settings."""
    return ccxt.bybit({"enableRateLimit": True, "options": {"defaultType": "swap"}})


def fetch_ohlcv_df(ex, symbol: str, timeframe: str, limit: int = 200) -> pd.DataFrame:
    raw = ex.fetch_ohlcv(symbol, timeframe, limit=limit)
    df = pd.DataFrame(raw, columns=["ts", "open", "high", "low", "close", "volume"])
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    return df


def fetch_universe(ex, min_quote_volume: float, exclude: list[str], max_universe: int) -> list[str]:
    ex.load_markets()
    swaps = [m["symbol"] for m in ex.markets.values()
             if m.get("swap") and m.get("linear") and m.get("quote") == "USDT"
             and m.get("active") and m["symbol"] not in exclude]
    tickers = ex.fetch_tickers(swaps)
    liquid = [(s, t.get("quoteVolume") or 0) for s, t in tickers.items() if s in swaps]
    liquid = [x for x in liquid if x[1] >= min_quote_volume]
    liquid.sort(key=lambda x: -x[1])
    return [s for s, _ in liquid[:max_universe]]


def fetch_ohlcv_history(ex, symbol: str, timeframe: str, days: int) -> pd.DataFrame:
    """Paginated history (Bybit returns up to 1000 candles per call, ascending from `since`)."""
    import time as _t

    step = ex.parse_timeframe(timeframe) * 1000
    since = int(_t.time() * 1000) - days * 86_400_000
    rows: list = []
    while True:
        batch = ex.fetch_ohlcv(symbol, timeframe, since=since, limit=1000)
        if not batch:
            break
        rows.extend(batch)
        nxt = batch[-1][0] + step
        if nxt <= since or len(batch) < 2:
            break
        since = nxt
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
    df = df.drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    return df
