from __future__ import annotations

import datetime as dt
import json

import pytest

from mxbess.checks import run_checks
from mxbess.checks.assets import NAMING_PATTERNS
from mxbess.models import SAFETY_CRITICAL_JOBPLANS
from mxbess.repository import FixtureRepository
from mxbess.seed.defects import build_manifest, inject_defects
from mxbess.seed.generate import (
    DEFAULT_SEED,
    PM_PLANS,
    REFERENCE_AS_OF,
    SiteSpec,
    generate_site,
)


@pytest.fixture(scope="module")
def clean():
    return generate_site(seed=DEFAULT_SEED, as_of=REFERENCE_AS_OF)


def test_generator_is_deterministic():
    first = generate_site(seed=7, as_of=REFERENCE_AS_OF)
    second = generate_site(seed=7, as_of=REFERENCE_AS_OF)
    assert first.model_dump_json() == second.model_dump_json()


def test_different_seeds_differ():
    first = generate_site(seed=1, as_of=REFERENCE_AS_OF)
    second = generate_site(seed=2, as_of=REFERENCE_AS_OF)
    assert first.model_dump_json() != second.model_dump_json()


def test_record_counts_per_level(clean):
    assert len(clean.locations) == 77  # 1 site + 4 blocks + 8 containers + 64 racks
    type_counts = {}
    for asset in clean.assets:
        type_counts[asset.asset_type] = type_counts.get(asset.asset_type, 0) + 1
    assert type_counts == {"SITE": 3, "BLOCK": 28, "CONTAINER": 8, "MODULE": 320}
    assert 300 <= len(clean.assets) <= 400
    assert len(clean.jobplans) == len(PM_PLANS) == 14
    assert len(clean.pms) == 68
    assert 150 <= len(clean.workorders) <= 250


def test_site_spec_is_tunable():
    spec = SiteSpec(blocks=1, containers_per_block=1, racks_per_container=2, modules_per_rack=3)
    dataset = generate_site(seed=3, as_of=REFERENCE_AS_OF, spec=spec)
    assert len(dataset.assets) == 17  # 7 block + 3 site + 1 container + 6 modules
    assert len(dataset.locations) == 5


def test_clean_assets_follow_naming_convention(clean):
    for asset in clean.assets:
        assert NAMING_PATTERNS[asset.asset_type].fullmatch(asset.asset_num), asset.asset_num


def test_clean_assets_have_required_fields(clean):
    for asset in clean.assets:
        assert asset.description
        assert asset.location
        assert asset.manufacturer
        assert asset.serial_num
        assert asset.install_date is not None
        assert asset.criticality is not None
        assert asset.status == "OPERATING"
        if asset.asset_type in {"CONTAINER", "MODULE"}:
            assert asset.parent


def test_clean_hierarchy_references_are_valid(clean):
    asset_numbers = {asset.asset_num for asset in clean.assets}
    location_ids = {location.location for location in clean.locations}
    for asset in clean.assets:
        if asset.parent:
            assert asset.parent in asset_numbers
        assert asset.location in location_ids
    for location in clean.locations:
        if location.parent:
            assert location.parent in location_ids


def test_clean_data_produces_no_findings(clean):
    findings = run_checks(FixtureRepository(clean))
    assert findings == []


def test_work_orders_are_in_the_prior_year_and_cover_all_statuses(clean):
    assert {wo.status for wo in clean.workorders} == {
        "WAPPR",
        "APPR",
        "INPROG",
        "COMP",
        "CLOSE",
        "CAN",
    }
    assert {wo.work_type for wo in clean.workorders} == {"PM", "CM"}
    for wo in clean.workorders:
        assert wo.reported_date <= clean.as_of
        assert wo.reported_date >= clean.as_of - dt.timedelta(days=380)
        assert wo.asset_num
        assert wo.description


def test_safety_critical_pms_exist(clean):
    safety = [pm for pm in clean.pms if pm.safety_critical]
    assert safety
    assert {pm.jobplan_num for pm in safety} <= {
        "JP-03",
        "JP-04",
        "JP-05",
        "JP-08",
        "JP-09",
        "JP-14",
    }


def test_safety_flags_match_the_jobplan_convention():
    assert {f"JP-{plan.code}" for plan in PM_PLANS if plan.safety_critical} == set(
        SAFETY_CRITICAL_JOBPLANS
    )


def test_defect_injection_is_deterministic(clean):
    first_dirty, first_defects = inject_defects(clean)
    second_dirty, second_defects = inject_defects(clean)
    assert first_dirty.model_dump_json() == second_dirty.model_dump_json()
    assert build_manifest(first_dirty, first_defects) == build_manifest(
        second_dirty, second_defects
    )


def test_manifest_counts_cover_every_code(clean):
    dirty, defects = inject_defects(clean)
    manifest = build_manifest(dirty, defects)
    assert set(manifest["counts"]) == {
        "A01",
        "A02",
        "A03",
        "A04",
        "A05",
        "A06",
        "P01",
        "P02",
        "P03",
        "P04",
        "W01",
        "W02",
        "W03",
        "W04",
    }
    assert manifest["total_findings"] == len(defects) == 44
    assert all(count >= 3 for count in manifest["counts"].values())
    json.dumps(manifest)  # serialisable
