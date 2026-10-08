"""EXPLORATORY round 1 (docs/MB_FADE_PREREG.md, addendum "wider stops, fewer and higher-quality setups").
Stage 1: python tools/run_vpfade_sweep.py DATA_DIR
    runs the 16 pre-declared candidates on the original coins (net of costs), prints in-sample AND out-of-sample for all of them,
    selects per rule set by IN-SAMPLE average R only (>= 200 in-sample trades), then runs the +F twin and a zero-cost diagnostic
    for the selected configs and writes DATA_DIR/sweep_selected.json.
Stage 2: python tools/run_vpfade_sweep.py DATA_DIR --holdout HOLDOUT_DIR
    runs ONLY the selected configs on coins that were not in the original universe (HOLDOUT_DIR also needs BTC_15m.csv).
Run PYTHONPATH=. from the repo root."""
import itertools
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

from cryptp.backtest import load_csv
from cryptp.vpfade import VPParams, run_vpfade

SPLIT, MIN_IS_TRADES, MIN_HOLDOUT_TRADES = 0.70, 200, 150


def make(rule, stop, quality, rr):
    kw = dict(mode="fade" if rule == "A" else "discount", min_stop_pct=float(stop), min_rr=None if rr == "base" else 3.0)
    if quality == "high":
        kw.update(dict(ext_atr=1.0, wick_frac=0.6, a_vol_mult=1.5) if rule == "A"
                  else dict(vol_mult=2.0, body_frac=0.65, close_frac=0.2, zone_frac=0.15))
    return kw


GRID = {f"{r} stop>={s}% {q} rr-{rr}": (r, make(r, s, q, rr))
        for r, s, q, rr in itertools.product(("A", "B"), (1, 2), ("base", "high"), ("base", "3.0"))}


def work(args):
    name, kw, coin, folder, gross, macro = args
    df = load_csv(str(Path(folder) / f"{coin}_15m.csv"))
    btc = None
    if macro:
        b = load_csv(str(Path(folder) / "BTC_15m.csv")).set_index("ts")["close"]
        btc = b.reindex(df["ts"]).ffill().to_numpy()
    fee, slip = (0.0, 0.0) if gross else (0.00055, 2.0)
    res = run_vpfade(df, f"{coin}/USDT:USDT", VPParams(**kw, macro=macro), fee_rate=fee, slippage_bps=slip, btc_close=btc)
    rows = [dict(name=name, coin=coin, side=t.side, entry_ts=t.entry_ts, r=t.r, stop_pct=abs(t.entry - t.stop) / t.entry * 100) for t in res.trades]
    return name, coin, rows, (df["ts"].iloc[0], df["ts"].iloc[-1])


def stats(r):
    r = np.asarray(r, float)
    if len(r) == 0:
        return dict(n=0, avg_r=None, lower2se=None, win_pct=None)
    se = r.std(ddof=1) / np.sqrt(len(r)) if len(r) > 1 else float("nan")
    return dict(n=int(len(r)), avg_r=float(r.mean()), lower2se=float(r.mean() - 2 * se), win_pct=float((r > 0).mean() * 100))


def run_jobs(jobs):
    out, spans = {}, {}
    with ProcessPoolExecutor(max_workers=min(len(jobs), os.cpu_count() or 2)) as ex:
        for name, coin, rows, span in ex.map(work, jobs, chunksize=1):
            out.setdefault(name, []).extend(rows)
            spans[coin] = span
    return out, spans


def split_stats(rows, cut):
    d = pd.DataFrame(rows)
    if d.empty:
        return dict(all=stats([]), ins=stats([]), oos=stats([]), median_stop_pct=None)
    return dict(all=stats(d["r"]), ins=stats(d[d["entry_ts"] < cut]["r"]), oos=stats(d[d["entry_ts"] >= cut]["r"]),
                median_stop_pct=float(d["stop_pct"].median()))


def fmt(s):
    return "   n/a        " if not s["n"] else f"{s['avg_r']:+.3f} (n={s['n']:>5})"


