from __future__ import annotations

import asyncio
import time
from collections import defaultdict

from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.core.config import settings


class RateLimitMiddleware(BaseHTTPMiddleware):
    """IP fixed-window limiter backed by Redis in production.

    Development and tests use a process-local fallback so Redis is not required
    to start the application. Production fails closed when Redis is unavailable.
    """

    def __init__(self, app) -> None:
        super().__init__(app)
        self._redis = Redis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=1,
            socket_timeout=1,
        )
        self._local: dict[tuple[str, int], int] = defaultdict(int)
        self._lock = asyncio.Lock()

    async def dispatch(self, request: Request, call_next):
        if request.url.path in {"/", "/health", "/webhook/github"}:
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"
        window = int(time.time()) // settings.RATE_LIMIT_WINDOW_SECONDS
        key = f"rate:{client_ip}:{window}"
        try:
            count = await self._redis.incr(key)
            if count == 1:
                await self._redis.expire(key, settings.RATE_LIMIT_WINDOW_SECONDS + 1)
        except Exception:
            if settings.APP_ENV.lower() == "production":
                return JSONResponse(
                    status_code=503,
                    content={"detail": "Rate limit service unavailable"},
                )
            async with self._lock:
                count = self._local[(client_ip, window)] + 1
                self._local[(client_ip, window)] = count
                if len(self._local) > 4096:
                    self._local = {
                        bucket: value
                        for bucket, value in self._local.items()
                        if bucket[1] >= window - 1
                    }

        if count > settings.RATE_LIMIT_REQUESTS:
            retry_after = settings.RATE_LIMIT_WINDOW_SECONDS - (
                int(time.time()) % settings.RATE_LIMIT_WINDOW_SECONDS
            )
            return JSONResponse(
                status_code=429,
                headers={"Retry-After": str(retry_after)},
                content={"detail": "Rate limit exceeded"},
            )
        return await call_next(request)
