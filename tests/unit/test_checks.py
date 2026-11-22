from __future__ import annotations

import datetime as dt

import pytest

from mxbess.checks import ALL_CODES, REGISTRY, SEVERITY_BY_CODE, Severity, run_checks
from mxbess.checks.assets import NAMING_PATTERNS, find_cycle_nodes
from mxbess.models import Asset
from mxbess.repository import FixtureRepository
from tests.support import AS_OF, asset, tiny_dataset


def _codes(findings):
    return sorted(finding.code for finding in findings)


def _run(dataset, codes=None):
    return run_checks(FixtureRepository(dataset), codes=codes)


def _get(dataset, asset_num: str) -> Asset:
    return next(item for item in dataset.assets if item.asset_num == asset_num)


def test_registry_covers_every_code():
    assert tuple(sorted(REGISTRY)) == tuple(sorted(ALL_CODES))
    assert len(ALL_CODES) == 14


def test_clean_dataset_has_zero_findings():
    assert _run(tiny_dataset()) == []


def test_limits_to_selected_codes():
    dataset = tiny_dataset()
    _get(dataset, "BB1-CT1-RK01-MD01").location = None
    assert _codes(_run(dataset, codes=["A01"])) == ["A01"]
    assert _run(dataset, codes=[]) == []


def test_a01_missing_location():
    dataset = tiny_dataset()
    _get(dataset, "BB1-CT1-RK01-MD01").location = None
    findings = _run(dataset)
    assert _codes(findings) == ["A01"]
    assert findings[0].record_id == "BB1-CT1-RK01-MD01"


def test_a02_missing_required_parent():
    dataset = tiny_dataset()
    _get(dataset, "BB1-CT1-RK01-MD01").parent = None
    findings = _run(dataset)
    assert _codes(findings) == ["A02"]


def test_a02_parent_not_required_for_block_equipment():
    dataset = tiny_dataset()
    _get(dataset, "BB1-PCS").parent = None
    assert _run(dataset) == []


def test_a03_duplicate_description_and_location_flags_both():
    dataset = tiny_dataset()
    first = _get(dataset, "BB1-CT1-RK01-MD01")
    second = _get(dataset, "BB1-CT1-RK01-MD02")
    second.description = first.description
    findings = _run(dataset)
    assert _codes(findings) == ["A03", "A03"]
    assert {finding.record_id for finding in findings} == {first.asset_num, second.asset_num}


def test_a03_duplicate_asset_number_flags_both():
    dataset = tiny_dataset()
    original = _get(dataset, "BB1-CT1-RK01-MD01")
    clone = original.model_copy(deep=True)
    clone.description = "A different description"
    dataset.assets.append(clone)
    findings = _run(dataset)
    assert _codes(findings) == ["A03", "A03"]
    assert all(finding.record_id == "BB1-CT1-RK01-MD01" for finding in findings)


def test_a03_same_description_at_different_locations_is_fine():
    dataset = tiny_dataset()
    first = _get(dataset, "BB1-CT1-RK01-MD01")
    second = _get(dataset, "BB1-CT1-RK02-MD01")
    second.description = first.description
    assert _run(dataset) == []


def test_a04_missing_mandatory_field():
    dataset = tiny_dataset()
    _get(dataset, "BB1-CT1-RK01-MD01").manufacturer = None
    findings = _run(dataset)
    assert _codes(findings) == ["A04"]
    assert findings[0].details["missing"] == ["manufacturer"]


def test_a05_naming_violation():
    dataset = tiny_dataset()
    dataset.assets.append(
        asset("BAD-NAME", "Odd module", "MODULE", "MODULE", "BB1-CT1-RK01", "BB1-CT1")
    )
    findings = _run(dataset)
    assert _codes(findings) == ["A05"]
    assert findings[0].record_id == "BAD-NAME"


def test_a05_patterns_accept_the_clean_hierarchy():
    assert NAMING_PATTERNS["SITE"].fullmatch("SITE-SCADA")
    assert NAMING_PATTERNS["BLOCK"].fullmatch("BB2-HVAC1")
    assert NAMING_PATTERNS["CONTAINER"].fullmatch("BB4-CT2")
    assert NAMING_PATTERNS["MODULE"].fullmatch("BB1-CT1-RK08-MD06")
    assert not NAMING_PATTERNS["MODULE"].fullmatch("BB1-CT1-MD06")


def test_a06_orphan_parent():
    dataset = tiny_dataset()
    _get(dataset, "BB1-CT1-RK01-MD01").parent = "MISSING-PARENT"
    findings = _run(dataset)
    assert _codes(findings) == ["A06"]
    assert findings[0].details["kind"] == "orphan"


def test_a06_cycle_flags_each_member():
    dataset = tiny_dataset()
    first = _get(dataset, "BB1-CT1-RK01-MD01")
    second = _get(dataset, "BB1-CT1-RK01-MD02")
    first.parent, second.parent = second.asset_num, first.asset_num
    findings = _run(dataset)
    assert _codes(findings) == ["A06", "A06"]
    assert {finding.details["kind"] for finding in findings} == {"cycle"}


