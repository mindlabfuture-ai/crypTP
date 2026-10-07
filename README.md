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
python -m cryptp run --live          # real orders, see safety below
```
Settings live in `config.yaml`. Copy `.env.example` to `.env` and export the keys for authenticated use.

## Safety
- Default is paper mode on Bybit testnet. Live code is untested against the real exchange: run it on testnet first.
- Use a dedicated sub-account, trade-only API key (no withdrawal), IP whitelist.
- Create a file named `KILL` in the working directory to stop new entries.
- Risk limits are deterministic code, never LLM decisions.
- No strategy guarantees TP hits. Backtest and paper trade before risking capital.

## Not built yet
Backtester, Claude analyst layer (news/sentiment narrative), TradingView webhook receiver, persistent trade log, WebSocket feeds.
