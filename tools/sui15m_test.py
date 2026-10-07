"""SUI 15m, 1:5 RR, $1,000 test (docs/SUI15M_PREREG.md). usage: PYTHONPATH=. python tools/sui15m_test.py SUI_15m.csv A|B [gross]
A = crypTP structure strategy with a single 5R target; B = Liquidity Sweep Reversal at 5R. 'gross' = zero fees and slippage (diagnostic)."""
import copy, json, sys
import numpy as np
import pandas as pd
from cryptp.backtest import load_csv, run_backtest, split_trades, summarize
from cryptp.config import load_config
from cryptp.sweep import SweepParams, run_sweep

path, cand = sys.argv[1], sys.argv[2]
gross = len(sys.argv) > 3 and sys.argv[3] == "gross"
fee, slip = (0.0, 0.0) if gross else (0.00055, 2.0)
df = load_csv(path)
sym = "SUI/USDT:USDT"
cfg = load_config("config.yaml")
cfg.risk.paper_equity, cfg.risk.risk_per_trade_pct, cfg.risk.max_leverage = 1000.0, 1.0, 3.0
if cand == "A":
    cfg.plan.r_multiples, cfg.plan.tp_fractions, cfg.plan.sides = [5.0], [1.0], "both"
    res = run_backtest(df, sym, cfg, fee_rate=fee, slippage_bps=slip, dm_mode="off")
else:
    res = run_sweep(df, sym, SweepParams(rr=5.0, use_be=False, risk_pct=1.0, max_leverage=3.0), fee_rate=fee, slippage_bps=slip, equity0=1000.0)

tr = res.trades
R = np.array([t.r for t in tr])
ins, oos, cut = split_trades(tr, 0.7, df)
se = R.std(ddof=1) / np.sqrt(len(R)) if len(R) > 1 else float("nan")
m = summarize(tr, res.equity0, res.equity)
yrs = {}
for t in tr:
    yrs.setdefault(t.entry_ts.year, []).append(t.r)
out = dict(candidate=cand, gross=gross, bars=len(df), start=str(df.ts.iloc[0].date()), end=str(df.ts.iloc[-1].date()), cut=str(cut.date()),
           trades=len(R), win_pct=float((R > 0).mean() * 100) if len(R) else 0.0, avgR=float(R.mean()) if len(R) else 0.0, se=float(se),
           lower=float(R.mean() - 2 * se) if len(R) else 0.0, pf=float(m["profit_factor"]), final=float(res.equity0 * (1 + m["return_pct"] / 100)),
           net_pct=float(m["return_pct"]), maxdd=float(m.get("max_drawdown_pct", 0.0)),
           is_n=len(ins), is_avgR=float(np.mean([t.r for t in ins])) if ins else float("nan"),
           oos_n=len(oos), oos_avgR=float(np.mean([t.r for t in oos])) if oos else float("nan"),
           years={int(y): (round(float(np.mean(v)), 3), len(v)) for y, v in sorted(yrs.items())},
           longs=(int(sum(t.side == "buy" for t in tr)), float(np.mean([t.r for t in tr if t.side == "buy"])) if any(t.side == "buy" for t in tr) else None),
           shorts=(int(sum(t.side == "sell" for t in tr)), float(np.mean([t.r for t in tr if t.side == "sell"])) if any(t.side == "sell" for t in tr) else None),
           median_stop_pct=float(np.median([abs(t.entry - t.stop) / t.entry * 100 for t in tr])) if tr else None)
name = f"sui15m_{cand}{'_gross' if gross else ''}.json"
json.dump(out, open(name, "w"), indent=1)
print(json.dumps(out, indent=1))
pd.DataFrame([{**t.__dict__, "r": t.r} for t in tr]).to_csv(name.replace(".json", ".trades.csv"), index=False)
