# SEI and UB assessment (2026-10-07)

Sources: CoinMarketCap quotes (all-venue), KuCoin SPOT candles pulled with `tools/pull_kucoin_spot.py` (OKX lists SEI perps only from
2025-11-14 and UB perps from 2026-04-28, so it is too short; Bybit is not reachable from this sandbox, so the Bybit perps themselves are
unverified). Spot price history is a proxy for the perp.

| | SEI | UB (Unibase) | SUI (reference) |
|---|---|---|---|
| CMC rank / market cap | 91 / $517M | 217 / $352M | - |
| All-venue 24h volume | $51.8M | **$3.4M** | - |
| KuCoin spot volume, 7d avg per day | $9.0M | **~$0.0M (median 15m bar $3.8k, 5% zero-volume bars)** | $165M |
| History available | 2023-08-15 -> now (1,150 days, 110,323 15m bars) | **2025-09-12 -> now (391 days, 37,470 15m bars)** | 2023-05 -> now |
| Median daily range (all / last 90d) | 7.3% / 4.7% | 12.4% / 10.4% | 7.4% / 5.3% |
| Median 15m bar range / round-trip cost (0.15%) | 0.57% / 3.8x | 0.92% / 6.1x (last 30d only 0.28%: thin book) | 0.63% / 4.2x |
| Correlation of daily returns to BTC (all / last 90d) | 0.59 / 0.55 | **0.14 / 0.15** | 0.61 / 0.68 |
| Distance from all-time high | -94% | -43% | -78% |
| Daily trend state (SMA-200, closed candles) | LONG (16 days), +34% above | LONG (173 days), +30% above | LONG (18 days) |
| Circulating / total supply | 7.58B / 10B (76%) | **2.5B / 10B (25%)** | - |
| Percent change 30d / 90d / 1y | +39% / +44% / -76% | +4% / +95% / +306% | - |

Reading, plainly:
- **SEI** is a usable SUI-like candidate: similar volatility and BTC beta, adequate liquidity, three years of 15m history that this repo has
  never touched. It is also a **fresh-data test**, which is the only kind that can still tell us anything new. Caveats: -76% over a year and
  -94% from its high; it just flipped LONG 16 days ago.
- **UB** is a different animal and a poor scalping candidate on current evidence: $3.4M of all-venue daily volume means wide spreads and
  slippage far above the 2 bps assumed for SUI (a $1,000 account is fine size-wise, but fills at the quoted price are not). Only 25% of the
  supply circulates, so unlock supply is a standing risk (I have NOT checked the unlock schedule). 391 days of history with one regime
  (+306% in a year) cannot validate anything, and the KuCoin spot market I can read is far thinner than wherever it trades most. Its low
  BTC correlation is real but also means a BTC-led market will not carry it.
- Neither can be confirmed on Bybit from here: check that SEIUSDT and UBUSDT are listed as linear perps with enough open interest before
  funding any plan.
