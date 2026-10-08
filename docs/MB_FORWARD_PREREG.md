# Pre-registration: forward test of a followed trader's posted setups

Written 2026-10-08 BEFORE the first forward setup was logged. Do not edit the rules after the fact; append a dated note instead.
Why: the backtests (`docs/MB_FADE_PREREG.md`) show no edge for any mechanical reading of his method, but they cannot test his discretion. A forward test of what he actually
posts, scored the way a follower could have traded it, is the only fair test left. Tools: `cryptp/forward.py`, `tools/forward_score.py`. Log: `docs/mb_forward_log.csv`.

## How setups get into the log
No scraping: the feed is posts the user pastes into this session, as before. Claude logs each one at the moment it is pasted.
- `kind = setup`: a post showing an OPEN or PENDING position or plan, before its outcome, with a readable entry, stop and target (his drawn position box: stop = outer edge of the
  grey box, target = outer edge of the teal box; or levels stated in the text). Scored.
- `kind = result_only`: a result card or recap posted after the exit with no earlier setup post. NOT scored; counted. This tally is the selection-bias measure: a high share of
  results-only posts means a follower never got the chance to take the trade.
- `kind = unscoreable`: a post whose levels cannot be read, or a conditional call with no fixed stop. Counted, not scored (conditional calls are tracked in `mb_calls_log.csv`).
- `logged_at_utc` is the moment of pasting, never earlier than the real post time, so it is conservative. If the Facebook time is known it goes in `post_time_note` and is NOT used for scoring.
  Posts should be pasted promptly; a late paste lowers a setup's followability, and that is the point.
- Everything before 2026-10-08 (the five logged perp trades, SUI, BTC, BEAT) is historical and is NOT part of this test.

## Scoring (fixed)
- Fill: a market order at the OPEN of the first 15m bar that starts AFTER `logged_at_utc` (the bar containing the log time is never used), +2 bps slippage, 0.055% fee per side.
- His stop and his target are used as drawn. Stop-first if a bar reaches both; target is a limit; time stop at the horizon (default 48h for perp setups, set per row) at the close of that bar.
- Unlevered. 1R = fill-to-stop distance, so R is net of fees and slippage and independent of the 98-298x he uses. Leverage is deliberately not replicated.
- `missed`: at the first fill the price is already beyond his stop or target, or the remaining reward:risk is below 1. Not averaged, but the missed RATE is reported and is a result.
- `open`: still inside its horizon; shown marked to the last closed bar, never averaged. `pending`: no closed bar after the log time yet.
- Only CLOSED bars are used; OKX perpetual 15m candles (public endpoint). Symbols are OKX instruments (e.g. DOGE-USDT-SWAP); a setup on a coin OKX does not list is `unscoreable`.

## Stopping rule and verdict (fixed in advance)
Evaluate at 30 valid (realized, not missed) setups or 12 weeks after the first logged setup, whichever comes first. No early verdict, no dropping or adding setups after the fact.
- **NOT FOLLOWABLE** if more than half of the scored setups are `missed`.
- **EVIDENCE OF A FOLLOWABLE EDGE** only if at least 30 valid setups AND the bootstrap 90% interval of mean R lies entirely above zero AND mean R >= +0.2.
- Otherwise **NO EVIDENCE**, including the case of fewer than 30 valid setups at 12 weeks.
`python tools/forward_score.py` prints the running table and applies exactly this rule.

## Known limits
One author, one regime, small sample: 30 setups at about 1.5R standard deviation gives a 90% interval about +-0.45R wide, so only a clearly strong edge can show.
The fill model is a market order at the next 15m open, so very fast setups look worse than they would for someone watching live; slower multi-day setups are not penalised that way.
He may post fewer or different setups once he knows he is followed. His leverage and any scaling or partial exits he does but does not post are not captured. Funding is not modelled.
