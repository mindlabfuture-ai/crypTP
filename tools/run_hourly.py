"""Run the frozen 1h pre-registration (docs/HOURLY_PREREG.md) ONCE.
usage: PYTHONPATH=. python tools/run_hourly.py DATA_DIR"""
import json, sys
import numpy as np
import pandas as pd
from cryptp.backtest import load_csv, summarize
from cryptp.daily15m import daily_allowed
from cryptp.hourly import HourlyParams, find_signals, run_hourly, to_hourly
from cryptp.indicators import atr

D = sys.argv[1].rstrip("/")
Z, P = 2.5, HourlyParams()


def load(coin):
    h = to_hourly(load_csv(f"{D}/{coin}_15m.csv"))
    return h, load_csv(f"{D}/{coin}_1d.csv"), pd.read_csv(f"{D}/funding_{coin}.csv")


def stats(res, mo_min=8):
    tr = res.trades
    R = np.array([t.r for t in tr])
    if len(R) < 2:
        return dict(n=len(R))
    m = summarize(tr, res.equity0, res.equity)
    se = R.std(ddof=1) / np.sqrt(len(R))
    mo = {}
    for t in tr: mo.setdefault(t.entry_ts.strftime("%Y-%m"), []).append(t.pnl)
    big = {k: sum(v) for k, v in mo.items() if len(v) >= mo_min}
    notes = pd.Series(res.trade_notes).value_counts().to_dict()
    return dict(n=len(R), win=float((R > 0).mean() * 100), avgR=float(R.mean()), se=float(se), lower=float(R.mean() - Z * se),
                pf=float(m["profit_factor"]), net=float(m["return_pct"]), dd=float(m.get("max_drawdown_pct", 0)),
                months_ge8=len(big), months_pos=sum(v > 0 for v in big.values()), best_R=float(R.max()),
                armed=res.armed_trades, be_moved=res.be_moved_trades, be_stopped=res.be_stopped, exits=notes,
                funding_paid=round(res.funding_paid, 2), funding_received=round(res.funding_received, 2),
                flat_cut_above_1r=res.flat_cut_above_1r, skipped_busy=res.skipped_busy,
                median_stop_pct=float(np.median([abs(t.entry - t.stop) / t.entry * 100 for t in tr])),
                avg_bars=float(np.mean([t.bars for t in tr])))


def go(h, daily, fund, coin, p=P, fee=0.00055, slip=2.0, funding=True, signals=None, start_i=0, end_i=None):
    return run_hourly(h, coin, p, fee, slip, 1000.0, fund, funding, signals, daily, start_i, end_i)


def evaluate(coin):
    h, daily, fund = load(coin)
    allowed, valid = daily_allowed(h, daily, P.sma_days)
    si = int(np.argmax(valid)); n = len(h); mid = si + (n - si) // 2
    sig_all = find_signals(h, P, daily)
    sigs = {i: a for i, a in sig_all.items() if i >= si}
    main = go(h, daily, fund, coin, signals=sigs, start_i=si)
    out = dict(coin=coin, window=f"{h['ts'].iloc[si]} -> {h['ts'].iloc[-1]}", bars=n - si, signals=len(sigs), main=stats(main))
    tr = main.trades
    for name, sel in (("H1", [t for t in tr if t.entry_ts < h["ts"].iloc[mid]]), ("H2", [t for t in tr if t.entry_ts >= h["ts"].iloc[mid]])):
        out[name] = dict(n=len(sel), avgR=float(np.mean([t.r for t in sel])) if sel else float("nan"))
    if coin != "SUI":
        return out, None
    out["gross"] = stats(go(h, daily, fund, coin, fee=0.0, slip=0.0, funding=False, signals=sigs, start_i=si))
    out["fixed3_control"] = stats(go(h, daily, fund, coin, HourlyParams(exit_mode="fixed3"), signals=sigs, start_i=si))
    out["secondary_midnight_flat"] = stats(go(h, daily, fund, coin, HourlyParams(midnight="flat"), signals=sigs, start_i=si))
    out["cost_sensitivity_avgR"] = {f"fees x{m}": stats(go(h, daily, fund, coin, fee=0.00055 * m, signals=sigs, start_i=si)).get("avgR") for m in (0.5, 1, 2)}
    a = atr(h).to_numpy(float)
    cand = np.array([i for i in range(si, n - 1) if allowed[i] and h["ts"].iloc[i + 1].hour < P.cutoff_hour and not np.isnan(a[i])])
    rng = []
    for seed in range(200):
        pick = np.random.default_rng(seed).choice(cand, size=len(sigs), replace=False)
        r = go(h, daily, fund, coin, signals={int(i): float(a[i]) for i in pick}, start_i=si)
        R = [t.r for t in r.trades]
        rng.append(float(np.mean(R)) if R else 0.0)
    out["random_entry"] = dict(p50=float(np.percentile(rng, 50)), p95=float(np.percentile(rng, 95)), max=float(max(rng)))
    k = si + (n - si) // 2
    part = run_hourly(h.iloc[:k], coin, P, 0.00055, 2.0, 1000.0, fund, True, None, daily, si, k)
    cut = h["ts"].iloc[k - 1] - pd.Timedelta(days=3)
    f = lambda tr_: [(t.entry_ts, round(float(t.entry), 8)) for t in tr_ if t.exit_ts < cut]
    out["prefix_match"] = bool(f(main.trades) == f(part.trades))
    return out, rng


sui, _ = evaluate("SUI")
sol, _ = evaluate("SOL")
S, G, SO = sui["main"], sui["gross"], sol["main"]
crit = {
    "trades>=150": S["n"] >= 150,
    "avgR-2.5SE>0": S["lower"] > 0,
    "PF>=1.15": S["pf"] >= 1.15,
    "gross avgR>0": G["avgR"] > 0,
    "maxDD<25%": S["dd"] > -25,
    "H1 and H2 avgR>0": bool(sui["H1"]["avgR"] > 0 and sui["H2"]["avgR"] > 0),
    "months>=60% positive": bool(S["months_ge8"] > 0 and S["months_pos"] / S["months_ge8"] >= 0.6),
    "beats random p95": S["avgR"] > sui["random_entry"]["p95"],
    "SOL replication (n>=100, avgR>0, PF>1)": bool(SO["n"] >= 100 and SO["avgR"] > 0 and SO["pf"] > 1.0),
}
res = dict(SUI=sui, SOL=sol, criteria={k: bool(v) for k, v in crit.items()}, PASS=bool(all(crit.values()) and sui["prefix_match"]))
json.dump(res, open("hourly_results.json", "w"), indent=1, default=float)
print(json.dumps(res, indent=1, default=float))
