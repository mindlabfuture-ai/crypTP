# ICT + SMC + VWAP model on SEI (UB reported only) — DRAFT pre-registration

Status: **DRAFT, awaiting approval. Nothing has been run for this rule set.** Rules freeze on approval.

## What this tests, and its limits
ICT/SMC are discretionary frameworks. This is ONE mechanical encoding of their common core (liquidity sweep -> market-structure shift ->
fair-value-gap retrace, in a session, on the right side of VWAP). A FAIL says this encoding does not work on this data, not that the
frameworks cannot work for a human reading context. Every number is a convention fixed BEFORE any run; none was tuned on data.

## Data
- **SEI**: KuCoin spot 15m, 2023-08-15 -> 2026-10-07 (110,323 bars) + daily candles + KuCoin SEIUSDTM funding. Never used in this repo before this
  assessment: genuinely fresh data. Spot is a price proxy for the perp.
- **UB**: KuCoin spot 15m, 2025-09-12 -> 2026-10-07 (37,470 bars). **Report-only** (391 days, one regime, KuCoin book far thinner than the real market;
  see docs/SEI_UB_ASSESSMENT.md). It has no pass/fail role. Slippage 10 bps per fill instead of 2.
- **SUI** (15m + daily + funding already on disk): replication coin, contaminated by earlier tests, so used only as a sanity replication.

## Rules (long shown; short is the exact mirror, proven by a price-reflection unit test before the run)
Time is UTC. 15m bars. Fractal swings left = right = 3 (a swing is usable only 3 bars after it forms).
1. **Sweep.** Bar s sweeps sell-side liquidity: low[s] < L and close[s] > L, where L is the most recent CONFIRMED swing low (swing bar <= s-4).
   Each swing low can be swept once.
2. **Market-structure shift (displacement).** Within bars s+1..s+6 the first bar m with close[m] > highest high of the 5 bars before s. If any
   bar in s..m closes below L, the setup is void.
3. **Fair value gap.** Among bars s..m find the most recent bullish gap: bar k (s+2 <= k <= m) with low[k] > high[k-2]. Zone = [high[k-2], low[k]],
   entry level CE = zone midpoint. No gap -> no trade.
4. **Entry.** Limit buy at CE, valid for bars m+1..m+12. A bar j fills if low[j] <= CE; fill price min(open[j], CE). The setup is void if any bar in
   m+1..j-1 closes below L. Entry fees and slippage are charged as TAKER (conservative; a maker fill would be cheaper, shown as a sensitivity).
5. **Filters at the fill bar j:**
   a. **Killzone:** bar j opens in 07:00-10:00 or 12:00-15:00 UTC (London and New York opens, fixed UTC, no daylight-saving adjustment).
   b. **VWAP discount:** CE <= the daily VWAP anchored at 00:00 UTC, computed with typical price (h+l+c)/3 x volume through bar j-1, and at least
      8 bars since the anchor. (Short: CE >= VWAP, "premium".)
   c. **4h bias:** structure trend on completed 4h candles (`cryptp.structure.analyze`, 3/3) is not "down" (short: not "up").
6. **Stop:** lowest low of bars s..m minus 0.1 x ATR(14) at bar m. Skip if the stop is < 0.45% or > 3.0% of the fill price.
7. **Exit (your rules; every stop change takes effect on the NEXT bar):**
   a. stop hit -> exit at the stop (gap-aware, 2 bps adverse slippage);
   b. **no profit-taking before +3R.** When a bar's high reaches entry + 3R, raise the stop to entry + 1.5R;
   c. after that trail: stop = max(stop, highest high since entry - 3.0 x ATR(14));
   d. at the close of the last bar of each UTC day, if the trade is open and in profit (close > entry), raise the stop to break-even (the entry price).
   No time cap: trades can run for days.
8. **Risk:** $1,000, 1% risk per trade, 3x max leverage, one position, max 3 trades per UTC day, cooldown 8 bars after an exit.
9. **Costs:** 0.055% per side + 2 bps slippage (SEI, SUI; UB 10 bps). Funding at the 00:00/08:00/16:00 UTC settlements a trade is open
   through (KuCoin proxy, 0.01% if none), reported separately. A long pays when the rate is positive; a short receives it.

## Pass criteria (decided before any result; ALL must hold; SEI full period, run once)
- >= 120 trades.
- Net avg R - 2.5 x SE(avg R) > 0; net PF >= 1.15; gross-of-costs avg R > 0.
- Max drawdown < 25%.
- Net avg R > 0 in BOTH time halves.
- Positive net R in at least 60% of calendar months having >= 6 trades.
- Beats the random-entry control's 95th percentile (200 draws): random entries inside the same killzones, side chosen by the same VWAP rule
  (long below VWAP, short above), same stop construction (12-bar extreme -/+ 0.1 ATR, same size limits), same exits and count. This isolates
  whether the sweep + shift + FVG + 4h-bias pattern adds anything beyond "session + VWAP side".
