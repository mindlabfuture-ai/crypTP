# Pre-registration: volume-profile fade ("MB" Facebook trader), hypothesis only

Written BEFORE any result was computed. Do not edit after the fact; append a dated note instead.
Source: a public follower's notes from the trader's own posts (screenshots and captions), 2026-09-29/30. No scraping was done.
Trade log: `docs/mb_trade_log.csv` (5 posted trades, all winners, so it says nothing about win rate).

## Rules as inferred from the posts
1. Define value with a fixed-range volume profile (VAH, POC, VAL) plus daily pivots, on 15m candles.
2. Entry (counter-trend fade): price breaks beyond VAH (short) or VAL (long) into thin volume, then rejects (wick / re-entry into value).
   Confluence he draws: R1/R2 pivot, fib 0.5-0.618 of the impulse, a supply/demand block.
3. Stop: just beyond the rejection extreme (about 0.35-1.1% away in the logged trades).
4. Target: the next high-volume node, usually POC, sometimes the daily pivot / opposite value edge.
5. Flip: at the POC target he re-evaluates and may take the opposite side (GRASS short, then long).
6. Macro filter (caption of 2026-09-29): trade alts only with the bias. Risk-off = BTC.D up, USDT.D up, TOTAL down, OTHERS.D down
   (no alt longs). Risk-on = the reverse (no alt shorts). Per coin, check the BTC pair (e.g. HBARBTC) trending with TOTAL.

## Test (to be run later; nothing run yet)
Un-leveraged, fixed-fractional risk, 15m candles from Bybit/OKX for a liquid alt universe (DOGE, LINK, HBAR, GRASS, and others),
standard costs as in the other PREREGs. Fixed-range profile = prior session. Compare: (a) fade with no filter, (b) fade + macro filter.
Metric: average R per trade after costs. Entries fill at the OPEN of the bar after the signal.
Works only if all hold: at least 300 pooled trades; avg R > 0 pooled; avg R > 0 in both in-sample and out-of-sample (70/30);
filter (b) beats (a) out-of-sample. Under 300 trades means "inconclusive".

## Known limits and traps
- 5 trades, all winners, posted by the person who benefits from a MEXC referral code on every card. Not evidence of an edge.
- Leverage is not part of the strategy and is not copied. At 98-298x, liquidation is about 0.34-1.0% from entry; in the logged trades
  the stop is at or beyond liquidation for 3 of the 4 trades with a known leverage (LINK, DOGE, HBAR). This repo's own safety guard
  (stop distance <= 50% of the distance to liquidation, `cryptp/safety.py`) would block every one of them.
- Dominance ratios are not independent (shares of the same total, so USDT.D rises mechanically when alts fall).
- Profile construction (range, session anchor) is discretionary; our fixed rule may differ from his.
- GRASS short entry/stop/target are read off the chart, not a card.

---
## Addendum 2026-10-07 (written BEFORE any result was computed): exact implementation spec
The user supplied one more post (BEAT, "sample execution") with his explicit long-side rules, so two rule sets are tested.
Everything below is fixed now; nothing is tuned after seeing results. Code: `cryptp/vpfade.py`, runner `tools/run_vpfade.py`.

**Data.** OKX USDT perps, 15m, 730 days to 2026-10-07: DOGE, LINK, HBAR, ADA, AVAX, NEAR, SUI, XRP, GRASS (shorter history), BTC (filter input only).
**Profile (deviation from "prior session" above, stated so it cannot be hidden):** trailing 96 bars (24h) ending at the bar BEFORE the signal bar,
100 price rows, each bar's volume spread uniformly over the rows its high-low range covers, POC = heaviest row, value area = 70% of volume grown from the POC
(standard two-row rule); VAH/VAL = outer edges. Discount = below POC, premium = above POC.
**Execution (all rules).** Signal at bar close; market fill at the next bar's open; stop-first if a bar reaches both; target is a limit at the level;
exit at the close after 96 bars if neither is hit; one position per coin; risk 1% of equity per trade with a 3x notional cap; 0.055% fee per side
and 2 bps slippage on market/stop fills (the project standard). R = P&L / initial risk. Min reward:risk gate (A 1.5, B 2.0) measured from the signal close.

**A. Fade (inferred from his posted winners).** Short when the signal bar's high is above VAH by >= 0.25 ATR(14), it CLOSES back below VAH, and its upper wick
is >= 40% of its range. Stop = bar high + 0.1 ATR; target = POC. Long is the exact mirror at VAL. If both sides qualify on one bar, no trade.

**B. Discount + pressure (his written rules, BEAT post).** "Pressure" = a strong candle in the trade direction: body >= 50% of range, close in the
outer 30% of the range, volume > its 20-bar average.
- B1 long: pressure candle (bullish), close between VAL and POC, and its low reached the lowest 25% of the discount zone (low <= VAL + 0.25*(POC-VAL)).
  Stop = min(VAL, bar low) - 0.1 ATR; target = VAH. Short mirrored in the premium zone.
