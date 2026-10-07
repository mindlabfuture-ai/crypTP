from __future__ import annotations

import argparse
import os
import time

from .config import load_config
from .exchange import fetch_ohlcv_df, make_exchange, make_public_exchange
from .safety import SafetyError
from .executor import LiveExecutor, PaperExecutor
from .indicators import atr
from .planner import build_plan_any
from .risk import RiskGate, position_size
from .screener import scan
from .structure import analyze


def _structure(ex, cfg, symbol):
    s = cfg.structure
    df = fetch_ohlcv_df(ex, symbol, s.timeframe, 300)
    htf = fetch_ohlcv_df(ex, symbol, s.htf, 200)
    ms = analyze(df, s.swing_left, s.swing_right)
    htf_ms = analyze(htf, s.swing_left, s.swing_right)
    return df, ms, htf_ms


def cmd_scan(cfg, _):
    print(scan(make_exchange(cfg), cfg).round(3).to_string())


def cmd_analyze(cfg, args):
    ex = make_exchange(cfg)
    df, ms, htf = _structure(ex, cfg, args.symbol)
    price, a = float(df["close"].iloc[-1]), float(atr(df).iloc[-1])
    print(f"{args.symbol} price={price} atr={a:.4f}")
    print(f"LTF trend={ms.trend} bos={ms.bos} support={ms.support} resistance={ms.resistance}")
    print(f"HTF trend={htf.trend}")
    plan = build_plan_any(args.symbol, price, a, ms, htf.trend, cfg.plan)
    print(plan or "no valid long plan")


def cmd_run(cfg, args):
    live = args.live
    ex = make_exchange(cfg, authed=live)
    if live:
        executor = LiveExecutor(ex, getattr(cfg, "safety", None), cfg.risk.max_leverage)
        equity = float(ex.fetch_balance()["USDT"]["total"])
    else:
        executor = PaperExecutor(cfg.risk.paper_equity)
        equity = cfg.risk.paper_equity
    gate = RiskGate(cfg.risk)
    print(f"mode={'LIVE' if live else 'PAPER'} testnet={cfg.exchange.testnet}")
    while True:
        today = time.strftime("%Y-%m-%d", time.gmtime())
        if today != getattr(gate, "day", today):
            gate.daily_pnl = 0.0
        gate.day = today
        if live:
            gate.open_symbols = {x["symbol"] for x in ex.fetch_positions() if float(x.get("contracts") or 0) > 0}
        else:
            gate.open_symbols = set(executor.positions)
        if not live:
            equity = executor.equity
            for sym in list(executor.positions):
                c = fetch_ohlcv_df(ex, sym, cfg.structure.timeframe, 2).iloc[-1]
                gate.daily_pnl += executor.on_candle(sym, float(c["high"]), float(c["low"]))
        for _, row in scan(ex, cfg).iterrows():
            df, ms, htf = _structure(ex, cfg, row["symbol"])
            price, a = float(df["close"].iloc[-1]), float(atr(df).iloc[-1])
            plan = build_plan_any(row["symbol"], price, a, ms, htf.trend, cfg.plan)
            if not plan:
                continue
            ok, why = gate.check(plan, equity)
            if not ok:
                print(f"blocked {plan.symbol}: {why}")
                continue
            qty = position_size(equity, plan, cfg.risk.risk_per_trade_pct, cfg.risk.max_leverage)
            print(f"ENTER {plan.symbol} qty={qty:.4f} entry={plan.entry} sl={plan.stop} tps={plan.targets}")
            try:
                executor.submit(plan, qty)
            except SafetyError as e:
                print(f"blocked {plan.symbol} by perp safety check: {e}")
                continue
            gate.open_symbols.add(plan.symbol)
        time.sleep(args.interval)


