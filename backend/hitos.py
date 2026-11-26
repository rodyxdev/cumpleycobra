"""Pago por hitos (etapa 2 de docs/hitos/diseno.md).

Todo está detrás de `MILESTONES_ENABLED` (apagado por defecto). Sin la variable,
`POST /tasks` rechaza `milestones` y el resto de la API se comporta exactamente
igual que antes.
"""

from __future__ import annotations

import os
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr

from . import drafting
from .hashing import milestone_rules_hash

MIN_MILESTONES = 2
MAX_MILESTONES = 10
MAX_MILESTONE_DEADLINE_MINUTES = 28 * 24 * 60  # 40_320 = 28 días (límite del contrato v2/v3)

Title = Annotated[StrictStr, Field(min_length=1, max_length=120)]


class MilestoneIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: Title
    criteria: list[drafting.Criterion] = Field(min_length=1, max_length=8)
    amount: StrictInt = Field(gt=0)
    deadline_minutes: StrictInt = Field(gt=0, le=MAX_MILESTONE_DEADLINE_MINUTES)


def enabled() -> bool:
    return os.environ.get("MILESTONES_ENABLED", "").strip().lower() in ("1", "true", "yes")


def contract_id() -> str | None:
    return (os.environ.get("MILESTONES_CONTRACT_ID") or "").strip() or None


def is_milestone_task(task: dict) -> bool:
    return bool(task.get("milestones"))


def target_for(task: dict, milestone: int | None) -> dict:
    """Devuelve el documento de la tarea o el del hito `milestone`."""
    return task if milestone is None else task["milestones"][milestone]


def build_milestones(
    items: list[MilestoneIn], *, task_id: str, base_spec: dict
) -> tuple[list[dict], int, int, list[str]]:
    """Valida los hitos y arma la estructura que se guarda en el documento de la tarea.

    Devuelve `(milestones, total_amount, max_deadline_minutes, combined_criteria)`.
    Lanza `ValueError` si hay cantidad fuera de rango, títulos o criterios vacíos, o plazos decrecientes.
    """
    n = len(items)
    if not MIN_MILESTONES <= n <= MAX_MILESTONES:
        raise ValueError(f"Un proyecto por hitos debe tener entre {MIN_MILESTONES} y {MAX_MILESTONES} hitos")
    milestones: list[dict] = []
    combined_criteria: list[str] = []
    total_amount = 0
    prev_deadline = 0
    for i, item in enumerate(items):
        title = item.title.strip()
        if not title:
            raise ValueError(f"El hito {i + 1} debe tener un título")
        criteria = [c.strip() for c in item.criteria if c.strip()]
        if not criteria:
            raise ValueError(f"El hito {i + 1} debe tener al menos un criterio")
        if item.deadline_minutes < prev_deadline:
            raise ValueError(
                "Los plazos de los hitos no pueden bajar: cada hito debe vencer igual o después que el anterior"
            )
        prev_deadline = item.deadline_minutes
        total_amount += item.amount
        combined_criteria.extend(criteria)
        m_spec = {**base_spec, "criteria": criteria}
        m_hash = milestone_rules_hash(m_spec, proyecto=task_id, indice=i, de=n, titulo=title)
        milestones.append({
            "index": i,
            "title": title,
            "spec": m_spec,
            "rules_hash": m_hash,
            "amount": item.amount,
            "deadline_minutes": item.deadline_minutes,
            "submissions": [],
            "cache": {},
            "codes": {},
            "latest_code_hash": None,
            "consented_code_hash": None,
            "release": None,
        })
    return milestones, total_amount, prev_deadline, combined_criteria
