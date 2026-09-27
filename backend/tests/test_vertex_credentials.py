"""Credenciales de Vertex en memoria: datos ficticios, sin red ni llaves reales."""

import base64
import json
import logging
import os
import traceback
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from google.auth import crypt
from google.oauth2 import service_account

from backend import gemini, main
from backend.config import ConfigError

FAKE_INFO = {
    "type": "service_account",
    "project_id": "PROYECTO-FICTICIO-NO-EXISTE",
    "private_key_id": "IDENTIFICADOR-FICTICIO",
    "private_key": "CLAVE-FICTICIA-NO-ES-UNA-LLAVE",
    "client_email": "cuenta-ficticia@example.invalid",
    "token_uri": "https://example.invalid/token",
}


def encode(info):
    return base64.b64encode(json.dumps(info).encode("utf-8")).decode("ascii")


@pytest.fixture
def settings(monkeypatch, tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    # Ningún test depende de las credenciales o variables reales del desarrollador.
    for name in ("GOOGLE_CREDENTIALS_B64", "GOOGLE_APPLICATION_CREDENTIALS", "GEMINI_API_KEY",
                 "GOOGLE_API_KEY", "GOOGLE_CLOUD_PROJECT", "GOOGLE_CLOUD_LOCATION",
                 "GOOGLE_GENAI_USE_ENTERPRISE"):
        monkeypatch.delenv(name, raising=False)
    return SimpleNamespace(use_vertex=True, gcp_project="PROYECTO-FICTICIO-NO-EXISTE",
                           gcp_location="global", gemini_api_key="API-KEY-FICTICIA",
                           state_file=tmp_path / "state.json")


def no_secrets(capsys, caplog, *extra):
    captured = capsys.readouterr()
    output = captured.out + captured.err + caplog.text + "".join(extra)
    for value in (encode(FAKE_INFO), json.dumps(FAKE_INFO), FAKE_INFO["private_key"],
                  FAKE_INFO["client_email"], FAKE_INFO["project_id"], FAKE_INFO["private_key_id"]):
        assert value not in output
    return output


def fake_signer(monkeypatch):
    # Solo se sustituye la lectura criptográfica: google-auth construye el objeto real.
    signer = Mock(spec=crypt.Signer)
    signer.key_id = "IDENTIFICADOR-FICTICIO"
    loader = Mock(return_value=signer)
    monkeypatch.setattr(crypt.RSASigner, "from_service_account_info", loader)
    return loader


def test_vertex_con_json_ficticio_y_credenciales_explicitas(settings, monkeypatch, capsys, caplog, tmp_path):
    import google.auth

    monkeypatch.setenv("GOOGLE_CREDENTIALS_B64", encode(FAKE_INFO))
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "RUTA-ADC-FICTICIA-NO-EXISTE")
    loader = fake_signer(monkeypatch)
    adc = Mock(side_effect=AssertionError("No debe usar ADC con credenciales explícitas"))
    monkeypatch.setattr(google.auth, "default", adc)
    original_client = gemini.genai.Client
    constructor = Mock(wraps=original_client)
    monkeypatch.setattr(gemini.genai, "Client", constructor)
    client = gemini.make_client(settings)
    try:
        passed = constructor.call_args.kwargs
        creds = passed["credentials"]
        assert isinstance(creds, service_account.Credentials)
        assert creds.project_id == FAKE_INFO["project_id"]
        assert creds.service_account_email == FAKE_INFO["client_email"]
        assert creds.scopes == ["https://www.googleapis.com/auth/cloud-platform"]
        assert client.vertexai is True
        assert passed["project"] == settings.gcp_project and passed["location"] == "global"
        assert passed["http_options"].timeout == 20000
        loader.assert_called_once_with(FAKE_INFO)
        adc.assert_not_called()
        assert os.environ["GOOGLE_APPLICATION_CREDENTIALS"] == "RUTA-ADC-FICTICIA-NO-EXISTE"
        assert list(tmp_path.iterdir()) == []
        no_secrets(capsys, caplog)
    finally:
        client.close()


