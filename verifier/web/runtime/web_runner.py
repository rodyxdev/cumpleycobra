"""Runner web (lado CONFIABLE): corre en el contenedor de Playwright, contra la entrega servida en
otra red interna (la URL base llega en el spec; bajo gVisor es una IP, no un alias).

Uso: python3 web_runner.py /spec/spec.json /out

Produce en /out:
- results.json: chequeos deterministas (por id de chequeo), capturas, texto oculto, desborde, errores.
- S1.jpg, S2.jpg, ...: capturas de página completa a 1440 px y 390 px por página (JPEG, alto acotado).
Sin video (plan de mejora: el perfil web solo toma capturas). Nada de lo que escriba la entrega
cuenta: este proceso es el único que produce resultados. Portado de v2 (`backend/web/runtime`).
"""

import json
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

VIEWPORTS = {"desktop": (1440, 900), "mobile": (390, 844)}
NAV_TIMEOUT_MS = 15_000
MAX_SCREENSHOT_HEIGHT = 3000   # lo que ve el juez; el resto de la página se describe por DOM
JPEG_QUALITY = 75

HIDDEN_TEXT_JS = r"""
() => {
  const out = [];
  const seen = new Set();
  const parse = (c) => { const m = c && c.match(/rgba?\(([^)]+)\)/); return m ? m[1].split(',').map(x => parseFloat(x)) : null; };
  const lum = (p) => { const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
                       return 0.2126 * f(p[0]) + 0.7152 * f(p[1]) + 0.0722 * f(p[2]); };
  const contrast = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
  const background = (el) => {
    while (el) { const c = parse(getComputedStyle(el).backgroundColor); if (c && (c.length < 4 || c[3] > 0.5)) return c; el = el.parentElement; }
    return [255, 255, 255];
  };
  const docW = document.documentElement.scrollWidth, docH = document.documentElement.scrollHeight;
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let node;
  while ((node = walker.nextNode())) {
    const text = node.textContent.replace(/\s+/g, ' ').trim();
    const el = node.parentElement;
    if (!text || !el || ['SCRIPT', 'STYLE', 'NOSCRIPT', 'TEMPLATE'].includes(el.tagName)) continue;
    const reasons = [];
    let a = el, opacity = 1;
    while (a) {
      const cs = getComputedStyle(a);
      if (cs.display === 'none') reasons.push('display:none');
      if (cs.visibility === 'hidden' || cs.visibility === 'collapse') reasons.push('visibility:hidden');
      opacity *= parseFloat(cs.opacity || '1');
      if (cs.clip && /rect\(\s*0(px)?[ ,]+0(px)?[ ,]+0(px)?[ ,]+0(px)?\s*\)/.test(cs.clip)) reasons.push('clip:rect(0)');
      if (cs.clipPath && /inset\(\s*(50|100)%|circle\(\s*0/.test(cs.clipPath)) reasons.push('clip-path');
      a = a.parentElement;
    }
    if (opacity < 0.05) reasons.push('opacity≈0');
    const cs = getComputedStyle(el);
    const size = parseFloat(cs.fontSize);
    if (size < 3) reasons.push('font-size:' + cs.fontSize);
    const fg = parse(cs.color);
    if (fg && fg.length === 4 && fg[3] <= 0.05) reasons.push('color transparente');
    else if (fg) { const k = contrast(fg, background(el)); if (k < 1.3) reasons.push('contraste ' + k.toFixed(2) + ':1'); }
    const range = document.createRange(); range.selectNodeContents(node);
    const r = range.getBoundingClientRect();
    const left = r.left + window.scrollX, top = r.top + window.scrollY;
    if (r.width < 1 || r.height < 1) reasons.push('tamaño 0');
    if (left + r.width < 0 || top + r.height < 0 || left > docW || top > docH) reasons.push('fuera de pantalla');
    if (Math.abs(parseFloat(cs.textIndent) || 0) > 999) reasons.push('text-indent');
    if (reasons.length) {
      const uniq = [...new Set(reasons)];
      const key = text + '|' + uniq.join(',');
      if (!seen.has(key)) { seen.add(key); out.push({ text: text.slice(0, 400), tag: el.tagName.toLowerCase(), reasons: uniq }); }
    }
  }
  return out;
}
"""

