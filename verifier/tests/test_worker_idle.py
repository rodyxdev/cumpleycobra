"""Apagado por inactividad del trabajador (fase 3). Sin Docker: la API es falsa."""

import pytest

from verifier import worker


class FakeApi:
    def __init__(self, base, token):
        self.claims = 0

    def post(self, path, body):
        assert path == "/verifier/claim"
        self.claims += 1
        return None


@pytest.fixture
def clock(monkeypatch, tmp_path):
    now = [0.0]
    monkeypatch.setattr(worker.time, "monotonic", lambda: now[0])

    def sleep(secs):
        now[0] += secs

    monkeypatch.setattr(worker.time, "sleep", sleep)
    monkeypatch.setattr(worker, "Api", FakeApi)
    monkeypatch.setenv("VERIFIER_API_URL", "http://api")
    monkeypatch.setenv("VERIFIER_QUEUE_TOKEN", "t")
    monkeypatch.setenv("VERIFIER_WORK_DIR", str(tmp_path))
    return now


def test_se_apaga_tras_el_tiempo_sin_trabajo(clock, monkeypatch):
    monkeypatch.setenv("VERIFIER_IDLE_SHUTDOWN_SECS", "900")
    offs = []
    monkeypatch.setattr(worker, "power_off", lambda: offs.append(clock[0]) or True)
    assert worker.main([]) == 0
    assert offs == [pytest.approx(900, abs=worker.IDLE_SLEEP_SECS)]


def test_si_no_puede_apagarse_sigue_atendiendo(clock, monkeypatch):
    monkeypatch.setenv("VERIFIER_IDLE_SHUTDOWN_SECS", "60")
    results = iter([False, True])
    offs = []
    monkeypatch.setattr(worker, "power_off", lambda: offs.append(clock[0]) or next(results))
    assert worker.main([]) == 0
    assert len(offs) == 2 and offs[1] - offs[0] >= 60


def test_sin_variable_nunca_se_apaga(monkeypatch):
    monkeypatch.delenv("VERIFIER_IDLE_SHUTDOWN_SECS", raising=False)
    assert worker.idle_shutdown_secs() is None
    monkeypatch.setenv("VERIFIER_IDLE_SHUTDOWN_SECS", "0")
    assert worker.idle_shutdown_secs() is None
    monkeypatch.setenv("VERIFIER_IDLE_SHUTDOWN_SECS", "10")
    with pytest.raises(ValueError):
        worker.idle_shutdown_secs()
