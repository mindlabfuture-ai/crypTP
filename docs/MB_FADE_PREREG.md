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
