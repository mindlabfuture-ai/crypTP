# 1h trend-continuation breakout on SUI, run-the-winner exit with midnight break-even — DRAFT pre-registration

Status: **DRAFT (revised: midnight forced flat replaced by a midnight break-even stop), awaiting approval. Nothing has been run for this rule set.** Rules freeze on approval.

## Why 1h and why this rule
- docs/BOUNCE_PREREG.md: on 15m, costs (~15 bps round trip) took ~0.22 R per trade at a 0.7% median stop. On 1h the stop is wider
  (~1.5-2%), so the same costs are ~0.08-0.10 R. A wider stop is the only lever on cost that does not require a new edge.
- The entry is a plain 24-bar (one day) channel breakout taken only in the daily LONG state. It was NOT designed or tuned on any data
  in this repository: every number below is a convention (24 bars = 1 day, ATR 14, 2 x ATR stop, 3R arm), set before any run.
- Disclosed: related ideas (1h structure/BOS, MACD+SMA200, SuperTrend, liquidity sweep) were already tested on this 1h data and failed;
  this is the 8th candidate on SUI and the data cannot be made unseen. That is why the bar is strict, there are two sanity controls, and
  a mandatory paper-forward period follows any pass.
- Prior expectation: low. A pass means "paper-forward", never "trade live".

## Rules (frozen on approval; long only; SUI 1h built by resampling the OKX 15m swap series, UTC)
1. **Daily state (closed daily candles only).** LONG if the last daily candle dated BEFORE the bar's UTC date closed above its SMA-200
   (same mapping as `cryptp/daily15m.daily_allowed`). Otherwise no trade.
2. **Signal (1h bar close).** close_t > highest high of the previous 24 bars (bar t excluded), and not true on bar t-1 (edge-triggered).
3. **Entry:** next bar's open + 2 bps slippage. No entries on bars opening at/after 20:00 UTC.
4. **Initial stop:** entry - 2.0 x ATR(14) at the signal bar. Skip if the stop is < 0.9% or > 5.0% of entry (the floor keeps costs <= ~0.17 R).
5. **Exit, each bar in this order:**
   a. stop hit -> exit at the stop (gap-aware, 2 bps adverse slippage);
   b. **no profit-taking before +3R.** When a bar's high reaches entry + 3R the stop is raised to entry + 1.5R, effective the NEXT bar;
   c. after that, at each bar close stop = max(stop, highest high since entry - 3.0 x ATR(14)), effective the next bar;
   d. **midnight break-even instead of a forced flat.** At the close of the last bar of each UTC day, if the trade is open and that close is
      above the entry price, the stop is raised to the entry price (break-even, not fee-adjusted), effective the next bar. If the close is at or
      below entry, the stop is left unchanged (a stop cannot be placed above the market). Stops never move down. There is no time exit and no
      cap on how long a trade is held; trades can run for days.
6. **Risk:** $1,000, 1% risk per trade, 3x max leverage, one position, max 2 trades per UTC day, cooldown 4 bars after an exit. A trade held across days keeps the only position slot, so signals during it are skipped.
7. **Costs:** 0.055% per side + 2 bps slippage per fill; funding at **all three** settlements (00:00, 08:00, 16:00 UTC) a trade is open through,
   so overnight holds pay or receive funding (KuCoin proxy `funding_SUI.csv`, 0.01% if none). A long pays when the rate is positive.
   Funding is reported separately, and the pass test is on net results after funding. A break-even stop exit still costs fees and slippage
   (about -0.1 R at a 1.5% stop).
8. Implementation reuses `cryptp/bounce.run_bounce` machinery with the entry/stop/exit parameters above; causality (prefix) test and a
   hand-built exit-mechanics test must pass before the run.

