"""Optional aiohttp health endpoint."""

from __future__ import annotations

import json
from typing import Any, Callable, Awaitable

from aiohttp import web
import structlog

log = structlog.get_logger(__name__)


def create_health_app(status_fn: Callable[[], Awaitable[dict[str, Any]]]) -> web.Application:
    app = web.Application()

    async def health(_: web.Request) -> web.Response:
        payload = await status_fn()
        code = 200 if payload.get("ok", True) else 503
        return web.Response(
            text=json.dumps(payload, ensure_ascii=False),
            status=code,
            content_type="application/json",
        )

    app.router.add_get("/health", health)
    return app


async def start_health_server(
    host: str,
    port: int,
    status_fn: Callable[[], Awaitable[dict[str, Any]]],
) -> web.AppRunner:
    app = create_health_app(status_fn)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host=host, port=port)
    await site.start()
    log.info("health.started", host=host, port=port)
    return runner
