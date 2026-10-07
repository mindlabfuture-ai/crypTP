# Daily direction + 15m entry timing, 1:3 RR (SUI) — DRAFT pre-registration

Status: **DRAFT, awaiting approval. Nothing has been run on data.** Rules freeze when approved.

## Idea
The daily dashboard state decides *whether* we may trade; the 15m chart decides *when*.

## Rules (frozen on approval)
1. **Direction (daily, closed candles only).** For each 15m bar, use the most recent daily candle whose UTC date is
   strictly before the bar's date. State = LONG if that close > SMA-200 of closed daily closes, else FLAT.
   FLAT means no new trades (long-only; shorts are not tested here).
2. **Entry timing (15m), only while LONG.** Pullback-and-resume:
   - trend: bar close > EMA(50);
   - pullback: within the last 12 bars, some low <= EMA(20);
   - trigger: bar close > EMA(20) AND close > previous bar's high.
   Signal at bar close, fill at next bar's open (+2 bps slippage). Edge-triggered, cooldown 8 bars after an exit.
3. **Stop** = lowest low of the last 12 bars minus 0.1 x ATR(14). Skip if stop distance < 0.45% or > 3.0% of entry.
4. **Target** = single take-profit at **3.0 R**. No partials, no breakeven move.
5. **Day trade:** no entries after 20:00 UTC; any open position is closed at the last bar close of the UTC day.
6. **Risk:** $1,000 start, 1% of equity per trade, max leverage 3x, one position, max 3 trades/day.
7. **Costs:** 0.055% per side taker fee + 2 bps slippage. Funding ignored (intraday holds, mostly flat at 00:00 UTC).

## Data and split
SUI 15m, 2023-05-05 -> 2026-10-07 (120,141 bars) with the daily SMA-200 built from the SUI daily file.
70% in-sample / 30% out-of-sample by time. **No parameter is tuned; one run only.**

## Pass criteria (decided before seeing results)
Break-even win rate at 1:3 is ~25% before costs, ~26-29% after.
- >= 100 trades total.
- Full-sample avg R - 2.5 x SE(avg R) > 0 (strict, because this is the Nth candidate on the same SUI data).
- Out-of-sample avg R > 0 and profit factor > 1.
- Max drawdown < 25%.
Miss any one -> reported as FAIL, with no re-tuning on this data.

## Controls (reported alongside, not used for selection)
- Same 15m trigger with the daily filter OFF (shows whether the daily filter adds anything).
- Same 15m trigger with the filter inverted (trade only when FLAT).
- Prefix/causality test: results on truncated data match the full run for early trades.
