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
