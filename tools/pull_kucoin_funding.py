import requests, time, sys, pandas as pd
sym, out = sys.argv[1], sys.argv[2]
rows, t0, now = [], int(pd.Timestamp("2019-06-01", tz="UTC").timestamp() * 1000), int(time.time() * 1000)
step = 20 * 86400 * 1000
cur, empty_streak, first = t0, 0, None
while cur < now:
    j = None
    for attempt in range(5):
        try:
            j = requests.get("https://api-futures.kucoin.com/api/v1/contract/funding-rates",
                             params={"symbol": sym, "from": cur, "to": min(cur + step, now)}, timeout=20).json()
            if j.get("code") == "200000": break
        except Exception: pass
        time.sleep(1 + attempt)
    d = (j or {}).get("data") or []
    rows += d
    cur += step
    time.sleep(0.15)
df = pd.DataFrame(rows)
if len(df):
    df = df.drop_duplicates("timepoint").sort_values("timepoint")
    df["ts"] = pd.to_datetime(df["timepoint"], unit="ms", utc=True)
    df[["ts", "fundingRate"]].rename(columns={"fundingRate": "rate"}).to_csv(out, index=False)
    gaps = df["ts"].diff().dropna()
    print(sym, len(df), df["ts"].iloc[0], "->", df["ts"].iloc[-1], "| median interval", gaps.median(), "| max gap", gaps.max(), "| mean rate/8h %.5f%%" % (100 * df["fundingRate"].mean()), flush=True)
else:
    print(sym, "NO DATA", flush=True)