def cmd_backtest(cfg, args):
    import os as _os

    from .backtest import (format_summary, load_csv, run_backtest, split_trades, summarize,
                           synthetic_ohlcv)
    from .exchange import fetch_ohlcv_history

    tf = cfg.structure.timeframe
    if args.synthetic:
        print("SYNTHETIC random-walk data: a pipeline check only, results are meaningless")
        df = synthetic_ohlcv(seed=1)
    elif args.csv:
        df = load_csv(args.csv)
    else:
        cache = f"data/{args.symbol.replace('/', '_').replace(':', '_')}_{tf}_{args.days}d.csv"
        if _os.path.exists(cache):
            df = load_csv(cache)
        else:
            df = fetch_ohlcv_history(make_exchange(cfg), args.symbol, tf, args.days)
            _os.makedirs("data", exist_ok=True)
            df.to_csv(cache, index=False)
    cfg.risk.paper_equity = args.equity
    if args.stop_mult is not None:
        cfg.plan.min_stop_cost_mult = args.stop_mult
    res = run_backtest(df, args.symbol, cfg, fee_rate=args.fee / 100, slippage_bps=args.slip,
                       dm_mode=args.dm, sides=args.sides)
    print(f"{args.symbol} {tf}  {df['ts'].iloc[0]:%Y-%m-%d} -> {df['ts'].iloc[-1]:%Y-%m-%d}  "
          f"{len(df)} bars  fee {args.fee}%/side  slippage {args.slip}bps  start equity {args.equity}  dumb-money {args.dm or cfg.dumb_money.mode}  sides {args.sides or cfg.plan.sides}")
    print(format_summary("ALL", summarize(res.trades, res.equity0, res.equity)))
    ins, oos, cut = split_trades(res.trades, args.split, df)
    print(format_summary(f"in-sample", summarize(ins, res.equity0)))
    print(format_summary(f"out-of-sample", summarize(oos, res.equity0)) + f"   (split {cut:%Y-%m-%d})")
    print(f"buy & hold over the same period: {res.buy_hold_pct:+.1f}%")
    if len(res.trades) < 30:
        print(f"WARNING: only {len(res.trades)} trades. Too few to conclude anything.")
    if args.out:
        import pandas as pd
        pd.DataFrame([{**t.__dict__, "r": t.r} for t in res.trades]).to_csv(args.out, index=False)
        print(f"trades written to {args.out}")


def cmd_popular(cfg, args):
    """Benchmark the two ChartArt strategies on the same data and costs."""
    from .backtest import load_csv, synthetic_ohlcv
    from .popular import STRATEGIES, format_fills, run_reversal, summarize_fills

    df = synthetic_ohlcv(seed=1) if args.synthetic else load_csv(args.csv)
    cut = df["ts"].iloc[int(len(df) * args.split)]
    print(f"{args.csv or 'synthetic'}  {df['ts'].iloc[0]:%Y-%m-%d} -> {df['ts'].iloc[-1]:%Y-%m-%d}  {len(df)} bars  "
          f"fee {args.fee}%/side  slippage {args.slip}bps  100% equity, 1x")
    for name, fn in STRATEGIES.items():
        ls, ss = fn(df)
        for long_only in (False, True):
            r = run_reversal(df, ls, ss, name, long_only, args.fee / 100, args.slip, args.equity)
            tag = f"{name}/{'long' if long_only else 'both'}"
            print(format_fills(tag, summarize_fills(r.trades, r.equity0, r.equity)))
            ins = [t for t in r.trades if t.entry_ts < cut]
            oos = [t for t in r.trades if t.entry_ts >= cut]
            print("   " + format_fills("in-sample", summarize_fills(ins, r.equity0)))
            print("   " + format_fills("out-of-sample", summarize_fills(oos, r.equity0)))
    print(f"buy & hold over the same period: {r.buy_hold_pct:+.1f}%")


