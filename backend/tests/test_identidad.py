"""Identidad SEP-10 y perfiles: retos, sesiones, perfil del dueño y calificación con sesión."""

import time

import pytest
from fastapi.testclient import TestClient
from stellar_sdk import Keypair, Network, TransactionEnvelope, xdr as sx
from stellar_sdk.sep.ed25519_public_key_signer import Ed25519PublicKeySigner
from stellar_sdk.sep.stellar_web_authentication import build_challenge_transaction

from backend import identidad, main
from backend.tests.test_reputacion import C1, C2, P1, MultiChain, rate, session, world  # noqa: F401

P = Network.TESTNET_NETWORK_PASSPHRASE
A, B = Keypair.random(), Keypair.random()


@pytest.fixture
def auth(world):  # noqa: F811 - world ya fija las llaves de prueba en el entorno
    main.app.state.challenges = identidad.Challenges()
    accounts = {A.public_key: ([Ed25519PublicKeySigner(A.public_key, 1)], 0),
                B.public_key: ([Ed25519PublicKeySigner(B.public_key, 1)], 0)}
    state = {"down": False}

    def lookup(address):
        if state["down"]:
            raise identidad.ChainError("Horizon caído")
        return accounts.get(address)  # None: la cuenta no existe (se exige la llave maestra)

    main.app.state.signers_lookup = lookup
    world.accounts, world.horizon = accounts, state
    yield world
    del main.app.state.signers_lookup
    del main.app.state.challenges


def challenge(world, address):
    r = world.client.get("/auth/challenge", params={"address": address})
    assert r.status_code == 200, r.text
    return r.json()["transaction"]


def sign(xdr, *keypairs):
    env = TransactionEnvelope.from_xdr(xdr, P)
    for kp in keypairs:
        env.sign(kp)
    return env.to_xdr()


def token(world, signed):
    return world.client.post("/auth/token", json={"transaction": signed})


def bearer(t):
    return {"Authorization": f"Bearer {t}"}


# --- Reto y sesión -------------------------------------------------------------------------------
def test_flujo_completo_da_una_sesion_de_12_horas(auth):
    r = token(auth, sign(challenge(auth, A.public_key), A))
    assert r.status_code == 200
    body = r.json()
    assert body["address"] == A.public_key and 12 * 3600 - 5 <= body["expires_at"] - time.time() <= 12 * 3600
    assert identidad.session_address(main.auth_keys(), body["token"]) == A.public_key
    ch = auth.client.get("/auth/challenge", params={"address": A.public_key}).json()
    assert ch["expires_in"] == 300 and ch["network_passphrase"] == P


def test_reto_reutilizado(auth):
    signed = sign(challenge(auth, A.public_key), A)
    assert token(auth, signed).status_code == 200
    again = token(auth, signed)
    assert again.status_code == 401 and again.json()["error"] == "CHALLENGE_USED"


def test_reto_caducado(auth, monkeypatch):
    signed = sign(challenge(auth, A.public_key), A)
    real = time.time
    monkeypatch.setattr(identidad.time, "time", lambda: real() + 301)
    r = token(auth, signed)
    assert r.status_code == 401 and r.json()["error"] == "CHALLENGE_EXPIRED"


def test_firma_de_otra_cuenta(auth):
    r = token(auth, sign(challenge(auth, A.public_key), B))
    assert r.status_code == 401 and r.json()["error"] == "SIGNATURE_INVALID"
    # Tampoco sirve sin firma del cliente.
    r = token(auth, challenge(auth, A.public_key))
    assert r.status_code == 401 and r.json()["error"] == "SIGNATURE_INVALID"


@pytest.mark.parametrize("op_index", [0, 1], ids=["nonce", "web_auth_domain"])
def test_xdr_alterado(auth, op_index):
    signed = sign(challenge(auth, A.public_key), A)
    env = sx.TransactionEnvelope.from_xdr(signed)
    env.v1.tx.operations[op_index].body.manage_data_op.data_value = sx.DataValue(b"A" * 64)
    r = token(auth, env.to_xdr())
    assert r.status_code == 401 and r.json()["error"] == "CHALLENGE_INVALID"


def test_reto_de_otro_servidor_o_mal_formado(auth):
    foreign = build_challenge_transaction(Keypair.random().secret, A.public_key, identidad.HOME_DOMAIN,
                                          identidad.WEB_AUTH_DOMAIN, P, timeout=300)
    assert token(auth, sign(foreign, A)).json()["error"] == "CHALLENGE_INVALID"
    assert token(auth, "no-es-xdr").json()["error"] == "CHALLENGE_INVALID"
    assert auth.client.get("/auth/challenge", params={"address": "no-es-direccion"}).status_code == 400


def test_cuenta_sin_registro_en_horizon_exige_la_llave_maestra(auth):
    C = Keypair.random()  # no está en Horizon
    assert token(auth, sign(challenge(auth, C.public_key), C)).status_code == 200
    assert token(auth, sign(challenge(auth, C.public_key), A)).json()["error"] == "SIGNATURE_INVALID"


def test_horizon_caido_no_consume_el_reto(auth):
    signed = sign(challenge(auth, A.public_key), A)
    auth.horizon["down"] = True
    r = token(auth, signed)
    assert r.status_code == 502 and r.json()["error"] == "CHAIN_UNAVAILABLE"
    auth.horizon["down"] = False
    assert token(auth, signed).status_code == 200


