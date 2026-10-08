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

---
## Results (appended after the run; the pre-registered text above is unchanged)

SMA200, long/flat, daily, costs included, OKX perpetual data (BTC/ETH from 2020, SOL from 2021, ADA from 2020, SUI from 2023).

| | strategy net / maxDD / Calmar | buy & hold net / maxDD / Calmar |
|---|---|---|
| BTC | +813% / -64% / 0.67 | +833% / -77% / 0.56 |
| ETH | +2747% / -58% / 1.24 | +1044% / -79% / 0.61 |
| SOL | +1157% / -66% / 0.96 | +197% / -96% / 0.24 |
| ADA | +635% / -84% / 0.47 | +180% / -95% / 0.20 |
| SUI | +186% / -72% / 0.61 | +112% / -88% / 0.34 |

Criteria: (1) Calmar > buy and hold on 5 of 5: PASS. (3) net > 0 on 5 of 5: PASS.
(2) max drawdown <= 60% of buy and hold's on >= 4 of 5: FAIL (0 of 5; the filter cut drawdowns by only 12-32%).
(4) robustness: at SMA150 criteria 1 and 3 hold, but at SMA250 Calmar beats buy and hold on only 3 of 5: FAIL.
Overall: DOES NOT MEET THE PRE-REGISTERED BAR.

Observations: the filter avoided most of the 2022 bear (BTC +0% vs -65%, ETH -18% vs -68%) but did NOT protect in 2025
(BTC -18% vs -7% held; ADA -75% vs -64%) because the 200-day average lags a fast crash. Long/short was worse than long/flat
(BTC Calmar 0.33 vs 0.67; ADA near zero), so shorts again added risk without edge. Funding costs are not modelled.
Survivorship: these five coins are survivors, picked with hindsight. About two market cycles of data.
Status on 2026-10-07: all five coins closed above their SMA200 (BTC +19%, ETH +27%, SOL +40%, ADA +26%, SUI +38%).
