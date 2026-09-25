"""Referencia USD/MXN de Frankfurter; caché y respaldo explícito, sin tocar montos."""

import asyncio
import time
from datetime import date
from decimal import Decimal, InvalidOperation

import httpx

URL = "https://api.frankfurter.dev/v2/rate/USD/MXN"
# Referencia fija de demo, no una cotización observada. Su fecha no se actualiza.
FALLBACK = {"rate": "20.000000", "as_of": "2026-09-24", "source": "Referencia fija de respaldo (no cotización)", "fallback": True}


class FxReference:
    def __init__(self):
        self.value = None
        self.expires = 0
        self.lock = asyncio.Lock()

    async def get(self):
        async with self.lock:
            if self.value and time.monotonic() < self.expires:
                return self.value
            async with httpx.AsyncClient(timeout=3) as client:
                for attempt in range(3):
                    try:
                        response = await client.get(URL)
                        response.raise_for_status()
                        data = response.json()
                        rate = Decimal(str(data["rate"]))
                        as_of = date.fromisoformat(data["date"])
                        if (not rate.is_finite() or not 0 < rate < 1000 or as_of > date.today()
                                or data.get("base") != "USD" or data.get("quote") != "MXN"):
                            raise ValueError("Referencia inválida")
                        self.value = {"rate": str(rate), "as_of": as_of.isoformat(), "source": "Frankfurter", "fallback": False}
                        self.expires = time.monotonic() + 3600
                        return self.value
                    except (httpx.HTTPError, ValueError, KeyError, TypeError, InvalidOperation) as exc:
                        transient = isinstance(exc, httpx.TransportError) or (
                            isinstance(exc, httpx.HTTPStatusError) and (exc.response.status_code == 429 or exc.response.status_code >= 500))
                        if transient and attempt < 2:
                            await asyncio.sleep((1, 3)[attempt])
                            continue
                        break
            # Mantener fecha y fuente anteriores, marcando explícitamente el respaldo.
            self.value = {**(self.value or FALLBACK), "fallback": True}
            self.expires = time.monotonic() + 60
            return self.value
