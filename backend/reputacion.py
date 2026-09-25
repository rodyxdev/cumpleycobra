"""Reputación verificable del programador: solo tareas Released confirmadas en el contrato.

Fuentes:
- El estado Released y el programador pagado se leen del contrato (get_task), nunca solo de state.json.
- Cómo se pagó, el hash y la fecha salen de los eventos del contrato: `release` (firmado por el
  árbitro tras el veredicto del motor) o `client_release` (aprobación manual del cliente). Se leen
  con getEvents del RPC, que guarda unos 7 días; si el evento ya no está o el RPC falla, se usa lo
  guardado en state.json (el release del motor) y la tarea manual queda sin hash.
- De state.json solo salen la descripción, el número de criterios y la calificación.

El historial nunca incluye código, tokens, trace, logic ni la dirección del cliente.
"""

import logging
import threading
import weakref
from datetime import datetime, timezone

from stellar_sdk import scval, xdr
from stellar_sdk.soroban_rpc import EventFilter, EventFilterType

log = logging.getLogger("cumpleycobra.reputacion")

DESCRIPTION_MAX = 140
PAYMENT_TOPICS = ("release", "client_release")
MAX_EVENT_PAGES = 1000
TERMINAL = {"Released", "Refunded"}


# ---------------------------------------------------------------------------
# Eventos de pago del contrato
# ---------------------------------------------------------------------------
class PaymentEvents:
    """Eventos release y client_release, leídos del RPC con cursor: cada consulta sigue donde quedó."""

    def __init__(self, server, contract_id: str):
        self.server = server
        self.contract_id = contract_id
        self.cursor: str | None = None
        self.by_task: dict[str, dict] = {}
        self.lock = threading.Lock()

    def _filters(self):
        topics = [[scval.to_symbol(t).to_xdr(), "*"] for t in PAYMENT_TOPICS]  # uno u otro tópico
        return [EventFilter(event_type=EventFilterType.CONTRACT, contract_ids=[self.contract_id], topics=topics)]

    def _record(self, event) -> None:
        if not event.in_successful_contract_call:
            return
        topics = [scval.to_native(xdr.SCVal.from_xdr(t)) for t in event.topic]
        if len(topics) < 2 or topics[0] not in PAYMENT_TOPICS:
            return
        self.by_task[str(topics[1])] = {
            "paid_by": "motor" if topics[0] == "release" else "manual",
            "transaction_hash": event.transaction_hash,
            "paid_at": _iso(event.ledger_close_at),
        }

    def refresh(self) -> dict[str, dict]:
        """Lee los eventos nuevos y devuelve {task_id: {paid_by, transaction_hash, paid_at}}."""
        with self.lock:
            filters = self._filters()
            try:
                resp = self._first_page(filters)
            except Exception:  # noqa: BLE001 - el cursor pudo salir de la ventana del RPC
                self.cursor = None
                resp = self._first_page(filters)
            for _ in range(MAX_EVENT_PAGES):
                for event in resp.events:
                    self._record(event)
                previous, self.cursor = self.cursor, resp.cursor
                # Sin eventos y sin avance del cursor: ya se llegó al último ledger.
                if not resp.events and resp.cursor == previous:
                    break
                resp = self.server.get_events(filters=filters, cursor=self.cursor, limit=100)
            return dict(self.by_task)

    def _first_page(self, filters):
        if self.cursor is not None:
            return self.server.get_events(filters=filters, cursor=self.cursor, limit=100)
        oldest = self.server.get_health().oldest_ledger
        return self.server.get_events(start_ledger=oldest + 1, filters=filters, limit=100)


# Lecturas de get_task por cliente de cadena. Un estado terminal (Released o Refunded) no cambia y se
# guarda sin vencimiento; los demás (sin depósito o Funded) vencen a los NON_TERMINAL_TTL segundos.
NON_TERMINAL_TTL = 30
_onchain_cache: "weakref.WeakKeyDictionary[object, dict[str, tuple]]" = weakref.WeakKeyDictionary()


