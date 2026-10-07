# SMC + VWAP (order-block retest) on SEI — DRAFT pre-registration

Status: **DRAFT, awaiting approval. Nothing has been run for this rule set.** Rules freeze on approval.

## What changes from the ICT model, and what I must disclose
- Dropped: the liquidity-sweep requirement, the fair-value gap, and the session killzone (the ICT elements). Kept: the 4h structure bias, the
  daily-anchored VWAP discount/premium side, and your exits (3R minimum, lock, trail, midnight break-even).
- Added (SMC core): a **break of structure** followed by an **order-block retest**.
- **SEI is no longer fresh.** The previous run touched all of it, and its ablation table showed that removing the killzone raised the trade count
  from 58 to 179. That is part of why this design has no killzone; I cannot pretend I did not see it. To compensate: the evidence bar is stricter
  (Z = 3.0 instead of 2.5, 150 trades instead of 120), a SUI replication is required, and a mandatory paper-forward period follows any pass.
- All numbers below are conventions fixed before any run, none tuned on data. Prior expectation: low; this is the 10th rule set in the repo.

## Data
SEI 15m (KuCoin spot proxy, 2023-08-15 -> 2026-10-07, 110,323 bars) + KuCoin SEIUSDTM funding. Replication: SUI 15m. UB: report only
(10 bps slippage; thin venue; 391 days).

## Rules (long shown; short is the exact mirror, proven by a price-reflection unit test before the run). UTC, 15m bars.
1. **Structure.** Fractal swings 3/3 (usable 4 bars after they form). **Break of structure (BOS), long:** bar b closes above the most recent
   confirmed swing high H, the first break of that swing (each swing can be broken once), AND is an **impulse**: true range[b] >= 1.2 x ATR(14)[b]
   and close[b] in the top 25% of its range.
2. **Order block.** The most recent bearish candle (close < open) among bars b-10..b-1; zone = that candle's [low, high]; entry level
   CE = zone midpoint. None -> no trade.
3. **Order.** Limit buy at CE live for bars b+1..b+16 (fill if low <= CE at min(open, CE)); void if any bar closes below the OB low.
   Entry fees and slippage are charged as taker (conservative). A touched setup is consumed even if a filter then rejects it.
4. **Filters at the fill bar:**
   a. **VWAP discount:** CE <= the daily VWAP anchored at 00:00 UTC through the previous bar (typical price x volume), with >= 8 bars since the anchor.
      Short: CE >= VWAP (premium).
   b. **4h bias:** completed-4h structure trend (`cryptp.structure.analyze` 3/3) is not "down" (short: not "up").
5. **Stop:** OB low minus 0.1 x ATR(14) at bar b. Skip if the stop is < 0.45% or > 3.0% of the fill price.
6. **Exit** (every stop change effective on the NEXT bar): stop hit -> exit (gap-aware, 2 bps adverse slippage); **no profit-taking before +3R**; at
   +3R the stop locks +1.5R; then trails 3.0 x ATR(14) from the best extreme; at the close of each UTC day's last bar, if open and in profit, stop to
   break-even. No time cap.
7. **Risk:** $1,000, 1% per trade, 3x max leverage, one position, max 3 trades per UTC day, cooldown 8 bars.
8. **Costs:** 0.055% per side + 2 bps slippage; funding at the 00:00/08:00/16:00 UTC settlements (KuCoin proxy, 0.01% if none), reported separately.

## Pass criteria (decided before any result; ALL must hold; SEI full period, run once)
- >= 150 trades.
- Net avg R - **3.0** x SE > 0; net PF >= 1.15; gross-of-costs avg R > 0.
- Max drawdown < 25%.
- Net avg R > 0 in BOTH time halves.
- >= 60% of calendar months with >= 6 trades positive.
- Beats the random-entry 95th percentile (200 draws: random bars, side by the VWAP rule, 12-bar-extreme stop, same exits and count).
- SUI replication: >= 100 trades, net avg R > 0 and PF > 1.0.
- Prefix (causality) test and the mirror unit test pass.
Any miss -> FAIL, no retuning.

