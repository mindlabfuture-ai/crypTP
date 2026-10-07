# Pre-registration: SuperTrend strategy (Pine v4, MPL 2.0)

Written and committed BEFORE any result was computed. Do not edit after the fact; append a dated note instead.

## Rules (script defaults, ported as faithfully as possible)
ATR period 10 (Wilder RMA, "change ATR method" = true), multiplier 3.0, source hl2. Up/down bands ratchet exactly as the script does;
trend flips to +1 when close > previous down band and to -1 when close < previous up band. Buy signal = flip to +1, sell signal = flip to -1.
The script goes long on a buy signal and short on a sell signal (always in the market, reversing); no stop, no target.
Orders fill at the OPEN of the bar after the signal. Sized at 100% of equity, 1x (the script uses a fixed 1 unit; percent of equity makes
coins comparable and matches the other benchmarks). Costs: 0.055% taker fee per side + 2 bps slippage per fill.
Variants: "as written" = long/short (PRIMARY, the script as published); "long/flat" = long on buy, flat on sell (informational).

## Data and timeframes
OKX perpetual candles, BTC, ETH, SOL, ADA, SUI.
- DAILY (PRIMARY, decides the verdict): full available history (BTC/ETH from Jan 2020, ADA Mar 2020, SOL Jan 2021, SUI May 2023).
- 1H (SECONDARY, informational): Oct 2022 - Oct 2026. A 1H pass cannot rescue a daily fail.
Metrics are measured from a common start (after a 50-bar warm-up) against buy and hold on the same coin and period.

## What "works" means (daily, as-written long/short variant, judged against buy and hold)
1. Calmar (CAGR / max drawdown) higher than buy and hold on at least 4 of the 5 coins; AND
2. max drawdown at most 60% of buy-and-hold's on at least 4 of 5; AND
3. net return after costs positive on at least 3 of 5; AND
4. conclusions 1 and 3 still hold with multiplier 2.5 and with multiplier 3.5 (period fixed at 10): not a knife-edge.
A coin whose equity reaches zero (ruin; the engine has no liquidation, so a short squeeze with no stop can do this) counts as net -100%
and as failing criteria 1 and 2 for that coin.

## Known limits
About two market cycles; five correlated survivor coins; funding costs not modelled; 100% equity with no stop on the short side is
aggressive by construction (that is how the script is written, not a choice made here).