- B2 long: close crosses above the POC after at least one close below it in the prior 12 bars; within the next 12 bars, a bullish pressure candle whose low
  touches the (frozen) POC +0.1 ATR and closes above it. Cancelled if a close falls below POC - 0.1 ATR. Stop = min(POC, bar low) - 0.1 ATR; target = VAH
  at the signal bar. Short mirrored. If B1 and B2 both fire on a bar the trade is the same side, so there is one trade; opposing sides on one bar = no trade.

**Macro filter (variant "+F"), a PROXY.** Index dominance/TOTAL history is not on the exchange API, so: bias-down = BTC close below its 7-day EMA
(672 bars) AND the coin/BTC ratio below its own 7-day EMA; bias-up the reverse. Shorts only in bias-down, longs only in bias-up. Not applied to BTC.

**Configs and criteria.** Four configs (A, A+F, B, B+F) are ALL reported, never best-of. Each is judged by the criteria above: >= 300 pooled trades;
pooled avg R > 0; avg R > 0 in BOTH halves (common calendar cut at 70% of the pooled time span: in-sample before, out-of-sample after);
and a "+F" config only counts as an improvement if its OOS avg R beats its unfiltered twin's. Also reported, for information only: pooled mean R minus 2 SE,
per-coin avg R, long/short split, median stop distance. Anything run after this point with changed numbers is labelled exploratory.

**Not modelled.** His "wait for the crash momentum to fade" rule (no clean mechanical form), funding costs, the real dominance indices, discretionary
patterns (Adam & Eve, FVG), and any leverage above 3x. Because risk is 1% per trade with a 3x cap, liquidation never binds in this test; his 98-298x sizing
is deliberately not replicated.

---
## Results (appended 2026-10-07 after the run; the pre-registered text above is unchanged)
Run: `PYTHONPATH=. python tools/run_vpfade.py data`, OKX perps 15m, 2024-10-07 to 2026-10-07 (GRASS from 2024-10-28), 9 coins, ~70k bars each, no gaps.
Common calendar cut 2026-03-02 (in-sample before, out-of-sample after). Net of costs (0.055%/side + 2 bps slippage). Average R per trade (trades):

| config | pooled | in-sample | out-of-sample | win % | verdict |
|---|---|---|---|---|---|
| A (fade) | -0.286 (6,659) | -0.242 (4,496) | -0.379 (2,163) | 27 | **FAIL** |
| A+F | -0.226 (1,140) | -0.207 (838) | -0.278 (302) | 28 | **FAIL** |
| B (discount + pressure) | -0.256 (7,478) | -0.245 (5,304) | -0.284 (2,174) | 23 | **FAIL** |
| B+F | -0.184 (1,647) | -0.204 (1,269) | -0.115 (378) | 24 | **FAIL** |

All four fail "pooled avg R > 0" and both half criteria. The filter did beat its unfiltered twin out-of-sample (the only criterion it met), but it
improved a losing result, it did not produce a winning one. The pooled mean minus 2 SE is below zero for every config (-0.33, -0.34, -0.30, -0.28).
Per-coin: negative on nearly every coin for A and B; the few positive coins under +F (HBAR 0.07 and NEAR 0.05 on A+F; GRASS 0.05 on B+F) are on 108-191 trades each
and are not distinguishable from noise across nine coins and four configs.

