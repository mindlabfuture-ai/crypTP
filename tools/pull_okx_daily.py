import requests, time, pandas as pd, sys
inst, days, out = sys.argv[1], int(sys.argv[2]), sys.argv[3]
stop = (time.time() - days * 86400) * 1000
rows, after = [], None
while True:
    p = {"instId": inst, "bar": "1Dutc", "limit": 100}
    if after: p["after"] = after
    for attempt in range(6):
        try:
            j = requests.get("https://www.okx.com/api/v5/market/history-candles", params=p, timeout=20).json()
            if j.get("code") == "0": break
        except Exception: pass
        time.sleep(1 + attempt)
    else:
        break
    d = j["data"]
    if not d: break
    rows += [r for r in d if r[8] == "1"]
    after = d[-1][0]
    if float(after) < stop: break
    time.sleep(0.3)
df = pd.DataFrame(rows, columns=["ts","open","high","low","close","volume","a","b","c"])[["ts","open","high","low","close","volume"]]
df = df.astype(float).drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
df.to_csv(out, index=False)
print(inst, len(df), df["ts"].iloc[0].date(), "->", df["ts"].iloc[-1].date(), "gaps", int((df["ts"].diff().dropna() > pd.Timedelta(days=1)).sum()), flush=True)
