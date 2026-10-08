# TradingView alerts -> crypTP

Pine scripts only run inside TradingView, so crypTP consumes their **alerts** over a webhook
and does not reimplement or copy their code.

## 1. Run the receiver
```
export TV_WEBHOOK_SECRET='long-random-string'
python -m cryptp webhook            # paper mode (default)
```
TradingView only calls ports **80/443** over public HTTPS, so host it behind a domain
(e.g. Railway sets `PORT` and gives you HTTPS). Webhooks need a paid TradingView plan.
Webhook URL: `https://<your-host>/tv`. Health check: `GET /health`.

## 2. Create alerts
On a Bybit perpetual chart (`BYBIT:BTCUSDT.P`), add alert -> Condition: the indicator's alert
-> Trigger: **Once Per Bar Close** -> Webhook URL on -> Message (replace the default text):

```
{"secret":"YOUR_SECRET","event":"<EVENT>","symbol":"{{exchange}}:{{ticker}}","tf":"{{interval}}","price":{{close}}}
```

| Indicator alert condition                  | `<EVENT>`          | Role |
|--------------------------------------------|--------------------|------|
| Wyckoff: long entry                        | `wy_long_entry`    | long trigger |
| Wyckoff: Spring                            | `wy_spring`        | long trigger |
| Wyckoff: SOS                               | `wy_sos`           | long trigger |
| Wyckoff: LPS                               | `wy_lps`           | long trigger |
| Wyckoff: Phase C test                      | `wy_ctest`         | long trigger |
| Wyckoff: short entry / SOW / UTAD / LPSY   | `wy_short_entry` `wy_sow` `wy_utad` `wy_lpsy` | exit / veto |
| SMC: Bullish CHoCH / Bullish BOS (swing)   | `smc_bull_choch` `smc_bull_bos` | bullish bias |
| SMC: Bearish CHoCH / Bearish BOS (swing)   | `smc_bear_choch` `smc_bear_bos` | exit / veto |

Use the **swing** SMC alerts (not the "Internal" ones) for bias. Wyckoff Phase E has no direction
in its alert, so it is not used.

## 3. Decision rules (`signals.py`, `agent.py`)
- **Long** when a Wyckoff long trigger is within `wy_ttl_min`, SMC swing bias is bullish within
  `smc_ttl_min` (`require_smc: true`), no bearish Wyckoff event came after the trigger, and the
  planner finds a valid structure stop with enough room. Then the risk gate and sizing apply.
- **Exit** an open position when a bearish Wyckoff event or bearish SMC swing break arrives
  after the entry.
- Everything else is recorded and ignored.

## Limits
- TradingView caps alerts per plan, and each condition on each symbol is its own alert. Roughly
  8 to 10 alerts per coin: use them for a short watchlist, fed from the screener's top picks.
- The Wyckoff script's entry alerts only cover the chart timeframe.
- Both scripts are slow, structure-based tools. Run them on 1H to 4H and let crypTP refine entries.
- Paper mode only: the live executor is untested.