**Diagnostic (zero fees and slippage, NOT a pass criterion; the repo's usual check of whether costs or the idea is the problem):**
A +0.045R pooled (lower 2 SE -0.002), A+F +0.094R (n=1,140, lower 2 SE -0.023), B -0.042R, B+F +0.036R. So before costs the signal is about zero
(A's shorts +0.10R vs longs -0.00R is the only side-level hint), and the costs, about 0.3R per trade because the median stop is only 0.5-0.8% away,
turn "about zero" into a loss. A 27% win rate against a 1.5:1 minimum reward:risk needs about 40% to break even.

**What this does and does not show.** It shows this mechanical reading of the method (24h profile, fixed thresholds, no discretion) has no edge on 9 liquid
alts over two years, net or gross, and that the macro-filter proxy helps a little but not enough. It does NOT show his discretionary trading has no edge:
trade selection, reading confluence by eye, the "wait for the crash to pause" rule, real dominance data and the 98-298x sizing were not modelled, and his posted wins
are a handful of chosen trades. The pre-registered conclusion stands: no evidence of an edge. Parameters were not tuned after seeing this; any variant run from here is exploratory.

---
## Addendum 2026-10-07 (EXPLORATORY round 1, written BEFORE it was run): wider stops, fewer and higher-quality setups
Motivated by the result above (about zero before costs, costs ~0.3R per trade because stops were only 0.5-0.8% away). This is a data-driven follow-up, so it is
labelled exploratory and judged by stricter rules than a fresh pre-registration, not looser ones.

**Fixed grid (16 candidates, all net of costs, no macro filter):** rule set {A, B} x stop floor {1%, 2%} x quality {base, high} x min reward:risk {base, 3.0}.
- *Stop floor:* the stop is widened, never tightened, so it sits at least X% from the signal close; the reward:risk gate is applied AFTER widening, so a wide stop
  only trades when the target is far enough. Fewer trades is the intended effect.
- *Quality "high":* A: poke >= 1.0 ATR beyond VAH/VAL (was 0.25), rejection wick >= 60% of range (was 40%), signal-bar volume > 1.5x its 20-bar average (was unused).
  B: pressure-candle volume > 2.0x average (was 1.0x), body >= 65% of range (was 50%), close in the outer 20% (was 30%), low in the outer 15% of the zone (was 25%).
- *min reward:risk "base":* 1.5 for A, 2.0 for B (as before); the alternative is 3.0.

**Selection rule:** per rule set, the candidate with the highest IN-SAMPLE (before 2026-03-02) average R among those with at least 200 in-sample trades.
Out-of-sample is looked at once, after selection, and never used to choose. All 16 candidates' in-sample AND out-of-sample numbers are printed so the multiplicity is visible.
**Held-out coins:** six coins that were NOT in the original universe (LTC, DOT, BCH, ATOM, UNI, APT) are pulled and used only to run the two selected configs, once.
**Follow-ups on the selected configs only:** the same config with the macro filter (+F), and the zero-cost diagnostic.

**"Promising" means all of:** the selected config has OOS average R > 0 on the original coins, AND average R > 0 pooled on the held-out coins with at least 150 trades.
Anything less is "no evidence", and no further parameters are tried this round. Even "promising" is not "validated": 16 candidates x 2 rule sets were looked at, the cut date is
one split, and it would still need a clean pre-registration and a forward test on data that does not exist yet.

---
## Results, exploratory round 1, stage 1 (appended 2026-10-07; the plan above is unchanged)
Original 9 coins, 15m, net of costs, cut 2026-03-02. All 16 candidates, average R per trade (trades), sorted by in-sample:

| candidate | in-sample | out-of-sample | median stop |
|---|---|---|---|
| A stop>=2% high rr-3.0 | +1.308 (2) | n/a | 3.7% |
| A stop>=1% high rr-3.0 | +0.496 (3) | -1.128 (1) | 1.8% |
| **A stop>=1% base rr-3.0 (selected for A)** | **+0.043 (674)** | **-0.082 (203)** | 1.0% |
| A stop>=2% base rr-3.0 | -0.001 (141) | -0.176 (36) | 2.0% |
| A stop>=2% base rr-base | -0.007 (789) | -0.086 (224) | 2.0% |
| A stop>=1% base rr-base | -0.056 (2,391) | -0.135 (767) | 1.0% |
| B stop>=2% base rr-3.0 **(selected for B)** | -0.112 (681) | -0.299 (125) | 2.0% |
| B stop>=2% base rr-base | -0.155 (1,710) | -0.125 (401) | 2.0% |
| B stop>=1% base rr-base | -0.185 (3,922) | -0.150 (1,177) | 1.0% |
| B stop>=1% base rr-3.0 | -0.230 (2,110) | -0.194 (555) | 1.1% |
| B "high" (4 candidates) | -0.25 to -0.42 (72-429) | -0.32 to -0.82 (12-107) | 1.2-2.0% |
| A "high" (remaining 2) | -0.29 (47), -0.30 (20) | -0.36 (23), -0.18 (10) | 1.3-2.0% |

Selected by in-sample only (>= 200 in-sample trades): **A stop>=1% base rr-3.0** (in-sample +0.043, out-of-sample **-0.082**, lower 2 SE -0.36) and
**B stop>=2% base rr-3.0** (in-sample -0.112, out-of-sample **-0.299**). Their +F twins: A+F -0.360 / -0.193 on 94 / 26 trades; B+F -0.143 / +0.074 on 118 / 12 trades (too few to read).
Zero-cost diagnostic: A +0.177 in-sample, +0.053 out-of-sample; B -0.045, -0.233.

**Reading it.**
- Wider stops did what they should to costs: the cost drag fell from about 0.33R per trade to about 0.13R (A: +0.177 gross vs +0.043 net in-sample), because costs are now a smaller share of the risk.
  But the gross signal is about zero out-of-sample (+0.05R), so there is nothing for the lower costs to protect.
- "Higher quality" filters mostly produce too few trades to evaluate (A "high": 2-47 in-sample trades). Where there are enough (B "high", 72-429 trades) they are worse than the base version, not better.
  The two candidates ranked first have 2 and 3 trades: noise.
- Only 1 of 16 candidates has a positive in-sample average R at >= 200 trades (+0.043, i.e. about zero), and it is negative out-of-sample: what best-of-16 selection on noise looks like.
- **Verdict under the pre-declared rule: NO EVIDENCE.** The selected configs fail "out-of-sample average R > 0" on the original coins, so the held-out-coins stage cannot make either one "promising";
  it is still run (stage 2, appended below when done) as an independent check, and no further parameters will be tried this round.
