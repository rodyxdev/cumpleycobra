"""Relay (lado NO confiable): servidor HTTP mínimo que traduce peticiones a llamadas aisladas.

POST /call {"module", "name", "args", "kwargs"} → lanza un proceso nuevo con `adapter.py`
(una petición por llamada, con timeout) y devuelve su respuesta. GET /health → 200.
Solo se aceptan los símbolos declarados en CC_SYMBOLS ("modulo:nombre,..."). Este proceso
arranca antes de importar nada de la entrega; la entrega solo corre en los procesos hijos.
"""

import json
import os
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ALLOWED = {tuple(s.split(":", 1)) for s in os.environ.get("CC_SYMBOLS", "").split(",") if ":" in s}
CALL_TIMEOUT = float(os.environ.get("CC_CALL_TIMEOUT", "5"))
MAX_REQUEST = 1024 * 1024
MAX_RESPONSE = 4 * 1024 * 1024


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys.stderr.write("[relay] " + (fmt % args) + "\n")

    def _send(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self._send(200, {"status": "ok"})
        else:
            self._send(404, {"status": "not_found"})

    def do_POST(self):
        if self.path != "/call":
            return self._send(404, {"status": "not_found"})
        length = int(self.headers.get("Content-Length", "0"))
        if length > MAX_REQUEST:
            return self._send(413, {"status": "too_large"})
        raw = self.rfile.read(length)
        try:
            request = json.loads(raw)
            symbol = (request["module"], request["name"])
        except (ValueError, KeyError, TypeError):
            return self._send(400, {"status": "bad_request"})
        if symbol not in ALLOWED:
            return self._send(403, {"status": "forbidden", "message": f"{symbol[0]}.{symbol[1]} no está en la interfaz"})
        self._send(200, call(raw))


def call(raw):
    proc = subprocess.Popen(
        [sys.executable, "-I", "-X", "utf8", "/cc/adapter.py"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        cwd="/tmp", start_new_session=True,
    )
    try:
        out, err = proc.communicate(raw, timeout=CALL_TIMEOUT)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, 9)
        proc.communicate()
        return {"status": "timeout", "message": f"la llamada superó {CALL_TIMEOUT:g}s"}
    finally:
        try:
            os.killpg(proc.pid, 9)  # mata también procesos que la entrega haya dejado colgando
        except ProcessLookupError:
            pass
    stderr_tail = err[-2000:].decode("utf-8", "replace")
    if stderr_tail.strip():
        # Queda en los logs del SUT como evidencia de lo que hizo la entrega (texto no confiable).
        sys.stderr.write("[entrega] " + stderr_tail[-1000:].replace("\n", "\n[entrega] ") + "\n")
    line = out[:MAX_RESPONSE].split(b"\n", 1)[0]
    try:
        response = json.loads(line)
    except ValueError:
        return {"status": "crashed", "exit_code": proc.returncode,
                "message": f"el proceso terminó sin responder (exit {proc.returncode})", "stderr": stderr_tail}
    response["stderr"] = stderr_tail
    return response


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8000), Handler).serve_forever()