def onchain_cache(chain) -> dict[str, tuple]:
    """{task_id: (lectura de get_task, vence_en | None)} de este cliente de cadena."""
    try:
        return _onchain_cache.setdefault(chain, {})
    except TypeError:  # objeto sin weakref: sin caché
        return {}


def cache_entry(onchain: dict | None, now: float) -> tuple:
    terminal = bool(onchain) and onchain.get("status") in TERMINAL
    return onchain, None if terminal else now + NON_TERMINAL_TTL


# ---------------------------------------------------------------------------
# Lógica pura
# ---------------------------------------------------------------------------
def _iso(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        value = datetime.fromtimestamp(value, tz=timezone.utc)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    return str(value)


def short_description(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= DESCRIPTION_MAX else text[: DESCRIPTION_MAX - 1].rstrip() + "…"


def _submission_time(task: dict, code_hash: str | None):
    times = [s["at"] for s in task.get("submissions", []) if s.get("code_hash") == code_hash and s.get("at")]
    return times[-1] if times else None


def paid_records(tasks: dict, onchain: dict[str, dict | None], events: dict[str, dict]) -> list[dict]:
    """Una fila por tarea Released on-chain. `onchain` viene de get_task; `events`, de PaymentEvents."""
    records = []
    for task_id, task in tasks.items():
        oc = onchain.get(task_id)
        if not oc or oc.get("status") != "Released" or not oc.get("freelancer"):
            continue
        rel = task.get("release") or {}
        ev = events.get(task_id)
        if ev:
            paid_by, tx_hash, paid_at = ev["paid_by"], ev["transaction_hash"], ev["paid_at"]
        elif rel.get("status") == "success":
            paid_by, tx_hash = "motor", rel.get("transaction_hash")
            paid_at = _iso(_submission_time(task, rel.get("code_hash")))
        else:
            paid_by, tx_hash, paid_at = "manual", None, None  # client_release fuera de la ventana del RPC
        rating = task.get("rating")
        records.append({
            "address": oc["freelancer"],
            "client": oc.get("client"),
            "task_id": task_id,
            "description": short_description(task["spec"]["description"]),
            "criteria_count": len(task["spec"]["criteria"]),
            "amount": int(oc["amount"]),
            "paid_by": paid_by,
            "transaction_hash": tx_hash,
            "paid_at": paid_at,
            "rating": {"estrellas": rating["estrellas"], "comentario": rating.get("comentario")} if rating else None,
        })
    return records


def summary(address: str, records: list[dict]) -> dict:
    mine = [r for r in records if r["address"] == address]
    stars = [r["rating"]["estrellas"] for r in mine if r["rating"]]
    return {
        "address": address,
        "engine_paid": sum(r["paid_by"] == "motor" for r in mine),
        "manual_paid": sum(r["paid_by"] == "manual" for r in mine),
        "distinct_clients": len({r["client"] for r in mine if r["client"]}),
        "rating_average": round(sum(stars) / len(stars), 2) if stars else None,
        "rating_count": len(stars),
    }


def leaderboard(records: list[dict]) -> list[dict]:
    rows = [summary(a, records) for a in {r["address"] for r in records}]
    return sorted(rows, key=lambda r: (-r["engine_paid"], -r["manual_paid"],
                                       -(r["rating_average"] or 0), r["address"]))


HISTORY_FIELDS = ("task_id", "description", "criteria_count", "amount", "paid_by",
                  "transaction_hash", "paid_at", "rating")


def profile(address: str, records: list[dict]) -> dict:
    mine = [r for r in records if r["address"] == address]
    mine.sort(key=lambda r: r["paid_at"] or "", reverse=True)
    # Solo campos públicos: nada de la dirección del cliente, código, tokens, trace ni logic.
    return {**summary(address, records), "history": [{k: r[k] for k in HISTORY_FIELDS} for r in mine]}