# Se compara contra el ancho CONFIGURADO del viewport, no contra window.innerWidth: con
# emulación móvil, Chrome agranda el viewport de layout hasta el ancho del contenido y un
# desborde deja de verse en innerWidth.
OVERFLOW_JS = r"""
(vw) => {
  const culprits = [];
  for (const el of document.querySelectorAll('body *')) {
    const r = el.getBoundingClientRect();
    if (r.width > 0 && r.right > vw + 1) {
      culprits.push({ tag: el.tagName.toLowerCase(), id: el.id || null, cls: (el.className && el.className.toString().slice(0, 60)) || null, right: Math.round(r.right) });
    }
  }
  return { scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth, viewportWidth: vw,
           overflow: document.documentElement.scrollWidth > vw + 1 || window.innerWidth > vw + 1,
           culprits: culprits.slice(0, 8) };
}
"""


def same_page(a, b):
    """/x, /x/, /x.html y /x/index.html son la misma página (así las sirve un servidor estático)."""
    def clean(path):
        path = "/" + (path or "").strip().lstrip("/")
        for suffix in ("/index.html", "/index.htm"):
            if path.endswith(suffix):
                path = path[: -len(suffix)]
        if path.endswith(".html"):
            path = path[: -len(".html")]
        return path.rstrip("/") or "/"
    return clean(a) == clean(b)


def norm(text):
    return " ".join(unicodedata.normalize("NFC", text or "").split()).casefold()


def wait_for_server(base, deadline_s=40):
    end = time.monotonic() + deadline_s
    while time.monotonic() < end:
        try:
            urllib.request.urlopen(base + "/", timeout=2)
            return True
        except urllib.error.HTTPError:
            return True
        except Exception:  # noqa: BLE001
            time.sleep(0.3)
    return False


