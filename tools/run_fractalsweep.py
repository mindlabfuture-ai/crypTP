"""Rownyel fractal stop-hunt backtest (docs/ROWNYEL_PREREG.md). Run from the repo root:
  PYTHONPATH=. python tools/run_fractalsweep.py [--gross] [--seeds 20]
Reads 15m CSVs (tools/pull_okx_15m.py): G1 = data/, G3 = data/holdout/ (verdict group, with G1), G2 = data/rownyel/ (his coins, reported apart).
Runs 1h-A, 1h-B, 4h-A, 4h-B (never best-of), judges G1+G3 pooled against the pre-registered criteria, and runs the random-entry control.
Writes data/rownyel_results.json."""
import json
import sys
import zlib
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

from cryptp.backtest import load_csv
from cryptp.fractalsweep import FSParams, run_fractalsweep

CONFIGS = {"1h-A": ("1h", None), "1h-B": ("1h", 1.0), "4h-A": ("4h", None), "4h-B": ("4h", 1.0)}
HOLD = {"1h": 480, "4h": 120}                    # 20 days either way
PER_BUCKET = {"1h": 4, "4h": 16}                 # 15m bars per bucket
MIN_TRADES, SPLIT = 300, 0.70


def load_group(folder):
    return {p.name[:-8]: str(p) for p in sorted(Path(folder).glob("*_15m.csv")) if not p.name.startswith("BTC")}


def resample(df, tf):
    d = df.set_index("ts")
    agg = d.resample(tf, label="left", closed="left").agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
    cnt = d["open"].resample(tf, label="left", closed="left").count()
    agg = agg[cnt == PER_BUCKET[tf]].dropna().reset_index()          # complete buckets only
    return agg


def work(args):
    cfg, coin, path, gross, control = args           # control: None or (seed, n_entries)
    tf, be = CONFIGS[cfg]
    df = resample(load_csv(path), tf)
    p = FSParams(be_at_r=be, max_hold=HOLD[tf])
    fee, slip = (0.0, 0.0) if gross else (0.00055, 2.0)
    entry_bars = None
    if control is not None:
        seed, n = control
        rng = np.random.default_rng([seed, zlib.crc32(coin.encode()), zlib.crc32(cfg.encode())])
        lo, hi = 40, len(df) - 2
        entry_bars = np.zeros(len(df), bool)
        entry_bars[rng.choice(np.arange(lo, hi), size=min(n, hi - lo), replace=False)] = True
    res = run_fractalsweep(df, f"{coin}/USDT:USDT", p, fee_rate=fee, slippage_bps=slip, entry_bars=entry_bars)
    rows = [dict(coin=coin, entry_ts=t.entry_ts, r=t.r, stop_pct=abs(t.entry - t.stop) / t.entry * 100, bars=t.bars) for t in res.trades]
    return cfg, coin, control, rows, (load_csv(path)["ts"].iloc[0], load_csv(path)["ts"].iloc[-1])


def stats(r):
    r = np.asarray(r, float)
    if len(r) == 0:
        return dict(n=0, avg_r=None, se=None, lower2se=None, win_pct=None)
    se = r.std(ddof=1) / np.sqrt(len(r)) if len(r) > 1 else float("nan")
    return dict(n=int(len(r)), avg_r=float(r.mean()), se=float(se), lower2se=float(r.mean() - 2 * se), win_pct=float((r > 0).mean() * 100))


def fmt(s):
    return "n/a" if not s["n"] else f"{s['avg_r']:+.3f}R (n={s['n']}, win {s['win_pct']:.0f}%, lower2SE {s['lower2se']:+.3f})"


