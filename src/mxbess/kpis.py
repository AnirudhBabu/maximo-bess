"""Maintenance KPIs computed from a :class:`~mxbess.models.Dataset`.

Definitions are deliberately explicit because "PM compliance", "backlog" and
"overdue" are easy to compute three different ways and get three answers:

* **PM compliance** - PM work orders due on or before the as-of date, excluding
  cancelled ones.  A due WO is on time when it is COMP/CLOSE and its actual
  finish is on or before its target finish.  ``compliance_pct = on_time / due``.
* **Backlog** - work orders in WAPPR, APPR or INPROG.
* **Ageing** - days from report date to as-of, bucketed 0-30, 31-90, >90.
* **Corrective vs preventive** - all work orders by WORKTYPE, not just closed.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from .checks.assets import MANDATORY_ASSET_FIELDS
from .models import (
    ALL_WO_STATUSES,
    CLOSED_WO_STATUSES,
    OPEN_WO_STATUSES,
    PARENT_REQUIRED_TYPES,
    Dataset,
    WorkOrder,
)

COMPLETENESS_FIELDS: tuple[str, ...] = (
    "description",
    "location",
    "parent",
    *MANDATORY_ASSET_FIELDS,
    "status",
)


@dataclass(frozen=True)
class PMCompliance:
    due: int
    completed: int
    on_time: int
    open_overdue: int

    @property
    def compliance_pct(self) -> float | None:
        return None if self.due == 0 else round(100.0 * self.on_time / self.due, 1)


@dataclass(frozen=True)
class Ratio:
    corrective: int
    preventive: int

    @property
    def corrective_per_preventive(self) -> float | None:
        return None if self.preventive == 0 else round(self.corrective / self.preventive, 2)


@dataclass(frozen=True)
class FieldCompleteness:
    asset_type: str
    field: str
    populated: int
    total: int

    @property
    def percent(self) -> float | None:
        return None if self.total == 0 else round(100.0 * self.populated / self.total, 1)


def pm_compliance(dataset: Dataset) -> PMCompliance:
    due_wos = [
        wo
        for wo in dataset.workorders
        if wo.work_type == "PM"
        and wo.target_finish is not None
        and wo.target_finish <= dataset.as_of
        and wo.status != "CAN"
    ]
    completed = [wo for wo in due_wos if wo.status in CLOSED_WO_STATUSES]
    on_time = [
        wo
        for wo in completed
        if wo.actual_finish is not None
        and wo.target_finish is not None
        and wo.actual_finish <= wo.target_finish
    ]
    open_overdue = [wo for wo in due_wos if wo.status in OPEN_WO_STATUSES]
    return PMCompliance(
        due=len(due_wos),
        completed=len(completed),
        on_time=len(on_time),
        open_overdue=len(open_overdue),
    )


def open_backlog(dataset: Dataset) -> list[WorkOrder]:
    return [wo for wo in dataset.workorders if wo.status in OPEN_WO_STATUSES]


def backlog_ageing(dataset: Dataset) -> dict[str, int]:
    buckets = {"0-30": 0, "31-90": 0, "90+": 0}
    for wo in open_backlog(dataset):
        age = max((dataset.as_of - wo.reported_date).days, 0)
        if age <= 30:
            buckets["0-30"] += 1
        elif age <= 90:
            buckets["31-90"] += 1
        else:
            buckets["90+"] += 1
    return buckets


def corrective_vs_preventive(dataset: Dataset) -> Ratio:
    counts = Counter(wo.work_type for wo in dataset.workorders)
    return Ratio(corrective=counts.get("CM", 0), preventive=counts.get("PM", 0))


def wo_count_by_status(dataset: Dataset) -> dict[str, int]:
    counts = Counter(wo.status for wo in dataset.workorders)
    return {status: counts.get(status, 0) for status in ALL_WO_STATUSES}


def asset_completeness(dataset: Dataset) -> list[FieldCompleteness]:
    """Completeness per mandatory field, overall and for each asset type.

    ``parent`` is only required for CONTAINER and MODULE assets, so its
    denominator excludes SITE and BLOCK equipment.
    """
    rows: list[FieldCompleteness] = []
    groups: dict[str, list] = {"ALL": list(dataset.assets)}
    for asset_type in ("SITE", "BLOCK", "CONTAINER", "MODULE"):
        groups[asset_type] = [asset for asset in dataset.assets if asset.asset_type == asset_type]

    for group_name, assets in groups.items():
        for field in COMPLETENESS_FIELDS:
            if field == "parent":
                scoped = [a for a in assets if a.asset_type in PARENT_REQUIRED_TYPES]
            else:
                scoped = assets
            populated = sum(1 for asset in scoped if getattr(asset, field) not in (None, ""))
            rows.append(
                FieldCompleteness(
                    asset_type=group_name,
                    field=field,
                    populated=populated,
                    total=len(scoped),
                )
            )
    return rows


def findings_by_severity(findings) -> dict[str, int]:
    counts = Counter(finding.severity.value for finding in findings)
    return {severity: counts.get(severity, 0) for severity in ("HIGH", "MEDIUM", "LOW")}


def findings_by_code(findings) -> dict[str, int]:
    counts = Counter(finding.code for finding in findings)
    return dict(sorted(counts.items()))