def stage1(folder):
    coins = sorted(p.name[:-8] for p in Path(folder).glob("*_15m.csv") if not p.name.startswith("BTC"))
    jobs = [(n, kw, c, folder, False, False) for n, (_, kw) in GRID.items() for c in coins]
    out, spans = run_jobs(jobs)
    t0, t1 = min(s[0] for s in spans.values()), max(s[1] for s in spans.values())
    cut = t0 + (t1 - t0) * SPLIT
    res = {n: split_stats(out[n], cut) for n in GRID}
    print(f"coins {coins}\ncut {str(cut)[:10]} (in-sample before, out-of-sample after); net of costs; ALL 16 candidates, sorted by in-sample avg R\n")
    print(f"{'candidate':<32}{'in-sample':<20}{'out-of-sample':<20}{'median stop':>12}  win%")
    for n in sorted(GRID, key=lambda k: -(res[k]["ins"]["avg_r"] if res[k]["ins"]["n"] else -9)):
        r = res[n]
        print(f"{n:<32}{fmt(r['ins']):<20}{fmt(r['oos']):<20}{(r['median_stop_pct'] or 0):>11.2f}%  {r['all']['win_pct'] or 0:.0f}")
    selected = {}
    for rule in ("A", "B"):
        cands = [n for n in GRID if GRID[n][0] == rule and res[n]["ins"]["n"] >= MIN_IS_TRADES]
        if cands:
            best = max(cands, key=lambda k: res[k]["ins"]["avg_r"])
            selected[rule] = best
    print("\n== SELECTED by in-sample average R only (>= %d in-sample trades)" % MIN_IS_TRADES)
    detail = {}
    for rule, name in selected.items():
        kw = GRID[name][1]
        f_out, _ = run_jobs([(name, kw, c, folder, False, True) for c in coins])
        g_out, _ = run_jobs([(name, kw, c, folder, True, False) for c in coins])
        detail[rule] = dict(name=name, kw=kw, net=res[name], filtered=split_stats(f_out[name], cut) if name in f_out else None,
                            gross=split_stats(g_out[name], cut) if name in g_out else None)
        d = detail[rule]
        print(f"\n[{rule}] {name}")
        print(f"   net            in-sample {fmt(d['net']['ins'])}  out-of-sample {fmt(d['net']['oos'])}  (lower2SE oos {d['net']['oos']['lower2se']})")
        if d["filtered"]:
            print(f"   +F macro       in-sample {fmt(d['filtered']['ins'])}  out-of-sample {fmt(d['filtered']['oos'])}")
        if d["gross"]:
            print(f"   zero-cost diag in-sample {fmt(d['gross']['ins'])}  out-of-sample {fmt(d['gross']['oos'])}")
    if not selected:
        print("   none: no candidate had enough in-sample trades")
    json.dump(dict(cut=str(cut), coins=coins, all=res, selected=detail), open(Path(folder) / "sweep_selected.json", "w"), indent=1, default=str)


def stage2(folder, holdout):
    sel = json.load(open(Path(folder) / "sweep_selected.json"))
    cut = pd.Timestamp(sel["cut"])
    coins = sorted(p.name[:-8] for p in Path(holdout).glob("*_15m.csv") if not p.name.startswith("BTC"))
    print(f"held-out coins {coins}; cut {str(cut)[:10]}; selected configs only, run once, net of costs")
    for rule, d in sel["selected"].items():
        name, kw = d["name"], d["kw"]
        plain, _ = run_jobs([(name, kw, c, holdout, False, False) for c in coins])
        filt, _ = run_jobs([(name, kw, c, holdout, False, True) for c in coins])
        s_plain, s_filt = split_stats(plain.get(name, []), cut), split_stats(filt.get(name, []), cut)
        oos_main = d["net"]["oos"]
        promising = (oos_main["avg_r"] is not None and oos_main["avg_r"] > 0 and s_plain["all"]["avg_r"] is not None
                     and s_plain["all"]["avg_r"] > 0 and s_plain["all"]["n"] >= MIN_HOLDOUT_TRADES)
        print(f"\n[{rule}] {name}")
        print(f"   original coins OOS {fmt(oos_main)}")
        print(f"   held-out coins     all {fmt(s_plain['all'])}  in-sample {fmt(s_plain['ins'])}  out-of-sample {fmt(s_plain['oos'])}  (lower2SE {s_plain['all']['lower2se']})")
        print(f"   held-out +F        all {fmt(s_filt['all'])}")
        print(f"   verdict: {'PROMISING (needs a clean pre-registration + forward test)' if promising else 'NO EVIDENCE'}")


if __name__ == "__main__":
    a = sys.argv[1:]
    folder = a[0] if a and not a[0].startswith("--") else "data"
    if "--holdout" in a:
        stage2(folder, a[a.index("--holdout") + 1])
    else:
        stage1(folder)
