"""PostgresStore contra un Postgres real (CYC_TEST_DATABASE_URL); sin la variable, se omite."""
import asyncio
import json
import os
import threading
import time

import pytest

from backend import identidad
from backend.storage import postgres as pgm

URL = os.environ.get("CYC_TEST_DATABASE_URL", "").strip()
pytestmark = pytest.mark.skipif(not URL, reason="sin CYC_TEST_DATABASE_URL")


@pytest.fixture()
def make_store():
    stores = []
    token = pgm._session.set(None)

    def make():
        store = pgm.PostgresStore(URL, max_size=6)
        stores.append(store)
        return store

    first = make()
    with first.pool.connection() as conn:
        conn.execute("TRUNCATE tasks, profiles, proposals, sep10_challenges")
    yield make
    pgm._session.reset(token)
    for store in stores:
        store.close()


def in_request(store, fn):
    """Corre `fn` como lo haría una petición: con su propia sesión."""
    token = store.begin()
    try:
        return fn()
    finally:
        store.end(token)


def test_migraciones_idempotentes(make_store):
    store = make_store()
    assert pgm.migrate(store.pool) == []  # ya aplicadas por el primer store
    with store.pool.connection() as conn:
        versions = [r[0] for r in conn.execute("SELECT version FROM schema_migrations ORDER BY version")]
    assert versions == ["001_inicial"]


def test_guarda_y_relee_conservando_el_orden_de_claves_y_filas(make_store):
    store = make_store()
    doc = {"z": 1, "a": {"y": [3, 2, 1], "b": "ñandú"}, "codes": {"h2": {"ok": 1}, "h1": {"ok": 2}}}

    def write():
        store.tasks["t2"] = doc
        store.tasks["t1"] = {"n": 1}
        store.save()

    in_request(store, write)
    other = make_store()
    got = in_request(other, lambda: (list(other.tasks), other.tasks["t2"]))
    assert got[0] == ["t2", "t1"]  # orden de creación, como un dict de state.json
    assert json.dumps(got[1]) == json.dumps(doc)  # mismo orden de claves (columna json, no jsonb)
    assert list(got[1]["codes"]) == ["h2", "h1"]


def test_save_solo_escribe_lo_que_cambio(make_store):
    store = make_store()
    in_request(store, lambda: (store.tasks.__setitem__("a", {"v": 1}), store.tasks.__setitem__("b", {"v": 1}),
                               store.save()))
    with store.pool.connection() as conn:
        before = dict(conn.execute("SELECT id, updated_at FROM tasks").fetchall())

    def touch_a():
        store.tasks["a"]["v"] = 2
        store.tasks.get("b")
        store.save()

    in_request(store, touch_a)
    with store.pool.connection() as conn:
        after = dict(conn.execute("SELECT id, updated_at FROM tasks").fetchall())
    assert after["a"] > before["a"] and after["b"] == before["b"]


def test_fuera_de_peticion_las_lecturas_vienen_frescas(make_store):
    a, b = make_store(), make_store()
    in_request(a, lambda: (a.tasks.__setitem__("t", {"n": 1}), a.save()))
    assert b.tasks["t"]["n"] == 1
    in_request(a, lambda: (a.tasks["t"].__setitem__("n", 2), a.save()))
    assert b.tasks["t"]["n"] == 2  # sesión implícita: se recarga
    assert [d["n"] for d in b.tasks.values()] == [2]


def test_candado_entre_dos_instancias_no_pierde_escrituras(make_store):
    """Dos «instancias» (dos stores, dos pools) suman envíos a la misma tarea en paralelo."""
    a, b = make_store(), make_store()
    in_request(a, lambda: (a.tasks.__setitem__("t", {"submissions": []}), a.save()))

    async def submit(store, n):
        token = store.begin()
        try:
            task = store.tasks["t"]  # leída ANTES del candado, como hace el backend
            async with store.lock("t"):
                task["submissions"].append(n)  # el candado la recargó en su lugar
                await asyncio.sleep(0.01)
                store.save()
        finally:
            store.end(token)

    async def run():
        await asyncio.gather(*(submit(a if i % 2 else b, i) for i in range(10)))

    asyncio.run(run())
    final = in_request(a, lambda: a.tasks["t"]["submissions"])
    assert sorted(final) == list(range(10))


def test_candado_sincrono_excluye_entre_hilos(make_store):
    a, b = make_store(), make_store()
    inside, overlaps = [0], [0]
    guard = threading.Lock()

    def work(store):
        with store.sync_lock("cyc:release-arbitro"):
            with guard:
                inside[0] += 1
                overlaps[0] = max(overlaps[0], inside[0])
            time.sleep(0.02)
            with guard:
                inside[0] -= 1

    threads = [threading.Thread(target=work, args=(a if i % 2 else b,)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert overlaps[0] == 1


def test_retos_sep10_compartidos_y_de_un_solo_uso(make_store, monkeypatch):
    a, b = make_store(), make_store()
    ca, cb = identidad.PgChallenges(a.pool), identidad.PgChallenges(b.pool)
    monkeypatch.setattr(identidad, "_nonce", lambda xdr, passphrase: f"n-{xdr}")
    now = time.time()
    ca._add("n-x1", "GADDR", now + identidad.CHALLENGE_TTL, now)
    # Otra instancia lo consume: sobrevive entre procesos.
    assert cb.take("x1", "pp", now=now) == ("GADDR", pytest.approx(now + identidad.CHALLENGE_TTL))
    with pytest.raises(identidad.AuthError) as used:
        ca.take("x1", "pp", now=now)
    assert used.value.code == "CHALLENGE_USED"
    with pytest.raises(identidad.AuthError) as unknown:
        ca.take("x2", "pp", now=now)
    assert unknown.value.code == "CHALLENGE_INVALID"
    # Si Horizon falló, el reto vuelve a quedar pendiente.
    cb.restore("x1", "pp", "GADDR", now + 60)
    assert ca.take("x1", "pp", now=now)[0] == "GADDR"
    # Caducado.
    ca._add("n-x3", "GADDR", now - 1, now)
    with pytest.raises(identidad.AuthError) as expired:
        cb.take("x3", "pp", now=now)
    assert expired.value.code == "CHALLENGE_EXPIRED"


def test_importar_y_exportar_state_json_ida_y_vuelta(make_store, tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("estado_postgres", "scripts/estado_postgres.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    original = {"version": 1,
                "tasks": {"t2": {"spec": {"criteria": ["b", "a"]}, "codes": {"h2": {}, "h1": {"approved": True}}},
                          "t1": {"amount": 10_000_000, "nota": "ñ ✓ \u0000 fin"}},
                "profiles": {"GAAA": {"nombre": "Ana"}},
                "proposals": {"p1": {"task_id": "t1", "programador": "GAAA", "estado": "pendiente"}}}
    source = tmp_path / "state.json"
    source.write_text(json.dumps(original, ensure_ascii=False), encoding="utf-8")
    store = make_store()
    assert script.importar(store, source, forzar=False) == {"tasks": 2, "profiles": 1, "proposals": 1}
    with pytest.raises(SystemExit):
        script.importar(store, source, forzar=False)  # no pisa una base con datos
    back = tmp_path / "vuelta.json"
    script.exportar(store, back)
    assert json.dumps(json.loads(back.read_text(encoding="utf-8"))) == json.dumps(original)
