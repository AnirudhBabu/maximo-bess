from __future__ import annotations

import datetime as dt

import pytest

from mxbess import mapping
from mxbess.models import PM, Asset, Location, WorkOrder
from tests.support import tiny_dataset


def test_object_structures_cover_every_repository_kind():
    assert set(mapping.OBJECT_STRUCTURES) == {"location", "asset", "jobplan", "pm", "workorder"}
    assert set(mapping.NATURAL_KEY_FIELDS) == set(mapping.OBJECT_STRUCTURES)


def test_asset_payload_uses_maximo_columns():
    asset = tiny_dataset().assets[1]  # BB1-PCS
    payload = mapping.to_payload("asset", asset)
    assert payload["ASSETNUM"] == "BB1-PCS"
    assert payload["ASSETTYPE"] == "PCS"
    assert payload["INSTALLDATE"] == "2024-01-01"
    assert payload["SITEID"] == "BISHA-BESS"
    assert "ASSET_TYPE" not in payload
    assert "asset_type" not in payload


def test_payload_omits_none_by_default_and_can_include_it():
    location = Location(
        location="L1",
        description="Location 1",
        site_id="S",
        org_id="O",
        parent=None,
    )
    assert "PARENT" not in mapping.to_payload("location", location)
    assert mapping.to_payload("location", location, include_none=True)["PARENT"] is None


def test_pm_payload_sets_frequency_unit():
    pm = tiny_dataset().pms[0]
    payload = mapping.to_payload("pm", pm)
    assert payload["FREQUENCY"] == 30
    assert payload["FREQUNIT"] == "DAYS"
    assert payload["NEXTDATE"] == "2026-11-11"


def test_from_payload_parses_dates_and_infers_asset_type():
    payload = {
        "ASSETNUM": "BB1-PCS",
        "DESCRIPTION": "PCS",
        "ASSETTYPE": "PCS",
        "SITEID": "S",
        "ORGID": "O",
        "LOCATION": "BB1",
        "INSTALLDATE": "2024-01-01T00:00:00+00:00",
        "CRITICALITY": "1",
        "STATUS": "OPERATING",
    }
    asset = mapping.from_payload("asset", payload)
    assert isinstance(asset, Asset)
    assert asset.asset_type == "BLOCK"
    assert asset.install_date == dt.date(2024, 1, 1)
    assert asset.criticality == 1


@pytest.mark.parametrize(
    ("asset_num", "asset_type", "equipment_type"),
    [
        ("SITE-SCADA", "SITE", "SCADA"),
        ("SITE-AUXPWR", "SITE", "AUX"),
        ("BB1-HVAC2", "BLOCK", "HVAC"),
        ("BB1-CT2", "CONTAINER", "CONTAINER"),
        ("BB1-CT1-RK03-MD04", "MODULE", "MODULE"),
        ("UNKNOWN-ASSET", "MODULE", "GENERIC"),
    ],
)
def test_asset_identity_falls_back_to_numbering(asset_num, asset_type, equipment_type):
    payload = {
        "ASSETNUM": asset_num,
        "DESCRIPTION": "x",
        "SITEID": "S",
        "ORGID": "O",
    }
    asset = mapping.from_payload("asset", payload)
    assert asset.asset_type == asset_type
    assert asset.equipment_type == equipment_type


def test_parse_date_accepts_datetime():
    payload = {
        "ASSETNUM": "BB1-PCS",
        "DESCRIPTION": "x",
        "SITEID": "S",
        "ORGID": "O",
        "ASSETTYPE": "PCS",
        "INSTALLDATE": dt.datetime(2024, 1, 1, 12, 0),
    }
    assert mapping.from_payload("asset", payload).install_date == dt.date(2024, 1, 1)


@pytest.mark.parametrize(
    ("equipment_type", "expected"),
    [
        ("SCADA", "SITE"),
        ("AUXPWR", "SITE"),
        ("HVAC", "BLOCK"),
        ("CONTAINER", "CONTAINER"),
        ("MODULE", "MODULE"),
        ("CUSTOM", "MODULE"),
    ],
)
def test_infer_asset_type(equipment_type, expected):
    payload = {
        "ASSETNUM": "X",
        "DESCRIPTION": "X",
        "ASSETTYPE": equipment_type,
        "SITEID": "S",
        "ORGID": "O",
    }
    assert mapping.from_payload("asset", payload).asset_type == expected


def test_from_payload_pm_and_workorder():
    pm_payload = {
        "PMNUM": "PM-1",
        "DESCRIPTION": "PM",
        "SITEID": "S",
        "ORGID": "O",
        "ASSETNUM": "A",
        "JPNUM": "JP-1",
        "FREQUENCY": "30",
        "NEXTDATE": "2026-12-01",
        "STATUS": "ACTIVE",
    }
    pm = mapping.from_payload("pm", pm_payload)
    assert isinstance(pm, PM)
    assert pm.frequency_days == 30
    assert pm.next_due == dt.date(2026, 12, 1)

    wo_payload = {
        "WONUM": "WO-1",
        "DESCRIPTION": "WO",
        "SITEID": "S",
        "ORGID": "O",
        "STATUS": "INPROG",
        "WORKTYPE": "CM",
        "REPORTDATE": "2026-01-01",
        "ACTLABHRS": "3.5",
        "WOPRIORITY": "2",
    }
    wo = mapping.from_payload("workorder", wo_payload)
    assert isinstance(wo, WorkOrder)
    assert wo.labor_hours == 3.5
    assert wo.priority == 2


def test_pm_safety_flag_is_recovered_from_jobplan():
    base = {
        "PMNUM": "PM-1",
        "DESCRIPTION": "PM",
        "SITEID": "S",
        "ORGID": "O",
        "JPNUM": "JP-04",
        "FREQUENCY": "180",
        "NEXTDATE": "2026-12-01",
        "STATUS": "ACTIVE",
    }
    assert mapping.from_payload("pm", base).safety_critical is True
    base["JPNUM"] = "JP-02"
    assert mapping.from_payload("pm", base).safety_critical is False


def test_where_clause_escapes_quotes():
    assert mapping.where_clause_for_key("asset", 'A"B') == 'ASSETNUM="A""B"'


def test_serialisation_round_trip_through_payloads():
    dataset = tiny_dataset()
    for asset in dataset.assets:
        payload = mapping.to_payload("asset", asset)
        restored = mapping.from_payload("asset", payload)
        assert restored.asset_num == asset.asset_num
        assert restored.equipment_type == asset.equipment_type
        assert restored.location == asset.location
        assert restored.parent == asset.parent


def test_unverified_notes_exist():
    assert "auth header" in mapping.UNVERIFIED
    assert "PATCH" in mapping.UNVERIFIED
