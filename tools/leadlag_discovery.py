"""SOL -> SUI lead-lag DISCOVERY on the first 50% of history only (the rest is never read).
usage: PYTHONPATH=. python tools/leadlag_discovery.py SUI_15m.csv SOL_15m.csv"""
import sys
import numpy as np
import pandas as pd
from cryptp.backtest import load_csv

sui, sol = load_csv(sys.argv[1]), load_csv(sys.argv[2])
m = sui[["ts", "close"]].merge(sol[["ts", "close"]], on="ts", suffixes=("_sui", "_sol")).sort_values("ts").reset_index(drop=True)
cut = len(m) // 2
m = m.iloc[:cut]                                   # DISCOVERY WINDOW ONLY
print(f"discovery window {m['ts'].iloc[0]} -> {m['ts'].iloc[-1]}  bars {len(m)}")
r = np.log(m[["close_sui", "close_sol"]]).diff().dropna()
rs, ro = r["close_sui"], r["close_sol"]
print("\ncontemporaneous corr (15m returns): %.3f" % rs.corr(ro))
print("\ncorr(SUI ret at t, SOL ret at t-k)   [k>0: SOL leads]")
for k in range(-3, 6):
    print(f"  k={k:+d}  {rs.corr(ro.shift(k)):+.4f}")
# does a SOL move that SUI has NOT yet followed predict SUI's next bars?  gap = SOL 4-bar return - beta * SUI 4-bar return
beta = np.cov(rs, ro)[0, 1] / ro.var()
print("\nbeta of SUI on SOL: %.2f" % beta)
for w in (1, 2, 4, 8):
    gap = (ro.rolling(w).sum() * beta - rs.rolling(w).sum())          # >0: SUI lagged a SOL up-move
    fwd = {h: rs.rolling(h).sum().shift(-h) for h in (1, 2, 4, 8)}
    q = gap.quantile([0.05, 0.95]).to_numpy()
    print(f"\nlookback {w} bars: gap std {gap.std() * 100:.3f}%   (fwd SUI return in bps by horizon)")
    for name, sel in (("gap top 5% (SUI lagged UP)", gap >= q[1]), ("gap bottom 5% (SUI lagged DOWN)", gap <= q[0]), ("all bars", gap.notna())):
        row = "  ".join(f"h{h}: {fwd[h][sel].mean() * 1e4:+6.1f}" for h in fwd)
        print(f"  {name:<32} n={int(sel.sum()):>5}  {row}")

# CONTROL: is it SOL, or just SUI bouncing after its own drops?  (still the discovery window only)
print("\n--- control: forward 4-bar SUI return (bps) regressed on SUI's own past 4-bar return and SOL's past 4-bar return ---")
w, h = 4, 4
X = pd.DataFrame({"sui": rs.rolling(w).sum(), "sol": ro.rolling(w).sum()})
y = rs.rolling(h).sum().shift(-h)
d = pd.concat([X, y.rename("y")], axis=1).dropna().iloc[::h]            # non-overlapping rows so t-stats are honest
A = np.c_[np.ones(len(d)), d["sui"], d["sol"]]
coef, *_ = np.linalg.lstsq(A, d["y"].to_numpy(), rcond=None)
res = d["y"].to_numpy() - A @ coef
se = np.sqrt(np.diag(np.linalg.inv(A.T @ A)) * res.var(ddof=3))
for n_, c_, s_ in zip(("const", "SUI own past", "SOL past"), coef, se):
    print(f"  {n_:<13} coef {c_:+.4f}   t = {c_ / s_:+.2f}")
print(f"  n = {len(d)} non-overlapping rows")
q = rs.rolling(w).sum().quantile(0.05)
sel = (rs.rolling(w).sum() <= q)
print(f"SUI-only control, own worst 5% 4-bar drops: n={int(sel.sum())}  fwd4 = {y[sel].mean() * 1e4:+.1f} bps  (all bars {y.mean() * 1e4:+.1f})")
