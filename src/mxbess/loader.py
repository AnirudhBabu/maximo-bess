"""Idempotent loader.

Dependency order is locations -> assets -> job plans -> PMs -> work orders.
Every record is looked up by natural key before create, so a second run
produces zero creates; a run that partially failed can simply be re-run.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Any

from .models import Dataset, DomainModel
from .repository import UpsertOutcome, WritableRepository

logger = logging.getLogger("mxbess.loader")

LOCATION_DEPTH = {"SITE": 0, "BLOCK": 1, "CONTAINER": 2, "RACK": 3}
ASSET_DEPTH = {"SITE": 0, "BLOCK": 1, "CONTAINER": 2, "MODULE": 3}
KIND_ORDER = ("location", "asset", "jobplan", "pm", "workorder")


@dataclass
class KindCounts:
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    failed: int = 0

    def record(self, outcome: UpsertOutcome) -> None:
        setattr(self, outcome.value, getattr(self, outcome.value) + 1)


@dataclass
class LoadFailure:
    kind: str
    key: str
    error: str


@dataclass
class LoadReport:
    counts: dict[str, KindCounts] = field(
        default_factory=lambda: {kind: KindCounts() for kind in KIND_ORDER}
    )
    failures: list[LoadFailure] = field(default_factory=list)

    @property
    def created(self) -> int:
        return sum(counts.created for counts in self.counts.values())

    @property
    def updated(self) -> int:
        return sum(counts.updated for counts in self.counts.values())

    @property
    def unchanged(self) -> int:
        return sum(counts.unchanged for counts in self.counts.values())

    @property
    def ok(self) -> bool:
        return not self.failures

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "totals": {
                "created": self.created,
                "updated": self.updated,
                "unchanged": self.unchanged,
                "failed": len(self.failures),
            },
            "counts": {kind: asdict(counts) for kind, counts in self.counts.items()},
            "failures": [asdict(failure) for failure in self.failures],
        }


def _ordered(dataset: Dataset):
    locations = sorted(dataset.locations, key=lambda item: LOCATION_DEPTH[item.level])
    assets = sorted(dataset.assets, key=lambda item: ASSET_DEPTH[item.asset_type])
    yield from (("location", location) for location in locations)
    yield from (("asset", asset) for asset in assets)
    yield from (("jobplan", jobplan) for jobplan in dataset.jobplans)
    yield from (("pm", pm) for pm in dataset.pms)
    yield from (("workorder", workorder) for workorder in dataset.workorders)


_UPSERT_METHODS = {
    "location": "upsert_location",
    "asset": "upsert_asset",
    "jobplan": "upsert_jobplan",
    "pm": "upsert_pm",
    "workorder": "upsert_workorder",
}


def load_dataset(dataset: Dataset, repository: WritableRepository) -> LoadReport:
    """Upsert every record in dependency order, continuing past failures."""
    report = LoadReport()
    for kind, record in _ordered(dataset):
        method = getattr(repository, _UPSERT_METHODS[kind])
        try:
            outcome = method(record)
        except Exception as exc:
            report.counts[kind].failed += 1
            report.failures.append(
                LoadFailure(kind=kind, key=_key_of(record), error=f"{type(exc).__name__}: {exc}")
            )
            logger.warning("load failed for %s %s: %s", kind, _key_of(record), exc)
            continue
        report.counts[kind].record(outcome)
    logger.info(
        "load complete: %d created, %d updated, %d unchanged, %d failed",
        report.created,
        report.updated,
        report.unchanged,
        len(report.failures),
    )
    return report


def _key_of(record: DomainModel) -> str:
    return str(record.natural_key)  # type: ignore[attr-defined]