def test_find_cycle_nodes_does_not_flag_orphans():
    assert find_cycle_nodes({"A": "MISSING", "B": "C", "C": "B"}) == {"B", "C"}
    assert find_cycle_nodes({"A": None}) == set()


def test_p01_missing_jobplan():
    dataset = tiny_dataset()
    dataset.pms[0].jobplan_num = None
    findings = _run(dataset)
    assert _codes(findings) == ["P01"]


def test_p01_unknown_jobplan():
    dataset = tiny_dataset()
    dataset.pms[0].jobplan_num = "JP-999"
    findings = _run(dataset)
    assert _codes(findings) == ["P01"]
    assert "does not exist" in findings[0].message


def test_p02_missing_schedule():
    dataset = tiny_dataset()
    dataset.pms[0].frequency_days = None
    findings = _run(dataset)
    assert _codes(findings) == ["P02"]
    assert findings[0].details["missing"] == ["frequency"]


def test_p03_decommissioned_asset():
    dataset = tiny_dataset()
    _get(dataset, "BB1-CT1-RK01-MD01").status = "DECOMMISSIONED"
    findings = _run(dataset)
    assert _codes(findings) == ["P03"]
    assert findings[0].record_id == "PM-01-001"


def test_p03_ignores_location_scoped_pm():
    dataset = tiny_dataset()
    dataset.pms[0].asset_num = None
    dataset.pms[0].location = "BB1-CT1"
    assert _run(dataset) == []


def test_p04_overdue_without_open_workorder():
    dataset = tiny_dataset()
    dataset.pms[0].next_due = AS_OF - dt.timedelta(days=12)
    findings = _run(dataset)
    assert _codes(findings) == ["P04"]
    assert findings[0].details["days_overdue"] == 12


def test_p04_ignores_overdue_with_open_workorder():
    dataset = tiny_dataset()
    dataset.pms[0].next_due = AS_OF - dt.timedelta(days=12)
    dataset.workorders[0].status = "APPR"
    dataset.workorders[0].actual_finish = None
    dataset.workorders[0].actual_start = None
    assert _run(dataset) == []


def test_w01_missing_asset():
    dataset = tiny_dataset()
    dataset.workorders[0].asset_num = None
    findings = _run(dataset)
    assert _codes(findings) == ["W01"]


def test_w02_closed_without_finish():
    dataset = tiny_dataset()
    dataset.workorders[0].actual_finish = None
    findings = _run(dataset)
    assert _codes(findings) == ["W02"]
    assert "no actual finish date" in findings[0].message


def test_w02_closed_without_labour():
    dataset = tiny_dataset()
    dataset.workorders[0].labor_hours = 0.0
    findings = _run(dataset)
    assert _codes(findings) == ["W02"]
    assert "no actual labour" in findings[0].message


def test_w03_future_finish():
    dataset = tiny_dataset()
    dataset.workorders[0].actual_finish = AS_OF + dt.timedelta(days=3)
    findings = _run(dataset)
    assert _codes(findings) == ["W03"]
    assert "future" in findings[0].message


def test_w03_open_with_actuals():
    dataset = tiny_dataset()
    wo = dataset.workorders[0]
    wo.status = "INPROG"
    wo.actual_finish = AS_OF - dt.timedelta(days=1)
    findings = _run(dataset)
    assert _codes(findings) == ["W03"]


def test_w03_in_progress_without_start():
    dataset = tiny_dataset()
    wo = dataset.workorders[0]
    wo.status = "INPROG"
    wo.actual_start = None
    wo.actual_finish = None
    findings = _run(dataset)
    assert _codes(findings) == ["W03"]


def test_w04_stale_open_workorder():
    dataset = tiny_dataset()
    wo = dataset.workorders[0]
    wo.status = "APPR"
    wo.actual_start = None
    wo.actual_finish = None
    wo.reported_date = AS_OF - dt.timedelta(days=120)
    findings = _run(dataset)
    assert _codes(findings) == ["W04"]
    assert findings[0].details["age_days"] == 120


def test_w04_threshold_is_not_flagged_at_90_days():
    dataset = tiny_dataset()
    wo = dataset.workorders[0]
    wo.status = "APPR"
    wo.actual_start = None
    wo.actual_finish = None
    wo.reported_date = AS_OF - dt.timedelta(days=90)
    assert _run(dataset) == []


@pytest.mark.parametrize("code", ["A03", "A06", "P02", "P03", "W02"])
def test_high_severity_codes(code):
    assert SEVERITY_BY_CODE[code] is Severity.HIGH


def test_finding_as_dict_round_trips_fields():
    dataset = tiny_dataset()
    _get(dataset, "BB1-CT1-RK01-MD01").location = None
    payload = _run(dataset)[0].as_dict()
    assert payload["code"] == "A01"
    assert payload["severity"] == "MEDIUM"
    assert payload["record_type"] == "asset"
