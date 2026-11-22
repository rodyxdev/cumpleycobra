"""Perfil web: portafolio de dos páginas. 1 correcta y 4 que no deben aprobarse."""

NOMBRE = "web_portafolio"

ACUERDO = {
    "description": "Sitio de portafolio de dos páginas para la diseñadora Ana Ruiz: una página de inicio con sus "
                   "proyectos y una página de contacto.",
    "criteria": [
        "Las dos páginas muestran el nombre \"Ana Ruiz\".",
        "La página de inicio tiene un enlace llamado \"Contacto\" que lleva a /contacto.",
        "La página /contacto muestra el correo \"hola@anaruiz.mx\".",
        "La página de inicio muestra al menos tres proyectos, cada uno como una tarjeta con su título visible.",
    ],
    "language": "web",
    "allowed_deps": [],
    "examples": [],
    "web": {"pages": ["/", "/contacto"]},
}

ESTILO = ("<style>body{font-family:system-ui,sans-serif;margin:0;padding:24px} .grid{display:grid;"
          "grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:16px} .card{border:1px solid #ccc;"
          "border-radius:8px;padding:16px}</style>")


def html(titulo, cuerpo):
    return (f'<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" '
            f'content="width=device-width, initial-scale=1"><title>{titulo}</title>{ESTILO}</head><body>'
            f"{cuerpo}</body></html>\n")


def inicio(href="/contacto", proyectos=("Marca Café Luna", "Revista Norte", "App Ruta Verde"), nombre="Ana Ruiz"):
    tarjetas = "".join(f'<div class="card"><h2>{p}</h2><p>Identidad visual y diseño editorial.</p></div>' for p in proyectos)
    return html(f"{nombre} · Portafolio", f'<header><h1>{nombre}</h1><nav><a href="{href}">Contacto</a></nav></header>'
                                       f'<main><div class="grid">{tarjetas}</div></main>')


def contacto(correo="hola@anaruiz.mx", nombre="Ana Ruiz"):
    return html(f"Contacto · {nombre}", f'<header><h1>{nombre}</h1><nav><a href="/">Inicio</a></nav></header>'
                                       f'<main><p>Escríbeme a {correo}</p></main>')


def _e(id_, aprobar, motivo, index, contact):
    return {"id": id_, "aprobar": aprobar, "motivo": motivo,
            "files": {"index.html": index, "contacto/index.html": contact}}


ENTREGAS = [
    _e("correcta", True, "cumple todo", inicio(), contacto()),
    _e("enlace-roto", False, "el enlace Contacto lleva a /contact", inicio(href="/contact"), contacto()),
    _e("correo-equivocado", False, "el correo de contacto es otro", inicio(), contacto(correo="contacto@anaruiz.mx")),
    _e("dos-proyectos", False, "solo muestra dos proyectos", inicio(proyectos=("Marca Café Luna", "Revista Norte")),
       contacto()),
    _e("sin-nombre-en-contacto", False, "la página de contacto no muestra el nombre", inicio(),
       contacto(nombre="Portafolio")),
]
