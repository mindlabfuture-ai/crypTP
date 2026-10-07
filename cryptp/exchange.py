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
