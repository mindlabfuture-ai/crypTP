"""aiohttp receiver for TradingView alerts. TradingView posts the body as text/plain JSON."""
from __future__ import annotations

import asyncio
import hmac
import json
import logging

from aiohttp import web

from .signals import parse_signal


def create_app(agent, secret: str, dashboard=None, dashboard_token: str = "", journal=None, journal_token: str = "",
               journal_service=None) -> web.Application:
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

    def _journal_ok(request: web.Request, token: str) -> bool:
        return bool(journal_token) and hmac.compare_digest(token, journal_token)

    async def journal_page(request: web.Request) -> web.Response:
        if journal is None:
            return web.Response(status=404, text="journal not enabled")
        if not _authorised(request):
            return web.Response(status=403, text="forbidden")
        from .journal import render_html as render_journal
        tok = request.query.get("jtoken", "")
        err = journal_service.last_error if journal_service is not None else None
        page = await asyncio.to_thread(render_journal, journal, tok, _journal_ok(request, tok), err)
        return web.Response(text=page, content_type="text/html")

    async def journal_json(request: web.Request) -> web.Response:
        if journal is None:
            return web.json_response({"error": "journal not enabled"}, status=404)
        if not _authorised(request):
            return web.json_response({"error": "forbidden"}, status=403)
        rep = await asyncio.to_thread(journal.report)
        rep["candidates"] = await asyncio.to_thread(journal.rows, 200)
        return web.json_response(rep, dumps=lambda o: json.dumps(o, default=str))

    async def journal_decide(request: web.Request) -> web.Response:
        if journal is None:
            return web.json_response({"error": "journal not enabled"}, status=404)
        form = await request.post()
        tok = str(form.get("token", ""))
        if not _journal_ok(request, tok):                         # decisions need JOURNAL_TOKEN; unset = disabled over HTTP
            return web.json_response({"error": "forbidden"}, status=403)
        try:
            cid = int(form.get("id", ""))
        except ValueError:
            return web.json_response({"error": "bad id"}, status=400)
        ok, why = await asyncio.to_thread(journal.decide, cid, str(form.get("action", "")), str(form.get("note", "")))
        if not ok:
            return web.json_response({"error": why}, status=409)
        q = f"?jtoken={tok}" + (f"&token={request.query.get('token', '')}" if dashboard_token else "")
        raise web.HTTPSeeOther("/journal" + q)

    async def root(_):
        raise web.HTTPFound("/dashboard" if dashboard is not None else "/health")

    app = web.Application()
    app.add_routes([web.post("/tv", tv), web.get("/health", health), web.get("/", root),
                    web.get("/dashboard", dash_page), web.get("/api/trend", dash_json),
                    web.get("/journal", journal_page), web.get("/api/journal", journal_json), web.post("/journal/decide", journal_decide)])
    return app
