"""Run the frozen SMC+VWAP pre-registration (docs/SMC_VWAP_PREREG.md) ONCE.
usage: PYTHONPATH=. python tools/run_smc.py DATA_DIR"""
import json, sys
import numpy as np
import pandas as pd
from cryptp.backtest import load_csv, summarize
from cryptp.ict import IctParams, Setup, prepare, run_ict

D = sys.argv[1].rstrip("/")
Z = 3.0
P = IctParams(model="smc", use_killzone=False)


def stats(res, mo_min=6):
    tr = res.trades
    R = np.array([t.r for t in tr])
    if len(R) < 2:
        return dict(n=len(R), filters=res.filtered)
    m = summarize(tr, res.equity0, res.equity)
    se = R.std(ddof=1) / np.sqrt(len(R))
    mo = {}
    for t in tr: mo.setdefault(t.entry_ts.strftime("%Y-%m"), []).append(t.pnl)
    big = {k: sum(v) for k, v in mo.items() if len(v) >= mo_min}
    return dict(n=len(R), longs=sum(t.side == "buy" for t in tr), win=float((R > 0).mean() * 100), avgR=float(R.mean()), se=float(se),
                lower=float(R.mean() - Z * se), pf=float(m["profit_factor"]), net=float(m["return_pct"]), dd=float(m.get("max_drawdown_pct", 0)),
                months_ge6=len(big), months_pos=sum(v > 0 for v in big.values()), best_R=float(R.max()),
                armed=res.armed_trades, be_moved=res.be_moved_trades, be_stopped=res.be_stopped,
                exits=pd.Series(res.trade_notes).value_counts().to_dict(), funding_paid=round(res.funding_paid, 2),
                funding_received=round(res.funding_received, 2), filters=res.filtered,
                median_stop_pct=float(np.median([abs(t.entry - t.stop) / t.entry * 100 for t in tr])),
                avg_bars=float(np.mean([t.bars for t in tr])))


def load(coin):
    return load_csv(f"{D}/{coin}_15m.csv"), pd.read_csv(f"{D}/funding_{coin}.csv")


def go(df, coin, fund, p=P, prep=None, fee=0.00055, slip=2.0, funding=True, **kw):
    return run_ict(df, coin, p, fee, slip, 1000.0, fund, funding, prep, **kw)


