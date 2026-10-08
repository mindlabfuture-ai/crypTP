# Pre-registration: "rownyel" fractal stop-hunt long strategy

Written 2026-10-08 BEFORE any result was computed. Do not edit after the fact; append a dated note instead.
Code: `cryptp/fractalsweep.py`, runner `tools/run_fractalsweep.py`.

## Source and what is being tested
Five TradingView charts signed "rownyel" (PEAQ 4h, JTO 1d, KAT 1h, SEI 5m, XTZ 15m; screenshots 2026-10-02 to 10-04), all long plans with entry, stop and take-profit boxes,
the "Fractals [NT-DIGITALS]" indicator, a "STOP HUNT" label (XTZ), a bounce off a swept low (SEI), "move stoploss here" / "partial or breakeven area" notes, and Elliott-wave counts.
Planned reward:risk on those charts: 5.3 (KAT), 5.4 (XTZ), 7.3 (SEI), 13.8 (PEAQ), 53 (JTO); stops 3-13% away. Scored as drawn from the screenshot time (not part of this test): JTO, SEI and XTZ
were stopped out, KAT was open at -0.6R, PEAQ could not be scored (not on OKX).
This test cannot be a faithful copy: Elliott counts are subjective and cannot be coded. What CAN be coded, and is tested, is the mechanical core: **buy the sweep of a fractal low, stop under the wick, far target.**

## Rules (fixed now)
**Data.** OKX USDT perps, 15m, 730 days to 2026-10-08, resampled to 1h and 4h (complete bars only). Coins in three groups:
G1 = ADA AVAX DOGE GRASS HBAR LINK NEAR SUI XRP; G3 = LTC DOT BCH ATOM UNI APT (never used in any earlier test); G2 = JTO SEI XTZ KAT (the coins in his charts).
**The verdict is judged on G1+G3 pooled (15 coins, none chosen by him).** G2 is reported separately because he may have picked those coins after the fact.

**Fractal low.** Williams fractal, 2 bars each side: bar j has a strictly lower low than the two bars before and the two after. It is confirmed at the close of bar j+2 and usable from bar j+3.
A fractal level stays active for 100 bars. A level that is pierced without a close back above it is consumed (a real breakdown, not a sweep).

**Signal (long only), at the close of bar i.** Some active fractal level L with: low[i] <= L - 0.1*ATR(14); close[i] > L (reclaimed on the same bar); close in the upper half of the bar's range.
If several levels qualify, the highest one is used. No other filter (no trend, no macro, no Elliott context).
**Entry:** market, at the open of bar i+1.
**Stop:** bar low - 0.1*ATR, then widened, never tightened, to at least 2.0% below the signal close; the trade is skipped if that stop would be more than 15% below. (His stops are 3-13%.)
**Target:** a limit at signal close + 5 x (signal close - stop), i.e. 5R. Stop-first if a bar reaches both. Time stop: exit at the close after 20 days (480 bars on 1h, 120 on 4h).
**Management variants:** (A) fixed stop and 5R target; (B) once a bar's high reaches +1R from the signal close, the stop moves to the entry price from the next bar (his "move stop here" / "breakeven area").
**Sizing and costs (project standard):** one position per coin, risk 1% of equity per trade, 3x notional cap, 0.055% fee per side, 2 bps slippage on market and stop fills. R = P&L / initial risk.

## Configs and criteria
Four configs, ALL reported, never best-of: 1h-A, 1h-B, 4h-A, 4h-B. Common calendar cut at 70% of the time span (in-sample before, out-of-sample after; about 2026-03-02).
A config passes only if, on G1+G3 pooled: at least 300 trades; avg R > 0; avg R > 0 in BOTH halves; AND (avg R - 2 SE) > 0 (stricter than the earlier tests because there are four configs).
Fewer than 300 trades = inconclusive. Zero-cost runs are a diagnostic, not a criterion.
**Control (diagnostic, not a criterion):** random-entry control: same coins, same number of entries per coin as the sweep signals, entry bars drawn uniformly at random (20 seeds), stop = lowest low of the last 5 bars - 0.1*ATR
with the same 2% floor and 15% cap, same 5R target and management. The sweep adds something only if its pooled avg R beats the 95th percentile of the 20 control runs.
This checks whether a long-only, wide-stop, far-target book makes or loses money regardless of the sweep (market drift and geometry).

## Not modelled
Elliott wave counts and the "wave 2/B finished, wave 3/C next" context; his hand-picked targets (planned 5-53R; 5R is the low end); partial profit-taking; trailing stops beyond break-even;
the 5m and 15m chart variants (1h and 4h cover his KAT/PEAQ timeframes; 1d is too few bars for a two-year test); funding costs. Long-only on purpose: every plan he posted is long, so this is also a bet that the market rises.

