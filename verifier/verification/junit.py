"""Lectura del reporte JUnit XML (xunit1) que escribe pytest."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

MESSAGE_LIMIT = 2000


@dataclass(frozen=True)
class TestOutcome:
    __test__ = False  # que pytest no la confunda con una clase de tests

    nodeid: str          # "test_c1.py::test_suma"; para errores de colección, "test_c1.py"
    file: str            # "test_c1.py"
    name: str
    outcome: str         # passed | failed | error | skipped
    message: str
    summary: str = ""    # una línea (atributo `message` del JUnit), sin el código del test

    @property
    def criterion_id(self) -> str | None:
        return criterion_for_file(self.file)


def criterion_for_file(file: str) -> str | None:
    match = re.fullmatch(r"test_(c\d+)\.py", file.rsplit("/", 1)[-1])
    return match.group(1).upper() if match else None


def hidden_test_filename(criterion_id: str) -> str:
    return f"test_{criterion_id.lower()}.py"


def parse_junit(xml_bytes: bytes) -> list[TestOutcome]:
    root = ET.fromstring(xml_bytes)
    outcomes = []
    for case in root.iter("testcase"):
        classname = case.get("classname", "")
        name = case.get("name", "")
        file = case.get("file") or (classname.replace(".", "/") + ".py" if classname else name.replace(".", "/") + ".py")
        file = file.rsplit("/", 1)[-1]
        outcome, message, summary = "passed", "", ""
        for tag in ("failure", "error", "skipped"):
            child = case.find(tag)
            if child is not None:
                outcome = {"failure": "failed"}.get(tag, tag)
                text = (child.get("message") or "") + "\n" + (child.text or "")
                message = text.strip()[:MESSAGE_LIMIT]
                summary = (child.get("message") or "").strip().split("\n")[0][:300]
                break
        nodeid = f"{file}::{name}" if classname else file  # sin classname = error de colección
        outcomes.append(TestOutcome(nodeid=nodeid, file=file, name=name, outcome=outcome, message=message,
                                    summary=summary))
    return outcomes
