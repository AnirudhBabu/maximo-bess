"""Check registry, finding type and shared helpers."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from ..models import Dataset
from ..repository import Repository


class Severity(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


SEVERITY_BY_CODE: dict[str, Severity] = {
    "A01": Severity.MEDIUM,
    "A02": Severity.MEDIUM,
    "A03": Severity.HIGH,
    "A04": Severity.MEDIUM,
    "A05": Severity.LOW,
    "A06": Severity.HIGH,
    "P01": Severity.MEDIUM,
    "P02": Severity.HIGH,
    "P03": Severity.HIGH,
    "P04": Severity.MEDIUM,
    "W01": Severity.MEDIUM,
    "W02": Severity.HIGH,
    "W03": Severity.MEDIUM,
    "W04": Severity.LOW,
}

ALL_CODES: tuple[str, ...] = tuple(SEVERITY_BY_CODE)


@dataclass(frozen=True)
class Finding:
    """One data-quality problem, identified by check code + record."""

    code: str
    severity: Severity
    record_type: str
    record_id: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity.value,
            "record_type": self.record_type,
            "record_id": self.record_id,
            "message": self.message,
            "details": dict(self.details),
        }


CheckFn = Callable[[Dataset], list[Finding]]
REGISTRY: dict[str, CheckFn] = {}


def check(code: str) -> Callable[[CheckFn], CheckFn]:
    """Register a check function under its stable code."""

    def decorator(function: CheckFn) -> CheckFn:
        if code not in SEVERITY_BY_CODE:
            raise ValueError(f"unknown check code {code!r}")
        if code in REGISTRY:
            raise ValueError(f"duplicate check code {code!r}")
        REGISTRY[code] = function
        return function

    return decorator


def make_finding(
    code: str,
    record_type: str,
    record_id: str,
    message: str,
    **details: Any,
) -> Finding:
    return Finding(
        code=code,
        severity=SEVERITY_BY_CODE[code],
        record_type=record_type,
        record_id=record_id,
        message=message,
        details=details,
    )


def run_checks(repo: Repository, codes: Iterable[str] | None = None) -> list[Finding]:
    """Run all registered checks (or a subset) over a repository snapshot."""
    dataset = repo.dataset()
    selected = sorted(codes) if codes is not None else list(ALL_CODES)
    findings: list[Finding] = []
    for code in selected:
        function = REGISTRY.get(code)
        if function is None:
            raise KeyError(f"no check registered for {code!r}")
        findings.extend(function(dataset))
    findings.sort(key=lambda finding: (finding.code, finding.record_id, finding.message))
    return findings
