"""Run the frozen FLAT-state shorts pre-registration (docs/FLATSHORT_PREREG.md).
usage: PYTHONPATH=. python tools/run_flatshort.py DATA_DIR"""
import json, sys
import numpy as np
from cryptp.backtest import load_csv, split_trades, summarize
from cryptp.daily15m import DailyParams, run_daily15m

D = sys.argv[1].rstrip("/")
Z = 2.5


def evaluate(d15, daily, sym, p, fee=0.00055, slip=2.0):
    res = run_daily15m(d15, daily, sym, p, fee, slip)
    tr = res.trades
    R = np.array([t.r for t in tr])
    if len(R) < 2:
        return dict(n=len(R))
    ins, oos, cut = split_trades(tr, 0.7, d15)
    m = summarize(tr, res.equity0, res.equity)
    mo = summarize(oos, res.equity0) if oos else {}
    se = R.std(ddof=1) / np.sqrt(len(R))
    mean = lambda xs: float(np.mean([t.r for t in xs])) if xs else float("nan")
    yrs = {}
    for t in tr: yrs.setdefault(t.entry_ts.year, []).append(t.r)
    return dict(n=len(R), win=float((R > 0).mean() * 100), avgR=float(R.mean()), se=float(se), lower=float(R.mean() - Z * se),
                pf=float(m["profit_factor"]), net=float(m["return_pct"]), dd=float(m.get("max_drawdown_pct", 0)),
                is_n=len(ins), is_R=mean(ins), oos_n=len(oos), oos_R=mean(oos), oos_pf=float(mo.get("profit_factor", float("nan"))),
                cut=str(cut.date()), years={int(y): (round(float(np.mean(v)), 3), len(v)) for y, v in sorted(yrs.items())},
                median_stop=float(np.median([abs(t.entry - t.stop) / t.entry * 100 for t in tr])))


S = lambda **k: DailyParams(side="short", **k)
df, daily = load_csv(f"{D}/SUI_15m.csv"), load_csv(f"{D}/SUI_1d.csv")
out = {"main": evaluate(df, daily, "SUI", S()),
       "gross": evaluate(df, daily, "SUI", S(), 0.0, 0.0),
       "filter_off": evaluate(df, daily, "SUI", S(daily_filter="off")),
       "long_state": evaluate(df, daily, "SUI", S(daily_filter="opposite"))}
for c in ("ETH", "SOL"):
    out[f"{c}_90d"] = evaluate(load_csv(f"{D}/{c}_15m_90d.csv"), load_csv(f"{D}/{c}_1d.csv"), c, S())
k = int(len(df) * 0.6)
full = run_daily15m(df, daily, "SUI", S()).trades
part = run_daily15m(df.iloc[:k], daily, "SUI", S()).trades
last = df["ts"].iloc[k - 1]
out["prefix_match"] = bool([(t.entry_ts, round(t.entry, 8)) for t in full if t.exit_ts < last]
                           == [(t.entry_ts, round(t.entry, 8)) for t in part if t.exit_ts < last])
json.dump(out, open("flatshort_results.json", "w"), indent=1, default=float)
print(json.dumps(out, default=float))