def test_sesion_caducada_alterada_o_ausente(auth):
    keys = main.auth_keys()
    old = identidad.issue_session(keys, A.public_key, now=time.time() - 12 * 3600 - 1)["token"]
    r = auth.client.put("/perfil", headers=bearer(old), json={"nombre": "Ana"})
    assert r.status_code == 401 and r.json()["error"] == "SESSION_REQUIRED" and "caducó" in r.json()["message"]
    good = identidad.issue_session(keys, A.public_key)["token"]
    payload, mac = good.split(".")
    forged_payload = identidad._b64(f"{B.public_key}.{int(time.time()) + 3600}".encode())
    for bad in (f"{forged_payload}.{mac}", good[:-2] + "xx", "basura"):
        assert auth.client.put("/perfil", headers=bearer(bad), json={}).json()["error"] == "SESSION_REQUIRED"
    assert auth.client.put("/perfil", json={}).json()["error"] == "SESSION_REQUIRED"


# --- Perfil ---------------------------------------------------------------------------------------
def test_perfil_solo_lo_edita_su_dueno(auth):
    me = bearer(identidad.issue_session(main.auth_keys(), A.public_key)["token"])
    r = auth.client.put("/perfil", headers=me, json={"address": B.public_key, "nombre": "Intruso"})
    assert r.status_code == 403 and r.json()["error"] == "NOT_PROFILE_OWNER"
    assert B.public_key not in main.store().profiles
    r = auth.client.put("/perfil", headers=me, json={"nombre": "  Ana  ", "habilidades": ["Python", " python ", "FastAPI", " "],
                                                     "bio": "Scripts de datos."})
    assert r.status_code == 200
    assert r.json() == {"address": A.public_key, "nombre": "Ana", "habilidades": ["Python", "FastAPI"], "bio": "Scripts de datos."}
    prof = auth.client.get(f"/programadores/{A.public_key}").json()
    assert prof["nombre"] == "Ana" and prof["habilidades"] == ["Python", "FastAPI"] and prof["identidad_verificada"]


@pytest.mark.parametrize("body", [{"nombre": "x" * 61}, {"habilidades": ["a"] * 9}, {"habilidades": ["x" * 31]},
                                  {"bio": "x" * 281}, {"habilidades": [""]}, {"otro": 1}])
def test_limites_del_perfil(auth, body):
    me = bearer(identidad.issue_session(main.auth_keys(), A.public_key)["token"])
    r = auth.client.put("/perfil", headers=me, json=body)
    assert r.status_code == 400 and r.json()["error"] == "INVALID_REQUEST"


def test_listado_incluye_nombre_y_habilidades(auth):
    auth.task(P1)
    assert "nombre" not in auth.client.get("/programadores").json()["programmers"][0]  # sin perfil publicado
    auth.client.put("/perfil", headers=session(P1), json={"nombre": "Rodrigo", "habilidades": ["Python"], "bio": "Hola"})
    row = auth.client.get("/programadores").json()["programmers"][0]
    assert row["nombre"] == "Rodrigo" and row["habilidades"] == ["Python"] and row["bio"] == "Hola"


# --- Calificación con sesión -------------------------------------------------------------------------
def test_calificar_exige_la_sesion_del_cliente_on_chain(auth):
    tid, tok = auth.task(P1, C1)
    r = auth.client.post(f"/tasks/{tid}/calificacion", headers={"X-Client-Token": tok}, json={"estrellas": 5})
    assert r.status_code == 401 and r.json()["error"] == "SESSION_REQUIRED"
    r = rate(auth, tid, tok, as_client=C2)
    assert r.status_code == 403 and r.json()["error"] == "NOT_TASK_CLIENT"
    r = rate(auth, tid, tok, as_client=P1)  # ni siquiera el programador
    assert r.json()["error"] == "NOT_TASK_CLIENT"
    assert "rating" not in main.store().tasks[tid]
    assert rate(auth, tid, tok, as_client=C1, estrellas=4).status_code == 200


# --- El flujo del dinero no exige identidad ------------------------------------------------------
def test_sin_llaves_de_identidad_el_flujo_principal_sigue(world, monkeypatch):  # noqa: F811
    monkeypatch.delenv("SEP10_SIGNING_SECRET")
    r = world.client.get("/auth/challenge", params={"address": A.public_key})
    assert r.status_code == 503 and r.json()["error"] == "AUTH_NOT_CONFIGURED"
    # Crear y aceptar una tarea no pide sesión ni llaves de identidad.
    tid, _ = world.task(P1, status="Funded", engine=False)
    assert main.store().tasks[tid]["freelancer_address"] == P1


def test_la_llave_sep10_nunca_es_la_del_arbitro(world, monkeypatch):  # noqa: F811
    arbiter = Keypair.random().secret
    monkeypatch.setenv("SEP10_SIGNING_SECRET", arbiter)
    main.app.state.settings.arbiter_secret = arbiter
    try:
        r = world.client.get("/auth/challenge", params={"address": A.public_key})
        assert r.status_code == 503 and "árbitro" in r.json()["message"]
    finally:
        del main.app.state.settings.arbiter_secret