class Runner:
    def __init__(self, spec, out):
        self.spec, self.out = spec, out
        self.base = spec["base_url"].rstrip("/")
        self.results = {"screenshots": [], "checks": {}, "pages": {}, "console": [], "errors": []}
        self.shot = 0
        self.tabs = {}

    def url(self, page_path):
        return self.base + page_path

    def new_context(self, browser, viewport):
        width, height = VIEWPORTS[viewport]
        ctx = browser.new_context(
            viewport={"width": width, "height": height},
            is_mobile=viewport == "mobile", has_touch=viewport == "mobile",
            device_scale_factor=1, service_workers="block",
        )
        # Solo se permite hablar con la entrega: nada sale a internet (de todos modos la red es interna).
        ctx.route("**/*", lambda route: route.continue_() if route.request.url.startswith(self.base) else route.abort())
        page = ctx.new_page()
        page.on("console", lambda m: m.type == "error" and self.results["console"].append(
            {"viewport": viewport, "url": page.url, "text": m.text[:300]}))
        page.on("pageerror", lambda e: self.results["console"].append(
            {"viewport": viewport, "url": page.url, "text": f"pageerror: {str(e)[:300]}"}))
        self.tabs[viewport] = page
        return ctx

    def open(self, ctx, page_path, viewport):
        page = self.tabs[viewport]
        page.goto(self.url(page_path), wait_until="load", timeout=NAV_TIMEOUT_MS)
        page.wait_for_timeout(400)
        return page

    def capture(self, page, page_path, viewport, label):
        self.shot += 1
        sid = f"S{self.shot}"
        path = self.out / f"{sid}.jpg"
        height = page.evaluate("document.documentElement.scrollHeight")
        width = VIEWPORTS[viewport][0]
        opts = {"path": str(path), "full_page": True, "type": "jpeg", "quality": JPEG_QUALITY}
        if height > MAX_SCREENSHOT_HEIGHT:
            opts["clip"] = {"x": 0, "y": 0, "width": width, "height": MAX_SCREENSHOT_HEIGHT}
        page.screenshot(**opts)
        self.results["screenshots"].append({"id": sid, "page": page_path, "viewport": viewport, "width": width,
                                            "label": label, "file": path.name,
                                            "truncated": height > MAX_SCREENSHOT_HEIGHT})
        return sid

    def survey(self, ctx, viewport):
        for page_path in self.spec["pages"]:
            info = self.results["pages"].setdefault(page_path, {})
            try:
                page = self.open(ctx, page_path, viewport)
            except Exception as exc:  # noqa: BLE001
                info[viewport] = {"error": f"no cargó: {exc}"[:400]}
                continue
            sid = self.capture(page, page_path, viewport, "página completa")
            info[viewport] = {
                "screenshot": sid,
                "title": page.title(),
                "visible_text": page.evaluate("document.body ? document.body.innerText : ''")[:20000],
                "hidden_text": page.evaluate(HIDDEN_TEXT_JS),
                "overflow": page.evaluate(OVERFLOW_JS, VIEWPORTS[viewport][0]),
            }

    # --- chequeos deterministas -----------------------------------------------------------

    def check(self, ctx_by_vp, item):
        kind, page_path, args = item["kind"], item["page"], item["args"]
        fn = getattr(self, f"_check_{kind}")
        try:
            return fn(ctx_by_vp, page_path, args)
        except Exception as exc:  # noqa: BLE001 - un error del chequeo es un fallo, con el motivo
            return {"passed": False, "detail": f"el chequeo falló al correr: {type(exc).__name__}: {str(exc)[:300]}"}

    def _text_in(self, page_path, viewport):
        return norm(self.results["pages"].get(page_path, {}).get(viewport, {}).get("visible_text", ""))

    def _check_text_present(self, ctx_by_vp, page_path, args):
        target = norm(args[0])
        per = {vp: target in self._text_in(page_path, vp) for vp in VIEWPORTS}
        return {"passed": all(per.values()), "viewports": per,
                "detail": f"texto {args[0]!r} visible: " + ", ".join(f"{k}={'sí' if v else 'no'}" for k, v in per.items())}

    def _check_title_contains(self, ctx_by_vp, page_path, args):
        title = self.results["pages"].get(page_path, {}).get("desktop", {}).get("title", "")
        ok = norm(args[0]) in norm(title)
        return {"passed": ok, "detail": f"<title> = {title!r}"}

    def _check_element_visible(self, ctx_by_vp, page_path, args):
        role, name = args
        per, details = {}, []
        for vp, ctx in ctx_by_vp.items():
            page = self.open(ctx, page_path, vp)
            loc = page.get_by_role(role, name=name).first
            visible = loc.count() > 0 and loc.is_visible()
            inside = False
            if visible:
                loc.scroll_into_view_if_needed(timeout=3000)
                box = loc.bounding_box()
                inside = bool(box) and box["x"] >= -1 and box["x"] + box["width"] <= VIEWPORTS[vp][0] + 1
            per[vp] = visible and inside
            details.append(f"{vp}: visible={'sí' if visible else 'no'}, dentro del ancho={'sí' if inside else 'no'}")
        return {"passed": all(per.values()), "viewports": per, "detail": "; ".join(details)}

    def _check_link_navigates(self, ctx_by_vp, page_path, args):
        name, dest = args
        page = self.open(ctx_by_vp["desktop"], page_path, "desktop")
        link = page.get_by_role("link", name=name).first
        if link.count() == 0:
            return {"passed": False, "detail": f"no hay un enlace llamado {name!r}"}
        href = link.get_attribute("href")
        link.click(timeout=5000)
        page.wait_for_timeout(800)
        if dest.startswith("#"):
            hash_ok = urllib.parse.urlparse(page.url).fragment == dest[1:]
            in_view = page.evaluate(
                "(id) => { const el = document.getElementById(id); if (!el) return false;"
                " const r = el.getBoundingClientRect(); return r.top < window.innerHeight && r.bottom > 0; }", dest[1:])
            ok = hash_ok or in_view
            detail = f"href={href!r}; url={page.url}; ancla a la vista={'sí' if in_view else 'no'}"
        else:
            parsed = urllib.parse.urlparse(page.url)
            ok = page.url.rstrip("/") == dest.rstrip("/") or (dest.startswith("/") and same_page(parsed.path, dest))
            detail = f"href={href!r}; url tras el clic={page.url}"
        sid = self.capture(page, page_path, "desktop", f"tras hacer clic en {name!r}")
        return {"passed": ok, "detail": detail, "screenshot": sid}

    def _check_form_submits(self, ctx_by_vp, page_path, args):
        endpoint, success = args[0], args[1]
        fields = [a.split("=", 1) for a in args[2:] if "=" in a and not a.startswith("boton=")]
        button = next(a.split("=", 1)[1] for a in args if a.startswith("boton="))
        page = self.open(ctx_by_vp["desktop"], page_path, "desktop")
        captured = []

        def handle(route):
            req = route.request
            captured.append({"method": req.method, "url": req.url, "body": (req.post_data or "")[:4000]})
            route.fulfill(status=200, content_type="application/json", body='{"ok": true}')

        page.route(f"**{endpoint}", handle)
        try:
            return self._submit(page, page_path, endpoint, success, fields, button, captured)
        finally:
            page.unroute(f"**{endpoint}")

    def _submit(self, page, page_path, endpoint, success, fields, button, captured):
        missing = []
        for label, value in fields:
            box = page.get_by_label(label).first
            if box.count() == 0:
                missing.append(label)
                continue
            box.fill(value)
        if missing:
            return {"passed": False, "detail": f"no hay campos con la etiqueta: {missing}"}
        btn = page.get_by_role("button", name=button).first
        if btn.count() == 0:
            return {"passed": False, "detail": f"no hay un botón llamado {button!r}"}
        btn.click(timeout=5000)
        try:
            page.get_by_text(success).first.wait_for(state="visible", timeout=5000)
            confirmed = True
        except PlaywrightTimeout:
            confirmed = False
        page.wait_for_timeout(300)
        body = urllib.parse.unquote_plus(" ".join(c["body"] for c in captured))
        values_sent = all(value in body for _, value in fields)
        post = any(c["method"] == "POST" for c in captured)
        sid = self.capture(page, page_path, "desktop", "tras enviar el formulario")
        ok = post and values_sent and confirmed
        return {"passed": ok, "screenshot": sid,
                "detail": (f"POST a {endpoint}: {'sí' if post else 'no'}; valores enviados: {'sí' if values_sent else 'no'}; "
                           f"confirmación visible: {'sí' if confirmed else 'no'}"),
                "requests": captured}

    def _check_no_horizontal_overflow(self, ctx_by_vp, page_path, args):
        info = self.results["pages"].get(page_path, {}).get("mobile", {}).get("overflow")
        if info is None:
            return {"passed": False, "detail": "la página no cargó en móvil"}
        return {"passed": not info["overflow"],
                "detail": (f"viewport de {info['viewportWidth']} px: scrollWidth={info['scrollWidth']}, "
                           f"innerWidth={info['innerWidth']}"),
                "culprits": info["culprits"]}

    def run(self):
        if not wait_for_server(self.base):
            self.results["errors"].append(f"la entrega no respondió en {self.base}")
        with sync_playwright() as p:
            browser = p.chromium.launch()
            contexts = {vp: self.new_context(browser, vp) for vp in VIEWPORTS}
            for vp, ctx in contexts.items():
                self.survey(ctx, vp)
            for item in self.spec["checks"]:
                self.results["checks"][item["id"]] = self.check(contexts, item)
            for ctx in contexts.values():
                ctx.close()
            browser.close()
        (self.out / "results.json").write_text(json.dumps(self.results, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    spec = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    out = Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    Runner(spec, out).run()
    print("ok")
