# Pre-registration: the SMC e-book's confirmed-entry model

Written 2026-10-08 BEFORE any code was run on data. Do not edit the rules after the fact; append a dated note instead.
Code: `cryptp/confirmed.py`, runner `tools/run_confirmed.py`.

## Why this test
The two earlier tests (`MB_FADE_PREREG.md`, `ROWNYEL_PREREG.md`) found no edge in anticipatory entries: buying the sweep of a low straight away did WORSE than random entries.
The supplied e-book's central claim is that the same liquidity sweep should only be traded after confirmation on a lower timeframe. This test asks that directly:
**does waiting for a lower-timeframe structure shift after an HTF liquidity sweep turn the setup into a winner, and does it beat entering without the confirmation?**

## What the e-book says (summarised from the supplied PDF) and how it is made mechanical
- **IFC / liquidity sweep:** an HTF candle that takes a major swing high or low and closes back inside marks where stops were cleared; then switch to a lower timeframe and wait for confirmation.
- **BOS / CHoCH need a candle-body close** beyond the level; a wick alone is only liquidity.
- **Entry modules:** "CHoCH with IDM" (after the shift, wait for the first pullback's extreme, the inducement, to be taken, then enter) and "CHoCH without IDM" (enter on the shift itself).
- **Stop** beyond the swept extreme; **move the stop to break-even after the structure break**; targets at the next major structure; reward:risk of 1:5 to 1:10 is called a great ratio.
- Its crypto example pairs H1 (HTF) with M5 (LTF). Only 15m history is available here (730 days), so the lower timeframe is **15m** (coarser than the book's M5, a stated deviation).

## Rules (fixed now)
**Data and universe.** OKX USDT perps, 15m, 730 days to 2026-10-08, resampled to HTF bars (complete bars only). 15 coins: ADA AVAX DOGE GRASS HBAR LINK NEAR SUI XRP LTC DOT BCH ATOM UNI APT. Both directions are traded (the book is two-sided).

**Step 1: HTF liquidity sweep.** Williams fractal (2 bars each side) highs and lows on the HTF; a level is active for 100 HTF bars once confirmed and is consumed when pierced without a close back inside. An HTF bar qualifies as a long sweep if its low pierces an active fractal low by at least
0.1 x ATR(14, HTF), it closes back above that level, and it closes in the upper half of its range (mirrored for shorts; the highest swept low / lowest swept high is used).
The structure stop is S* = the bar's extreme -/+ 0.1 x ATR(HTF). The setup is armed from the first 15m bar AFTER the HTF bar closes, for 12 HTF bars (12 hours on 1h, 48 hours on 4h). A newer same-direction sweep replaces an armed one. HTF information is used only once its bar has completed.

**Step 2: LTF CHoCH.** Within the window, the first 15m bar that CLOSES above the most recent confirmed 15m fractal high (long) / below the most recent confirmed 15m fractal low (short). Fractals are confirmed 2 bars after the pivot and usable from the third bar after it.
**Step 3: entry model.**
- **M2 (CHoCH without IDM):** enter at the open of the bar after the CHoCH bar.
- **M1 (CHoCH with IDM):** the first 15m fractal low (long) / high (short) confirmed AFTER the CHoCH bar is the IDM. Enter at the open after the first bar that pierces the IDM by at least 0.1 x ATR(14, 15m) and closes back above (below) it.
**Cancel:** any 15m low (high) beyond S* before entry cancels the setup; so does the window expiring. One attempt per HTF sweep.
**Stop:** S* (for M1 also no higher than the IDM-sweep wick -/+ 0.1 x ATR(15m)). **Gates:** the stop must be between 1.0% and 12.0% from the signal close, else skip.
**Target:** the nearest confirmed HTF fractal high above (long) / low below (short) the signal close, active at that time; skip if reward:risk from the signal close is below 3.0 or no such level exists.
**Management:** once a bar's high (low) reaches +1R from the signal close, the stop moves to the entry price from the next bar (the book's "stop to break-even after the break"). Stop-first if a bar reaches both. Time stop: close after 20 days (1,920 bars).
**Sizing and costs (project standard):** one position per coin, risk 1% per trade, 3x notional cap, 0.055% fee per side, 2 bps slippage on market and stop fills. R = P&L / initial risk.

## Configs, control and criteria
Four configs, ALL reported, never best-of: 1h-M1, 1h-M2, 4h-M1, 4h-M2 (HTF-entry model). Common calendar cut at 70% of the span (about 2026-03-02).
A config passes only if, on the 15 coins pooled: at least 300 trades; avg R > 0; avg R > 0 in BOTH halves; AND (avg R - 2 SE) > 0. Fewer than 300 trades = inconclusive.
**Control C0 ("unconfirmed"), the point of the test:** the same HTF sweeps, the same S*, gates, target and management, but entering at the open of the first 15m bar after the HTF sweep closes, with no CHoCH and no IDM.
Confirmation "adds something" only if a config's pooled avg R is above C0's pooled avg R + 2 SE of C0. Long and short results are reported separately. A zero-cost run is a diagnostic, not a criterion.

## Not modelled
Order-block and imbalance (FVG) criteria, decisional vs extreme blocks, session liquidity (Asia/London/NY), daily-candle liquidity, flip entries, the single-candle entry, scaling in, the 5m timeframe, HTF trend bias from BOS, discretionary POI selection, funding costs.
This is a simplified model of the book's confirmation sequence, not a full reproduction of it, so a failure rejects this mechanical reading, not the book's discretionary use.

## Known limits
Fractal sweeps and CHoCH-type breaks occur constantly, so a confirmed setup can nearly always be found afterwards; this test asks whether they pay when traded forward under fixed rules. Coins are correlated. Any variant run after seeing results is labelled exploratory.

---
## Results (appended 2026-10-08 after the run; the pre-registered text above is unchanged)
Run: `PYTHONPATH=. python tools/run_confirmed.py` (net) and `--gross` (diagnostic). No preliminary run on real data was made before this one; the tests were mutation-checked first (an HTF look-ahead, a wick-only CHoCH, dropped cancel/reward:risk rules, a wrong-target rule and a skipped IDM are all caught).
OKX perps, 15 coins pooled, cut 2026-03-02. Average R per trade (trades), net of costs:

| config | pooled | in-sample | out-of-sample | long / short | verdict | adds over its control? |
|---|---|---|---|---|---|---|
| 1h-M1 (CHoCH + IDM) | -0.245 (190) | -0.345 | +0.140 (39) | -0.344 / -0.119 | inconclusive (<300 trades) | no |
| 1h-M2 (CHoCH only) | -0.309 (263) | -0.348 | -0.169 (57) | -0.368 / -0.250 | inconclusive (<300 trades) | no |
| 4h-M1 | -0.350 (425) | -0.382 | -0.260 (110) | -0.362 / -0.335 | **FAIL** | no |
| 4h-M2 | -0.120 (540) | -0.159 | -0.003 (134) | -0.081 / -0.168 | **FAIL** | no |
| **1h-C0 control (no confirmation)** | **-0.210 (1,671)** | -0.231 | -0.123 | -0.325 / -0.073 | | |
| **4h-C0 control** | **-0.150 (1,023)** | -0.148 | -0.155 | -0.152 / -0.149 | | |

Win rates 6-12% (a break-even stop at +1R turns many reversals into scratches). The 1h configs are formally inconclusive under the pre-set 300-trade minimum, but their 2-SE intervals lie entirely below zero (1h-M1 upper bound -0.04, 1h-M2 -0.15).
**Waiting for confirmation did not help.** Every confirmed config is at or below its unconfirmed control; none comes near the control's upper 2-SE bound (1h -0.139, 4h -0.048). The best, 4h-M2 (-0.120 vs -0.150), is a 0.03R difference, which is noise.
The only visible effect of confirmation is that it throws away most setups: 1,671 -> 190 / 263 trades on 1h, 1,023 -> 425 / 540 on 4h, without improving what is left.
**Diagnostic, zero costs:** pooled -0.159, -0.228, -0.277, -0.044 for the four configs, controls -0.113 (1h) and -0.067 (4h); out-of-sample +0.235 (n=39), -0.076, -0.182, +0.071, all inside the noise.
Costs are not the cause: before costs the confirmed entries are still negative or about zero, and none beats its control.

**What this does and does not show.** This mechanical version of the e-book's confirmation sequence (HTF sweep, 15m body-close CHoCH, optional inducement sweep, structure stop, nearest-HTF-fractal target, break-even at +1R) has no edge on 15 liquid alts over two years,
and the confirmation itself added nothing over entering right after the sweep. It does NOT test order-block and imbalance quality, session liquidity, the book's 5m timeframe (only 15m was available), flip and single-candle entries, scaling in, HTF trend bias, or discretionary zone choice.
So it rejects this mechanical reading, not the book's full discretionary use. The pre-registered conclusion stands: no evidence of an edge. Nothing was tuned after seeing results; any variant from here is exploratory.
