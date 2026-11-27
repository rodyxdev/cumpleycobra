"""Funciones experimentales de Ship It, detrás de EXTRAS_ENABLED (apagada por defecto: 404).

Nada de aquí toca el flujo del dinero ni el contrato: solo lee lo que ya existe. Si una función
se queda, se mueve a su módulo y sale de esta bandera; si no, se borra este archivo y su
`include_router` en main.py.
"""

import os
from xml.sax.saxutils import escape

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

router = APIRouter()


def enabled() -> bool:
    return os.environ.get("EXTRAS_ENABLED", "").strip().lower() in ("1", "true", "yes")


def _require_enabled() -> None:
    if not enabled():
        raise HTTPException(status_code=404)


def _text_width(text: str) -> int:
    # Aproximación de ancho para Verdana 11 px (la misma idea que las insignias de los README).
    return int(sum(7.2 if ch.isupper() or ch.isdigit() else 6.1 for ch in text)) + 12


def badge_svg(summary: dict) -> str:
    """Insignia de dos bloques: «Cumple&Cobra» y las tareas pagadas con su calificación."""
    paid = summary["engine_paid"] + summary["manual_paid"]
    value = f"{paid} pagada" + ("" if paid == 1 else "s")
    if summary.get("rating_average") is not None:
        value += f" · ★ {summary['rating_average']:.1f}"
    label = "Cumple&Cobra"
    lw, vw = _text_width(label), _text_width(value)
    width = lw + vw
    color = "#1f8a4c" if paid else "#6b7280"
    title = f"{label}: {value} (verificado en el contrato de Stellar testnet)"
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="20" role="img" aria-label="{escape(title, {chr(34): "&quot;"})}">'
        f"<title>{escape(title)}</title>"
        f'<rect width="{lw}" height="20" rx="3" fill="#0b3b6f"/>'
        f'<rect x="{lw}" width="{vw}" height="20" rx="3" fill="{color}"/>'
        f'<rect x="{lw}" width="4" height="20" fill="{color}"/>'
        '<g fill="#fff" font-family="Verdana,DejaVu Sans,sans-serif" font-size="11" text-anchor="middle">'
        f'<text x="{lw / 2:.1f}" y="14">{escape(label)}</text>'
        f'<text x="{lw + vw / 2:.1f}" y="14">{escape(value)}</text>'
        "</g></svg>"
    )


@router.get("/programadores/{address}/insignia.svg")
async def programmer_badge(address: str):
    """Insignia pública para el README o el portafolio del programador, con datos on-chain."""
    _require_enabled()
    from backend import main, reputacion  # import tardío: main incluye este router

    main.check_address(address, "address")
    summary = reputacion.summary(address, await main.released_records())
    return Response(badge_svg(summary), media_type="image/svg+xml",
                    headers={"Cache-Control": "public, max-age=300"})


EXPLORER_TX = "https://stellar.expert/explorer/testnet/tx/"
EXPLORER_CONTRACT = "https://stellar.expert/explorer/testnet/contract/"


@router.get("/tasks/{task_id}/comprobante")
async def payment_receipt(task_id: str):
    """Comprobante público de un pago: solo lo que ya es público en el contrato y en su evento.

    Sin código, tokens, análisis ni dirección del cliente. Con `rules_hash`, `code_hash` y
    `verdict_hash`, cualquiera puede cruzarlo con el evento de `release` en el explorador.
    """
    _require_enabled()
    from backend import hitos, main, reputacion

    task = main.get_task_or_404(task_id)
    if hitos.is_milestone_task(task):
        raise main.err(400, "INVALID_REQUEST", "El comprobante todavía no aplica a tareas por hitos")
    onchain, _ = await main.read_chain(task_id)
    if not onchain or onchain.get("status") != "Released":
        raise main.err(409, "TASK_NOT_RELEASED", "La tarea todavía no se paga en el contrato")
    events: dict = {}
    source = main.payment_events()
    if source is not None:
        try:
            events = await main.run_in_threadpool(source.refresh)
        except Exception:  # noqa: BLE001 - sin eventos se usa lo guardado
            events = {}
    record = reputacion.paid_records({task_id: task}, {task_id: onchain}, events)[0]
    release = task.get("release") or {}
    engine = record["paid_by"] == "motor" and release.get("status") == "success"
    contract_id = getattr(main.app.state.settings, "contract_id", None)
    tx = record["transaction_hash"]
    return {
        "task_id": task_id,
        "programador": record["address"],
        "amount": record["amount"],
        "paid_by": record["paid_by"],
        "paid_at": record["paid_at"],
        "transaction_hash": tx,
        "explorer_url": EXPLORER_TX + tx if tx else None,
        "contract_id": contract_id,
        "contract_url": EXPLORER_CONTRACT + contract_id if contract_id else None,
        "rules_hash": onchain.get("rules_hash"),
        "rules_hash_matches": onchain.get("rules_hash") == task["rules_hash"],
        "criteria_count": record["criteria_count"],
        "code_hash": release.get("code_hash") if engine else None,
        "verdict_hash": release.get("verdict_hash") if engine else None,
        "verify_url": f"/verificar?tarea={task_id}",
    }
