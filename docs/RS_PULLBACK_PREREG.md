# Regime + relative strength + maker pullback, fixed 1:3 — DRAFT pre-registration

Status: **DRAFT, awaiting approval. Nothing has been run for this rule set.** Rules freeze on approval. The paper-forward journal
(`cryptp/journal.py`) implements exactly these rules live, from the same code (`cryptp/rspullback.py`).

## Why this is different from the ten failed tests
Every earlier test asked "does this chart pattern predict this one coin?" and the answer was ~0 before costs. This test changes the two things
that beat us:
1. **What to trade:** each day, only the coins that are outperforming BTC (cross-sectional relative strength, which tends to persist for days in
   crypto), and only when the market regime is risk-on.
2. **What it costs:** maker limit entries (0.02% instead of 0.055% + slippage) and stops of 1.5-3% (instead of 0.6-0.8%), so a round trip costs
   ~0.05 R instead of ~0.25 R.
Disclosed: the 1h data has been used by earlier tests; the regime filter (daily SMA-200 breadth) was built and partly validated here before. The
relative-strength selection and the maker-pullback execution have not been tested in this repo. This is the 11th rule set. Prior: modest.

## Universe and data
- Tradable: **ETH, SOL, ADA, SUI, SEI** USDT perps. Benchmark: BTC. Breadth set (the dashboard's): BTC, ETH, SOL, ADA, SUI.
- 1h candles: OKX swaps for BTC/ETH/SOL/ADA/SUI (2022-10 -> 2026-10-07); SEI from KuCoin spot 15m resampled to 1h. Daily candles from the same files.
  Funding: KuCoin proxies already on disk.
- Test period: from the first day all five breadth coins have a daily SMA-200 (about 2023-11-21) to 2026-10-07. A coin is eligible only once its own
  SMA-200 exists (SEI from about 2024-03).

## Rules (frozen on approval). All times UTC; all daily values from CLOSED daily candles (through yesterday).
1. **Regime:** at least 4 of the 5 breadth coins closed above their SMA-200 yesterday (the dashboard's RISK-ON). Otherwise no orders today.
2. **Eligible:** the coin itself closed above its SMA-200 yesterday.
3. **Relative strength:** RS = coin's 7-day return minus BTC's 7-day return (yesterday's close vs the close 7 days earlier). Take the **top 2** eligible
   coins with RS > 0.
4. **Level:** yesterday's VWAP, from yesterday's 24 1h bars (typical price x volume). Skip the coin if today's 00:00 open is not at least 0.1% above
   the level (then it is not a pullback).
5. **Stop:** yesterday's low minus 0.25 x ATR(14) on 1h (as of yesterday's last bar). If that is closer than 1.5% below the level, use exactly 1.5%
   below the level (minimum width, for costs). If it is more than 3.0% below the level, skip the coin today.
6. **Target:** level + 3 x (level - stop). **Fixed 1:3.** No trailing, no partials, no break-even moves.
7. **Order:** maker limit buy at the level, valid 00:00-23:59 today. Filled only if a 1h bar trades THROUGH it: low < level x (1 - 0.05%)
   (queue conservatism); fill at min(bar open, level). Unfilled orders expire at the end of the day. If a 1h bar opens at or below the
   stop before the order has filled, the order is cancelled.
8. **Exit:** stop (taker 0.055% + 2 bps adverse slippage, gap-aware: at the open if it opens through); target (maker 0.02%, at the target);
   if one 1h bar touches both, the stop is assumed first. **Time stop: 72 hours after the fill**, exit at that bar's close (taker + slippage).
   On the fill bar itself only the stop is checked.
9. **Risk:** $1,000 start, 1% of equity risked per trade (sized at the fill), max leverage 3x, at most 2 open positions, one per coin. **Daily loss
   stop:** once realised R today reaches -2, cancel today's unfilled orders. **Weekly stop:** once the ISO week's realised R reaches -5, no new orders
   until next Monday.
10. **Funding** at 00:00/08:00/16:00 UTC on open notional (KuCoin proxies; 0.01% if none), long pays positive. Reported separately.

## Pass criteria (decided before any result; ALL must hold; run once)
- >= 100 trades.
- Net avg R - 2.5 x SE > 0; net PF >= 1.2; gross avg R > 0.
- Max drawdown < 25%.
- Net avg R > 0 in BOTH time halves.
- **Leave-one-coin-out:** net avg R > 0 with any single coin removed (the result must not rest on one coin).
- **Random-coin control:** beats the 95th percentile of 200 runs that keep every rule except the choice of coin, which is random among that day's
  eligible coins (same number of picks). This is the direct test of the relative-strength idea.
- Prefix (causality) test passes.
Any miss -> FAIL, no retuning.

## Reported, not selecting
No regime filter; top-1 only; taker entry (no maker assumption); fill rate and how often the 1.5% floor or 3% cap applied; per-coin results;
funding paid/received.

## After
- PASS: keep running the journal (below) for >= 60 days; size up only if the forward results agree. Live stays gated.
- FAIL: the journal still runs, because your discretion (approve/skip) is a separate question the backtest cannot answer.

## The paper-forward journal (built alongside, see README)
Every day after 00:05 UTC it proposes the candidates these rules produce (coin, limit level, stop, 3R target, RS, regime). You approve or skip each one.
It then tracks every candidate's outcome on live 1h candles at the costs above: approved ones count as your paper trades; skipped ones are tracked as
"shadow" trades, so after a few weeks you can see whether your approvals beat the system's unfiltered picks.
