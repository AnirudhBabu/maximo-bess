from __future__ import annotations

from mxbess.loader import load_dataset
from mxbess.models import Asset
from tests.support import tiny_dataset

EXPECTED_RECORDS = 16  # 5 locations + 8 assets + 1 job plan + 1 PM + 1 WO


def test_load_is_idempotent(make_api_repo, fake_maximo):
    dataset = tiny_dataset()
    repo = make_api_repo()

    first = load_dataset(dataset, repo)
    assert first.ok
    assert first.created == EXPECTED_RECORDS
    assert first.failures == []
    state_after_first = fake_maximo.snapshot()

    second = load_dataset(dataset, repo)
    assert second.ok
    assert second.created == 0
    assert second.updated == 0
    assert second.unchanged == EXPECTED_RECORDS
    assert fake_maximo.snapshot() == state_after_first


def test_load_respects_dependency_order(make_api_repo, fake_maximo):
    load_dataset(tiny_dataset(), make_api_repo())
    post_order = [event for event in fake_maximo.events if event[0] == "POST"]
    positions = {(kind, key): index for index, (_method, kind, key) in enumerate(post_order)}

    assert positions[("location", "BISHA-BESS")] < positions[("location", "BB1")]
    assert positions[("location", "BB1")] < positions[("location", "BB1-CT1")]
    assert positions[("location", "BB1-CT1")] < positions[("location", "BB1-CT1-RK01")]
    assert positions[("asset", "BB1-PCS")] < positions[("asset", "BB1-CT1")]
    assert positions[("asset", "BB1-CT1")] < positions[("asset", "BB1-CT1-RK01-MD01")]
    assert positions[("jobplan", "JP-01")] < positions[("pm", "PM-01-001")]
    assert positions[("pm", "PM-01-001")] < positions[("workorder", "PMWO-0001")]
    assert len(post_order) == EXPECTED_RECORDS


def test_update_only_changes_what_differs(make_api_repo, fake_maximo):
    dataset = tiny_dataset()
    repo = make_api_repo()
    load_dataset(dataset, repo)

    changed = dataset.model_copy(deep=True)
    target = next(asset for asset in changed.assets if asset.asset_num == "BB1-PCS")
    target.description = "Renamed PCS inverter"
    report = load_dataset(changed, repo)

    assert report.ok
    assert report.created == 0
    assert report.updated == 1
    assert report.counts["asset"].updated == 1
    stored = fake_maximo.records["asset"]["BB1-PCS"]
    assert stored["DESCRIPTION"] == "Renamed PCS inverter"


def test_partial_failure_is_resumable(make_api_repo, fake_maximo):
    fake_maximo.fail_once.add(("POST", "asset", "BB1-CT1-RK01-MD02"))
    dataset = tiny_dataset()
    repo = make_api_repo(max_retries=0)

    first = load_dataset(dataset, repo)
    assert not first.ok
    assert len(first.failures) == 1
    assert first.failures[0].key == "BB1-CT1-RK01-MD02"
    assert first.counts["asset"].failed == 1
    assert "BB1-CT1-RK01-MD02" not in fake_maximo.records["asset"]

    second = load_dataset(dataset, repo)
    assert second.ok
    assert second.created == 1
    assert second.counts["asset"].created == 1
    assert len(fake_maximo.records["asset"]) == 8


def test_load_report_serialises(make_api_repo):
    report = load_dataset(tiny_dataset(), make_api_repo())
    payload = report.as_dict()
    assert payload["ok"] is True
    assert payload["totals"] == {
        "created": EXPECTED_RECORDS,
        "updated": 0,
        "unchanged": 0,
        "failed": 0,
    }
    assert payload["counts"]["asset"]["created"] == 8


def test_api_repository_reads_back_written_state(make_api_repo):
    dataset = tiny_dataset()
    repo = make_api_repo()
    load_dataset(dataset, repo)

    read_back = repo.dataset()
    assert len(read_back.locations) == 5
    assert len(read_back.assets) == 8
    assert len(read_back.pms) == 1
    assert len(read_back.workorders) == 1

    pcs = next(asset for asset in read_back.assets if asset.asset_num == "BB1-PCS")
    assert isinstance(pcs, Asset)
    assert pcs.asset_type == "BLOCK"
    assert pcs.equipment_type == "PCS"
    assert pcs.manufacturer == "Acme"
    assert pcs.install_date is not None
    assert read_back.as_of == repo.as_of

    module = next(asset for asset in read_back.assets if asset.asset_num == "BB1-CT1-RK01-MD01")
    assert module.asset_type == "MODULE"
    assert module.parent == "BB1-CT1"


def test_location_scope_filter_is_applied(make_api_repo, rsps):
    repo = make_api_repo()
    load_dataset(tiny_dataset(), repo)
    repo.dataset()
    get_calls = [
        call.request
        for call in rsps.calls
        if call.request.method == "GET" and "/mxapilocations" in call.request.url
    ]
    assert get_calls
    assert all("SITEID" in call.url for call in get_calls)