- SUI replication with the same rules: >= 100 trades, net avg R > 0 and PF > 1.0.
- Prefix (causality) test and the mirror unit test pass.
Any miss -> FAIL, no retuning; this is the 9th rule set tried in this repo and the criteria reflect that.

## Reported, not selecting
- Ablations (one change each): no VWAP filter; no killzone filter; no 4h bias; no FVG (enter at the next open after the shift); long-only; short-only.
- Maker-entry sensitivity (entry fee 0.02%); fee multipliers 0.5x/1x/2x.
- Trades moved to break-even at midnight, how many stopped at break-even, trades that reached +3R, funding paid/received, setups seen per step
  (sweeps, shifts, gaps, fills, filtered by each rule) so a thin sample is explained.
- UB: all of the above, as information only.

## After
- FAIL: stop searching for entry signals on this history; next evidence is a paper-forward journal (agent as discretionary assistant).
- PASS: >= 60 days of paper-forward on Bybit testnet before any live capital; live stays gated; UB would still need its own liquidity check.

---
# RESULT (single run, rules unchanged from the draft above; approved before running)

Status: **FAIL** (6 of 10 criteria missed). Run with `tools/run_ict.py`. Hand-built detection, limit-fill, lock and break-even tests and the
price-reflection mirror test passed before the run (144 tests). Prefix (causality) test passed. SEI window 2023-08-15 -> 2026-10-07 (110,323 bars).
One interpretation fixed during the build (not tuned): a setup whose limit price is touched is consumed even if a filter then rejects it.

**Funnel (SEI, both sides):** sweeps 3,789 long / 3,577 short -> shifts 969 / 928 -> setups with a fair-value gap 394 / 429 -> 823 limit orders.
Filters at the fill bar rejected 366 (killzone), 51 (VWAP side), 15 (4h bias), 7 (stop size) -> **58 trades** (27 long, 31 short) in three years.

| SEI | Trades | Win % | Avg R | SE | Avg R - 2.5 SE | PF | Net | Max DD |
|---|---|---|---|---|---|---|---|---|
| **Main (fees, slippage, funding)** | 58 | 22.4 | -0.187 | 0.256 | -0.825 | 0.76 | -11.2% | -17.8% |
| Gross (no costs, no funding) | 56 | 25.0 | +0.038 | 0.271 | -0.639 | 1.03 | +1.1% | -10.2% |

| Criterion | Result |
|---|---|
| >= 120 trades | **FAIL** (58) |
| Avg R - 2.5 SE > 0 | **FAIL** (-0.825) |
| PF >= 1.15 | **FAIL** (0.76) |
| Gross avg R > 0 | pass (+0.038, indistinguishable from zero) |
| Max DD < 25% | pass (-17.8%) |
| Both halves net avg R > 0 | **FAIL** (H1 -0.364 on 31 trades; H2 +0.017 on 27) |
| >= 60% of months with >= 6 trades positive | **FAIL** (0 of 1 qualifying month) |
| Beats random-entry p95 | **FAIL** (-0.187 vs p95 +0.409; random median -0.205) |
| SUI replication (>= 100 trades, avg R > 0, PF > 1) | **FAIL** (60 trades, -0.325 R, PF 0.61) |
| Prefix test | pass |

Ablations (one change each, reported only): no VWAP filter 91 trades -0.180 R; no killzone 179 trades -0.038 R; no 4h bias 71 trades -0.166 R;
no FVG (enter at next open after the shift) 104 trades +0.104 R but SE 0.33 and one +29.5 R outlier; long-only 27 trades +0.003 R;
short-only 31 trades -0.352 R. Maker-entry fee (0.02%) -0.142 R; fee multipliers 0.5x/1x/2x: -0.117 / -0.187 / -0.325 R.
Exits: 57 stops and 1 break-even stop; 14 trades reached +3R (best +7.2 R). Funding paid $2.86, received $1.48.
UB (report only, 10 bps slippage): 8 trades, -0.64 R. Not a result: too few trades and the venue is too thin.

Reading:
- The model is mostly a filter that almost never trades: 823 well-formed ICT setups become 58 trades once the killzone (366 rejected) and VWAP side
  are required. At 58 trades the standard error on average R is 0.26, so neither an edge nor its absence can be shown; the criteria fail on
  trade count, a negative point estimate (-0.19 R) and the SUI replication, all in the same direction.
- Gross edge is +0.04 R, i.e. nothing, before 0.15% of costs on a 0.79% median stop (about 0.19 R).
- The random-entry p95 (+0.41 R) is wide because 58 random trades with 3R+ runners are very noisy; the main result is below the random median too.
- None of the ablations is both large and credible: the only positive one (no FVG, +0.10 R) rests on one +29.5 R trade and a standard error three
  times its value. Reporting it as a lead would be exactly the kind of after-the-fact search this process exists to prevent.
- Per the pre-registration: no retuning. The honest next evidence is a paper-forward journal, where you (or the agent as assistant) take ICT setups with
  full context and we measure them out of sample.
