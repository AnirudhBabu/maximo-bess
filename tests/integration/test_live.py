"""Live integration tests (Phase 6).

Skipped unless ``MXBESS_LIVE=1`` and ``.env`` contains a confirmed trial
instance.  These tests create records in the trial; they are intentionally
marked so the normal CI run never touches a real instance.
"""

from __future__ import annotations

import datetime as dt
import os
import uuid
from pathlib import Path

import pytest

from mxbess import mapping
from mxbess.checks import run_checks
from mxbess.client import MaximoClient
from mxbess.config import load_settings
from mxbess.loader import load_dataset
from mxbess.repository import ApiRepository
from mxbess.seed.defects import build_manifest, inject_defects
from mxbess.seed.generate import generate_site
from mxbess.verify import verify_manifest

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.getenv("MXBESS_LIVE") != "1",
        reason="set MXBESS_LIVE=1 after Phase 0 confirms API access",
    ),
]


@pytest.fixture(scope="module")
def settings():
    config = load_settings(dotenv_path=Path(".env"))
    config.require_live()
    return config


@pytest.fixture(scope="module")
def client(settings):
    with MaximoClient(
        settings.api_root,
        settings.api_key.get_secret_value(),
        timeout=settings.timeout_seconds,
        max_retries=settings.max_retries,
        page_size=settings.page_size,
    ) as api:
        yield api


def test_smoke_read_assets(client):
    records = client.get_all("asset", page_size=1)
    assert isinstance(records, list)


def test_create_read_update_and_deactivate_round_trip(client, settings):
    suffix = uuid.uuid4().hex[:10].upper()
    location_id = f"ZZ-MXBESS-{suffix}"
    asset_num = f"ZZ-MXBESS-{suffix}-A"

    from mxbess.models import Asset, Location

    location = Location(
        location=location_id,
        description="mxbess integration test location",
        site_id=settings.site_id,
        org_id=settings.org_id,
        parent=None,
        level="BLOCK",
    )
    repo = ApiRepository(client, site_id=settings.site_id, org_id=settings.org_id)
    assert repo.upsert_location(location).value == "created"

    asset = Asset(
        asset_num=asset_num,
        description="mxbess integration test asset",
        asset_type="BLOCK",
        equipment_type="PCS",
        site_id=settings.site_id,
        org_id=settings.org_id,
        location=location_id,
        manufacturer="mxbess",
        serial_num=f"SN-{suffix}",
        install_date=dt.date.today(),
        criticality=5,
    )
    assert repo.upsert_asset(asset).value == "created"

    payload = client.find_one_by_key("asset", mapping.where_clause_for_key("asset", asset_num))
    assert payload is not None
    assert payload["LOCATION"] == location_id

    client.update("asset", asset_num, {"DESCRIPTION": "mxbess integration test asset (updated)"})
    updated = client.get_one("asset", asset_num)
    assert updated["DESCRIPTION"].endswith("(updated)")

    client.update("asset", asset_num, {"STATUS": "DECOMMISSIONED"})
    assert client.get_one("asset", asset_num)["STATUS"] == "DECOMMISSIONED"


def test_full_load_and_rerun_creates_no_duplicates(client, settings):
    dataset = generate_site(as_of=dt.date.today())
    repo = ApiRepository(client, site_id=settings.site_id, org_id=settings.org_id)
    first = load_dataset(dataset, repo)
    assert first.created > 0

    second = load_dataset(dataset, repo)
    assert second.created == 0
    assert second.updated == 0
    assert second.failures == []

    live = repo.dataset()
    assert len(live.assets) >= len(dataset.assets)
    assert len(live.pms) >= len(dataset.pms)
    assert len(live.workorders) >= len(dataset.workorders)


def test_live_checks_find_all_injected_defects(client, settings):
    dataset = generate_site(as_of=dt.date.today())
    dirty, defects = inject_defects(dataset)
    manifest = build_manifest(dirty, defects)
    repo = ApiRepository(client, site_id=settings.site_id, org_id=settings.org_id)
    load_dataset(dirty, repo)

    findings = run_checks(repo)
    verification = verify_manifest(findings, manifest)
    assert verification.exact, verification.summary()