def halves(df, res):
    mid = df["ts"].iloc[len(df) // 2]
    f = lambda sel: float(np.mean([t.r for t in sel])) if sel else float("nan")
    a = [t for t in res.trades if t.entry_ts < mid]; b = [t for t in res.trades if t.entry_ts >= mid]
    return dict(H1=dict(n=len(a), avgR=f(a)), H2=dict(n=len(b), avgR=f(b)))


def random_control(df, fund, prep, n_pick, seeds=200):
    o, h, l = (df[k].to_numpy(float) for k in ("open", "high", "low"))
    hrs = df["ts"].dt.hour.to_numpy()
    vw, dp, a = prep.vwap_prev, prep.day_pos, prep.atr
    cand = np.array([j for j in range(300, len(df) - 1) if dp[j] >= P.vwap_min_bars and not np.isnan(vw[j])
                     and not np.isnan(a[j - 1])])
    out = []
    for seed in range(seeds):
        pick = np.random.default_rng(seed).choice(cand, size=n_pick, replace=False)
        sd = {}
        for j in pick:
            long = o[j] < vw[j]
            st = (l[j - 12:j].min() - P.stop_atr * a[j - 1]) if long else (h[j - 12:j].max() + P.stop_atr * a[j - 1])
            sd.setdefault(int(j) - 1, []).append(Setup(1 if long else -1, int(j) - 1, np.inf if long else -np.inf, float(st), int(j)))
        r = run_ict(df, "X", P, 0.00055, 2.0, 1000.0, fund, True, prep, None, sd, True)
        R = [t.r for t in r.trades]
        out.append(float(np.mean(R)) if R else 0.0)
    return out


sei, f_sei = load("SEI")
prep = prepare(sei, P)
main = go(sei, "SEI", f_sei, prep=prep)
S = stats(main)
out = dict(SEI=dict(window=f"{sei['ts'].iloc[0]} -> {sei['ts'].iloc[-1]}", bars=len(sei), detection=prep.counts, main=S, **halves(sei, main)))
out["SEI"]["gross"] = stats(go(sei, "SEI", f_sei, prep=prep, fee=0.0, slip=0.0, funding=False))
abl = {}
for name, kw in (("no_vwap", dict(use_vwap=False)), ("no_bias", dict(use_bias=False))):
    abl[name] = stats(go(sei, "SEI", f_sei, IctParams(model="smc", use_killzone=False, **kw), prep=prep))
for name, kw in (("no_impulse_filter", dict(use_impulse=False)), ("ob_edge_entry", dict(ob_entry="edge")),
                 ("long_only", dict(sides="long")), ("short_only", dict(sides="short"))):
    pp = IctParams(model="smc", use_killzone=False, **kw)
    abl[name] = stats(go(sei, "SEI", f_sei, pp, prep=prepare(sei, pp)))
out["SEI"]["ablations"] = abl
out["SEI"]["maker_entry_0.02pct"] = stats(go(sei, "SEI", f_sei, prep=prep, fee_entry=0.0002)).get("avgR")
out["SEI"]["fee_sensitivity_avgR"] = {f"x{m}": stats(go(sei, "SEI", f_sei, prep=prep, fee=0.00055 * m)).get("avgR") for m in (0.5, 1, 2)}
rnd = random_control(sei, f_sei, prep, max(S["n"], 20))
out["SEI"]["random_entry"] = dict(p50=float(np.percentile(rnd, 50)), p95=float(np.percentile(rnd, 95)), max=float(max(rnd)))
k = int(len(sei) * 0.6)
sub = sei.iloc[:k].reset_index(drop=True)
part = run_ict(sub, "SEI", P, 0.00055, 2.0, 1000.0, f_sei, True, prepare(sub, P))
cut = sei["ts"].iloc[k - 1] - pd.Timedelta(days=3)
f = lambda r: [(t.entry_ts, round(float(t.entry), 8), t.side) for t in r.trades if t.exit_ts < cut]
out["SEI"]["prefix_match"] = bool(f(main) == f(part))
sui, f_sui = load("SUI")
out["SUI_replication"] = stats(go(sui, "SUI", f_sui, prep=prepare(sui, P)))
ub, f_ub = load("UB")
out["UB_report_only"] = stats(go(ub, "UB", f_ub, prep=prepare(ub, P), slip=10.0))
G = out["SEI"]["gross"]; R = out["SUI_replication"]
crit = {
    "trades>=150": S["n"] >= 150,
    "avgR-3.0SE>0": S["lower"] > 0,
    "PF>=1.15": S["pf"] >= 1.15,
    "gross avgR>0": G["avgR"] > 0,
    "maxDD<25%": S["dd"] > -25,
    "H1 and H2 avgR>0": bool(out["SEI"]["H1"]["avgR"] > 0 and out["SEI"]["H2"]["avgR"] > 0),
    "months>=60% positive": bool(S["months_ge6"] > 0 and S["months_pos"] / S["months_ge6"] >= 0.6),
    "beats random p95": S["avgR"] > out["SEI"]["random_entry"]["p95"],
    "SUI replication (n>=100, avgR>0, PF>1)": bool(R.get("n", 0) >= 100 and R.get("avgR", -1) > 0 and R.get("pf", 0) > 1.0),
    "prefix test": out["SEI"]["prefix_match"],
}
out["criteria"] = {k_: bool(v) for k_, v in crit.items()}
out["PASS"] = bool(all(crit.values()))
json.dump(out, open("smc_results.json", "w"), indent=1, default=float)
print(json.dumps(out, indent=1, default=float))
