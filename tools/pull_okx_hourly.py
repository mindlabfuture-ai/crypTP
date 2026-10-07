import requests, time, pandas as pd, sys
inst, days, out = sys.argv[1], int(sys.argv[2]), sys.argv[3]
stop = (time.time() - days * 86400) * 1000
rows, after, calls, empty = [], None, 0, 0
while True:
    p = {"instId": inst, "bar": "1H", "limit": 100}
    if after: p["after"] = after
    for attempt in range(6):
        try:
            j = requests.get("https://www.okx.com/api/v5/market/history-candles", params=p, timeout=20).json()
            if j.get("code") == "0": break
        except Exception:
            pass
        time.sleep(1 + attempt)
    else:
        print("giving up", inst, flush=True); break
    d = j["data"]
    calls += 1
    if not d: break
    rows += [r for r in d if r[8] == "1"]
    after = d[-1][0]
    if float(after) < stop: break
    time.sleep(0.3)
df = pd.DataFrame(rows, columns=["ts","open","high","low","close","volume","a","b","c"])[["ts","open","high","low","close","volume"]]
df = df.astype(float).drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
df = df[df["ts"] >= pd.Timestamp.now("UTC") - pd.Timedelta(days=days)].reset_index(drop=True)
df.to_csv(out, index=False)
gaps = (df["ts"].diff().dropna() > pd.Timedelta(hours=1)).sum()
print(inst, len(df), df["ts"].iloc[0], "->", df["ts"].iloc[-1], "calls", calls, "gaps", gaps, flush=True)