## Data and partitions
- SUI 1h, usable from the first date the daily SMA-200 exists (2023-11-21) to 2026-10-07. Nothing is held out for tuning because nothing is tuned.
- Stability halves (by time, equal bars): H1 and H2. Both are reported; both must pass the sign test below.
- **Replication on SOL** (same rules, same period, SOL's own daily state): not used for design; a pass criterion.
- **Run once.** Any rule change after seeing results voids this registration; a new one must be written first.

## Pass criteria (decided before any result; ALL must hold)
- >= 150 trades on SUI.
- Net avg R - 2.5 x SE(avg R) > 0.
- Net profit factor >= 1.15; gross-of-costs avg R > 0.
- Max drawdown < 25%.
- Net avg R > 0 in BOTH halves H1 and H2.
- Positive net R in at least 60% of calendar months having >= 8 trades.
- Beats the random-entry control at its 95th percentile (200 random entry sets, same count, same exit, same daily-state and cutoff rules).
- SOL replication: net avg R > 0 and profit factor > 1.0 with >= 100 trades.
Any miss -> FAIL, no retuning.

## Controls and secondary (reported, not selecting)
- **Cost sensitivity:** avg R at fees x 0.5, x 1, x 2 (shows whether the verdict hinges on cost assumptions).
- **Midnight-flat variant, labelled SECONDARY:** identical rules except rule 5d is a forced flat at the close of each UTC day (no overnight
  funding). It is reported only to show what the break-even rule changes; it **cannot rescue a primary FAIL** and is not part of pass/fail.
- **Midnight-BE statistics:** how many trades were moved to break-even at least once, how many of those were then stopped at break-even
  (each costing fees and slippage, about -0.1 R), how many went on to reach +3R, and total funding paid and received.
- Fixed +3R target without trail, same entries (what the run-the-winner exit adds).

## After
- FAIL: stop searching for SUI entry signals on this history; remaining supported tools are the daily SMA-200 state (spot), the dashboard
  and the safety checks. The honest next evidence is a paper-forward log of the agent as a discretionary assistant.
- PASS: Bybit-testnet/paper-forward >= 60 days with the same rules before any live capital; live stays gated.

---
# RESULT (single run, rules unchanged from the draft above; approved before running)

Status: **FAIL** (4 of 9 criteria missed). Run with `tools/run_hourly.py`. Engine hand-checked by unit tests before the run
(midnight break-even only when in profit, lock effective next bar, causal signals); prefix test passed.
SUI window 2023-11-21 -> 2026-10-07 (first bar with a daily SMA-200). 353 raw signals; 130 trades (143 signals arrived while a trade was
still open, because trades now run for days and hold the only position slot).

| SUI | Trades | Win % | Avg R | SE | Avg R - 2.5 SE | PF | Net | Max DD |
|---|---|---|---|---|---|---|---|---|
| **Main (fees, slippage, funding)** | 130 | 20.0 | -0.012 | 0.138 | -0.357 | 0.96 | -3.1% | -18.2% |
| Gross (no costs, no funding) | 130 | 20.0 | +0.053 | | | 1.08 | +5.5% | -15.2% |
| Control: fixed +3R, no trail | 135 | 20.0 | +0.031 | | | 1.03 | +2.7% | -16.7% |
| Secondary: midnight forced flat | 154 | 40.9 | -0.002 | | | 0.98 | -1.5% | -18.0% |

| Criterion | Result |
|---|---|
| >= 150 trades | **FAIL** (130) |
| Avg R - 2.5 SE > 0 | **FAIL** (-0.357) |
| PF >= 1.15 | **FAIL** (0.96) |
| Gross avg R > 0 | pass (+0.053, within noise) |
| Max DD < 25% | pass (-18.2%) |
| Net avg R > 0 in both halves | **FAIL** (H1 +0.084 on 81 trades; H2 -0.172 on 49) |
| >= 60% of months (>= 8 trades) positive | **FAIL** (3 of 7) |
| Beats random-entry p95 | pass, barely (-0.012 vs p95 -0.016; random median -0.173) |
| SOL replication (n >= 100, avg R > 0, PF > 1) | pass, barely (213 trades, +0.019 R, PF 1.01; H1 +0.097, H2 -0.157) |

Cost sensitivity (SUI avg R): fees x0.5 +0.006, x1 -0.012, x2 -0.050.

Exit anatomy (SUI): 26 trades reached +3R (best +6.8 R); 50 trades were moved to break-even at midnight and 37 of those (74%) were stopped
at break-even (each ~-0.1 R after fees); exits: 93 stops, 37 break-even stops, none by time. Funding: paid $25.23, received $2.06 over
the 3-year run (median hold ~19 h, median stop 3.3% of price, wider than the ~1.6% assumed in the draft). The forced-flat variant cut
28 trades that were above +1 R.

Reading:
- A genuine near-zero result, not a clean failure: gross +0.05 R, net -0.01 R on SUI and +0.02 R on SOL, both beating random entries
  only marginally. Costs and funding consume exactly the small edge there is, and the effect is not statistically distinguishable from zero.
- Second-half performance is negative on both coins (SUI -0.17 R, SOL -0.16 R), so whatever small edge existed in 2023-2024 is not present
  in 2025-26. This is the same pattern as every earlier test.
- Run-the-winner plus the midnight break-even did NOT beat the plain fixed +3R target (-0.012 vs +0.031): the break-even stops (74% of those
  moved) and funding cost more than the occasional big winner added.
- Per the pre-registration: no retuning; the secondary variant cannot rescue the failure.
