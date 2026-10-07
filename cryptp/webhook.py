"""aiohttp receiver for TradingView alerts. TradingView posts the body as text/plain JSON."""
from __future__ import annotations

import asyncio
import hmac
import json
import logging

from aiohttp import web

from .signals import parse_signal


def create_app(agent, secret: str, dashboard=None, dashboard_token: str = "") -> web.Application:
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

    def _authorised(request: web.Request) -> bool:
        return not dashboard_token or hmac.compare_digest(request.query.get("token", ""), dashboard_token)

    async def dash_page(request: web.Request) -> web.Response:
        if dashboard is None:
            return web.Response(status=404, text="dashboard not enabled")
        if not _authorised(request):
            return web.Response(status=403, text="forbidden")
        from .dashboard import render_html
        rep = await asyncio.to_thread(dashboard.get)
        return web.Response(text=render_html(rep), content_type="text/html")

    async def dash_json(request: web.Request) -> web.Response:
        if dashboard is None:
            return web.json_response({"error": "dashboard not enabled"}, status=404)
        if not _authorised(request):
            return web.json_response({"error": "forbidden"}, status=403)
        return web.json_response(await asyncio.to_thread(dashboard.get))

    async def root(_):
        raise web.HTTPFound("/dashboard" if dashboard is not None else "/health")

    app = web.Application()
    app.add_routes([web.post("/tv", tv), web.get("/health", health), web.get("/", root),
                    web.get("/dashboard", dash_page), web.get("/api/trend", dash_json)])
    return app
