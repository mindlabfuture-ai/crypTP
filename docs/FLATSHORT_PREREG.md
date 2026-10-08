# FLAT-state shorts on the 15m trigger, 1:3 RR (perpetuals) — DRAFT pre-registration

Status: **DRAFT, awaiting approval. Nothing has been run for this test.** Rules freeze on approval.

## Question
When the daily state is FLAT (last closed daily close <= SMA-200), does the exact mirror of the 15m pullback-resume trigger, taken SHORT,
have an edge? Perps are required (spot cannot short).

## What is already known (disclosed so the test is not read as fresh)
- docs/DAILY15M_PREREG.md: the long trigger had ~0 gross edge on SUI; the same long trigger taken while FLAT lost -0.17 R (850 trades).
  That is evidence AGAINST longs in downtrends, not a test of shorts. A mirror short is not the same series of trades, but the
  prior that it is profitable after costs is low. The honest expectation is FAIL; the test exists to close the question cleanly.
- This is the 5th candidate rule set on the same SUI data, so the significance bar is the strict one below.

## Rules (mirror of the frozen long rules, nothing new tuned)
1. **Direction (daily, closed candles only).** Same mapping as the long test (last daily candle dated BEFORE the bar's UTC date).
   SHORT permitted only if that close <= its SMA-200 (and the SMA exists). Long trades: none.
2. **Entry (15m).** Mirror pullback-and-resume:
   - trend: close < EMA(50);
   - pullback: within the last 12 bars some high >= EMA(20);
   - trigger: close < EMA(20) AND close < previous bar's low; edge-triggered (condition newly true).
   Signal at bar close; fill at the next open with 2 bps adverse slippage; cooldown 8 bars after an exit.
3. **Stop** = highest high of the last 12 bars plus 0.1 x ATR(14). Skip if stop distance < 0.45% or > 3.0% of entry.
4. **Target** = single take-profit at 3.0 R. No partials, no breakeven move.
5. **Day trade:** no entries on bars opening at/after 20:00 UTC; flat at the last bar close of the UTC day.
6. **Risk:** $1,000, 1% risk per trade, 3x max leverage, one position, max 3 trades per day.
7. **Costs:** 0.055% per side + 2 bps slippage. Funding is not charged. Disclosed bound: holds cross at most the 08:00 and 16:00
   UTC settlements; at the 0.01%/8h baseline that is <= 0.02% of notional per trade (~0.01 R at the median 1.9% stop). A short in a
   FLAT regime usually RECEIVES positive funding, so ignoring it is conservative for most days, but squeeze periods can flip it.
8. **Implementation:** reuse `cryptp/daily15m.py` with a `side` parameter; the short path must be proven an exact mirror by a unit test
   on price-reflected data (price p -> 2C - p) BEFORE the real run, as was done for the structure planner.

## Data and split
- Primary: SUI 15m, 2023-05-05 -> 2026-10-07, 70/30 by time. One run, no tuning.
- Secondary (out-of-sample coins, reported separately, not pooled into the pass test): ETH and SOL 15m, the last 90 days only. This
  window is far too short to pass or fail anything alone; it is a sanity check that the sign matches.

## Pass criteria (decided before seeing results)
All must hold on SUI:
- >= 100 trades.
- Full-sample avg R - 2.5 x SE > 0.
- Out-of-sample (last 30%) avg R > 0 AND profit factor > 1 AND >= 50 OOS trades (the long test's 48 was explicitly "not meaningful").
- Max drawdown < 25%.
- Gross (no costs) avg R > 0 and net avg R > 0: the edge must exist before costs, not appear only after.
- Positive avg R in at least 3 of the calendar years that have >= 30 trades.
Any miss -> FAIL, with no re-tuning on this data. A PASS would still only mean "worth a forward paper test", not "trade it live".

## Controls (reported alongside)
- Same short trigger with the daily filter OFF (all regimes).
- Same short trigger in the LONG state (the filter inverted).
- Causality (prefix) test, as before.
- Exact-mirror unit test (item 8).

## What happens after
- PASS: paper-forward on Bybit testnet/paper for >= 60 days before any live capital; live remains gated.
- FAIL: stop searching for intraday 15m triggers on SUI with this data; the remaining supported tool is the daily SMA-200 state for
  spot risk management.

---
# RESULTS (single run, rules unchanged from the draft above; approved before running)

Status: **FAIL.** Run with `tools/run_flatshort.py`. Mirror unit test (price reflection 2C - p, long vs short) passed before the run.
Re-running the long test after adding the short path reproduced it exactly (672 trades, avg R -0.107).

| SUI run | Trades | Win % | Avg R | SE | Avg R - 2.5 SE | PF | Net | Max DD | OOS trades | OOS avg R | OOS PF |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **Main: shorts in FLAT state (costs)** | 867 | 34.1 | -0.109 | 0.049 | -0.231 | 0.84 | -64.5% | -73.1% | 521 | -0.113 | 0.83 |
| Gross (no fees or slippage) | 869 | 34.9 | -0.002 | 0.049 | -0.125 | 0.98 | -10.3% | -47.4% | 523 | +0.003 | 0.99 |
| Control: filter off (all regimes) | 1818 | 34.4 | -0.085 | 0.034 | -0.170 | 0.89 | -82.4% | -85.5% | 568 | -0.138 | 0.80 |
| Control: shorts in LONG state | 649 | 34.1 | -0.082 | 0.057 | -0.224 | 0.87 | -45.0% | -50.9% | 47 | -0.415 | 0.45 |

Sign check (90 days, shorts, daily state as defined): ETH 46 trades avg R -0.52 (PF 0.29); SOL 57 trades avg R -0.38 (PF 0.51).

Average R by year (main): 2023 -0.39 (11), 2024 +0.05 (197), 2025 -0.25 (270), 2026 -0.09 (389).

Criteria: trades >= 100 passed; avg R - 2.5 SE > 0 **failed** (-0.23); OOS avg R > 0 **failed** (-0.113; PF 0.83; 521 OOS trades, so
the sample is adequate this time); max DD < 25% **failed** (-73%); gross avg R > 0 **failed** (-0.002, i.e. zero); at least 3 positive
years with >= 30 trades **failed** (1 of 3: 2024 only). The ETH/SOL sign check also came out negative.

Reading:
- The mirrored trigger has zero gross edge on SUI (-0.002 R, 869 trades), exactly like the long side. Costs (~0.11 R per trade at a
  ~1.5% median stop) turn zero into a steady loss. The daily regime did not help: shorts in the FLAT state lose as much as unfiltered
  shorts.
- With 521 out-of-sample trades this is a clean negative, not an underpowered one.
- Together with the long test, the 15m pullback-resume trigger has no directional edge on SUI in either regime. Per the
  pre-registered consequence: stop searching for intraday 15m triggers on SUI with this data.
