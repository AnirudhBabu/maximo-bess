from __future__ import annotations

from mxbess.models import Asset, Location
from mxbess.repository import (
    CsvRepository,
    FixtureRepository,
    UpsertOutcome,
    save_dataset_csv,
    save_maximo_import_csv,
)
from mxbess.seed.generate import REFERENCE_AS_OF, generate_site
from tests.support import tiny_dataset


def test_fixture_repository_upsert_outcomes():
    dataset = tiny_dataset()
    repo = FixtureRepository(dataset)
    location = Location(
        location="NEW-LOC",
        description="New location",
        site_id="BISHA-BESS",
        org_id="BISHA",
        parent="BISHA-BESS",
        level="BLOCK",
    )
    assert repo.upsert_location(location) is UpsertOutcome.CREATED
    assert repo.upsert_location(location) is UpsertOutcome.UNCHANGED
    location.description = "Changed"
    assert repo.upsert_location(location) is UpsertOutcome.UPDATED
    assert repo.dataset().location_by_id("NEW-LOC").description == "Changed"


def test_fixture_repository_is_a_deep_copy():
    dataset = tiny_dataset()
    repo = FixtureRepository(dataset)
    repo.dataset().assets[0].description = "Changed"
    assert dataset.assets[0].description != "Changed"


def test_csv_round_trip(tmp_path):
    dataset = tiny_dataset()
    repo = CsvRepository(tmp_path)
    repo.save(dataset)

    reloaded = CsvRepository(tmp_path).dataset()
    assert reloaded.model_dump_json() == dataset.model_dump_json()
    assert reloaded.as_of == dataset.as_of
    assert (tmp_path / "assets.csv").is_file()
    assert (tmp_path / "dataset_meta.json").is_file()


def test_csv_upserts_persist(tmp_path):
    repo = CsvRepository(tmp_path)
    repo.save(tiny_dataset())

    new_asset = Asset(
        asset_num="BB1-CT1-RK02-MD02",
        description="Module MD02 rack 2",
        asset_type="MODULE",
        equipment_type="MODULE",
        site_id="BISHA-BESS",
        org_id="BISHA",
        location="BB1-CT1-RK02",
        parent="BB1-CT1",
        manufacturer="Acme",
        serial_num="SN-NEW",
        install_date="2024-01-01",
        criticality=2,
    )
    assert repo.upsert_asset(new_asset) is UpsertOutcome.CREATED
    assert repo.upsert_asset(new_asset) is UpsertOutcome.UNCHANGED
    new_asset.description = "Changed description"
    assert repo.upsert_asset(new_asset) is UpsertOutcome.UPDATED

    fresh = CsvRepository(tmp_path).dataset()
    assert len(fresh.assets) == 9
    assert fresh.asset_by_num("BB1-CT1-RK02-MD02").description == "Changed description"


def test_csv_missing_files_yield_empty_dataset(tmp_path):
    dataset = CsvRepository(tmp_path / "empty").dataset()
    assert dataset.locations == []
    assert dataset.assets == []


def test_save_dataset_csv_returns_directory(tmp_path):
    directory = save_dataset_csv(tiny_dataset(), tmp_path / "csv")
    assert directory == tmp_path / "csv"
    assert (directory / "pms.csv").is_file()


def test_maximo_import_csv_uses_maximo_headers(tmp_path):
    directory = save_maximo_import_csv(tiny_dataset(), tmp_path / "import")
    asset_header = (directory / "assets.csv").read_text(encoding="utf-8").splitlines()[0]
    assert asset_header.startswith("ASSETNUM,DESCRIPTION,")
    assert "ASSETTYPE" in asset_header
    assert "asset_type" not in asset_header
    pm_header = (directory / "pms.csv").read_text(encoding="utf-8").splitlines()[0]
    assert "FREQUNIT" in pm_header
    assert "NEXTDATE" in pm_header


def test_csv_repository_reads_maximo_export(tmp_path):
    import pandas as pd

    directory = save_maximo_import_csv(tiny_dataset(), tmp_path / "import")
    repo = CsvRepository(directory)
    back = repo.dataset()

    assert len(back.locations) == 5
    assert len(back.assets) == 8
    assert len(back.pms) == 1
    pcs = back.asset_by_num("BB1-PCS")
    assert pcs.equipment_type == "PCS"
    assert pcs.asset_type == "BLOCK"
    assert pcs.install_date is not None
    assert back.pms[0].frequency_days == 30
    assert back.pms[0].next_due is not None
    assert back.workorders[0].labor_hours == 2.0

    # Rows from another site are ignored when reading a Maximo export.
    frame = pd.read_csv(directory / "assets.csv", dtype=str, keep_default_na=False)
    extra = dict.fromkeys(frame.columns, "")
    extra.update(
        {
            "ASSETNUM": "OTHER-SITE-PCS",
            "DESCRIPTION": "Asset at another site",
            "SITEID": "OTHER",
            "ORGID": "OTHER",
            "ASSETTYPE": "PCS",
        }
    )
    frame = pd.concat([frame, pd.DataFrame([extra])], ignore_index=True)
    frame.to_csv(directory / "assets.csv", index=False)
    assert len(CsvRepository(directory).dataset().assets) == 8


def test_maximo_export_roundtrip_recovers_safety_flags(tmp_path):
    dataset = generate_site(seed=5, as_of=REFERENCE_AS_OF)
    directory = save_maximo_import_csv(dataset, tmp_path / "import")
    assert (directory / "README.txt").is_file()

    back = CsvRepository(directory).dataset()
    expected = {pm.pm_num for pm in dataset.pms if pm.safety_critical}
    actual = {pm.pm_num for pm in back.pms if pm.safety_critical}
    assert expected
    assert actual == expected
