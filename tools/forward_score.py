"""Score the forward-test log against live OKX 15m candles (docs/MB_FORWARD_PREREG.md).
usage: PYTHONPATH=. python tools/forward_score.py [docs/mb_forward_log.csv] [--out data/forward_scored.csv]
Only rows with kind == setup are scored; result_only and unscoreable rows are tallied (the selection-bias count).
Only CLOSED bars are used. Public endpoints only, no keys."""
import sys
import time
from pathlib import Path

import pandas as pd
import requests

from cryptp.forward import Setup, VALID, score_setup, summarize

MIN_VALID, MAX_WEEKS, MIN_MEAN_R = 30, 12, 0.2


def utc(x) -> pd.Timestamp:
    t = pd.Timestamp(x)
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


def fetch(inst: str, since: pd.Timestamp) -> pd.DataFrame:
    rows, after = [], None
    while True:
        p = {"instId": inst, "bar": "15m", "limit": 100}
        if after:
            p["after"] = after
        for attempt in range(6):
            try:
                j = requests.get("https://www.okx.com/api/v5/market/history-candles", params=p, timeout=20).json()
                if j.get("code") == "0":
                    break
            except Exception:
                pass
            time.sleep(1 + attempt)
        else:
            sys.exit(f"could not fetch {inst} from OKX")
        d = j["data"]
        if not d:
            break
        rows += [r for r in d if r[8] == "1"]                    # closed bars only
        after = d[-1][0]
        if pd.Timestamp(int(after), unit="ms", tz="UTC") <= since:
            break
        time.sleep(0.25)
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "v", "a", "b", "c"])[["ts", "open", "high", "low", "close"]]
    df = df.astype(float).drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    return df


def main():
    argv = sys.argv[1:]
    out_path = argv[argv.index("--out") + 1] if "--out" in argv else "data/forward_scored.csv"
    pos = [a for i, a in enumerate(argv) if not a.startswith("--") and (i == 0 or argv[i - 1] != "--out")]
    log_path = pos[0] if pos else "docs/mb_forward_log.csv"
    log = pd.read_csv(log_path)
    tally = log["kind"].value_counts().to_dict() if len(log) else {}
    setups = log[log["kind"] == "setup"]
    print(f"log: {len(log)} rows {tally}")
    if setups.empty:
        print("no scoreable setups logged yet")
        return
    rows, cache = [], {}
    for _, r in setups.iterrows():
        s = Setup(id=str(r["id"]), symbol=r["symbol"], side=r["side"], logged_at=utc(r["logged_at_utc"]),
                  stop=float(r["his_stop"]), target=float(r["his_target"]),
                  his_entry=None if pd.isna(r["his_entry"]) else float(r["his_entry"]),
                  horizon_hours=48.0 if pd.isna(r["horizon_hours"]) else float(r["horizon_hours"]))
        if s.symbol not in cache:
            cache[s.symbol] = fetch(s.symbol, setups[setups["symbol"] == s.symbol]["logged_at_utc"].map(utc).min() - pd.Timedelta(minutes=30))
        rows.append(score_setup(cache[s.symbol], s))
    res = pd.DataFrame(rows)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    res.to_csv(out_path, index=False)
    show = res[["id", "symbol", "side", "status", "fill", "exit", "r_net", "planned_rr", "note"]].copy()
    show["r_net"] = show["r_net"].map(lambda x: "" if pd.isna(x) else f"{x:+.2f}")
    show["planned_rr"] = show["planned_rr"].map(lambda x: "" if pd.isna(x) else f"{x:.1f}")
    print(show.to_string(index=False))
    s = summarize(rows)
    print(f"\nscored {s['scored']} (valid {s['valid']}, missed {s['missed']}, open {s['open']}, pending {s['pending']})")
    if s["valid"]:
        print(f"realized: mean {s['mean_r']:+.2f}R, win {s['win_pct']:.0f}%, 90% CI [{s['ci90_low']:+.2f}, {s['ci90_high']:+.2f}]")
    weeks = (pd.Timestamp.now("UTC") - setups["logged_at_utc"].map(utc).min()).days / 7
    done = s["valid"] >= MIN_VALID or weeks >= MAX_WEEKS
    if not done:
        print(f"verdict: NOT YET (valid {s['valid']}/{MIN_VALID}, {weeks:.1f}/{MAX_WEEKS} weeks)")
        return
    if s["missed_rate"] is not None and s["missed_rate"] > 0.5:
        print("verdict: NOT FOLLOWABLE (more than half the setups were already past their target or stop when a follower could act)")
    elif s["valid"] >= MIN_VALID and s.get("ci90_low", -1) > 0 and s["mean_r"] >= MIN_MEAN_R:
        print("verdict: EVIDENCE OF A FOLLOWABLE EDGE (still one author, one regime; see the protocol caveats)")
    else:
        print("verdict: NO EVIDENCE" + ("" if s["valid"] >= MIN_VALID else f" (only {s['valid']} valid setups after {weeks:.0f} weeks)"))


if __name__ == "__main__":
    main()
