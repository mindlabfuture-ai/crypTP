"""Run the frozen squeeze-breakout pre-registration (docs/SQUEEZE_PROPOSAL.md) on SUI 15m.
usage: PYTHONPATH=. python tools/run_squeeze.py SUI_15m.csv"""
import json, sys
import numpy as np
import pandas as pd
from cryptp.backtest import load_csv, split_trades, summarize
from cryptp.squeeze import SqueezeParams, run_squeeze

df = load_csv(sys.argv[1])
SYM = "SUI/USDT:USDT"
Z = 2.5                                                                      # frozen criterion 3


def evaluate(p, fee=0.00055, slip=2.0):
    res = run_squeeze(df, SYM, p, fee, slip, 1000.0)
    tr = res.trades
    R = np.array([t.r for t in tr])
    if len(R) < 2:
        return dict(n=len(R))
    ins, oos, cut = split_trades(tr, 0.7, df)
    m = summarize(tr, res.equity0, res.equity)
    se = R.std(ddof=1) / np.sqrt(len(R))
    yrs = {}
    for t in tr: yrs.setdefault(t.entry_ts.year, []).append(t.r)
    mean = lambda xs: float(np.mean([t.r for t in xs])) if xs else float("nan")
    return dict(n=len(R), win=float((R > 0).mean() * 100), avgR=float(R.mean()), se=float(se), lower=float(R.mean() - Z * se),
                pf=float(m["profit_factor"]), final=float(1000 * (1 + m["return_pct"] / 100)), net=float(m["return_pct"]), dd=float(m.get("max_drawdown_pct", 0)),
                is_n=len(ins), is_R=mean(ins), oos_n=len(oos), oos_R=mean(oos), cut=str(cut.date()),
                years={int(y): (round(float(np.mean(v)), 3), len(v)) for y, v in sorted(yrs.items())},
                longs=(sum(t.side == "buy" for t in tr), mean([t for t in tr if t.side == "buy"])),
                shorts=(sum(t.side == "sell" for t in tr), mean([t for t in tr if t.side == "sell"])),
                median_stop=float(np.median([abs(t.entry - t.stop) / t.entry * 100 for t in tr])), R=R.tolist())


main, gross = evaluate(SqueezeParams()), evaluate(SqueezeParams(), 0.0, 0.0)
rob = {"min squeeze 4 bars": evaluate(SqueezeParams(min_squeeze_bars=4)), "min squeeze 8 bars": evaluate(SqueezeParams(min_squeeze_bars=8)),
       "volume 1.0x": evaluate(SqueezeParams(vol_mult=1.0)), "far-side stop": evaluate(SqueezeParams(stop_mode="far"))}
g = np.array(gross["R"])
exit_mix = dict(target=float((g > 4.5).mean() * 100), stop=float((g < -0.9).mean() * 100), time_exit=float(((g >= -0.9) & (g <= 4.5)).mean() * 100))
out = dict(main={k: v for k, v in main.items() if k != "R"}, gross={k: v for k, v in gross.items() if k != "R"}, exit_mix=exit_mix,
           robustness={k: {kk: vv for kk, vv in v.items() if kk != "R"} for k, v in rob.items()})
json.dump(out, open("squeeze_results.json", "w"), indent=1, default=float)
print(json.dumps(out, indent=1, default=float))