def cmd_trend(cfg, args):
    """Daily SMA trend-regime backtest vs buy and hold (rules fixed in docs/TREND_PREREG.md)."""
    from .backtest import load_csv
    from .trend import evaluate

    df = load_csv(args.csv)
    for lo in (True, False):
        r = evaluate(df, args.sma, lo, args.fee / 100, args.slip, args.equity)
        s, h = r["strat"], r["hold"]
        print(f"SMA{args.sma} {'long/flat ' if lo else 'long/short'} {r['start']} -> {r['end']}  trades {r['trades']}  "
              f"in-market {r['time_in_market_pct']:.0f}%  net {s['total_pct']:+.0f}%  CAGR {s['cagr_pct']:+.1f}%  "
              f"maxDD {s['max_dd_pct']:.0f}%  Calmar {s['calmar']:.2f}" + ("  RUINED" if r["ruined"] else ""))
    print(f"buy & hold                                          net {h['total_pct']:+.0f}%  CAGR {h['cagr_pct']:+.1f}%  "
          f"maxDD {h['max_dd_pct']:.0f}%  Calmar {h['calmar']:.2f}")
    state = "ABOVE (trend filter says LONG)" if r["last_close"] > r["last_sma"] else "BELOW (trend filter says FLAT)"
    print(f"latest close {r['last_close']:.4f} vs SMA{args.sma} {r['last_sma']:.4f}: {state}")


def _dashboard_service(cfg, ex=None, csv_dir=None):
    """`ex` is ignored on purpose: the dashboard always reads mainnet public data (never the trading agent's testnet)."""
    from .backtest import load_csv
    from .dashboard import DashboardService

    d = cfg.dashboard
    if csv_dir:
        import os as _os

        def fetch(sym):
            coin = sym.split("/")[0]
            spot = f"{csv_dir}/{coin}_spot_1d.csv"                  # spot symbols (no ':') prefer a *_spot_1d.csv file
            return load_csv(spot if ":" not in sym and _os.path.exists(spot) else f"{csv_dir}/{coin}_1d.csv")
        funding = None
    else:
        pub = make_public_exchange()
        fetch = lambda sym: fetch_ohlcv_df(pub, sym, "1d", 800)

        def funding(sym):
            fr = pub.fetch_funding_rate(sym)
            iv = str(fr.get("interval") or "8h")
            hours = float(iv[:-1]) if iv[:-1].replace(".", "").isdigit() and iv.endswith("h") else 8.0
            return float(fr["fundingRate"]) * (24 / hours) * 365 * 100
    return DashboardService(fetch, d.symbols, d.sma, d.near_pct, d.cache_seconds, funding, getattr(d, "watchlist", []))


def cmd_dashboard(cfg, args):
    import json as _json

    from .dashboard import render_text

    svc = _dashboard_service(cfg, None, args.csv_dir)
    rep = svc.get()
    print(_json.dumps(rep, indent=1, default=str) if args.json else render_text(rep))


