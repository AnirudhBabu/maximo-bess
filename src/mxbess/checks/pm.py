"""Preventive-maintenance checks P01-P04."""

from __future__ import annotations

from ..models import OPEN_WO_STATUSES, Dataset
from ._core import Finding, check, make_finding


@check("P01")
def check_p01_pm_without_jobplan(dataset: Dataset) -> list[Finding]:
    findings: list[Finding] = []
    for pm in dataset.pms:
        if not pm.jobplan_num:
            findings.append(make_finding("P01", "pm", pm.pm_num, "PM has no job plan"))
        elif dataset.jobplan_by_num(pm.jobplan_num) is None:
            findings.append(
                make_finding(
                    "P01",
                    "pm",
                    pm.pm_num,
                    f"job plan {pm.jobplan_num} does not exist",
                    jobplan_num=pm.jobplan_num,
                )
            )
    return findings


@check("P02")
def check_p02_pm_without_schedule(dataset: Dataset) -> list[Finding]:
    findings: list[Finding] = []
    for pm in dataset.pms:
        missing: list[str] = []
        if not pm.frequency_days:
            missing.append("frequency")
        if not pm.next_due:
            missing.append("next_due")
        if missing:
            findings.append(
                make_finding(
                    "P02",
                    "pm",
                    pm.pm_num,
                    "PM has no " + " or ".join(missing),
                    missing=missing,
                )
            )
    return findings


@check("P03")
def check_p03_pm_on_inactive_asset(dataset: Dataset) -> list[Finding]:
    findings: list[Finding] = []
    for pm in dataset.pms:
        asset = dataset.asset_by_num(pm.asset_num)
        if asset is not None and asset.status != "OPERATING":
            findings.append(
                make_finding(
                    "P03",
                    "pm",
                    pm.pm_num,
                    f"PM targets {asset.asset_num} which is {asset.status}",
                    asset_num=asset.asset_num,
                    asset_status=asset.status,
                )
            )
    return findings


@check("P04")
def check_p04_overdue_pm_without_workorder(dataset: Dataset) -> list[Finding]:
    pm_with_open_wo = {
        wo.pm_num for wo in dataset.workorders if wo.pm_num and wo.status in OPEN_WO_STATUSES
    }
    findings: list[Finding] = []
    for pm in dataset.pms:
        if (
            pm.status != "ACTIVE"
            or pm.frequency_days is None
            or pm.next_due is None
            or pm.next_due >= dataset.as_of
            or pm.pm_num in pm_with_open_wo
        ):
            continue
        days = (dataset.as_of - pm.next_due).days
        findings.append(
            make_finding(
                "P04",
                "pm",
                pm.pm_num,
                f"PM is overdue by {days} days with no open work order",
                days_overdue=days,
                next_due=pm.next_due.isoformat(),
            )
        )
    return findings
