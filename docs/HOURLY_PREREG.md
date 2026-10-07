# 1h trend-continuation breakout on SUI, run-the-winner exit with midnight break-even — DRAFT pre-registration

Status: **DRAFT (revised: midnight forced flat replaced by a midnight break-even stop), awaiting approval. Nothing has been run for this rule set.** Rules freeze on approval.

## Why 1h and why this rule
- docs/BOUNCE_PREREG.md: on 15m, costs (~15 bps round trip) took ~0.22 R per trade at a 0.7% median stop. On 1h the stop is wider
  (~1.5-2%), so the same costs are ~0.08-0.10 R. A wider stop is the only lever on cost that does not require a new edge.
- The entry is a plain 24-bar (one day) channel breakout taken only in the daily LONG state. It was NOT designed or tuned on any data
  in this repository: every number below is a convention (24 bars = 1 day, ATR 14, 2 x ATR stop, 3R arm), set before any run.
- Disclosed: related ideas (1h structure/BOS, MACD+SMA200, SuperTrend, liquidity sweep) were already tested on this 1h data and failed;
  this is the 8th candidate on SUI and the data cannot be made unseen. That is why the bar is strict, there are two sanity controls, and
  a mandatory paper-forward period follows any pass.
- Prior expectation: low. A pass means "paper-forward", never "trade live".

## Rules (frozen on approval; long only; SUI 1h built by resampling the OKX 15m swap series, UTC)
1. **Daily state (closed daily candles only).** LONG if the last daily candle dated BEFORE the bar's UTC date closed above its SMA-200
   (same mapping as `cryptp/daily15m.daily_allowed`). Otherwise no trade.
2. **Signal (1h bar close).** close_t > highest high of the previous 24 bars (bar t excluded), and not true on bar t-1 (edge-triggered).
3. **Entry:** next bar's open + 2 bps slippage. No entries on bars opening at/after 20:00 UTC.
4. **Initial stop:** entry - 2.0 x ATR(14) at the signal bar. Skip if the stop is < 0.9% or > 5.0% of entry (the floor keeps costs <= ~0.17 R).
5. **Exit, each bar in this order:**
   a. stop hit -> exit at the stop (gap-aware, 2 bps adverse slippage);
   b. **no profit-taking before +3R.** When a bar's high reaches entry + 3R the stop is raised to entry + 1.5R, effective the NEXT bar;
   c. after that, at each bar close stop = max(stop, highest high since entry - 3.0 x ATR(14)), effective the next bar;
   d. **midnight break-even instead of a forced flat.** At the close of the last bar of each UTC day, if the trade is open and that close is
      above the entry price, the stop is raised to the entry price (break-even, not fee-adjusted), effective the next bar. If the close is at or
      below entry, the stop is left unchanged (a stop cannot be placed above the market). Stops never move down. There is no time exit and no
      cap on how long a trade is held; trades can run for days.
6. **Risk:** $1,000, 1% risk per trade, 3x max leverage, one position, max 2 trades per UTC day, cooldown 4 bars after an exit. A trade held across days keeps the only position slot, so signals during it are skipped.
7. **Costs:** 0.055% per side + 2 bps slippage per fill; funding at **all three** settlements (00:00, 08:00, 16:00 UTC) a trade is open through,
   so overnight holds pay or receive funding (KuCoin proxy `funding_SUI.csv`, 0.01% if none). A long pays when the rate is positive.
   Funding is reported separately, and the pass test is on net results after funding. A break-even stop exit still costs fees and slippage
   (about -0.1 R at a 1.5% stop).
8. Implementation reuses `cryptp/bounce.run_bounce` machinery with the entry/stop/exit parameters above; causality (prefix) test and a
   hand-built exit-mechanics test must pass before the run.

## Data and partitions
- SUI 1h, usable from the first date the daily SMA-200 exists (2023-11-21) to 2026-10-07. Nothing is held out for tuning because nothing is tuned.
- Stability halves (by time, equal bars): H1 and H2. Both are reported; both must pass the sign test below.
- **Replication on SOL** (same rules, same period, SOL's own daily state): not used for design; a pass criterion.
- **Run once.** Any rule change after seeing results voids this registration; a new one must be written first.

## Pass criteria (decided before any result; ALL must hold)
- >= 150 trades on SUI.
- Net avg R - 2.5 x SE(avg R) > 0.
- Net profit factor >= 1.15; gross-of-costs avg R > 0.
- Max drawdown < 25%.
- Net avg R > 0 in BOTH halves H1 and H2.
- Positive net R in at least 60% of calendar months having >= 8 trades.
- Beats the random-entry control at its 95th percentile (200 random entry sets, same count, same exit, same daily-state and cutoff rules).
- SOL replication: net avg R > 0 and profit factor > 1.0 with >= 100 trades.
Any miss -> FAIL, no retuning.

## Controls and secondary (reported, not selecting)
- **Cost sensitivity:** avg R at fees x 0.5, x 1, x 2 (shows whether the verdict hinges on cost assumptions).
- **Midnight-flat variant, labelled SECONDARY:** identical rules except rule 5d is a forced flat at the close of each UTC day (no overnight
  funding). It is reported only to show what the break-even rule changes; it **cannot rescue a primary FAIL** and is not part of pass/fail.
- **Midnight-BE statistics:** how many trades were moved to break-even at least once, how many of those were then stopped at break-even
  (each costing fees and slippage, about -0.1 R), how many went on to reach +3R, and total funding paid and received.
- Fixed +3R target without trail, same entries (what the run-the-winner exit adds).

## After
- FAIL: stop searching for SUI entry signals on this history; remaining supported tools are the daily SMA-200 state (spot), the dashboard
  and the safety checks. The honest next evidence is a paper-forward log of the agent as a discretionary assistant.
- PASS: Bybit-testnet/paper-forward >= 60 days with the same rules before any live capital; live stays gated.
