# Pre-registration: SUI, 15-minute bars, 1:5 reward-to-risk, $1,000 account

Written and committed BEFORE any result was computed. Do not edit after the fact; append a dated note instead.

## Setup (fixed)
- Market: SUI/USDT perpetual, 15-minute candles from listing (May 2023) to Oct 2026. Source: OKX (Bybit is blocked from the dev sandbox).
- Account: starts at $1,000, compounding. Risk 1% of current equity per trade (stop distance sets the size), leverage capped at 3x.
- Every trade: stop at -1R, a single take-profit at +5R, no partial exits, no breakeven move, one position at a time, entry at the OPEN
  of the bar after the signal. Costs: 0.055% taker fee per side + 2 bps slippage on market/stop fills (target fills at the limit).
  Funding is ignored (holds are hours long; funding is ~0.01% per 8h).
- The user did not name an entry rule, so two existing candidates are tested, each exactly once:
  A. crypTP structure strategy (swing structure + break of structure, higher-timeframe 4h filter, ATR structure stop), long and short,
     with the fee-aware stop filter on (stop >= 3x round-trip cost) and the target replaced by a single 5R target. Nothing else changed.
  B. Liquidity Sweep Reversal script (docs/SWEEP_PREREG.md) at its defaults (including the 12:00-16:00 UTC session), long and short,
     with reward:risk = 5.0, breakeven OFF, and risk-based sizing.
- 70% in-sample / 30% out-of-sample split by time.

## A candidate "works" only if ALL hold
1. At least 300 trades.
2. Average R per trade after costs > 0.
3. Average R minus 2 standard errors > 0 (SE = std of R / sqrt(trades)): the edge is distinguishable from luck.
   (At 1:5 with ~17% winners, one trade's R has a standard deviation of ~2.3, so 300 trades give SE ~0.13 R.)
4. Average R > 0 in BOTH the in-sample and the out-of-sample halves.
5. Average R > 0 in at least 3 of the calendar years that have 30 or more trades.
Two candidates are tested, so a candidate that passes only marginally (criterion 3 within 0.5 SE of the bar) is treated as unproven.

## Known limits
One coin, ~3.4 years, one bear/bull cycle at most; SUI's own 2025 collapse dominates the later data; paper fills are idealised
(no queue, no partial fills, no outages); OKX data stands in for Bybit.

---
## Results (appended after the run; the pre-registered text above is unchanged)

SUI/USDT perpetual, 15-minute candles, 2023-05-05 to 2026-10-07 (120,141 bars, no gaps), $1,000 start, 1% risk per trade, single 1:5 target,
standard costs. Out-of-sample = last 30% (from 2025-09-27).

| | A: crypTP structure | B: Liquidity Sweep |
|---|---|---|
| Trades | 993 | 303 |
| Win rate (break-even before costs: ~16.7%) | 16.2% | 17.5% |
| Average R after costs (SE) | -0.196 (0.069) | -0.035 (0.130) |
| Average R minus 2 SE | -0.334 | -0.295 |
| Profit factor | 0.80 | 0.95 |
| Account | $1,000 -> $113 (-88.7%), max DD -89.6% | $1,000 -> $835 (-16.5%), max DD -52.2% |
| Zero-cost average R | -0.027 | +0.053 |
| Cost per trade | 0.169 R | 0.088 R |
| In-sample / out-of-sample avg R | -0.152 (742) / -0.328 (251) | +0.077 (202) / -0.259 (101) |
| Per year avg R (n) | 2023 -0.15 (187), 2024 -0.23 (321), 2025 -0.10 (304), 2026 -0.34 (181) | 2023 +0.36 (70), 2024 +0.16 (59), 2025 -0.12 (99), 2026 -0.45 (75) |
| Long / short avg R | -0.19 (530) / -0.21 (463) | -0.33 (152) / +0.26 (151) |
| Median stop | 0.88% of price | 1.87% of price |

Pre-registered criteria: (1) >= 300 trades: PASS for both. (2) avg R > 0: FAIL both. (3) avg R - 2 SE > 0: FAIL both.
(4) positive in-sample and out-of-sample: FAIL both. (5) positive in >= 3 years with >= 30 trades: FAIL both. Verdict: both FAIL.

Reading: A has no edge even before costs (win rate 16.2% is below the 16.7% break-even) and costs of ~0.17 R per trade on tight stops
turned that into an 89% loss. B sits at break-even before costs (+0.05 R, well inside one standard error) and its results decayed each year
(+0.36, +0.16, -0.12, -0.45). The long/short split in B (-0.33 vs +0.26) is post-hoc, reflects SUI's 2025-26 decline, and is not a tradable
finding. At about 90 trades a year, B could not be validated by forward paper trading for years (SE 0.13 R at 300 trades).
