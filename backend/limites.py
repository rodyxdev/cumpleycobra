"""Límite de peticiones a las rutas que llaman a Gemini: /tasks/draft, /tasks/draft/review y /evaluate.

Aditivo y desactivado por defecto (local): solo actúa si hay variables de entorno.
- RATE_LIMIT_PER_MINUTE: máximo por IP en una ventana deslizante de 60 s.
- RATE_LIMIT_DAILY: tope global por día UTC, para toda la app (protege la cuota de la API key).

Vive en memoria del único proceso (ver backend/Dockerfile); un reinicio lo pone en cero.
Al excederse: 429 RATE_LIMITED con mensaje en español y Retry-After.
"""

import os
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

LIMITED_PATHS = {"/tasks/draft", "/tasks/draft/review", "/evaluate"}
WINDOW_SECS = 60

MSG_PER_IP = ("Demasiadas solicitudes al motor de análisis desde tu conexión. "
              "Espera un minuto y vuelve a intentarlo.")
MSG_DAILY = ("Se alcanzó el límite diario de análisis de esta demo. "
             "Vuelve a intentarlo mañana.")


def _limit(name: str) -> int:
    try:
        return max(0, int(os.environ.get(name, "0").strip() or 0))
    except ValueError:
        return 0  # un valor mal escrito no bloquea la demo: queda desactivado


class RateLimiter:
    def __init__(self, clock=time.time):
        self.clock = clock
        self.hits: dict[str, deque] = defaultdict(deque)
        self.day: str | None = None
        self.day_count = 0
        self.lock = threading.Lock()

    def check(self, ip: str, per_minute: int, daily: int) -> tuple[str, int] | None:
        """None si pasa (y la cuenta); si no, (mensaje, segundos para reintentar)."""
        if not per_minute and not daily:
            return None
        now = self.clock()
        today = datetime.fromtimestamp(now, tz=timezone.utc).date().isoformat()
        with self.lock:
            if today != self.day:
                self.day, self.day_count = today, 0
            window = self.hits[ip]
            while window and window[0] <= now - WINDOW_SECS:
                window.popleft()
            if daily and self.day_count >= daily:
                tomorrow = (int(now) // 86400 + 1) * 86400
                return MSG_DAILY, max(1, tomorrow - int(now))
            if per_minute and len(window) >= per_minute:
                return MSG_PER_IP, max(1, int(window[0] + WINDOW_SECS - now) + 1)
            window.append(now)
            self.day_count += 1
            return None


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Solo POST a LIMITED_PATHS; los límites se leen del entorno en cada petición."""

    def __init__(self, app, limiter: RateLimiter | None = None):
        super().__init__(app)
        self.limiter = limiter or RateLimiter()

    async def dispatch(self, request, call_next):
        if request.method == "POST" and request.url.path in LIMITED_PATHS:
            ip = request.client.host if request.client else "desconocida"
            refused = self.limiter.check(ip, _limit("RATE_LIMIT_PER_MINUTE"), _limit("RATE_LIMIT_DAILY"))
            if refused:
                message, retry = refused
                return JSONResponse(status_code=429, content={"error": "RATE_LIMITED", "message": message},
                                    headers={"Retry-After": str(retry)})
        return await call_next(request)
