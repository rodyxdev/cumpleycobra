"""Cada prueba parte de ventanas y cuotas independientes, sin usar límites del entorno local."""
import pytest
from backend.limites import rate_limiter


@pytest.fixture(autouse=True)
def isolated_limits(monkeypatch):
    for name in ("RATE_LIMIT_PER_MINUTE", "RATE_LIMIT_DAILY", "RATE_LIMIT_DAILY_BORRADOR",
                 "RATE_LIMIT_DAILY_MOTOR", "RATE_LIMIT_WRITES_PER_MINUTE"):
        monkeypatch.delenv(name, raising=False)
    rate_limiter.hits.clear()
    rate_limiter.day, rate_limiter.day_count = None, {"borrador": 0, "motor": 0}
    yield
    rate_limiter.hits.clear()
    rate_limiter.day, rate_limiter.day_count = None, {"borrador": 0, "motor": 0}
