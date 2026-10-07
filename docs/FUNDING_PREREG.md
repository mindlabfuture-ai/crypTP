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
