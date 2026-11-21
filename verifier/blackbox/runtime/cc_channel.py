"""Canal (lado CONFIABLE): lo que usan los tests ocultos para hablar con la entrega.

Perfil script:
    from cc_channel import remote
    resumir_ventas = remote("ventas", "resumir_ventas")
    resumir_ventas("a,1,2")   # se ejecuta en el contenedor de la entrega

Las excepciones de tipos builtin (ValueError, KeyError, ...) se re-lanzan con el mismo tipo
y mensaje. Los fallos del canal (timeout, proceso caído, import fallido) son `ChannelError`,
que hereda de BaseException para que un `pytest.raises(Exception)` no los confunda con
un comportamiento correcto.

Perfil api:
    from cc_channel import api
    r = api.post("/items", json={...})   # httpx.Response
"""

import builtins
import json
import os
import time
import urllib.error
import urllib.request

import cc_codec

SUT_URL = os.environ.get("CC_SUT_URL", "http://sut:8000")
REQUEST_TIMEOUT = float(os.environ.get("CC_CALL_TIMEOUT", "5")) + 5


class ChannelError(BaseException):
    """La entrega no respondió normalmente (no es una excepción de la entrega)."""


class SubmissionTimeout(ChannelError):
    pass


class SubmissionCrashed(ChannelError):
    pass


class SubmissionImportError(ChannelError):
    pass


class MissingSymbol(ChannelError):
    pass


class RemoteException(Exception):
    """Excepción no builtin lanzada por la entrega (se conserva el nombre del tipo)."""


_remote_types: dict = {}


def _exception_type(name, module):
    candidate = getattr(builtins, name, None) if module == "builtins" else None
    if isinstance(candidate, type) and issubclass(candidate, Exception):
        return candidate
    if candidate is not None and issubclass(candidate, BaseException):
        return SubmissionCrashed  # SystemExit, KeyboardInterrupt...
    if name not in _remote_types:
        _remote_types[name] = type(name, (RemoteException,), {})
    return _remote_types[name]


def _post(path, payload):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(SUT_URL + path, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return json.loads(exc.read() or b"{}") | {"http_status": exc.code}
    except (urllib.error.URLError, OSError) as exc:
        raise SubmissionCrashed(f"no se pudo contactar a la entrega: {exc}") from None


def call(module, name, *args, **kwargs):
    response = _post("/call", {"module": module, "name": name,
                               "args": cc_codec.encode(list(args)), "kwargs": cc_codec.encode(kwargs)})
    status = response.get("status")
    if status == "ok":
        return cc_codec.decode(response["value"])
    if status == "raised":
        exc_type = _exception_type(response["type"], response.get("module", ""))
        raise exc_type(response.get("message", ""))
    message = response.get("message", "")
    if status == "timeout":
        raise SubmissionTimeout(message)
    if status == "import_error":
        raise SubmissionImportError(message)
    if status in ("missing", "forbidden"):
        raise MissingSymbol(message)
    raise SubmissionCrashed(f"{message} {response.get('stderr', '')[-500:]}".strip())


def remote(module, name):
    def proxy(*args, **kwargs):
        return call(module, name, *args, **kwargs)

    proxy.__name__ = name
    proxy.__qualname__ = f"remote:{module}.{name}"
    return proxy


class _Module:
    def __init__(self, module):
        self._module = module

    def __getattr__(self, name):
        return remote(self._module, name)


def remote_module(module):
    return _Module(module)


def wait_ready(deadline_s=20.0, path="/health"):
    """Espera a que la entrega acepte conexiones. Devuelve True si respondió."""
    end = time.monotonic() + deadline_s
    while time.monotonic() < end:
        try:
            with urllib.request.urlopen(SUT_URL + path, timeout=2):
                return True
        except urllib.error.HTTPError:
            return True  # respondió HTTP (aunque sea 404): el servidor está arriba
        except (urllib.error.URLError, OSError):
            time.sleep(0.2)
    return False


class _Api:
    """Cliente HTTP hacia la app de la entrega (perfil api)."""

    def __init__(self):
        self._client = None

    def _http(self):
        if self._client is None:
            import httpx

            self._client = httpx.Client(base_url=SUT_URL, timeout=REQUEST_TIMEOUT)
        return self._client

    def request(self, method, url, **kwargs):
        return self._http().request(method, url, **kwargs)

    def __getattr__(self, method):
        if method in ("get", "post", "put", "patch", "delete", "head", "options"):
            return lambda url, **kw: self.request(method.upper(), url, **kw)
        raise AttributeError(method)


api = _Api()
