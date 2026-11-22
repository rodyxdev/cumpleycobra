"""Perfil web del verificador: higiene, build con npm y el runner de Playwright (con Docker)."""

import json
import tempfile
from pathlib import Path

import pytest

from verifier.contract import ExecutionSpec, WebCheck
from verifier.sandbox import docker_available
from verifier.web import prepare_site, run_web_checks, static_site
from verifier.web.hygiene import check_web_hygiene

requires_docker = pytest.mark.skipif(not docker_available(), reason="Docker no está disponible")

PAGINA = """<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width"><title>Tienda Sol</title></head>
<body><h1>Tienda Sol</h1><a href="#contacto">Contacto</a>
<div style="width:2000px">ancho de más</div>
<section id="contacto" style="margin-top:1200px"><h2>Contacto</h2></section>
<img src="https://example.com/rastreo.png" alt="">
</body></html>
"""


def write(root: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    for d in [root, *[p for p in root.rglob("*") if p.is_dir()]]:
        d.chmod(0o755)
    return root


def lock(packages: dict | None = None) -> str:
    return json.dumps({"name": "sitio", "version": "1.0.0", "lockfileVersion": 3, "requires": True,
                       "packages": {"": {"name": "sitio", "version": "1.0.0"}, **(packages or {})}})


# --- contrato ------------------------------------------------------------------------------

def test_el_perfil_web_lleva_paginas_y_no_interfaz():
    ExecutionSpec(profile="web", web={"pages": ["/", "/contacto"]})
    with pytest.raises(ValueError):
        ExecutionSpec(profile="web")
    with pytest.raises(ValueError):
        ExecutionSpec(profile="web", web={"pages": ["/../etc"]})
    with pytest.raises(ValueError):
        WebCheck(id="c1-1", kind="text_present", page="/", args=[])
    with pytest.raises(ValueError):
        WebCheck(id="c1-1", kind="form_submits", page="/", args=["/api", "Gracias", "Nombre=Ana"])
    WebCheck(id="c1-1", kind="form_submits", page="/", args=["/api", "Gracias", "Nombre=Ana", "boton=Enviar"])


# --- higiene ---------------------------------------------------------------------------------

def test_higiene_web(tmp_path):
    assert check_web_hygiene(write(tmp_path / "a", {"index.html": PAGINA}), []).ok
    assert not check_web_hygiene(write(tmp_path / "b", {"otra.html": PAGINA}), []).ok
    r = check_web_hygiene(write(tmp_path / "c", {"index.html": PAGINA, ".npmrc": "registry=https://malo.example"}), [])
    assert any(".npmrc" in b for b in r.blockers)
    r = check_web_hygiene(write(tmp_path / "d", {"package.json": json.dumps({"dependencies": {"left-pad": "1"}})}), [])
    assert any("package-lock" in b for b in r.blockers)
    pkg = json.dumps({"name": "sitio", "dependencies": {"left-pad": "1.3.0"}})
    bad_lock = lock({"node_modules/left-pad": {"version": "1.3.0", "resolved": "https://malo.example/left-pad.tgz",
                                               "integrity": "sha512-x"}})
    r = check_web_hygiene(write(tmp_path / "e", {"package.json": pkg, "package-lock.json": bad_lock}), ["left-pad"])
    assert any("registry.npmjs.org" in b for b in r.blockers)
    r = check_web_hygiene(write(tmp_path / "f", {"package.json": pkg, "package-lock.json": lock()}), [])
    assert any("no permitida" in b for b in r.blockers)
    r = check_web_hygiene(write(tmp_path / "g", {"index.html": PAGINA, "node_modules/x/index.js": "1"}), [])
    assert any("node_modules" in b for b in r.blockers)


# --- con Docker ---------------------------------------------------------------------------

@requires_docker
def test_runner_marca_desborde_y_bloquea_recursos_externos():
    with tempfile.TemporaryDirectory() as tmp:
        site = write(Path(tmp) / "s", {"index.html": PAGINA})
        checks = [{"id": "c1-1", "kind": "no_horizontal_overflow", "page": "/", "args": []},
                  {"id": "c2-1", "kind": "link_navigates", "page": "/", "args": ["Contacto", "#contacto"]},
                  {"id": "c3-1", "kind": "element_visible", "page": "/", "args": ["heading", "Tienda Sol"]}]
        run = run_web_checks(static_site(site), ["/"], checks, Path(tmp) / "out")
        s = run.summary()
        assert s["report_found"], s["stderr_tail"]
        assert s["checks"]["c1-1"]["passed"] is False      # el div de 2000 px desborda a 390 px
        assert s["checks"]["c2-1"]["passed"] is True
        assert s["checks"]["c3-1"]["passed"] is True       # el encabezado sí cabe: solo el div desborda
        assert {sh["viewport"] for sh in s["screenshots"]} == {"desktop", "mobile"}
        assert (Path(tmp) / "out" / "S1.jpg").read_bytes()[:2] == b"\xff\xd8"
        # La imagen externa nunca se pidió fuera de la red interna: el servidor solo vio peticiones locales.
        assert "rastreo" not in s["server"]["logs_tail"]


@requires_docker
def test_proyecto_npm_con_build_sin_red():
    build = ("const fs=require('fs');fs.mkdirSync('dist',{recursive:true});"
             "fs.writeFileSync('dist/index.html','<!doctype html><title>Hecho con build</title><h1>Listo</h1>')")
    with tempfile.TemporaryDirectory() as tmp:
        ws = write(Path(tmp) / "p", {
            "package.json": json.dumps({"name": "sitio", "version": "1.0.0", "scripts": {"build": "node build.js"}}),
            "package-lock.json": lock(), "build.js": build})
        site = prepare_site(ws)
        try:
            assert site.ok, site.summary()
            assert site.kind == "npm" and site.subdir == "dist"
            run = run_web_checks(site, ["/"], [{"id": "c1-1", "kind": "title_contains", "page": "/",
                                                "args": ["Hecho con build"]}], Path(tmp) / "out")
            assert run.summary()["checks"]["c1-1"]["passed"] is True
        finally:
            site.remove()


@requires_docker
def test_un_build_que_falla_no_llega_al_navegador():
    with tempfile.TemporaryDirectory() as tmp:
        ws = write(Path(tmp) / "p", {
            "package.json": json.dumps({"name": "sitio", "version": "1.0.0", "scripts": {"build": "exit 3"}}),
            "package-lock.json": lock()})
        site = prepare_site(ws)
        try:
            assert not site.ok and "build" in site.error
        finally:
            site.remove()


ESCAPE = """<!doctype html><html><head><meta charset="utf-8"><title>escape</title></head><body><pre id="r">corriendo</pre>
<script>
const objetivos = {
  metadatos: "http://169.254.169.254/computeMetadata/v1/instance/attributes/verifier-queue-token",
  internet: "https://example.com/",
  host_docker: "http://172.17.0.1:8000/health",
};
(async () => {
  const out = [];
  for (const [nombre, url] of Object.entries(objetivos)) {
    try {
      const ctrl = new AbortController(); setTimeout(() => ctrl.abort(), 3000);
      const r = await fetch(url, {headers: {"Metadata-Flavor": "Google"}, signal: ctrl.signal, mode: "no-cors"});
      out.push(nombre + "=ALCANZADO");
    } catch (e) { out.push(nombre + "=bloqueado"); }
  }
  document.getElementById("r").textContent = out.join(" ");
})();
</script></body></html>
"""


@requires_docker
def test_el_js_de_la_entrega_no_sale_de_la_red_interna():
    """El JS del sitio corre en el Chromium del lado confiable: no alcanza metadatos, internet ni el host."""
    with tempfile.TemporaryDirectory() as tmp:
        site = write(Path(tmp) / "s", {"index.html": ESCAPE})
        checks = [{"id": "c1-1", "kind": "text_present", "page": "/", "args": ["metadatos=bloqueado"]},
                  {"id": "c1-2", "kind": "text_present", "page": "/", "args": ["internet=bloqueado"]},
                  {"id": "c1-3", "kind": "text_present", "page": "/", "args": ["host_docker=bloqueado"]}]
        run = run_web_checks(static_site(site), ["/"], checks, Path(tmp) / "out")
        s = run.summary()
        texto = s["pages"]["/"]["desktop"]["visible_text"]
        print("reporte del JS:", texto)
        assert "ALCANZADO" not in texto, texto
        assert all(c["passed"] for c in s["checks"].values()), texto
