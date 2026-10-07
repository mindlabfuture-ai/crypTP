# PRE-REGISTRATION: intraday squeeze-breakout, SUI 15m, 1:5 RR, $1,000

**Status: APPROVED by the user on 2026-10-07 ("approve, build it and run on SUI") and FROZEN before any strategy result was computed.**
Do not edit the rules or criteria below; append a dated note instead.
Only event COUNTS and price-range facts (no returns, no win rates) were looked at while designing it.

## Idea
A volatility squeeze (a quiet, compressed market) tends to be followed by a larger move. Trade the first decisive close out of the
compressed range, in the direction momentum already points, only when volume confirms, hold for the day at most, stop inside the range,
target 5x the risk.

## Rules (all fixed; none tuned on results)
1. **Squeeze:** Bollinger Bands (20, 2 sigma) fully inside Keltner Channels (SMA 20 +/- 1.5 x SMA20 of true range). Standard public
   formulation (the "TTM / LazyBear" squeeze); implemented independently from the formula.
2. **Setup:** at least **6** consecutive squeeze bars (1.5 hours). The **box** = highest high and lowest low over those bars.
3. **Trigger:** within **4** bars from the squeeze release (the first bar the squeeze is off), the first bar that CLOSES outside the box.
   Close above the box = long, below = short.
4. **Filters on the trigger bar:** (a) squeeze momentum (linear-regression momentum, standard definition) has the same sign as the
   direction; (b) volume >= **1.5 x** its 20-bar average; (c) the bar is before **20:00 UTC** (no new trades in the last 4 hours of the day).
5. **Entry:** market order at the OPEN of the next bar. One position at a time.
6. **Stop:** the box MIDPOINT (a failed breakout falls back through half the range). Skip the trade if the stop is closer than **0.45%** of
   price (3x round-trip cost) or farther than **3%**.
7. **Target:** a single take-profit at **+5R**. No partials, no breakeven move.
8. **Intraday:** if neither is hit, close at the open of the 00:00 UTC bar. No overnight holds.
9. **Account:** $1,000, risk **1%** of current equity per trade (stop distance sets size), leverage cap 3x. Costs: 0.055% taker fee per side
   plus 2 bps slippage on market/stop fills. Funding ignored (holds are under a day).

## Why these choices (not results)
- Box midpoint stop, not the far side: SUI's median daily range is 7.4% (6.3% in the last year) and 78% of days range >= 5%, but only
  26% of days range >= 10%. The box is ~2% tall, so a far-side stop makes a 5R target a ~10% move, rarely available in a day; the midpoint
  (~1%) makes it ~5%, available most days.
- Break-even win rate at 1:5 after costs: ~18.8% for a 1% stop (17.8% at 2%, 20.3% at 0.6%).
- Feasibility (counts only): with L=6, W=4, volume 1.5x and the 20:00 cutoff, SUI 15m shows **727 setups in 3.4 years** (~210 a year).

## Pass criteria (proposed; stricter than before because this is the third strategy family tried on this same SUI data)
1. At least 300 trades. 2. Average R after costs > 0. 3. **Average R minus 2.5 standard errors > 0** (was 2). 4. Positive in BOTH the
70% in-sample and 30% out-of-sample halves. 5. Positive in at least 3 calendar years with >= 30 trades.
Also reported (not for selection): L = 4 and 8, volume 1.0x, far-side stop, as robustness checks; and a zero-cost run.

## Known limits
One coin, ~3.4 years, dominated by SUI's 2025-26 decline; idealised fills (no queue, partial fills or outages); OKX data stands in for Bybit;
taker fees assumed (maker/limit entries would cut costs but cannot be simulated honestly here).

---
## Implementation notes (added at freeze, BEFORE any run; they only fix details the rules left implicit)
- The release bar counts as bar 1 of the 4-bar trigger window. The FIRST bar that closes outside the box ends the setup whether or not the
  filters pass (a failed filter means no trade for that setup; later bars are not scanned).
- Momentum = linear-regression value (length 20) of close minus the average of (mid of the 20-bar high/low range) and SMA20(close).
- The 0.45%-3% stop test uses the trigger bar's close and the box midpoint. After the fill at the next open, R = |fill price - stop|;
  the target is fill +/- 5R, and position size risks 1% of equity on that R. If the fill is already beyond the stop, skip the trade.
- A time exit at the 00:00 UTC bar's open is a market order (adverse slippage, taker fee). Stops are market (adverse slippage); the target is a
  limit (no slippage). If a bar reaches both stop and target, the stop is assumed first. A stop that gaps fills at the open.
- If a position is open when a trigger occurs, the trigger is skipped (one position at a time).
- Criterion 3 uses 2.5 standard errors. Average R and its standard error are over all trades, including time exits.

---
## Results (appended after the run; the frozen rules above are unchanged)

SUI/USDT perpetual 15m, 2023-05-05 to 2026-10-07 (120,141 bars), $1,000 start, 1% risk per trade, +5R target, box-midpoint stop,
flat by 00:00 UTC, standard costs. Out-of-sample from 2025-09-27.

| | Squeeze breakout (frozen spec) |
|---|---|
| Trades | 620 (310 long, 310 short) |
| Trades that reached the +5R target (zero-cost run) | **6.6%** (break-even needs ~18.8%) |
| Trades stopped at the midpoint | 68.3% |
| Trades closed at the 00:00 UTC time exit | 25.1% |
| "Win rate" (any trade with R > 0, incl. small time-exit gains) | 26.5% |
| Average R after costs (SE) | -0.177 (0.069); minus 2.5 SE = -0.350 |
| Profit factor | 0.76 |
| Account | $1,000 -> $305 (-69.5%), max drawdown -72.8% |
| Zero-cost average R | -0.073 (costs take 0.104 R per trade) |
| In-sample / out-of-sample avg R | -0.165 (414) / -0.202 (206) |
| Per year avg R (n) | 2023 -0.09 (123), 2024 -0.26 (163), 2025 -0.16 (190), 2026 -0.19 (144) |
| Long / short avg R | -0.21 / -0.14 |
| Median stop | 1.45% of price |

Criteria: (1) >= 300 trades PASS. (2) avg R > 0 FAIL. (3) avg R - 2.5 SE > 0 FAIL. (4) positive in both halves FAIL.
(5) positive in >= 3 years FAIL. Verdict: FAIL.

Robustness (information only): min squeeze 4 bars -0.146 R ($292), 8 bars -0.238 R ($271), volume 1.0x -0.153 R ($265),
far-side stop -0.168 R ($467). None is positive; the conclusion does not depend on the chosen parameters.

Reading: there is no edge before costs (-0.07 R at zero cost). Only 6.6% of breakouts ran 5R before the day ended, against 18.8% needed;
68% fell back through the box midpoint. Results are uniformly negative across years, both directions and both halves.
