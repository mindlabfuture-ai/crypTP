"""E-book confirmed-entry backtest (docs/EBOOK_CONFIRMED_PREREG.md). Run from the repo root:
  PYTHONPATH=. python tools/run_confirmed.py [--gross]
Reads 15m CSVs (tools/pull_okx_15m.py) for the 15 verdict coins in data/ and data/holdout/. Runs 1h-M1, 1h-M2, 4h-M1, 4h-M2 (never best-of) and the
unconfirmed control C0 on each timeframe, judges each config against the pre-registered criteria and compares it with its control.
Writes data/confirmed_results.json (or ..._gross.json)."""
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

from cryptp.backtest import load_csv
from cryptp.confirmed import CParams, run_confirmed

CONFIGS = {"1h-M1": ("1h", "M1"), "1h-M2": ("1h", "M2"), "4h-M1": ("4h", "M1"), "4h-M2": ("4h", "M2"),
           "1h-C0": ("1h", "C0"), "4h-C0": ("4h", "C0")}
MIN_TRADES, SPLIT = 300, 0.70


def load_group(folder):
    return {p.name[:-8]: str(p) for p in sorted(Path(folder).glob("*_15m.csv")) if not p.name.startswith("BTC")}


def work(args):
    cfg, coin, path, gross = args
    tf, model = CONFIGS[cfg]
    df = load_csv(path)
    fee, slip = (0.0, 0.0) if gross else (0.00055, 2.0)
    res = run_confirmed(df, f"{coin}/USDT:USDT", CParams(tf=tf, model=model), fee_rate=fee, slippage_bps=slip)
    rows = [dict(coin=coin, side=t.side, entry_ts=t.entry_ts, r=t.r, stop_pct=abs(t.entry - t.stop) / t.entry * 100, bars=t.bars) for t in res.trades]
    return cfg, coin, rows, (df["ts"].iloc[0], df["ts"].iloc[-1])


def stats(r):
    r = np.asarray(r, float)
    if len(r) == 0:
        return dict(n=0, avg_r=None, se=None, lower2se=None, upper2se=None, win_pct=None)
    se = r.std(ddof=1) / np.sqrt(len(r)) if len(r) > 1 else float("nan")
    return dict(n=int(len(r)), avg_r=float(r.mean()), se=float(se), lower2se=float(r.mean() - 2 * se), upper2se=float(r.mean() + 2 * se), win_pct=float((r > 0).mean() * 100))


def fmt(s):
    return "n/a" if not s["n"] else f"{s['avg_r']:+.3f}R (n={s['n']}, win {s['win_pct']:.0f}%, lower2SE {s['lower2se']:+.3f})"


def main():
    gross = "--gross" in sys.argv[1:]
    coins = {**load_group("data"), **load_group("data/holdout")}
    print(f"{len(coins)} coins {sorted(coins)}  {'GROSS (no costs)' if gross else 'net of costs'}\n")
    out = {cfg: [] for cfg in CONFIGS}
    spans = {}
    with ProcessPoolExecutor() as ex:
        for cfg, coin, rows, span in ex.map(work, [(cfg, c, pth, gross) for cfg in CONFIGS for c, pth in coins.items()], chunksize=1):
            out[cfg] += rows
            spans[coin] = span
    t0, t1 = min(s[0] for s in spans.values()), max(s[1] for s in spans.values())
    cut = t0 + (t1 - t0) * SPLIT
    report = dict(gross=gross, cut=str(cut), configs={})
    for cfg in CONFIGS:
        d = pd.DataFrame(out[cfg])
        if d.empty:
            report["configs"][cfg] = dict(pooled=stats([]))
            continue
        ins, oos = d[d["entry_ts"] < cut], d[d["entry_ts"] >= cut]
        report["configs"][cfg] = dict(pooled=stats(d["r"]), in_sample=stats(ins["r"]), out_of_sample=stats(oos["r"]),
                                      longs=stats(d.loc[d["side"] == "buy", "r"]), shorts=stats(d.loc[d["side"] == "sell", "r"]),
                                      median_stop_pct=float(d["stop_pct"].median()), median_bars=float(d["bars"].median()),
                                      per_coin={c: stats(g["r"]) for c, g in d.groupby("coin")})
    for cfg, c in report["configs"].items():
        tf, model = CONFIGS[cfg]
        p, i, o = c["pooled"], c.get("in_sample"), c.get("out_of_sample")
        if model == "C0":
            c["verdict"] = "control"
        else:
            checks = {f"n >= {MIN_TRADES}": p["n"] >= MIN_TRADES, "pooled avg R > 0": bool(p["avg_r"] is not None and p["avg_r"] > 0),
                      "in-sample > 0": bool(i and i["avg_r"] is not None and i["avg_r"] > 0), "out-of-sample > 0": bool(o and o["avg_r"] is not None and o["avg_r"] > 0),
                      "avg R - 2SE > 0": bool(p["lower2se"] is not None and p["lower2se"] > 0)}
            c["checks"] = checks
            c["verdict"] = "INCONCLUSIVE (too few trades)" if p["n"] < MIN_TRADES else ("PASS" if all(checks.values()) else "FAIL")
            ctl = report["configs"][f"{tf}-C0"]["pooled"]
            c["adds_over_control"] = bool(p["avg_r"] is not None and ctl["upper2se"] is not None and p["avg_r"] > ctl["upper2se"])
        print(f"== {cfg}: {c['verdict']}")
        print("  pooled      ", fmt(p))
        if p["n"]:
            print("  in-sample   ", fmt(i))
            print("  out-of-samp ", fmt(o))
            print("  long | short", fmt(c["longs"]), "|", fmt(c["shorts"]))
            if model != "C0":
                print("  checks      ", {k: ("ok" if v else "NO") for k, v in c["checks"].items()})
                ctl = report["configs"][f"{tf}-C0"]["pooled"]
                print(f"  vs unconfirmed control {tf}-C0 ({ctl['avg_r']:+.3f}R, upper 2SE {ctl['upper2se']:+.3f}): confirmation {'ADDS' if c['adds_over_control'] else 'does not add'} value")
            print(f"  median stop {c['median_stop_pct']:.1f}%, median hold {c['median_bars']:.0f} bars")
            print("  per coin    ", {k: (round(v['avg_r'], 2), v['n']) for k, v in c["per_coin"].items() if v["n"]}, "\n")
    json.dump(report, open("data/confirmed_results_gross.json" if gross else "data/confirmed_results.json", "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
