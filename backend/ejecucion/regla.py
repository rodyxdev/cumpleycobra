"""Regla final determinista del verificador por ejecución (fase 3, adaptada de v2 `verdict.py`).

Por criterio (todos los criterios de v1 son obligatorios):
- tipo `test`, con algún test que no pasó:
    juez = test_defect con evidencia verificada (línea del test + texto del acuerdo) → revisión manual;
    cualquier otra cosa (incluido "pass") → fail. El modelo nunca aprueba sobre un fallo real.
- tipo `test`, con todos sus tests pasando:
    juez = pass → pass; juez = fail con evidencia verificada → fail;
    juez sin evidencia, test_defect, ausente o caído → revisión manual.
- tipo `lectura`: juez = pass → pass; juez = fail → fail; sin veredicto → revisión manual.
Global: aprobado solo si todos los criterios pasan y no hay señales de inyección, trampa o
manipulación. Revisión manual = no se paga solo; el cliente decide con `client_release`.
Antes de los criterios: higiene, build de dependencias y la capa de seguridad de v1 (que protege
al cliente que va a correr el código) rechazan por sí solas.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

from .juez import EvidenceChecker, JudgeOutput
from .senales import Signal

Status = Literal["pass", "fail", "manual_review", "not_evaluated"]
STAGES = ["hygiene", "build", "static", "tests", "judge", "final"]
FLAG_NAMES = {"injection": "inyección", "cheating": "trampa", "tampering": "manipulación"}


@dataclass
class CriterionDecision:
    index: int
    tipo: str | None
    status: Status
    stage: str
    reasons: list[str] = field(default_factory=list)
    tests: list[dict] = field(default_factory=list)
    judge_verdict: str | None = None
    judge_reasoning: str | None = None
    judge_evidence: list[dict] = field(default_factory=list)


@dataclass
class Decision:
    approved: bool
    status: Literal["approved", "rejected", "manual_review"]
    stage: str
    criteria: list[CriterionDecision]
    flags: dict[str, bool]
    reasons: list[str]
    security_flags: list[str]

    def comparison(self) -> list[str]:
        out = []
        for d in self.criteria:
            mark = "✓" if d.status == "pass" else "✗"
            if d.status == "pass":
                detail = (f"{len(d.tests)} de {len(d.tests)} tests pasan" if d.tests else "cumple al leer el código")
                if d.judge_reasoning:
                    detail += f". {d.judge_reasoning}"
            elif d.status == "manual_review":
                detail = "requiere revisión manual. " + " ".join(d.reasons)
            elif d.status == "not_evaluated":
                detail = "no evaluado. " + " ".join(d.reasons)
            else:
                detail = " ".join(d.reasons) or (d.judge_reasoning or "no cumple")
                if d.judge_reasoning and d.judge_reasoning not in detail:
                    detail += f" {d.judge_reasoning}"
            out.append(f"{mark} Criterio {d.index}: {detail.strip()}")
        return out

    def reason(self) -> str:
        if self.approved:
            return "La entrega cumple todos los criterios acordados: los tests ocultos pasan y el juez lo confirma."
        prefix = "Requiere revisión manual: " if self.status == "manual_review" else "Rechazado: "
        return prefix + "; ".join(self.reasons)

    def hash_criteria(self) -> list[dict]:
        return [{"index": d.index, "status": d.status} for d in self.criteria]

    def as_dict(self) -> dict:
        return {"approved": self.approved, "status": self.status, "stage": self.stage, "flags": self.flags,
                "reasons": self.reasons, "security_flags": self.security_flags,
                "criteria": [asdict(d) for d in self.criteria]}


def _test_summary(tests: list[dict]) -> list[dict]:
    return [{"nodeid": t["nodeid"], "name": t["name"], "outcome": t["outcome"],
             "summary": t.get("summary", ""), "message": t.get("message", "")[:600]} for t in tests]


def _judge_for(judge: JudgeOutput | None, index: int):
    return next((j for j in judge.criteria if j.numero == index), None) if judge else None


def _decide_test(index: int, tests: list[dict], judge: JudgeOutput | None,
                 checker: EvidenceChecker | None) -> CriterionDecision:
    d = CriterionDecision(index, "test", "manual_review", "tests", tests=_test_summary(tests))
    if not tests:
        d.status = "fail"
        d.reasons.append("no hay resultados de tests para este criterio")
        return d
    jc = _judge_for(judge, index)
    valid = checker.valid(jc.evidence) if (jc and checker) else []
    if jc:
        d.judge_verdict, d.judge_reasoning = jc.verdict, jc.reasoning
        d.judge_evidence = [{**e.model_dump(), "verified": e in valid} for e in jc.evidence]

    failing = [t for t in tests if t["outcome"] != "passed"]
    if failing:
        kinds = {e.kind for e in valid}
        if jc and jc.verdict == "test_defect" and {"test_code", "contract"} <= kinds:
            d.status, d.stage = "manual_review", "judge"
            d.reasons.append("el juez señala un test defectuoso con evidencia verificada")
        else:
            d.status = "fail"
            d.reasons.append(f"{len(failing)} de {len(tests)} tests no pasaron")
            if jc and jc.verdict == "pass":
                d.reasons.append("el juez dijo pass pero hay tests que fallan: se ignora al juez")
            if jc and jc.verdict == "test_defect":
                d.reasons.append("el juez alegó un test defectuoso sin evidencia verificable: se mantiene el fallo")
        return d

    d.stage = "judge"
    if jc is None:
        d.reasons.append("los tests pasan, pero el juez no emitió veredicto para este criterio")
    elif jc.verdict == "pass":
        d.status = "pass"
    elif jc.verdict == "fail" and valid:
        d.status = "fail"
        d.reasons.append("los tests pasan, pero el juez detectó un problema con evidencia verificada")
    else:
        d.reasons.append(f"los tests pasan; el juez dijo {jc.verdict} sin evidencia verificable")
    return d


def _decide_reading(index: int, judge: JudgeOutput | None, checker: EvidenceChecker | None) -> CriterionDecision:
    d = CriterionDecision(index, "lectura", "manual_review", "judge")
    jc = _judge_for(judge, index)
    if jc is None:
        d.reasons.append("el juez no emitió veredicto para este criterio")
        return d
    valid = checker.valid(jc.evidence) if checker else []
    d.judge_verdict, d.judge_reasoning = jc.verdict, jc.reasoning
    d.judge_evidence = [{**e.model_dump(), "verified": e in valid} for e in jc.evidence]
    if jc.verdict == "pass":
        d.status = "pass"
    elif jc.verdict == "fail":
        d.status = "fail"
    else:
        d.reasons.append("test_defect no aplica a un criterio sin tests")
    return d


def decide(*, suite: dict, hygiene: dict, build: dict | None, security_problems: list[str],
           signals: list[Signal], outcomes: dict[int, list[dict]], test_run_error: str | None,
           judge: JudgeOutput | None, judge_error: str | None, checker: EvidenceChecker | None) -> Decision:
    flags = {"injection": False, "cheating": False, "tampering": False}
    for s in signals:
        flags[s.kind] = True
    if judge and checker:
        flags["injection"] |= judge.injection_detected and bool(checker.valid(judge.injection_evidence))
        flags["cheating"] |= judge.cheating_detected and bool(checker.valid(judge.cheating_evidence))
    security_flags = [f"{FLAG_NAMES[s.kind]} en {s.ref}: {s.detail}" for s in signals]
    if judge and checker:
        for kind, detected, evidence in (("injection", judge.injection_detected, judge.injection_evidence),
                                         ("cheating", judge.cheating_detected, judge.cheating_evidence)):
            for e in checker.valid(evidence) if detected else []:
                security_flags.append(f"{FLAG_NAMES[kind]} señalada por el juez en {e.ref}: {e.quote[:120]}")

    indexes = [c["index"] for c in suite["criteria"]]
    tipos = {c["index"]: c["tipo"] for c in suite["criteria"]}

    def all_not_evaluated(stage: str, why: str) -> list[CriterionDecision]:
        return [CriterionDecision(i, tipos[i], "not_evaluated", stage, reasons=[why]) for i in indexes]

    if hygiene.get("blockers"):
        reasons = list(hygiene["blockers"])
        return Decision(False, "rejected", "hygiene", all_not_evaluated("hygiene", "la entrega no pasó la higiene"),
                        flags, reasons, security_flags)
    if build is not None and (build.get("exit_code") != 0 or build.get("timed_out")):
        reasons = ["no se pudieron instalar las dependencias declaradas (solo se aceptan wheels de PyPI)"]
        return Decision(False, "rejected", "build", all_not_evaluated("build", reasons[0]), flags, reasons, security_flags)
    if security_problems:
        security_flags = list(security_problems) + security_flags
        reasons = ["la capa de seguridad rechazó el código: " + "; ".join(security_problems)]
        return Decision(False, "rejected", "static", all_not_evaluated("static", "rechazo de seguridad"),
                        flags, reasons, security_flags)

    decisions = []
    for i in indexes:
        if tipos[i] == "lectura":
            decisions.append(_decide_reading(i, judge, checker))
        elif test_run_error:
            decisions.append(CriterionDecision(i, "test", "fail", "tests", reasons=[test_run_error]))
        else:
            decisions.append(_decide_test(i, outcomes.get(i, []), judge, checker))

    reasons: list[str] = []
    if judge_error:
        reasons.append(f"el juez no respondió ({judge_error})")
    failed = [d for d in decisions if d.status == "fail"]
    manual = [d for d in decisions if d.status == "manual_review"]
    if failed:
        stage = min((d.stage for d in failed), key=STAGES.index)
        reasons.append("criterios no cumplidos: " + ", ".join(str(d.index) for d in failed))
        status = "rejected"
    elif manual or any(flags.values()):
        stage = "judge" if manual else "final"
        if manual:
            reasons.append("criterios en revisión manual: " + ", ".join(str(d.index) for d in manual))
        status = "manual_review"
    else:
        stage, status = "final", "approved"
    if any(flags.values()):
        reasons.append("se detectaron señales de " + ", ".join(FLAG_NAMES[k] for k, v in flags.items() if v)
                       + ": no se aprueba automáticamente")
    return Decision(status == "approved", status, stage, decisions, flags, reasons, security_flags)