@pytest.mark.parametrize("vertex", [True, False], ids=["ADC-local", "AI-Studio"])
def test_sin_variable_conserva_constructor_anterior(settings, monkeypatch, capsys, caplog, vertex):
    settings.use_vertex = vertex
    constructor = Mock()
    loader = Mock(side_effect=AssertionError("No debe construir credenciales de cuenta de servicio"))
    monkeypatch.setattr(gemini.genai, "Client", constructor)
    monkeypatch.setattr(service_account.Credentials, "from_service_account_info", loader)
    assert gemini.make_client(settings) is constructor.return_value
    passed = constructor.call_args.kwargs
    assert "credentials" not in passed
    if vertex:
        assert set(passed) == {"vertexai", "project", "location", "http_options"}
        assert passed["vertexai"] is True and passed["project"] == settings.gcp_project
    else:
        assert set(passed) == {"api_key", "http_options"}
        assert passed["api_key"] == settings.gemini_api_key
    loader.assert_not_called()
    assert "GOOGLE_APPLICATION_CREDENTIALS" not in os.environ
    no_secrets(capsys, caplog)


INVALID = [
    "", "BASE64-FICTICIO-INVALIDO!", base64.b64encode(b"\xff").decode(),
    base64.b64encode(b'{"private_key":"CLAVE-FICTICIA-NO-ES-UNA-LLAVE"').decode(),
    encode(None), encode([]), encode("CLAVE-FICTICIA-NO-ES-UNA-LLAVE"),
    encode({**FAKE_INFO, "type": "authorized_user"}),
    *[encode({k: v for k, v in FAKE_INFO.items() if k != missing})
      for missing in ("project_id", "private_key", "client_email", "token_uri")],
    encode({**FAKE_INFO, "project_id": 123}), encode({**FAKE_INFO, "private_key": " "}),
    encode(FAKE_INFO),  # Forma correcta pero llave ficticia: el parser real debe rechazarla.
]


@pytest.mark.parametrize("encoded", INVALID, ids=[f"invalido-{i}" for i in range(len(INVALID))])
def test_invalida_impide_arranque_sin_revelar_datos(settings, monkeypatch, capsys, caplog, encoded):
    monkeypatch.setenv("GOOGLE_CREDENTIALS_B64", encoded)
    monkeypatch.setattr(main, "load_settings", lambda: settings)
    monkeypatch.setattr(main, "StellarClient", Mock())
    constructor = Mock()
    monkeypatch.setattr(gemini.genai, "Client", constructor)
    # Lifespan real: el servidor no llega a atender ni siquiera /health.
    with pytest.raises(ConfigError, match="GOOGLE_CREDENTIALS_B64 inválida") as exc:
        with TestClient(FastAPI(lifespan=main.lifespan)):
            pytest.fail("El arranque debió fallar")
    constructor.assert_not_called()
    assert exc.value.__context__ is None
    assert exc.value.__cause__ is None
    rendered = "".join(traceback.format_exception(exc.type, exc.value, exc.tb))
    output = no_secrets(capsys, caplog, rendered)
    if encoded:
        assert encoded not in output


def test_excepcion_del_sdk_no_filtra_la_llave(settings, monkeypatch, capsys, caplog):
    monkeypatch.setenv("GOOGLE_CREDENTIALS_B64", encode(FAKE_INFO))
    loader = Mock(side_effect=ValueError(json.dumps(FAKE_INFO)))
    monkeypatch.setattr(service_account.Credentials, "from_service_account_info", loader)
    with pytest.raises(ConfigError) as exc:
        gemini.make_client(settings)
    assert exc.value.__context__ is None
    no_secrets(capsys, caplog, "".join(traceback.format_exception(exc.type, exc.value, exc.tb)))


def test_variable_explicita_requiere_modo_vertex(settings, monkeypatch, capsys, caplog):
    settings.use_vertex = False
    monkeypatch.setenv("GOOGLE_CREDENTIALS_B64", encode(FAKE_INFO))
    fake_signer(monkeypatch)
    with pytest.raises(ConfigError, match="GOOGLE_GENAI_USE_VERTEXAI=true") as exc:
        gemini.make_client(settings)
    no_secrets(capsys, caplog, str(exc.value))