## Reported, not selecting
Ablations (one change each): no VWAP filter; no 4h bias; BOS without the impulse filter; OB entry at the zone edge instead of the midpoint;
long-only; short-only. Maker-entry sensitivity; fee multipliers 0.5x/1x/2x. Funnel counts (BOS events, impulses, OBs, orders, fills, each filter's
rejections), midnight break-even statistics, funding paid/received. UB as information only.

## After
- FAIL: stop mechanical entry searches on this history; build the paper-forward journal (you read the setups, the agent records and measures them).
- PASS: >= 60 days paper-forward on Bybit testnet before any live capital; live stays gated.

---
# RESULT (single run, rules unchanged from the draft above; approved before running)

Status: **FAIL** (8 of 10 criteria missed), and this time adequately powered. Run with `tools/run_smc.py`. Hand-built detection tests, the impulse test,
causality and the price-reflection mirror test passed before the run (148 tests); prefix test on the real data passed.

**Funnel (SEI, both sides):** 8,235 breaks of structure -> 3,459 impulses -> 3,455 order blocks/orders -> filters at the fill rejected 928 (VWAP side),
239 (4h bias), 423 (stop outside 0.45-3.0%) -> **170 trades** (86 long, 84 short) over three years.

| SEI | Trades | Win % | Avg R | SE | Avg R - 3 SE | PF | Net | Max DD |
|---|---|---|---|---|---|---|---|---|
| **Main (fees, slippage, funding)** | 170 | 24.1 | -0.341 | 0.146 | -0.779 | 0.57 | -45.7% | -47.5% |
| Gross (no costs, no funding) | 158 | 25.3 | -0.061 | 0.161 | -0.545 | 0.88 | -12.0% | -21.9% |

| Criterion | Result |
|---|---|
| >= 150 trades | pass (170) |
| Avg R - 3.0 SE > 0 | **FAIL** (-0.779) |
| PF >= 1.15 | **FAIL** (0.57) |
| Gross avg R > 0 | **FAIL** (-0.061) |
| Max DD < 25% | **FAIL** (-47.5%) |
| Net avg R > 0 in both halves | **FAIL** (H1 -0.396 on 114; H2 -0.229 on 56) |
| >= 60% of months (>= 6 trades) positive | **FAIL** (2 of 9) |
| Beats random-entry p95 | **FAIL** (-0.341 vs p95 +0.191; random median -0.142) |
| SUI replication (>= 100 trades, avg R > 0, PF > 1) | **FAIL** (227 trades, -0.065 R, PF 0.89) |
| Prefix test | pass |

Ablations (reported only): no VWAP 355 trades -0.258 R; no 4h bias 230 trades -0.323 R; no impulse filter 401 trades -0.364 R; OB-edge entry 356 trades
-0.350 R; long-only 87 trades -0.131 R; short-only 85 trades -0.430 R. Maker entry (0.02%) -0.286 R; fees x0.5/x1/x2: -0.254 / -0.341 / -0.515 R.
Exits: 167 stops, 3 break-even stops; 42 trades reached +3R (best +13.6 R). Median stop 0.60% of price; median hold ~6 bars (1.5 h).
SUI replication -0.065 R (227 trades); UB report-only: 120 trades -0.495 R (10 bps slippage, thin venue).

Reading:
- Before any costs the average trade loses (-0.06 R) over 158 trades: there is no gross edge to protect, and the pattern is worse than random entries
  with the same exit (random median -0.14 R, p95 +0.19 R; the model's -0.34 R is below the median).
- Costs then take ~0.28 R per trade, because the median stop is only 0.60% and the round trip is ~0.15%. Every ablation is negative; none of them
  contains a lead worth chasing.
- Both halves lose and both coins lose, so this is a clean negative, not an underpowered one.
- Per the pre-registration: no retuning, and no further mechanical entry searches on this history. Ten rule sets have now been tested with the same
  discipline, none with a net edge after costs.
