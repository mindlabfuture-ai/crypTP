# Pre-registration: Liquidity Sweep Reversal strategy (Pine, MPL 2.0)

Written and committed BEFORE any result was computed. Do not edit after the fact; append a dated note instead.

## Rules
Exactly the script's defaults, ported as faithfully as possible: pivot L/R = 7, level max age 150 bars, min level spacing
0.25 ATR, stop 1.2 ATR beyond the wick, min stop 0.5 ATR, reward:risk 1.5, breakeven at 50% of the way to target,
volume > 1.3 x SMA20, wick:body >= 1.5, next-bar confirmation past the sweep midpoint, session 12:00-16:00 UTC,
longs and shorts, 10% of equity per trade, one position at a time, ATR(14).
Entries fill at the OPEN of the bar after the signal (market order), exits on stop/limit.

## Deliberate differences from TradingView (stated so they cannot be hidden later)
- Costs are this project's standard 0.055% taker fee per side + 2 bps slippage on market/stop fills (the script
  assumes 0.04% + 1 tick), i.e. slightly more conservative.
- If a bar reaches both stop and target, the STOP is assumed first (TradingView guesses a path from the open).
- A stop that gaps fills at the open. A target limit fills at the target price.
- Pivot ties: strictly greater than the left bars, greater-or-equal to the right bars (and mirrored for lows).

## Data and test
1H candles, Oct 2022 - Oct 2026 (SUI from May 2023), BTC, ETH, SOL, ADA, SUI. First 70% in-sample, last 30% out-of-sample.
Primary timeframe 1H only (the script does not fix one). Metric: average R per trade after costs (R = P&L / initial risk).

## What "works" means (all must hold)
1. Pooled over the five coins: at least 300 trades AND average R > 0 after costs.
2. Average R > 0 on at least 3 of the 5 coins individually.
3. Average R > 0 in BOTH the in-sample and out-of-sample halves, pooled.
If the pooled trade count is below 300 the result is "inconclusive", not a pass.

## Known limits
Five correlated coins are not five independent tests; funding costs are not modelled; the session filter on 1H leaves
only 4 of 24 bars eligible, so trade counts may be small.

---
## Results (appended after the run; the pre-registered text above is unchanged)

Script defaults, 1H, Oct 2022 - Oct 2026, standard costs. Average R per trade (trades):

| | all | in-sample | out-of-sample |
|---|---|---|---|
| BTC | -0.18 (172) | -0.21 (114) | -0.13 (58) |
| ETH | -0.06 (200) | -0.03 (136) | -0.11 (64) |
| SOL | -0.38 (149) | -0.48 (90) | -0.24 (59) |
| ADA | -0.28 (158) | -0.21 (106) | -0.41 (52) |
| SUI | -0.17 (152) | -0.20 (96) | -0.12 (56) |
| Pooled | -0.20 (831) | -0.21 (542) | -0.20 (289) |

Pre-registered criteria: (1) >=300 pooled trades and avg R > 0: FAIL (831 trades, -0.20). (2) avg R > 0 on >=3 of 5 coins: FAIL (0 of 5).
(3) positive in both halves: FAIL (both negative). Verdict: FAIL.

Diagnostic (not used for selection): with ZERO fees and slippage the pooled avg R is still -0.135, so costs are not the cause
(median stop 2.4% of price; costs are ~0.07 R per trade). Outcome mix at zero cost: 48% stopped at -1R, 29% breakeven,
23% reach the +1.5R target, which is below the roughly 40% needed at 1.5:1 without the breakeven rule.
Both sides lose (long -0.06 to -0.43, short -0.01 to -0.33 by coin).

Port note: the Pine script resolves a bar that sweeps both a swing high and a swing low asymmetrically (the short sweep
overwrites pending state; longs win entry priority). The port reproduces this; a mirrored-data test matches on all other trades.
