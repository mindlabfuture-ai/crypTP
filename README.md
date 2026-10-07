# crypTP

Bybit (USDT perpetuals) toolkit: screen coins, analyze market structure, plan and execute day trades with a TP ladder.

## Pipeline
1. `screener.py` ranks liquid coins by relative strength vs BTC, volume surge, trend and breakout proximity.
2. `structure.py` finds swings, trend (HH/HL vs LH/LL), break of structure, nearest support/resistance.
3. `planner.py` builds a long-only plan: structure stop, TP ladder in R multiples, skipped if too little room to resistance.
4. `risk.py` sizes the position from a fixed % risk, with daily loss limit, max positions and a `KILL` file switch.
5. `executor.py` paper-simulates fills by default. `LiveExecutor` needs `CRYPTP_ALLOW_LIVE=yes` plus `--live`.

## Use
```
pip install -r requirements.txt
python -m pytest
python -m cryptp scan
python -m cryptp analyze BTC/USDT:USDT
python -m cryptp run                 # paper mode, loops every 15 min
python -m cryptp backtest BTC/USDT:USDT --days 90   # needs Bybit access; or use --csv FILE
python -m cryptp run --live          # real orders, see safety below
```
Settings live in `config.yaml`. Copy `.env.example` to `.env` and export the keys for authenticated use.

## Safety
- Default is paper mode on Bybit testnet. Live code is untested against the real exchange: run it on testnet first.
- Use a dedicated sub-account, trade-only API key (no withdrawal), IP whitelist.
- Create a file named `KILL` in the working directory to stop new entries.
- Risk limits are deterministic code, never LLM decisions.
- **Perp guards** (`cryptp/safety.py`, `safety:` in config.yaml), applied by `LiveExecutor` to every live entry. Before the order: leverage
  cap, stop on the losing side, stop distance <= 50% of the distance to the isolated-margin liquidation price, live price within 0.5% of
  the plan, adverse funding under 0.05% per 8h, exchange minimum size/notional. The order goes out on isolated margin with the stop
  attached; if the exchange does not then show that stop, the position is flattened and a `KILL` file is written. Any block is logged,
  not raised to the webhook. `mmr_pct` is an assumption: check Bybit's maintenance-margin tier per symbol. Untested on live Bybit.
- No strategy guarantees TP hits. Backtest and paper trade before risking capital.

## Backtester
`python -m cryptp backtest SYMBOL [--days N | --csv FILE | --synthetic] [--fee 0.055] [--slip 2] [--split 0.7] [--out trades.csv]`

Bar-by-bar replay of the same analyzer, planner, risk gate and paper executor the live agent uses.
- No lookahead: the signal comes from candles up to bar *i*, the fill is at the **open of bar i+1**,
  and the higher-timeframe trend uses only fully closed HTF candles (a test checks that a run on
  truncated data reproduces the full run's earlier trades).
- Costs: taker fee per side, slippage on stop exits, and a stop that gaps fills at the open, not the stop.
- Entry is edge-triggered (plan newly valid) with a cooldown after each exit.
- Output: trades, win rate, average R, profit factor, return, max drawdown, an in-sample / out-of-sample
  split with the *same fixed parameters*, and buy and hold for comparison. It warns below 30 trades.
- It tests crypTP's own structure rules. It does **not** replay the TradingView Wyckoff/SMC alerts: Pine
  cannot run here. To test those, export the alert history and add it as a signal source.
- Fetched candles are cached in `data/`. `--synthetic` is a pipeline check only; its results mean nothing.

## Daily trend dashboard
`/dashboard` (HTML) and `/api/trend` (JSON) on the running service, or `python -m cryptp dashboard [--csv-dir DIR] [--json]`.
For each coin in `config.yaml` -> `dashboard.symbols`: last completed daily close vs its 200-day average (LONG / FLAT), days in
state, move since the flip, distance to the line, 30-day slope of the average, flips in the last year, and the latest perp funding.
**Closed candles only**: today's forming candle is dropped before anything is computed. Reads Bybit *mainnet* public data (no keys,
never testnet). Cached 10 minutes. Set env `DASHBOARD_TOKEN` to require `?token=...`. It is a trend state, not a forecast: see
`docs/TREND_PREREG.md` and `docs/FUNDING_PREREG.md` for what the backtests did and did not show.

## Dumb Money filter (optional)
`cryptp/dumbmoney.py` is a Python port of the signal logic of *Dumb Money Concepts* by theUltimator5
(MPL 2.0, notice kept in the file). That script has no alerts, so it can't be fed in over a webhook; the
logic is computed from candles instead, so it also backtests. `dumb_money.mode` in `config.yaml`:
`off` (default), `veto` (no longs into FOMO / herd exhaustion / chase / index above 70) or
`require` (veto, and also need a recent panic flush, hopelessness or index below 30).
The port is not byte-identical to Pine (indicator seeding differs slightly).

## Benchmarks
`python -m cryptp popular --csv FILE` replays two popular ChartArt strategies (Bollinger+RSI, MACD+SMA200)
with the same costs and split, in their original long/short form and a long-only form, for comparison.

## TradingView
See docs/TRADINGVIEW.md: `python -m cryptp webhook` receives Wyckoff and Smart Money Concepts alerts.

## Paper trade journal (RS pullback)
Rules: docs/RS_PULLBACK_PREREG.md (shared code: `cryptp/rspullback.py`). Every UTC day after 00:05 the journal proposes up to two candidates
(only in the dashboard's RISK-ON regime, the strongest coins vs BTC over 7 days, maker limit at yesterday's VWAP, stop 1.5-3%, fixed 3R target, 72h
time stop). You approve or skip each one; every candidate's outcome is tracked on closed 1h candles at maker/taker costs and funding. Approved
candidates are your paper trades; skipped ones are tracked as "shadow" trades so you can see whether your judgement adds anything. No orders are placed.
- Server: set `JOURNAL_ENABLED=yes` (uses `CRYPTP_DB`), and `JOURNAL_TOKEN` to approve/skip from `/journal?jtoken=...`. `/api/journal` is JSON.
  If `DASHBOARD_TOKEN` is set, it also guards the journal pages.
- CLI: `python -m cryptp.cli journal --tick` (propose + update), `--decide ID approve|skip`, prints the report.

## Not built yet
Claude analyst layer (news/sentiment narrative), persistent trade log, WebSocket feeds.
