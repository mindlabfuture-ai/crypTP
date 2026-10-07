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
