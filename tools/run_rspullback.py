"""Run the frozen RS-pullback pre-registration (docs/RS_PULLBACK_PREREG.md) ONCE.
usage: PYTHONPATH=. python tools/run_rspullback.py DATA_DIR"""
import json, math, sys
from dataclasses import replace
import numpy as np
import pandas as pd
from cryptp.backtest import load_csv
from cryptp.hourly import to_hourly
from cryptp.rspullback import RSParams, eligible, plan_coin, rank_rs, regime, simulate

D = sys.argv[1].rstrip("/")
TRADABLE, BREADTH, BENCH, Z = ["ETH", "SOL", "ADA", "SUI", "SEI"], ["BTC", "ETH", "SOL", "ADA", "SUI"], "BTC", 2.5
P = RSParams()
DAILY = {c: load_csv(f"{D}/{c}_1d.csv") for c in sorted(set(TRADABLE) | set(BREADTH))}
H1 = {c: load_csv(f"{D}/{c}_1h_1460d.csv") for c in TRADABLE if c != "SEI"}
H1["SEI"] = to_hourly(load_csv(f"{D}/SEI_15m.csv"))
FUND = {}
for c in TRADABLE:
    f = pd.read_csv(f"{D}/funding_{c}.csv")
    FUND[c] = (pd.to_datetime(f["ts"], utc=True).dt.tz_localize(None).to_numpy("datetime64[ns]"), f["rate"].to_numpy(float))


def frate(coin):
    ts, r = FUND[coin]
    def g(t):
        i = np.searchsorted(ts, t.tz_convert(None).to_datetime64(), side="right") - 1
        return float(r[i]) if i >= 0 else P.default_funding
    return g


def days_range(daily, h1):
    start = max(d["ts"].iloc[0] for d in daily.values()) + pd.Timedelta(days=P.sma + 1)
    end = min(h["ts"].iloc[-1] for h in h1.values()).normalize() - pd.Timedelta(days=4)   # leave room for 72h exits
    return pd.date_range(start.normalize(), end, freq="D", tz="UTC")


_cache = {}
_day_cache = {}


def day_info(day, p, tradable, daily):
    """Regime, RS ranking and eligible coins for a day (pure functions of closed daily candles; cached for speed only)."""
    key = (day, p.use_regime, tuple(tradable), id(daily))
    if key not in _day_cache:
        ok = regime(daily, BREADTH, day, p)[0] if p.use_regime else True
        _day_cache[key] = (ok, rank_rs(daily, tradable, BENCH, day, p) if ok else [], eligible(daily, tradable, day, p) if ok else [])
    return _day_cache[key]


def outcome(day, coin, rs, p, h1):
    key = (day, coin, p.taker_entry, id(h1[coin]))
    if key not in _cache:
        h = h1[coin]
        t = h[h["ts"] == day]
        if not len(t):
            _cache[key] = (None, "no open bar", None)
        else:
            pl, why = plan_coin(coin, rs, day, h, float(t["open"].iloc[0]), p)
            _cache[key] = (pl, why, simulate(pl, h, p, frate(coin)) if pl else None)
    return _cache[key]


def run(p=P, tradable=TRADABLE, daily=DAILY, h1=H1, picker=None):
    """picker(day, ranked, elig) -> picks; default = RS top-N."""
    cands, skips = [], {}
    for day in days_range(daily, h1):
        ok, ranked, elig = day_info(day, p, tradable, daily)
        if not ok:
            continue
        picks = ranked[: p.top_n] if picker is None else picker(day, ranked[: p.top_n], elig)
        for coin, rs in picks:
            pl, why, out = outcome(day, coin, rs, p, h1)
            if pl is None:
                skips[why] = skips.get(why, 0) + 1
                continue
            cands.append((pl, out))
    # portfolio rules, in fill order
    fills = sorted([(o.fill_ts, pl, o) for pl, o in cands if o.status in ("closed", "open")], key=lambda x: x[0])
    taken, curve = [], []
    for fts, pl, o in fills:
        if o.status != "closed":
            continue
        openpos = [t for t in taken if t[2].fill_ts < fts < t[2].exit_ts]
        if len(openpos) >= p.max_open or any(t[1].coin == pl.coin for t in openpos):
            skips["portfolio full / coin held"] = skips.get("portfolio full / coin held", 0) + 1
            continue
        day_r = sum(t[2].r for t in taken if t[2].exit_ts < fts and t[2].exit_ts.normalize() == fts.normalize())
        wk = fts.isocalendar()[:2]
        week_r = sum(t[2].r for t in taken if t[2].exit_ts < fts and t[2].exit_ts.isocalendar()[:2] == wk)
        if day_r <= p.daily_stop_r or week_r <= p.weekly_stop_r:
            skips["daily/weekly stop"] = skips.get("daily/weekly stop", 0) + 1
            continue
        taken.append((fts, pl, o))
    # equity: realised, 1% of equity at the fill risked per trade (leverage cap never binds: stops >= 1.5% -> notional <= 0.67x)
    risk_at = {}
    eq = 1000.0
    pending = sorted(taken, key=lambda x: x[0])
    ex_sorted = sorted(taken, key=lambda x: x[2].exit_ts)
    k = 0
    for t in pending:
        while k < len(ex_sorted) and ex_sorted[k][2].exit_ts < t[0]:
            e = ex_sorted[k]; eq += risk_at[id(e)] * e[2].r; curve.append((e[2].exit_ts, eq)); k += 1
        risk_at[id(t)] = eq * p.risk_pct / 100
    while k < len(ex_sorted):
        e = ex_sorted[k]; eq += risk_at[id(e)] * e[2].r; curve.append((e[2].exit_ts, eq)); k += 1
    n_orders = len(cands)
    return dict(taken=taken, skips=skips, equity=eq, curve=curve, orders=n_orders,
                filled=sum(o.status in ("closed", "open") for _, o in cands))


