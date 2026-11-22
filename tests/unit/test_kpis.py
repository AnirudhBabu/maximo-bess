from __future__ import annotations

import datetime as dt

import pytest

from mxbess import kpis
from mxbess.checks import make_finding
from tests.support import AS_OF, tiny_dataset, workorder


@pytest.fixture
def kpi_dataset():
    dataset = tiny_dataset()
    pm_wos = []
    target = AS_OF - dt.timedelta(days=10)
    for index in range(10):
        in_progress = index == 9
        late = index in (7, 8)
        pm_wos.append(
            workorder(
                f"PMWO-{index:04d}",
                status="INPROG" if in_progress else "CLOSE",
                reported_date=target - dt.timedelta(days=5),
                target_finish=target,
                actual_start=None if in_progress else target - dt.timedelta(days=1),
                actual_finish=(
                    None if in_progress else target + dt.timedelta(days=2 if late else 0)
                ),
                labor_hours=None if in_progress else 2.0,
            )
        )
    for index, age in enumerate((10, 40, 120, 200)):
        pm_wos.append(
            workorder(
                f"CM-{index:04d}",
                status="APPR",
                work_type="CM",
                reported_date=AS_OF - dt.timedelta(days=age),
                target_finish=AS_OF + dt.timedelta(days=5),
                actual_start=None,
                actual_finish=None,
                labor_hours=None,
            )
        )
    dataset.workorders = pm_wos
    return dataset


def test_pm_compliance_is_seven_of_ten(kpi_dataset):
    compliance = kpis.pm_compliance(kpi_dataset)
    assert compliance.due == 10
    assert compliance.completed == 9
    assert compliance.on_time == 7
    assert compliance.open_overdue == 1
    assert compliance.compliance_pct == 70.0


def test_pm_compliance_is_none_without_due_workorders():
    dataset = tiny_dataset()
    dataset.workorders = []
    assert kpis.pm_compliance(dataset).compliance_pct is None


def test_backlog_and_ageing(kpi_dataset):
    assert len(kpis.open_backlog(kpi_dataset)) == 5
    assert kpis.backlog_ageing(kpi_dataset) == {"0-30": 2, "31-90": 1, "90+": 2}


def test_corrective_vs_preventive(kpi_dataset):
    ratio = kpis.corrective_vs_preventive(kpi_dataset)
    assert ratio.corrective == 4
    assert ratio.preventive == 10
    assert ratio.corrective_per_preventive == 0.4


def test_corrective_vs_preventive_without_preventive_work():
    dataset = tiny_dataset()
    dataset.workorders = [workorder("CM-1", work_type="CM")]
    ratio = kpis.corrective_vs_preventive(dataset)
    assert ratio.preventive == 0
    assert ratio.corrective_per_preventive is None


def test_wo_count_by_status_zero_fills(kpi_dataset):
    counts = kpis.wo_count_by_status(kpi_dataset)
    assert counts == {
        "WAPPR": 0,
        "APPR": 4,
        "INPROG": 1,
        "COMP": 0,
        "CLOSE": 9,
        "CAN": 0,
    }


def test_asset_completeness_all_complete():
    rows = kpis.asset_completeness(tiny_dataset())
    for row in rows:
        if row.total:
            assert row.percent == 100.0, (row.asset_type, row.field)


def test_asset_completeness_detects_missing_field():
    dataset = tiny_dataset()
    dataset.assets[4].manufacturer = None
    rows = {(row.asset_type, row.field): row for row in kpis.asset_completeness(dataset)}
    assert rows[("ALL", "manufacturer")].percent == 87.5
    assert rows[("MODULE", "manufacturer")].percent == 75.0
    assert rows[("ALL", "manufacturer")].populated == 7


def test_asset_completeness_parent_denominator_only_parented_types():
    rows = {(row.asset_type, row.field): row for row in kpis.asset_completeness(tiny_dataset())}
    assert rows[("ALL", "parent")].total == 5  # 1 container + 4 modules
    assert rows[("SITE", "parent")].total == 0
    assert rows[("SITE", "parent")].percent is None


def test_findings_summaries():
    findings = [
        make_finding("A01", "asset", "A", "x"),
        make_finding("A01", "asset", "B", "x"),
        make_finding("W02", "workorder", "W", "x"),
    ]
    assert kpis.findings_by_severity(findings) == {"HIGH": 1, "MEDIUM": 2, "LOW": 0}
    assert kpis.findings_by_code(findings) == {"A01": 2, "W02": 1}
