"""Run the frozen daily-direction + 15m-entry pre-registration (docs/DAILY15M_PREREG.md) on SUI.
usage: PYTHONPATH=. python tools/run_daily15m.py SUI_15m.csv SUI_1d.csv"""
import json, sys
import numpy as np
from cryptp.backtest import load_csv, split_trades, summarize
from cryptp.daily15m import DailyParams, run_daily15m

df, daily = load_csv(sys.argv[1]), load_csv(sys.argv[2])
SYM, Z = "SUI/USDT:USDT", 2.5


def evaluate(d15, p, fee=0.00055, slip=2.0):
    res = run_daily15m(d15, daily, SYM, p, fee, slip)
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
                median_stop=float(np.median([abs(t.entry - t.stop) / t.entry * 100 for t in tr])),
                first_trade=str(tr[0].entry_ts), R=R.tolist())


strip = lambda d: {k: v for k, v in d.items() if k != "R"}
out = {"main": strip(evaluate(df, DailyParams())),
       "gross": strip(evaluate(df, DailyParams(), 0.0, 0.0)),
       "filter_off": strip(evaluate(df, DailyParams(daily_filter="off"))),
       "filter_inverted": strip(evaluate(df, DailyParams(daily_filter="opposite")))}
# causality: trades from a truncated run must equal the full run's trades that exit before the cut
k = int(len(df) * 0.6)
full = run_daily15m(df, daily, SYM).trades
part = run_daily15m(df.iloc[:k], daily, SYM).trades
last = df["ts"].iloc[k - 1]
a = [(t.entry_ts, round(t.entry, 8)) for t in full if t.exit_ts < last][:]
b = [(t.entry_ts, round(t.entry, 8)) for t in part if t.exit_ts < last]
out["prefix_match"] = bool(a == b)
json.dump(out, open("daily15m_results.json", "w"), indent=1, default=float)
print(json.dumps(out, indent=1, default=float))
