"""aiohttp receiver for TradingView alerts. TradingView posts the body as text/plain JSON."""
from __future__ import annotations

import asyncio
import hmac
import json
import logging

from aiohttp import web

from .signals import parse_signal


def create_app(agent, secret: str) -> web.Application:
    if not secret:
        raise ValueError("TV_WEBHOOK_SECRET must be set")

    async def tv(request: web.Request) -> web.Response:
        try:
            payload = json.loads(await request.text())
        except ValueError:
            return web.json_response({"error": "bad json"}, status=400)
        if not hmac.compare_digest(str(payload.get("secret", "")), secret):
            return web.json_response({"error": "forbidden"}, status=403)
        try:
            sig = parse_signal(payload)
        except ValueError as e:
            return web.json_response({"error": str(e)}, status=400)
        try:
            msg = await asyncio.to_thread(agent.on_signal, sig)      # ccxt is blocking
        except Exception as e:                                       # exchange/network failure
            logging.exception("signal handling failed: %s", sig)
            return web.json_response({"error": f"{type(e).__name__}: {str(e)[:200]}"}, status=502)
        return web.json_response({"ok": True, "result": msg})

    async def health(_):
        return web.json_response({"ok": True})

    app = web.Application()
    app.add_routes([web.post("/tv", tv), web.get("/health", health)])
    return app