def stats(res):
    tr = res["taken"]
    R = np.array([t[2].r for t in tr])
    if len(R) < 2:
        return dict(n=len(R), skips=res["skips"])
    se = R.std(ddof=1) / math.sqrt(len(R))
    win, loss = R[R > 0].sum(), -R[R <= 0].sum()
    eqs = np.array([1000.0] + [e for _, e in res["curve"]])
    dd = float(((eqs - np.maximum.accumulate(eqs)) / np.maximum.accumulate(eqs)).min() * 100)
    mo = {}
    for t in tr: mo.setdefault(t[2].exit_ts.strftime("%Y-%m"), []).append(t[2].r)
    by_coin = {}
    for t in tr: by_coin.setdefault(t[1].coin, []).append(t[2].r)
    reasons = pd.Series([t[2].reason for t in tr]).value_counts().to_dict()
    return dict(n=len(R), win=float((R > 0).mean() * 100), avgR=float(R.mean()), se=float(se), lower=float(R.mean() - Z * se),
                pf=float(win / loss) if loss else float("inf"), gross_avgR=float(np.mean([t[2].r_gross for t in tr])),
                funding_avgR=float(np.mean([t[2].funding_r for t in tr])), net_pct=float(res["equity"] / 10 - 100), dd_realised=dd,
                months=len(mo), months_pos=sum(sum(v) > 0 for v in mo.values()), exits=reasons,
                by_coin={c: (len(v), round(float(np.mean(v)), 3)) for c, v in sorted(by_coin.items())},
                floor_pct=float(np.mean([t[1].floor_applied for t in tr]) * 100), orders=res["orders"], filled=res["filled"],
                skips=res["skips"], first=str(tr[0][0].date()), last=str(tr[-1][0].date()))


main = run()
S = stats(main)
mid = main["taken"][0][0] + (main["taken"][-1][0] - main["taken"][0][0]) / 2
halves = {h: float(np.mean([t[2].r for t in main["taken"] if (t[0] < mid) == (h == "H1")])) for h in ("H1", "H2")}
halves_n = {h: sum((t[0] < mid) == (h == "H1") for t in main["taken"]) for h in ("H1", "H2")}
loo = {c: stats(run(tradable=[x for x in TRADABLE if x != c])) for c in TRADABLE}
rng_avgs = []
for seed in range(200):
    g = np.random.default_rng(seed)
    def picker(day, ranked, elig, g=g):
        k = len(ranked)
        if not k or not elig:
            return []
        return [(c, 0.0) for c in g.choice(elig, size=min(k, len(elig)), replace=False)]
    r = run(picker=picker)
    R = [t[2].r for t in r["taken"]]
    rng_avgs.append(float(np.mean(R)) if R else 0.0)
variants = {"no_regime": stats(run(replace(P, use_regime=False))), "top1": stats(run(replace(P, top_n=1))),
            "taker_entry": stats(run(replace(P, taker_entry=True)))}
# causality: rerun on data truncated at 60% of the period; trades exiting well before the cut must be identical
cut = days_range(DAILY, H1)[int(len(days_range(DAILY, H1)) * 0.6)]
tD = {c: d[d["ts"] < cut] for c, d in DAILY.items()}
tH = {c: h[h["ts"] < cut] for c, h in H1.items()}
part = run(daily=tD, h1=tH)
key = lambda r: [(t[1].coin, str(t[0]), round(t[2].r, 9)) for t in r["taken"] if t[2].exit_ts < cut - pd.Timedelta(days=5)]
prefix = key(main) == key(part)
crit = {
    "trades>=100": S["n"] >= 100,
    "avgR-2.5SE>0": S["lower"] > 0,
    "PF>=1.2": S["pf"] >= 1.2,
    "gross avgR>0": S["gross_avgR"] > 0,
    "maxDD<25%": S["dd_realised"] > -25,
    "both halves avgR>0": halves["H1"] > 0 and halves["H2"] > 0,
    "leave-one-coin-out all >0": all(v.get("avgR", -1) > 0 for v in loo.values()),
    "beats random-coin p95": S["avgR"] > float(np.percentile(rng_avgs, 95)),
    "prefix test": prefix,
}
out = dict(main=S, halves=halves, halves_n=halves_n, leave_one_out={c: {k: v.get(k) for k in ("n", "avgR", "pf")} for c, v in loo.items()},
           random_coin=dict(p50=float(np.percentile(rng_avgs, 50)), p95=float(np.percentile(rng_avgs, 95)), max=float(max(rng_avgs))),
           variants={k: {kk: v.get(kk) for kk in ("n", "avgR", "pf", "net_pct", "dd_realised")} for k, v in variants.items()},
           criteria={k: bool(v) for k, v in crit.items()}, PASS=bool(all(crit.values())))
json.dump(out, open("rspullback_results.json", "w"), indent=1, default=str)
print(json.dumps(out, indent=1, default=str))
