from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from synelia_kernel.ids import nouvel_id
from synelia_kernel.journal import correlation_id_courant


class CorrelationMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        cid = request.headers.get("x-correlation-id") or nouvel_id()
        request.state.correlation_id = cid
        jeton = correlation_id_courant.set(cid)
        try:
            reponse = await call_next(request)
        finally:
            correlation_id_courant.reset(jeton)
        reponse.headers["X-Correlation-Id"] = cid
        reponse.headers.setdefault("X-Content-Type-Options", "nosniff")
        reponse.headers.setdefault("X-Frame-Options", "DENY")
        reponse.headers.setdefault("Referrer-Policy", "no-referrer")
        reponse.headers.setdefault("Cache-Control", "no-store")
        return reponse
