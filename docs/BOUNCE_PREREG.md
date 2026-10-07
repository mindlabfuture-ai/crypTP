# SUI own-drop bounce, run-the-winner exit — DRAFT pre-registration

Status: **DRAFT, awaiting approval. Nothing has been run on the validation or holdout data.** Rules freeze on approval.

## Origin and honesty about it
- docs/LEADLAG_DISCOVERY.md found, on the DISCOVERY half only (2023-05-06 -> 2025-01-20), that SOL does not lead SUI, and that SUI's own
  worst 5% 4-bar (1h) drops were followed by ~+16 bps over the next hour (all bars +0.8 bps). That is about the size of a 15 bps round trip.
  The 5% cut and the 4-bar window were chosen by looking at that half.
- This test asks whether a different EXIT (no profit-taking before +3R, then a trailing stop) can turn a break-even bounce into a net
  edge. The exit is a hypothesis, not a finding.
- Prior strategies (structure, squeeze, pullback, shorts) were run on the full SUI history, so the validation and holdout windows are not
  pristine for SUI generally. They ARE unused for designing THIS signal. This is the 7th candidate on this data, hence the strict bar.
- Prior expectation: low. A bounce roughly equal to costs rarely survives costs; the test exists so the question is closed with data.

## Data segments (SUI 15m, OKX swap; merged series of 119,994 bars)
- Discovery: 2023-05-06 -> 2025-01-20 15:45 UTC. Read for design only. Not used for pass/fail.
- **Validation: 2025-01-20 15:45 -> 2025-11-29 03:15 UTC.** One run.
- **Final holdout: 2025-11-29 03:15 -> 2026-10-07.** Run only if validation passes, with identical rules.
Indicator warm-up (rolling quantile, ATR) may read earlier bars; trades are only counted inside the segment.

## Rules (frozen on approval; long only, since the short mirror was not examined in discovery)
1. **Signal (bar close).** r4 = log(close_t / close_{t-4}). Threshold_t = the 5th percentile of r4 over the previous 2,880 bars
   (30 days), excluding bar t. Signal when r4 <= Threshold_t and it was not true on bar t-1 (edge-triggered).
2. **Entry:** next bar's open + 2 bps slippage. No entries on bars opening at/after 20:00 UTC.
3. **Initial stop:** lowest low of the last 4 bars minus 0.1 x ATR(14). Skip if stop distance < 0.45% or > 3.0% of entry.
4. **Exit, in this order each bar:**
   a. stop hit -> exit at the stop (gap-aware: at the open if it opens through), 2 bps adverse slippage;
   b. **no profit-taking before +3R.** Once a bar's high reaches entry + 3 x R, the stop is raised to entry + 1.5 x R, effective the NEXT bar;
   c. from then on at each bar close the stop = max(current stop, highest high since entry - 2.5 x ATR(14)), effective the NEXT bar;
   d. forced flat at the close of the last bar of the UTC day (minus 2 bps slippage). No cap on the winner otherwise.
5. **Risk and sizing:** $1,000 start, 1% of equity risked per trade, max leverage 3x, one position, max 3 trades per UTC day, cooldown
   8 bars after an exit.
6. **Costs:** 0.055% per side + 2 bps slippage per fill. **Funding:** at the 08:00 and 16:00 UTC settlements a trade is open through
   (00:00 is avoided by the forced flat), charge notional x rate, using the latest rate in `funding_SUI.csv` (KuCoin proxy) at or before that
   time, or 0.01% if none. A long pays when the rate is positive. Funding is reported as its own line.
7. Causality: signal uses bars <= t only; fills at t+1; the prefix test must pass.

