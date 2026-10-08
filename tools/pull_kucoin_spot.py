"""Pull KuCoin SPOT candles (public REST, 1500 rows/call) as a price-history source for coins OKX lists late.
usage: python tools/pull_kucoin_spot.py SEI-USDT 15min out.csv   (types: 15min, 1hour, 1day)"""
import sys, time
import pandas as pd
import requests

sym, typ, out = sys.argv[1:4]
step = {"15min": 900, "1hour": 3600, "1day": 86400}[typ]
end, rows, empty = int(time.time()), [], 0
while True:
    start = end - step * 1500
    for attempt in range(6):
        try:
            j = requests.get("https://api.kucoin.com/api/v1/market/candles",
                             params={"symbol": sym, "type": typ, "startAt": start, "endAt": end}, timeout=20).json()
            if j.get("code") == "200000":
                break
        except Exception:
            pass
        time.sleep(1 + attempt)
    else:
        sys.exit(f"giving up {sym}")
    d = j["data"]
    if not d:
        empty += 1
        if empty >= 3:                                  # three empty windows in a row: before listing
            break
    else:
        empty = 0
        rows += d
    end = start
    time.sleep(0.25)
df = pd.DataFrame(rows, columns=["ts", "open", "close", "high", "low", "volume", "turnover"]).astype(float)
df = df.drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
df["ts"] = pd.to_datetime(df["ts"], unit="s", utc=True)
df[["ts", "open", "high", "low", "close", "volume"]].to_csv(out, index=False)
gaps = int((df["ts"].diff().dropna() > pd.Timedelta(seconds=step * 3)).sum())
print(sym, typ, len(df), df["ts"].iloc[0], "->", df["ts"].iloc[-1], "gaps>3 bars:", gaps)