## Known limits
Fractal sweeps occur constantly, so a labelled "stop hunt" can almost always be found afterwards; the test asks whether buying them FORWARD pays, with fixed rules. Coins are correlated, so 15 coins are not 15 independent tests.
Any variant run after seeing results is labelled exploratory.

---
## Implementation note (2026-10-08, written before the final run; rules above are unchanged)
- A fractal level is used up by its FIRST qualifying sweep (whether or not a trade was possible at that moment); a level pierced without a close back above it is consumed. The text above only mentions the second case.
- Exact trigger details: the break-even stop is armed on the bar whose high reaches +1R (measured from the SIGNAL close) and takes effect from the next bar; a bar that reaches +1R and the stop is a stop.
- Random-entry control: entry bars drawn uniformly from bar 40 to the second-to-last bar, without replacement; entries that fall while a position is open are skipped, so the control can have slightly fewer trades.
- SEI and KAT have shorter OKX histories (SEI from 2025-11, KAT newer); G2 is small and reported only as a side note.
- **Disclosure:** a plumbing run (2 control seeds, G2 containing only SEI because the other downloads were unfinished) was executed on the real data before the final run, so its G1+G3 results were seen.
  The final run uses identical rules and identical G1+G3 data (only the control seeds go from 2 to 20 and G2 completes), so those numbers cannot change; no rule or parameter was changed after seeing them.
- The tests were mutation-checked: dropping the upper-half-close rule, never expiring levels, not consuming broken levels, a 4R target, and a 3- or 5-bar look-ahead are all caught.
  Using a fractal one bar early is an equivalent mutant (the confirming bars of a fractal can never pierce it), so it is correctly not caught.

---
## Results (appended 2026-10-08 after the final run; the pre-registered text above is unchanged)
Run: `PYTHONPATH=. python tools/run_fractalsweep.py --seeds 20` (net) and `--gross --seeds 8` (diagnostic). OKX perps resampled to 1h and 4h, 15 coins in the verdict group (G1+G3), cut 2026-03-02.
Average R per trade (trades). The G1+G3 numbers are identical to the preliminary plumbing run disclosed above.

| config | pooled G1+G3 (net) | in-sample | out-of-sample | his coins G2 | random-entry control, mean [5-95%] | verdict |
|---|---|---|---|---|---|---|
| 1h-A (fixed 5R) | -0.185 (3,992) | -0.248 | -0.008 | -0.122 (743) | -0.122 [-0.172, -0.067] | **FAIL** |
| 1h-B (break-even at +1R) | -0.154 (4,961) | -0.183 | -0.077 | -0.108 (901) | -0.088 [-0.138, -0.055] | **FAIL** |
| 4h-A | -0.197 (1,477) | -0.272 | -0.004 | -0.205 (250) | -0.123 [-0.192, -0.067] | **FAIL** |
| 4h-B | -0.098 (1,692) | -0.112 | -0.062 | -0.108 (294) | -0.069 [-0.122, -0.013] | **FAIL** |

Win rates 9-15% against 16.7% needed to break even at 5R. Every config fails "pooled avg R > 0", both half criteria, and "avg R - 2 SE > 0" (-0.25, -0.20, -0.30, -0.18).
**The sweep did worse than random entries with the same stop and target rules in all four configs** (below the control's 5th percentile in 1h-A, 1h-B and 4h-A; inside its range in 4h-B). It never came near beating the control's 95th percentile.
The control itself loses (-0.07 to -0.12R net): a long-only book with a wide stop and a far target lost money in this period regardless of any sweep.

**Diagnostic, zero fees and slippage (not a criterion):** pooled -0.119 (1h-A), -0.088 (1h-B), -0.142 (4h-A), -0.041 (4h-B); out-of-sample +0.062, -0.006, +0.056, +0.006 with lower 2 SE bounds of -0.08 to -0.16 (noise);
control means -0.03 to -0.07. Costs are about 0.06R per trade here (wide stops make them small), so they are not what sinks it: before costs the signal is already negative in-sample and about zero out-of-sample.
His own coins are no better than the rest (G2 -0.11 to -0.21 net).

**What this does and does not show.** A mechanical reading of "buy the sweep of a fractal low, stop under the wick, 5R target" has no edge on 15 liquid alts over two years, net or gross, and entering such sweeps was worse than entering at random.
It does NOT test the Elliott-wave context, hand-picked entries and targets (his plans were 5-53R; 5R is the low end), the choice of which coins and which moments to post, or his position sizing; the posted plans were 3 stopped, 1 open at a loss and 1 unscoreable when checked (see above).
The pre-registered conclusion stands: no evidence of an edge. No parameter was tuned after seeing results; any variant from here is exploratory.
