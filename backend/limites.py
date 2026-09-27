"""Ventanas por IP y cuotas diarias independientes, en memoria del único proceso."""

import os
import threading
import time
from collections import deque
from datetime import datetime, timezone

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

LIMITED_PATHS = {"/tasks/draft", "/tasks/draft/review", "/evaluate"}
WINDOW_SECS = 60
MSG_PER_IP = ("Demasiadas solicitudes al motor de análisis desde tu conexión. "
              "Espera un minuto y vuelve a intentarlo.")
MSG_DAILY = ("Se alcanzó el límite diario de {group} de esta demo. "
             "Vuelve a intentarlo mañana.")


class RateLimited(Exception):
    def __init__(self, message: str, retry_after: int):
        super().__init__(message)
        self.retry_after = retry_after


def limited_response(exc: RateLimited) -> JSONResponse:
    return JSONResponse(status_code=429, content={"error": "RATE_LIMITED", "message": str(exc)},
                        headers={"Retry-After": str(exc.retry_after)})


def _limit(name: str, default: int = 0) -> int:
    try:
        return max(0, int(os.environ.get(name, str(default)).strip() or 0))
    except ValueError:
        return 0


def client_ip(request) -> str:
    # Railway debe agregar la IP del cliente AL FINAL y ser la única entrada pública al servicio.
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded and forwarded.rsplit(",", 1)[-1].strip():
        return forwarded.rsplit(",", 1)[-1].strip()
    return request.client.host if request.client else "desconocida"


class RateLimiter:
    def __init__(self, clock=time.time):
        self.clock = clock
        self.hits: dict[tuple[str, str], deque] = {}
        self.day: str | None = None
        self.day_count = {"borrador": 0, "motor": 0}
        self.lock = threading.Lock()

    def check_ip(self, ip: str, per_minute: int, bucket: str = "gemini") -> RateLimited | None:
        now = self.clock()
        with self.lock:
            # También retirar IPs inactivas: no depender de que vuelvan a hacer una petición.
            for key, window in list(self.hits.items()):
                while window and window[0] <= now - WINDOW_SECS:
                    window.popleft()
                if not window:
                    del self.hits[key]
            if not per_minute:
                return None
            key = (bucket, ip)
            window = self.hits.setdefault(key, deque())
            if len(window) >= per_minute:
                return RateLimited(MSG_PER_IP, max(1, int(window[0] + WINDOW_SECS - now) + 1))
            window.append(now)
        return None

    def consume_daily(self, group: str) -> None:
        daily = _limit(f"RATE_LIMIT_DAILY_{group.upper()}", _limit("RATE_LIMIT_DAILY"))
        if not daily:
            return
        now = self.clock()
        today = datetime.fromtimestamp(now, tz=timezone.utc).date().isoformat()
        with self.lock:
            if today != self.day:
                self.day, self.day_count = today, {"borrador": 0, "motor": 0}
            if self.day_count[group] >= daily:
                tomorrow = (int(now) // 86400 + 1) * 86400
                raise RateLimited(MSG_DAILY.format(group=group), max(1, tomorrow - int(now)))
            self.day_count[group] += 1


rate_limiter = RateLimiter()


class RateLimitMiddleware(BaseHTTPMiddleware):
    """El middleware solo cuenta IP; Gemini consume cuota tras validar y consultar caché."""

    def __init__(self, app, limiter: RateLimiter | None = None):
        super().__init__(app)
        self.limiter = limiter or rate_limiter

    async def dispatch(self, request, call_next):
        if request.method == "POST" and request.url.path.rstrip("/") in LIMITED_PATHS:
            refused = self.limiter.check_ip(client_ip(request), _limit("RATE_LIMIT_PER_MINUTE"))
            if refused:
                return limited_response(refused)
        return await call_next(request)
