"""Work-order checks W01-W04."""

from __future__ import annotations

from ..models import CLOSED_WO_STATUSES, OPEN_WO_STATUSES, Dataset
from ._core import Finding, check, make_finding

STALE_THRESHOLD_DAYS = 90


@check("W01")
def check_w01_workorder_without_asset(dataset: Dataset) -> list[Finding]:
    return [
        make_finding("W01", "workorder", wo.wonum, "work order has no asset")
        for wo in dataset.workorders
        if not wo.asset_num
    ]


@check("W02")
def check_w02_closed_workorder_missing_actuals(dataset: Dataset) -> list[Finding]:
    findings: list[Finding] = []
    for wo in dataset.workorders:
        if wo.status not in CLOSED_WO_STATUSES:
            continue
        issues: list[str] = []
        if wo.actual_finish is None:
            issues.append("no actual finish date")
        if wo.labor_hours is None or wo.labor_hours <= 0:
            issues.append("no actual labour")
        if issues:
            findings.append(
                make_finding(
                    "W02",
                    "workorder",
                    wo.wonum,
                    "closed WO has " + " and ".join(issues),
                    issues=issues,
                )
            )
    return findings


@check("W03")
def check_w03_workorder_status_vs_dates(dataset: Dataset) -> list[Finding]:
    findings: list[Finding] = []
    for wo in dataset.workorders:
        issues: list[str] = []
        if wo.status in CLOSED_WO_STATUSES and wo.actual_finish is not None:
            if wo.actual_finish > dataset.as_of:
                issues.append("finish date is in the future")
            if wo.actual_start is not None and wo.actual_finish < wo.actual_start:
                issues.append("finish date is before start date")
            if wo.actual_finish < wo.reported_date:
                issues.append("finish date is before the reported date")
        elif wo.status == "INPROG":
            if wo.actual_finish is not None:
                issues.append("in-progress WO has an actual finish")
            if wo.actual_start is None:
                issues.append("in-progress WO has no actual start")
        elif wo.status in {"WAPPR", "APPR"}:
            if wo.actual_finish is not None:
                issues.append("open WO has an actual finish")
            if wo.actual_start is not None:
                issues.append("open WO has an actual start")
        if issues:
            findings.append(
                make_finding(
                    "W03",
                    "workorder",
                    wo.wonum,
                    "status " + wo.status + " is inconsistent with dates: " + "; ".join(issues),
                    issues=issues,
                )
            )
    return findings


@check("W04")
def check_w04_stale_open_workorder(dataset: Dataset) -> list[Finding]:
    findings: list[Finding] = []
    for wo in dataset.workorders:
        if wo.status not in OPEN_WO_STATUSES:
            continue
        age = (dataset.as_of - wo.reported_date).days
        if age > STALE_THRESHOLD_DAYS:
            findings.append(
                make_finding(
                    "W04",
                    "workorder",
                    wo.wonum,
                    f"open WO is {age} days old (threshold {STALE_THRESHOLD_DAYS})",
                    age_days=age,
                    threshold_days=STALE_THRESHOLD_DAYS,
                )
            )
    return findings