def main():
    argv = sys.argv[1:]
    gross = "--gross" in argv
    n_seeds = int(argv[argv.index("--seeds") + 1]) if "--seeds" in argv else 20
    g1, g3, g2 = load_group("data"), load_group("data/holdout"), load_group("data/rownyel")
    verdict_coins = {**g1, **g3}
    groups = {c: "G1" for c in g1} | {c: "G3" for c in g3} | {c: "G2" for c in g2}
    allc = {**g1, **g3, **g2}
    print(f"G1 {sorted(g1)}\nG3 {sorted(g3)}\nG2 {sorted(g2)}  {'GROSS (no costs)' if gross else 'net of costs'}\n")

    jobs = [(cfg, c, pth, gross, None) for cfg in CONFIGS for c, pth in allc.items()]
    out = {cfg: [] for cfg in CONFIGS}
    spans = {}
    with ProcessPoolExecutor() as ex:
        for cfg, coin, _, rows, span in ex.map(work, jobs, chunksize=1):
            out[cfg] += [dict(r, group=groups[coin]) for r in rows]
            spans[coin] = span
    t0 = min(spans[c][0] for c in verdict_coins)
    t1 = max(spans[c][1] for c in verdict_coins)
    cut = t0 + (t1 - t0) * SPLIT

    report = dict(gross=gross, cut=str(cut), configs={})
    counts = {cfg: pd.DataFrame(rows).groupby("coin").size().to_dict() if rows else {} for cfg, rows in out.items()}
    # random-entry control on the verdict coins, same trade count per coin as the sweep
    ctl_jobs = [(cfg, c, pth, gross, (s, counts[cfg].get(c, 0))) for cfg in CONFIGS for s in range(1, n_seeds + 1)
                for c, pth in verdict_coins.items() if counts[cfg].get(c, 0) > 0]
    ctl = {cfg: {} for cfg in CONFIGS}
    with ProcessPoolExecutor() as ex:
        for cfg, coin, control, rows, _ in ex.map(work, ctl_jobs, chunksize=4):
            ctl[cfg].setdefault(control[0], []).extend(r["r"] for r in rows)
    for cfg in CONFIGS:
        d = pd.DataFrame(out[cfg])
        main_d = d[d["group"].isin(["G1", "G3"])] if len(d) else d
        his = d[d["group"] == "G2"] if len(d) else d
        ins, oos = (main_d[main_d["entry_ts"] < cut], main_d[main_d["entry_ts"] >= cut]) if len(d) else (d, d)
        p, i, o = stats(main_d["r"] if len(d) else []), stats(ins["r"] if len(d) else []), stats(oos["r"] if len(d) else [])
        checks = {f"n >= {MIN_TRADES}": p["n"] >= MIN_TRADES, "pooled avg R > 0": bool(p["avg_r"] is not None and p["avg_r"] > 0),
                  "in-sample > 0": bool(i["avg_r"] is not None and i["avg_r"] > 0), "out-of-sample > 0": bool(o["avg_r"] is not None and o["avg_r"] > 0),
                  "avg R - 2SE > 0": bool(p["lower2se"] is not None and p["lower2se"] > 0)}
        verdict = "INCONCLUSIVE (too few trades)" if p["n"] < MIN_TRADES else ("PASS" if all(checks.values()) else "FAIL")
        seeds = [np.mean(v) for v in ctl[cfg].values() if len(v)]
        ctl_stats = dict(mean=float(np.mean(seeds)), p5=float(np.percentile(seeds, 5)), p95=float(np.percentile(seeds, 95)), seeds=len(seeds)) if seeds else None
        beats = bool(ctl_stats and p["avg_r"] is not None and p["avg_r"] > ctl_stats["p95"])
        report["configs"][cfg] = dict(pooled=p, in_sample=i, out_of_sample=o, checks=checks, verdict=verdict, control=ctl_stats, beats_control_p95=beats,
                                      g2=stats(his["r"] if len(d) else []), median_stop_pct=float(main_d["stop_pct"].median()) if len(d) else None,
                                      per_coin={c: stats(g["r"]) for c, g in d.groupby("coin")} if len(d) else {})
        print(f"== {cfg}: {verdict}")
        print("  G1+G3 pooled ", fmt(p))
        print("  in-sample    ", fmt(i))
        print("  out-of-samp  ", fmt(o))
        print("  G2 (his coins)", fmt(report["configs"][cfg]["g2"]))
        print("  checks       ", {k: ("ok" if v else "NO") for k, v in checks.items()})
        if ctl_stats:
            print(f"  random-entry control: mean {ctl_stats['mean']:+.3f}R, 5-95% [{ctl_stats['p5']:+.3f}, {ctl_stats['p95']:+.3f}] over {ctl_stats['seeds']} seeds; "
                  f"sweep {'BEATS' if beats else 'does not beat'} the control's 95th percentile")
        print(f"  median stop {report['configs'][cfg]['median_stop_pct']:.1f}%")
        print("  per coin avg R", {c: (round(v['avg_r'], 2), v['n']) for c, v in report["configs"][cfg]["per_coin"].items() if v["n"]}, "\n")
    json.dump(report, open("data/rownyel_results_gross.json" if gross else "data/rownyel_results.json", "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
