"""Volume-profile fade backtest (docs/MB_FADE_PREREG.md, addendum 2026-10-07).
usage: PYTHONPATH=. python tools/run_vpfade.py [DATA_DIR] [--coins DOGE,LINK,...] [--gross]
DATA_DIR holds <COIN>_15m.csv from tools/pull_okx_15m.py, including BTC_15m.csv (filter input only).
Runs A, A+F, B, B+F (never best-of), pools the coins, and judges each against the pre-registered criteria.
Writes DATA_DIR/vpfade_results.json and DATA_DIR/vpfade_<config>.trades.csv."""
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

from cryptp.backtest import load_csv
from cryptp.vpfade import VPParams, run_vpfade

CONFIGS = {"A": ("fade", False), "A+F": ("fade", True), "B": ("discount", False), "B+F": ("discount", True)}
MIN_TRADES, SPLIT = 300, 0.70


def one(args):
    cfg, coin, folder, gross = args
    mode, macro = CONFIGS[cfg]
    df = load_csv(str(Path(folder) / f"{coin}_15m.csv"))
    btc = None
    if macro:
        b = load_csv(str(Path(folder) / "BTC_15m.csv")).set_index("ts")["close"]
        btc = b.reindex(df["ts"]).ffill().to_numpy()
    fee, slip = (0.0, 0.0) if gross else (0.00055, 2.0)
    res = run_vpfade(df, f"{coin}/USDT:USDT", VPParams(mode=mode, macro=macro), fee_rate=fee, slippage_bps=slip, btc_close=btc)
    rows = [dict(cfg=cfg, coin=coin, side=t.side, entry_ts=t.entry_ts, exit_ts=t.exit_ts, entry=t.entry, stop=t.stop,
                 stop_pct=abs(t.entry - t.stop) / t.entry * 100, bars=t.bars, r=t.r, pnl=t.pnl) for t in res.trades]
    return cfg, coin, rows, (df["ts"].iloc[0], df["ts"].iloc[-1], len(df))


def stats(r):
    r = np.asarray(r, float)
    if len(r) == 0:
        return dict(n=0, avg_r=None, se=None, lower2se=None, win_pct=None)
    se = r.std(ddof=1) / np.sqrt(len(r)) if len(r) > 1 else float("nan")
    return dict(n=int(len(r)), avg_r=float(r.mean()), se=float(se), lower2se=float(r.mean() - 2 * se),
                win_pct=float((r > 0).mean() * 100))


def main():
    argv = sys.argv[1:]
    gross = "--gross" in argv
    coins_arg = argv[argv.index("--coins") + 1].split(",") if "--coins" in argv else None
    pos_args = [a for i, a in enumerate(argv) if not a.startswith("--") and (i == 0 or argv[i - 1] != "--coins")]
    folder = pos_args[0] if pos_args else "data"
    have = sorted(p.name[:-8] for p in Path(folder).glob("*_15m.csv"))
    coins = [c for c in (coins_arg or have) if c != "BTC" and c in have]
    if not coins or "BTC" not in have:
        sys.exit(f"need BTC_15m.csv and at least one coin in {folder} (found {have})")
    jobs = [(cfg, c, folder, gross) for cfg in CONFIGS for c in coins]
    out: dict[str, list] = {cfg: [] for cfg in CONFIGS}
    spans = {}
    with ProcessPoolExecutor(max_workers=min(len(jobs), os.cpu_count() or 2)) as ex:
        for cfg, coin, rows, span in ex.map(one, jobs):
            out[cfg] += rows
            spans[coin] = span
    t0 = min(s[0] for s in spans.values())
    t1 = max(s[1] for s in spans.values())
    cut = t0 + (t1 - t0) * SPLIT                                    # common calendar cut across all coins
    report = dict(coins=coins, gross=gross, start=str(t0), end=str(t1), cut=str(cut), bars={c: s[2] for c, s in spans.items()}, configs={})
    for cfg, rows in out.items():
        d = pd.DataFrame(rows)
        if d.empty:
            report["configs"][cfg] = dict(pooled=stats([]))
            continue
        d.to_csv(Path(folder) / f"vpfade_{cfg}.trades.csv", index=False)
        ins, oos = d[d["entry_ts"] < cut], d[d["entry_ts"] >= cut]
        report["configs"][cfg] = dict(
            pooled=stats(d["r"]), in_sample=stats(ins["r"]), out_of_sample=stats(oos["r"]),
            longs=stats(d.loc[d["side"] == "buy", "r"]), shorts=stats(d.loc[d["side"] == "sell", "r"]),
            median_stop_pct=float(d["stop_pct"].median()), median_bars=float(d["bars"].median()),
            per_coin={c: stats(g["r"]) for c, g in d.groupby("coin")},
        )
    for cfg, c in report["configs"].items():
        p, i, o = c["pooled"], c.get("in_sample"), c.get("out_of_sample")
        checks = {
            f"n >= {MIN_TRADES}": p["n"] >= MIN_TRADES,
            "pooled avg R > 0": bool(p["avg_r"] is not None and p["avg_r"] > 0),
            "in-sample avg R > 0": bool(i and i["avg_r"] is not None and i["avg_r"] > 0),
            "out-of-sample avg R > 0": bool(o and o["avg_r"] is not None and o["avg_r"] > 0),
        }
        if cfg.endswith("+F"):
            twin = report["configs"][cfg[:-2]].get("out_of_sample", {}).get("avg_r")
            checks["filter beats unfiltered OOS"] = bool(o and o["avg_r"] is not None and twin is not None and o["avg_r"] > twin)
        c["checks"] = checks
        c["verdict"] = ("INCONCLUSIVE (too few trades)" if p["n"] < MIN_TRADES else ("PASS" if all(checks.values()) else "FAIL"))
    json.dump(report, open(Path(folder) / "vpfade_results.json", "w"), indent=1, default=str)

    def fmt(s):
        return "n/a" if not s["n"] else f"{s['avg_r']:+.3f}R (n={s['n']}, win {s['win_pct']:.0f}%, lower2SE {s['lower2se']:+.3f})"
    print(f"coins {coins}  {report['start'][:10]} -> {report['end'][:10]}  cut {report['cut'][:10]}  {'GROSS (no costs)' if gross else 'net of costs'}")
    for cfg, c in report["configs"].items():
        print(f"\n== {cfg}: {c['verdict']}")
        print("  pooled      ", fmt(c["pooled"]))
        if c["pooled"]["n"]:
            print("  in-sample   ", fmt(c["in_sample"]))
            print("  out-of-samp ", fmt(c["out_of_sample"]))
            print("  longs/shorts", fmt(c["longs"]), "|", fmt(c["shorts"]))
            print(f"  median stop {c['median_stop_pct']:.2f}%  median hold {c['median_bars']:.0f} bars")
            print("  checks      ", {k: ("ok" if v else "NO") for k, v in c["checks"].items()})
            print("  per coin    ", {k: (round(v["avg_r"], 2), v["n"]) for k, v in c["per_coin"].items()})


if __name__ == "__main__":
    main()
