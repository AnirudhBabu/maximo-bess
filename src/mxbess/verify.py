"""Compare check findings against a defect manifest (recall / false positives)."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from .checks import Finding


@dataclass(frozen=True)
class ManifestVerification:
    expected: int
    actual: int
    matched: int
    missing: list[dict[str, Any]] = field(default_factory=list)
    unexpected: list[dict[str, Any]] = field(default_factory=list)

    @property
    def recall(self) -> float:
        return 1.0 if self.expected == 0 else self.matched / self.expected

    @property
    def precision(self) -> float:
        return 1.0 if self.actual == 0 else self.matched / self.actual

    @property
    def false_positive_count(self) -> int:
        return sum(item["count"] for item in self.unexpected)

    @property
    def exact(self) -> bool:
        return not self.missing and not self.unexpected

    def summary(self) -> str:
        return (
            f"expected {self.expected}, found {self.actual}, matched {self.matched}, "
            f"recall {self.recall:.1%}, precision {self.precision:.1%}, "
            f"false positives {self.false_positive_count}"
        )


def _counter_from_manifest(manifest: dict[str, Any]) -> Counter[tuple[str, str]]:
    return Counter(
        (str(defect["code"]), str(defect["record_id"])) for defect in manifest["defects"]
    )


def verify_manifest(findings: list[Finding], manifest: dict[str, Any]) -> ManifestVerification:
    expected = _counter_from_manifest(manifest)
    actual = Counter((finding.code, finding.record_id) for finding in findings)
    matched = sum((expected & actual).values())

    missing = [
        {"code": code, "record_id": record_id, "count": count}
        for (code, record_id), count in sorted((expected - actual).items())
    ]
    unexpected = [
        {"code": code, "record_id": record_id, "count": count}
        for (code, record_id), count in sorted((actual - expected).items())
    ]
    return ManifestVerification(
        expected=sum(expected.values()),
        actual=sum(actual.values()),
        matched=matched,
        missing=missing,
        unexpected=unexpected,
    )