def cmd_webhook(cfg, args):
    import asyncio

    from aiohttp import web

    from .agent import TradeAgent
    from .signals import SignalBook
    from .webhook import create_app

    live = args.live
    ex = make_exchange(cfg, authed=live)
    executor = LiveExecutor(ex, getattr(cfg, "safety", None), cfg.risk.max_leverage) if live else PaperExecutor(cfg.risk.paper_equity)

    def get_market(sym):
        df, ms, htf = _structure(ex, cfg, sym)
        return float(df["close"].iloc[-1]), float(atr(df).iloc[-1]), ms, htf.trend

    def get_candle(sym):
        c = fetch_ohlcv_df(ex, sym, cfg.structure.timeframe, 2).iloc[-1]
        return float(c["high"]), float(c["low"])

    def get_dm(sym):
        from .dumbmoney import compute
        d = cfg.dumb_money
        f = compute(fetch_ohlcv_df(ex, sym, cfg.structure.timeframe, 300), d.euphoria_bars,
                    d.capitulation_bars, d.index_hot, d.index_cold)
        return f.iloc[-2]                     # last CLOSED candle (the newest one is still forming)

    equity = (lambda: float(ex.fetch_balance()["USDT"]["total"])) if live else (lambda: executor.equity)
    agent = TradeAgent(cfg, SignalBook(cfg.signals, os.environ.get("CRYPTP_DB")), RiskGate(cfg.risk), executor, get_market, equity,
                       get_candle, live, get_dm, cfg.dumb_money.mode)

    async def ticker(_app):
        async def loop():
            while True:
                await asyncio.to_thread(agent.tick)
                await asyncio.sleep(60)
        task = asyncio.create_task(loop())
        yield
        task.cancel()

    dash = _dashboard_service(cfg)
    app = create_app(agent, os.environ.get("TV_WEBHOOK_SECRET", ""), dash, os.environ.get("DASHBOARD_TOKEN", ""))

    async def warm(_app):                                   # build the first report in the background so page 1 is fast
        asyncio.create_task(asyncio.to_thread(dash.get))
    app.on_startup.append(warm)
    app.cleanup_ctx.append(ticker)
    port = int(os.environ.get("PORT", cfg.signals.port))
    print(f"mode={'LIVE' if live else 'PAPER'} testnet={cfg.exchange.testnet} port={port}")
    web.run_app(app, port=port)


def main():
    p = argparse.ArgumentParser(prog="cryptp")
    p.add_argument("--config", default="config.yaml")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("scan")
    a = sub.add_parser("analyze")
    a.add_argument("symbol")
    r = sub.add_parser("run")
    r.add_argument("--live", action="store_true")
    r.add_argument("--interval", type=int, default=900)
    b = sub.add_parser("backtest")
    b.add_argument("symbol", nargs="?", default="BTC/USDT:USDT")
    b.add_argument("--days", type=int, default=90)
    b.add_argument("--csv")
    b.add_argument("--synthetic", action="store_true")
    b.add_argument("--fee", type=float, default=0.055, help="percent per side (Bybit linear taker)")
    b.add_argument("--slip", type=float, default=2.0, help="stop-exit slippage in bps")
    b.add_argument("--equity", type=float, default=1000.0)
    b.add_argument("--split", type=float, default=0.7)
    b.add_argument("--dm", choices=["off", "veto", "require"], help="dumb-money filter (default: config)")
    b.add_argument("--stop-mult", type=float, help="override plan.min_stop_cost_mult (0 = no fee-aware stop filter)")
    b.add_argument("--sides", choices=["long", "short", "both"], help="override plan.sides")
    b.add_argument("--out")
    pp = sub.add_parser("popular")
    pp.add_argument("--csv")
    pp.add_argument("--synthetic", action="store_true")
    pp.add_argument("--fee", type=float, default=0.055)
    pp.add_argument("--slip", type=float, default=2.0)
    pp.add_argument("--equity", type=float, default=1000.0)
    pp.add_argument("--split", type=float, default=0.7)
    t = sub.add_parser("trend")
    t.add_argument("--csv", required=True)
    t.add_argument("--sma", type=int, default=200)
    t.add_argument("--fee", type=float, default=0.055)
    t.add_argument("--slip", type=float, default=2.0)
    t.add_argument("--equity", type=float, default=1000.0)
    db = sub.add_parser("dashboard")
    db.add_argument("--csv-dir", help="read DIR/{COIN}_1d.csv instead of fetching from the exchange")
    db.add_argument("--json", action="store_true")
    w = sub.add_parser("webhook")
    w.add_argument("--live", action="store_true")
    args = p.parse_args()
    cfg = load_config(args.config)
    {"scan": cmd_scan, "analyze": cmd_analyze, "run": cmd_run, "webhook": cmd_webhook, "backtest": cmd_backtest, "popular": cmd_popular, "trend": cmd_trend, "dashboard": cmd_dashboard}[args.cmd](cfg, args)


if __name__ == "__main__":
    main()
