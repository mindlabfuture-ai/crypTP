from __future__ import annotations

import argparse
import os
import time

from .config import load_config
from .exchange import fetch_ohlcv_df, make_exchange
from .executor import LiveExecutor, PaperExecutor
from .indicators import atr
from .planner import build_plan
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
    plan = build_plan(args.symbol, price, a, ms, htf.trend, cfg.plan)
    print(plan or "no valid long plan")


def cmd_run(cfg, args):
    live = args.live
    ex = make_exchange(cfg, authed=live)
    if live:
        executor = LiveExecutor(ex)
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
            plan = build_plan(row["symbol"], price, a, ms, htf.trend, cfg.plan)
            if not plan:
                continue
            ok, why = gate.check(plan, equity)
            if not ok:
                print(f"blocked {plan.symbol}: {why}")
                continue
            qty = position_size(equity, plan, cfg.risk.risk_per_trade_pct, cfg.risk.max_leverage)
            print(f"ENTER {plan.symbol} qty={qty:.4f} entry={plan.entry} sl={plan.stop} tps={plan.targets}")
            executor.submit(plan, qty)
            gate.open_symbols.add(plan.symbol)
        time.sleep(args.interval)


def cmd_webhook(cfg, args):
    import asyncio

    from aiohttp import web

    from .agent import TradeAgent
    from .signals import SignalBook
    from .webhook import create_app

    live = args.live
    ex = make_exchange(cfg, authed=live)
    executor = LiveExecutor(ex) if live else PaperExecutor(cfg.risk.paper_equity)

    def get_market(sym):
        df, ms, htf = _structure(ex, cfg, sym)
        return float(df["close"].iloc[-1]), float(atr(df).iloc[-1]), ms, htf.trend

    def get_candle(sym):
        c = fetch_ohlcv_df(ex, sym, cfg.structure.timeframe, 2).iloc[-1]
        return float(c["high"]), float(c["low"])

    equity = (lambda: float(ex.fetch_balance()["USDT"]["total"])) if live else (lambda: executor.equity)
    agent = TradeAgent(cfg, SignalBook(cfg.signals, os.environ.get("CRYPTP_DB")), RiskGate(cfg.risk), executor, get_market, equity,
                       get_candle, live)

    async def ticker(_app):
        async def loop():
            while True:
                await asyncio.to_thread(agent.tick)
                await asyncio.sleep(60)
        task = asyncio.create_task(loop())
        yield
        task.cancel()

    app = create_app(agent, os.environ.get("TV_WEBHOOK_SECRET", ""))
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
    w = sub.add_parser("webhook")
    w.add_argument("--live", action="store_true")
    args = p.parse_args()
    cfg = load_config(args.config)
    {"scan": cmd_scan, "analyze": cmd_analyze, "run": cmd_run, "webhook": cmd_webhook}[args.cmd](cfg, args)


if __name__ == "__main__":
    main()
