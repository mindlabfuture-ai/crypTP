# Backtest results (Oct 2022 - Oct 2026, 1H, BTC/ETH/SOL perpetuals)

Data: OKX perpetual candles (Bybit is blocked from the dev sandbox), 35,038 bars per coin, no gaps.
Costs: 0.055% taker fee per side, 2 bps slippage on stop exits, gap-aware stop fills, next-bar-open entries.
Split: first 70% in-sample, last 30% out-of-sample (from 2025-07-26). Parameters were never tuned on results.

Pre-registered success criterion: positive average R after costs, at least 100 trades, in at least two
regimes (bull and bear years), including out-of-sample.

## crypTP structure strategy: average R per trade (trades)

| | all years | out-of-sample | verdict |
|---|---|---|---|
| BTC long | -0.13 (186) | -0.08 (53) | fail |
| BTC short | -0.28 (171) | -0.18 (56) | fail |
| BTC both | -0.20 (330) | -0.13 (100) | fail |
| BTC both + crowd veto | -0.22 (260) | -0.01 (76) | fail |
| ETH long | -0.09 (246) | +0.13 (67) | fail (OOS n < 100, all-years negative) |
| ETH short | -0.24 (221) | -0.20 (80) | fail |
| ETH both | -0.18 (428) | -0.12 (140) | fail |
| ETH both + crowd veto | -0.20 (356) | -0.18 (114) | fail |
| SOL long | -0.27 (322) | -0.06 (83) | fail |
| SOL short | -0.21 (312) | -0.06 (86) | fail |
| SOL both | -0.24 (586) | -0.07 (161) | fail |
| SOL both + crowd veto | -0.30 (513) | -0.17 (145) | fail |

0 of 12 variants pass. Shorts also lose in the 2025-26 bear (BTC short: 2025 -0.07, 2026 -0.21 avg R), so the
problem is not the market regime or the missing short side: the entry logic has no edge after costs.

## Findings
- Fee-aware stop filter: cut 1H long-only losses by roughly 75% versus no filter, but the result is still negative.
- Crowd (dumb-money) filter: no consistent benefit.
- Popular ChartArt benchmarks: large drawdowns, mostly worse than buy and hold; several "both sides" runs are wiped out
  (the engine does not model liquidation, so losses beyond -100% mean ruin).
- Bugs found by these tests: YAML `off` parsed as False (gate silently active), and a bullish default in BOS detection.

## Caveats
OKX data stands in for Bybit; single instruments, 1H only; funding costs are not modelled; paper fills are idealised.
