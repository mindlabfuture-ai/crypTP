# Pre-registration: daily SMA-200 trend regime strategy

Written and committed BEFORE any result was computed. Do not edit after the fact; append a dated note instead.

## Rules (no tuned parameters)
- Daily bars (UTC). Signal at the daily close, fill at the NEXT daily open.
- Long when close > SMA(200); flat when close < SMA(200). (Variant B: short when close < SMA(200).)
- 100% of equity, 1x, no stop, no target. Costs: 0.055% taker fee per side + 2 bps slippage per fill.
- Primary spec is SMA(200). SMA 100 / 150 / 250 are SENSITIVITY checks only, never used to choose a value.
- Coins: BTC, ETH, SOL, ADA, SUI (same five as before). Data: OKX perpetual daily candles, full available history.
- Funding costs on perpetuals are not modelled (a long held for months pays funding in most regimes); this flatters longs.

## What "works" means (judged against buy and hold on the same coin/period)
A trend filter is a risk-management tool, so it is judged on risk-adjusted terms, not on beating a bull market:
1. Calmar (CAGR / max drawdown) higher than buy and hold on at least 4 of the 5 coins; AND
2. Max drawdown at most 60% of buy-and-hold's on at least 4 of 5 coins; AND
3. Net return after costs positive on at least 3 of 5 coins; AND
4. Same conclusion (1 and 3) at SMA 150 and SMA 250, i.e. not a knife-edge.
Fewer trades means weak per-trade statistics, so no claim of "edge" is made from trade win rates.

## Known limits
Only about two market cycles of data; five highly correlated coins are not five independent tests;
coins with short history (SUI from May 2023) cannot have a 200-day average before about Nov 2023.
