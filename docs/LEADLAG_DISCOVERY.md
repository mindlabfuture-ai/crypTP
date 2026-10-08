# SOL -> SUI lead-lag discovery (first 50% of history only)

Data: SUI and SOL 15m (OKX swaps), 2023-05-06 -> 2026-10-07. Discovery window = first 50%: 2023-05-06 -> 2025-01-20 (59,997 bars).
The last 50% was not read. Script: `tools/leadlag_discovery.py`. (A first run read a half-written SOL file and was discarded; this is
the rerun on the complete file.)

| Finding | Result |
|---|---|
| Contemporaneous 15m return correlation | 0.60 (beta of SUI on SOL 0.73) |
| SUI return at t vs SOL return at t-k, k = 1..5 | -0.009, -0.007, -0.005, -0.002, -0.001 (no lead) |
| Regress SUI fwd 4-bar return on SUI own past 4 bars and SOL past 4 bars (non-overlapping, n=14,998) | SUI own t = +0.29, SOL t = -0.52 |
| "SUI lagged a SOL move" top 5% (n=3,000), fwd 4 bars | +9 to +12 bps depending on lookback (all bars +0.8) |
| Control: SUI's OWN worst 5% 4-bar drops, fwd 4 bars | **+16.2 bps** |

Reading: SOL does not lead SUI at 15m. The apparent "catch-up" signal is a bounce in SUI after its own sharp drops, which the control
reproduces without SOL (and is larger). The tail bounce (~+16 bps over 4 bars, a post-hoc 5% cut) is about the size of a round trip
(0.055% x 2 fees + 2 x 2 bps slippage = ~15 bps), so it is not a tradeable edge as measured; only a different exit (running
winners) could change that, and that is a hypothesis, not a finding.

Decision: the SOL lead-lag hypothesis is rejected. The validation (25%) and final-holdout (25%) segments are untouched.
