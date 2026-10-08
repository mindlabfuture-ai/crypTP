"""Run the frozen bounce pre-registration (docs/BOUNCE_PREREG.md).
usage: PYTHONPATH=. python tools/run_bounce.py SUI_15m.csv funding_SUI.csv validation
       PYTHONPATH=. python tools/run_bounce.py SUI_15m.csv funding_SUI.csv holdout --release-holdout   (only if validation passed)"""
import json, sys
import numpy as np
import pandas as pd
from cryptp.backtest import load_csv, summarize
from cryptp.bounce import BounceParams, find_signals, run_bounce, stop_price
from cryptp.indicators import atr

CUT1, CUT2 = pd.Timestamp("2025-01-20 15:45", tz="UTC"), pd.Timestamp("2025-11-29 03:15", tz="UTC")
seg = sys.argv[3]
if seg not in ("validation", "holdout"):
    sys.exit("segment must be validation or holdout (discovery is not a test segment)")
if seg == "holdout" and "--release-holdout" not in sys.argv:
    sys.exit("holdout is released only after validation passes: add --release-holdout")
df = load_csv(sys.argv[1])
fund = pd.read_csv(sys.argv[2])
lo, hi = (CUT1, CUT2) if seg == "validation" else (CUT2, df["ts"].iloc[-1] + pd.Timedelta(minutes=15))
si = int(df["ts"].searchsorted(lo)); ei = int(df["ts"].searchsorted(hi))
SYM, Z, P = "SUI/USDT:USDT", 2.5, BounceParams()


def stats(res):
    tr = res.trades
    R = np.array([t.r for t in tr])
    if len(R) < 2:
        return dict(n=len(R))
    m = summarize(tr, res.equity0, res.equity)
    se = R.std(ddof=1) / np.sqrt(len(R))
    mo = {}
    for t in tr: mo.setdefault(t.entry_ts.strftime("%Y-%m"), []).append(t.pnl)
    big = {k: sum(v) for k, v in mo.items() if len(v) >= 10}
    return dict(n=len(R), win=float((R > 0).mean() * 100), avgR=float(R.mean()), se=float(se), lower=float(R.mean() - Z * se),
                pf=float(m["profit_factor"]), net=float(m["return_pct"]), dd=float(m.get("max_drawdown_pct", 0)),
                months_ge10=len(big), months_pos=sum(v > 0 for v in big.values()),
                bigwin_R=float(R.max()), armed=getattr(res, "armed_trades", None), funding=float(getattr(res, "funding_paid", 0)),
                midnight_cut_above_1r=getattr(res, "midnight_cut_above_1r", None),
                median_stop_pct=float(np.median([abs(t.entry - t.stop) / t.entry * 100 for t in tr])),
                avg_bars=float(np.mean([t.bars for t in tr])))


def go(p=P, fee=0.00055, slip=2.0, funding=True, signals=None):
    return run_bounce(df, SYM, p, fee, slip, 1000.0, fund, funding, si, ei, signals)


main = go()
gross = go(fee=0.0, slip=0.0, funding=False)
fixed3 = go(BounceParams(exit_mode="fixed3"))
sigs = np.flatnonzero(find_signals(df, P))
sigs = sigs[(sigs >= si) & (sigs < ei - 1)]
A = atr(df); stops = stop_price(df, P, A)
cand = np.array([i for i in range(si, ei - 1) if df["ts"].iloc[i + 1].hour < P.cutoff_hour and not np.isnan(stops[i])])
rng_avgs = []
for seed in range(200):
    pick = np.random.default_rng(seed).choice(cand, size=len(sigs), replace=False)
    r = go(signals={int(i): float(stops[i]) for i in pick})
    R = [t.r for t in r.trades]
    rng_avgs.append(float(np.mean(R)) if R else 0.0)
p95 = float(np.percentile(rng_avgs, 95))
# causality: truncating the future must not change earlier trades
k = si + (ei - si) // 2
part = run_bounce(df.iloc[:k], SYM, P, 0.00055, 2.0, 1000.0, fund, True, si, k)
cut_ts = df["ts"].iloc[k - 1] - pd.Timedelta(days=1)
a = [(t.entry_ts, round(float(t.entry), 8)) for t in main.trades if t.exit_ts < cut_ts]
b = [(t.entry_ts, round(float(t.entry), 8)) for t in part.trades if t.exit_ts < cut_ts]
S, G = stats(main), stats(gross)
crit = {
    "trades>=100": S["n"] >= 100,
    "avgR-2.5SE>0": S["lower"] > 0,
    "PF>=1.15": S["pf"] >= 1.15,
    "gross avgR>0": G["avgR"] > 0,
    "net avgR>0": S["avgR"] > 0,
    "maxDD<25%": S["dd"] > -25,
    "months>=60% positive": S["months_ge10"] > 0 and S["months_pos"] / S["months_ge10"] >= 0.6,
    "beats random p95": S["avgR"] > p95,
}
out = dict(segment=seg, window=f"{df['ts'].iloc[si]} -> {df['ts'].iloc[ei - 1]}", signals_in_segment=int(len(sigs)),
           main=S, gross=G, fixed3_control=stats(fixed3),
           random_entry=dict(p50=float(np.percentile(rng_avgs, 50)), p95=p95, max=float(max(rng_avgs)), min=float(min(rng_avgs))),
           prefix_match=bool(a == b), criteria=crit, PASS=bool(all(crit.values()) and a == b))
json.dump(out, open(f"bounce_{seg}.json", "w"), indent=1, default=float)
print(json.dumps(out, indent=1, default=float))
