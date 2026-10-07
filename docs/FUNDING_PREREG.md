# Pre-registration: funding-cost check on the daily SMA-200 long/flat filter

Written and committed BEFORE any funding number was applied to a result. Do not edit after the fact; append a dated note instead.

## Question
The SMA-200 long/flat filter (docs/TREND_PREREG.md) held longs for months and ignored perpetual funding. Does it survive paying funding?

## Method
- Strategy unchanged: daily bars, long when close > SMA(200), flat otherwise, fills at the next daily open, 100% equity 1x,
  0.055% fee + 2 bps slippage per fill. Executed on a perpetual, so it pays/receives funding while long.
- Funding model: for each daily bar, sum the funding rates that settle in [00:00, next 00:00) UTC and charge (qty x open price x that sum)
  while the position is held during the bar. Positive rates cost longs; negative rates pay them.
- Funding data: KuCoin futures funding history (the only public source reachable here with multi-year history; OKX keeps ~3 months,
  Gate 180 days). Used as a PROXY for Bybit/OKX funding; checked against OKX over the overlapping recent window and reported.
- Window: per coin, the intersection of price data and funding data. The no-funding result is recomputed on the SAME window so the
  comparison is like for like.
- Comparators: buy-and-hold held as a perp (also pays funding) and buy-and-hold in spot (no funding), both over the same window.

## The filter "survives" only if ALL hold (5 coins: BTC, ETH, SOL, ADA, SUI)
1. Net return after funding and costs is positive on at least 4 of 5 coins; AND
2. Calmar (CAGR / max drawdown) with funding beats perp buy-and-hold with funding on at least 4 of 5; AND
3. CAGR after funding is at least 75% of CAGR without funding on at least 4 of 5 (funding does not eat the edge).
A coin lacking enough funding history for a 200-day-SMA window of at least 2 years is excluded and reported as such.

## Known limits
Proxy funding source; ignores margin/borrow interest and funding-interval changes; two market cycles at best; the filter already missed
the earlier drawdown and robustness bars, so passing this check does NOT make it proven. It only tests whether funding alone breaks it.
Longs can also be held in spot with no funding; this check concerns perp execution.

---
## Results (appended after the run; the pre-registered text above is unchanged)

SMA-200 long/flat, daily, executed on a perpetual and charged KuCoin funding (proxy). Windows are the contiguous funding history per coin
(BTC from 2020-07, ETH 2020-07, SOL 2021-08, ADA 2020-10, SUI 2023-11), 100% settlement coverage.

| | net w/o funding | net with funding | CAGR w/o | CAGR with | retained | max DD with | Calmar with | spot B&H Calmar |
|---|---|---|---|---|---|---|---|---|
| BTC | +813% | +296% | 42.7% | 24.8% | 58% | -75% | 0.33 | 0.56 |
| ETH | +2747% | +756% | 71.4% | 41.2% | 58% | -71% | 0.58 | 0.61 |
| SOL | +1157% | +460% | 63.4% | 39.7% | 63% | -74% | 0.54 | 0.24 |
| ADA | +586% | +59% | 38.2% | 8.1% | 21% | -93% | 0.09 | 0.18 |
| SUI | +186% | +79% | 44.1% | 22.3% | 51% | -76% | 0.29 | 0.34 |

Pre-registered criteria: (1) net > 0 after funding on >= 4 of 5: PASS (5/5). (2) Calmar beats perp buy-and-hold on >= 4 of 5: PASS (5/5),
BUT VACUOUSLY: the perp buy-and-hold comparator (fixed 1x quantity, no liquidation) pays so much funding that its equity goes negative
(drawdowns below -100%), so beating it means little. (3) CAGR after funding >= 75% of CAGR without on >= 4 of 5: FAIL (0 of 5; retained 21-63%).
OVERALL: DOES NOT SURVIVE FUNDING under the pre-registered bar.

Why funding hurts so much: it is not the 12-20%/yr all-days average that matters. A trend filter is long exactly when longs pay most:
annualised funding on the days the filter is LONG was 19% (BTC), 28% (ETH), 27% (SOL), 43% (ADA), 28% (SUI), versus 1-5% on the days it is flat
(SOL -11%).

Post-hoc observation (NOT part of the pre-registration): against spot buy and hold, the filter with funding beats it on Calmar for only 1 of 5
coins (SOL). The filter run on SPOT pays no funding, so its no-funding column is the relevant one for spot execution; the earlier verdict
(failed the drawdown and robustness bars) still applies there.

Proxy check (KuCoin vs OKX, last ~3 months, mean per 8h interval): BTC 0.0030% vs 0.0046%, ETH 0.0045% vs 0.0042%, SOL 0.0019% vs 0.0026%,
ADA 0.0056% vs 0.0065%, SUI 0.0094% vs 0.0065%; correlation of matched rates 0.22-0.80. The levels are the same order of magnitude but the
proxy is noisy and could move individual coins' results either way.
