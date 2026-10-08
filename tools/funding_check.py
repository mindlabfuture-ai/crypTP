"""Funding-cost check for the daily SMA-200 long/flat filter (docs/FUNDING_PREREG.md).
usage: python tools/funding_check.py DATA_DIR   (needs DATA_DIR/{COIN}_1d.csv and DATA_DIR/funding_{COIN}.csv; see tools/pull_*.py)"""
import json, sys, numpy as np, pandas as pd, requests
from cryptp.backtest import load_csv
from cryptp.funding import daily_funding, perp_buy_and_hold
from cryptp.trend import sma_trend_signals, evaluate_signals, _curve_metrics

S = sys.argv[1]  # the script reads f"{S}/data/..." so pass the folder that CONTAINS data/
coins = ["BTC", "ETH", "SOL", "ADA", "SUI"]
out = {}
for c in coins:
    px = load_csv(f"{S}/data/{c}_1d.csv")
    f = pd.read_csv(f"{S}/data/funding_{c}.csv", parse_dates=["ts"])
    g = f.ts.diff(); big = f.index[g > pd.Timedelta(days=2)]
    seg_start = f.ts.iloc[big[-1]] if len(big) else f.ts.iloc[0]
    f = f[f.ts >= seg_start].reset_index(drop=True)
    first_day = seg_start.floor("D") + pd.Timedelta(days=1)
    idx = int(px["ts"].searchsorted(first_day))
    sub = px.iloc[max(idx - 200, 0):].reset_index(drop=True)
    fund, cnt = daily_funding(sub, f)
    ls, ss = sma_trend_signals(sub, 200)
    a = evaluate_signals(sub, ls, ss, long_only=True, warmup=200, funding=None)
    b = evaluate_signals(sub, ls, ss, long_only=True, warmup=200, funding=fund)
    close = pd.Series(sub["close"].to_numpy(float), index=sub["ts"])
    start = 199
    hold_spot = _curve_metrics(close.iloc[start:])
    hold_perp = _curve_metrics(perp_buy_and_hold(close.iloc[start:], np.r_[0.0, fund[start + 1:]]))
    out[c] = dict(a=a, b=b, spot=hold_spot, perp=hold_perp, start=str(sub["ts"].iloc[start].date()), end=str(sub["ts"].iloc[-1].date()),
                  cov=float((cnt[start + 1:] >= 2).mean() * 100), mean_ann_pct=float(fund[start + 1:].mean() * 365 * 100))

print(f"{'coin':<5}{'window':<23}{'cov%':>5}{'fund %/yr':>10} | {'net w/o':>8}{'net w/':>8}{'CAGR w/o':>9}{'CAGR w/':>8}{'DD w/':>7}{'Calmar':>7} | {'perpB&H net':>11}{'DD':>7}{'Calmar':>7} | {'spotB&H net':>11}{'Calmar':>7}")
for c, o in out.items():
    A, B = o["a"]["strat"], o["b"]["strat"]
    print(f"{c:<5}{o['start']+'->'+o['end'][2:]:<23}{o['cov']:>5.0f}{o['mean_ann_pct']:>10.1f} | {A['total_pct']:>+8.0f}{B['total_pct']:>+8.0f}{A['cagr_pct']:>+9.1f}{B['cagr_pct']:>+8.1f}{B['max_dd_pct']:>7.1f}{B['calmar']:>7.2f} | {o['perp']['total_pct']:>+11.0f}{o['perp']['max_dd_pct']:>7.1f}{o['perp']['calmar']:>7.2f} | {o['spot']['total_pct']:>+11.0f}{o['spot']['calmar']:>7.2f}")
c1 = sum(o["b"]["strat"]["total_pct"] > 0 for o in out.values())
c2 = sum(o["b"]["strat"]["calmar"] > o["perp"]["calmar"] for o in out.values())
c3 = sum((o["a"]["strat"]["cagr_pct"] > 0) and (o["b"]["strat"]["cagr_pct"] >= 0.75 * o["a"]["strat"]["cagr_pct"]) for o in out.values())
print(f"\nPRE-REGISTERED: (1) net>0 after funding on >=4/5: {c1}/5 {'PASS' if c1>=4 else 'FAIL'} | (2) Calmar beats perp buy&hold on >=4/5: {c2}/5 {'PASS' if c2>=4 else 'FAIL'} | (3) CAGR retained >=75% on >=4/5: {c3}/5 {'PASS' if c3>=4 else 'FAIL'}")
print("OVERALL:", "SURVIVES funding" if (c1 >= 4 and c2 >= 4 and c3 >= 4) else "DOES NOT survive funding (per the pre-registered bar)")
print("\nPROXY CHECK: KuCoin vs OKX funding, last ~3 months (mean rate per 8h interval)")
okx = {"BTC": "BTC-USDT-SWAP", "ETH": "ETH-USDT-SWAP", "SOL": "SOL-USDT-SWAP", "ADA": "ADA-USDT-SWAP", "SUI": "SUI-USDT-SWAP"}
for c in coins:
    d = requests.get("https://www.okx.com/api/v5/public/funding-rate-history", params={"instId": okx[c], "limit": 100}, timeout=20).json()["data"]
    o = pd.DataFrame(d); o["ts"] = pd.to_datetime(o["fundingTime"].astype("int64"), unit="ms", utc=True).astype("datetime64[us, UTC]"); o["rate"] = o["fundingRate"].astype(float)
    k = pd.read_csv(f"{S}/data/funding_{c}.csv", parse_dates=["ts"]); k["ts"] = k["ts"].astype("datetime64[us, UTC]"); k = k[k.ts >= o.ts.min()]
    m = pd.merge_asof(o.sort_values("ts")[["ts", "rate"]], k.sort_values("ts")[["ts", "rate"]], on="ts", direction="nearest", tolerance=pd.Timedelta(hours=2), suffixes=("_okx", "_kc")).dropna()
    print(f"  {c}: OKX mean {100*o.rate.mean():.5f}% | KuCoin mean {100*k.rate.mean():.5f}% | corr of matched rates {m.rate_okx.corr(m.rate_kc):.2f} ({len(m)} matched)")