## Pass criteria (decided before seeing results; ALL must hold on the validation segment)
- >= 100 trades.
- Net avg R - 2.5 x SE(avg R) > 0.
- Net profit factor >= 1.15.
- Gross-of-costs avg R > 0 (the edge exists before costs), and net avg R > 0.
- Max drawdown < 25%.
- Positive net R in at least 60% of calendar months having >= 10 trades.
- Beats the random-entry control (below) at the 95th percentile of its avg R.
Any miss -> FAIL; no retuning on validation or holdout. A validation PASS is not a pass: it only releases the holdout run.
Final: holdout must meet the same criteria; a PASS then means "paper-forward at least 60 days", never live capital.

## Controls (reported; the random-entry one is also a criterion)
- **Random-entry control:** same exit, sizing, costs, one-position and 3-per-day limits, but entries at 200 random times drawn from
  the same hours, with the same number of attempts. Report the 200 avg-R values; the bounce must beat their 95th percentile.
- **Exit isolation:** the same entries with a fixed 1:3 target and the same initial stop (no trail), to show what the run-the-winner exit adds.
- **Truncation count:** how many trades were cut by the 00:00 flat while still above +1R (the cost of the midnight rule).
- Exact-signal unit test and prefix causality test before the run.

## What happens after
- FAIL: stop searching for SUI entry signals on this data; keep the daily SMA-200 state (spot risk management), the dashboard and the safety checks.
- PASS (validation then holdout): paper-forward on Bybit testnet >= 60 days; live stays gated (CRYPTP_ALLOW_LIVE=yes plus --live).

---
# VALIDATION RESULT (single run, rules unchanged from the draft above; approved before running)

Status: **FAIL. The final holdout was NOT run and stays sealed.** Run with `tools/run_bounce.py ... validation`.
Window 2025-01-20 15:45 -> 2025-11-29 03:00 UTC; 754 raw signals, 205 trades after the one-position, 3-per-day, stop-size and cutoff rules.

| Run | Trades | Win % | Avg R | SE | Avg R - 2.5 SE | PF | Net | Max DD |
|---|---|---|---|---|---|---|---|---|
| **Main (fees, slippage, funding)** | 205 | 25.9 | -0.151 | 0.156 | -0.542 | 0.83 | -30.2% | -45.5% |
| Gross (no costs, no funding) | 206 | 26.7 | +0.072 | 0.160 | -0.329 | 1.06 | +10.1% | -27.5% |
| Control: fixed +3R, no trail | 208 | 26.0 | -0.180 | 0.120 | -0.478 | 0.80 | -33.2% | -39.0% |
| Random entries, same exit (200 runs, avg R) | - | - | p50 -0.250, p95 -0.103, max +0.032 | | | | | |

Criteria: trades >= 100 passed; gross avg R > 0 passed (+0.07, but not distinguishable from zero: SE 0.16); every other criterion
**failed**: avg R - 2.5 SE (-0.54), PF 0.83 vs 1.15, net avg R (-0.15), max drawdown (-45.5% vs 25%), positive months (3 of 10 with
>= 10 trades), beating the random-entry 95th percentile (-0.151 vs -0.103). Causality (prefix) test: passed.

Facts worth keeping:
- The exit has the expected shape: 48 of 205 trades reached +3R (armed), the best ran +16.6 R, and the win rate is ~26% (the mix needs
  ~25% at 1:3 before costs). Running winners added about +0.03 R over the fixed 1:3 control; small and well inside the noise.
- The bounce entry is somewhat better than random entry with the same exit (-0.15 vs median -0.25), consistent with a small real bounce,
  but not enough: the 95th percentile of random entries is -0.10, and costs (-0.22 R gross-to-net, of which funding $4.77) consume the
  +0.07 R gross edge.
- The midnight flat cut 9 trades that were above +1R at the time (~4% of trades).
- Median stop 0.70% of price: tight stops make a fixed ~15 bps round trip cost ~0.22 R per trade. A scalper's cost problem, not a bug.

Conclusion: no net edge on validation. No retuning is permitted on this segment or the holdout. Per the pre-registered consequence:
stop searching for SUI entry signals on this data.
