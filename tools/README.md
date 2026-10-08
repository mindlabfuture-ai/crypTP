# Data pullers and analysis scripts (public endpoints only; set REQUESTS_CA_BUNDLE if behind a TLS-inspecting proxy)
- pull_okx_hourly.py INST DAYS OUT.csv   OKX perpetual 1H candles, e.g. BTC-USDT-SWAP 1460 data/BTC_1h_1460d.csv
- pull_okx_daily.py  INST DAYS OUT.csv   OKX perpetual daily (UTC) candles
- pull_kucoin_funding.py SYMBOL OUT.csv  KuCoin futures funding history, e.g. XBTUSDTM data/funding_BTC.csv
- funding_check.py FOLDER                funding-cost check (FOLDER contains data/)
