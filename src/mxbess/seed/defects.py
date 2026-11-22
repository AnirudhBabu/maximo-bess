"""Known-defect injection: the ground truth the checker is tested against.

``inject_defects`` mutates a *clean* generated dataset in a deterministic way
and returns one :class:`Defect` manifest entry for every finding the checker is
expected to produce.  The manifest is the contract used by
``tests/unit/test_manifest.py`` and by ``mxbess check --verify``.

Notes
-----
* A03 is injected as duplicate description+location pairs, not duplicate asset
  numbers: Maximo enforces unique ASSETNUM, so a duplicate number could never
  exist in a live load.  The duplicate-number branch of the check is covered by
  its own unit test on a hand-built dataset.
* A06 carries a ``live_risk`` note because Maximo may reject an unknown PARENT
  or a hierarchy cycle.  Phase 0/6 confirms what the trial instance allows.
"""

from __future__ import annotations

import datetime as dt
from collections import Counter
from dataclasses import asdict, dataclass

from ..models import CLOSED_WO_STATUSES, OPEN_WO_STATUSES, Asset, Dataset


@dataclass(frozen=True)
class Defect:
    defect_id: str
    code: str
    record_type: str
    record_id: str
    field: str | None = None
    note: str = ""
    live_risk: str | None = None


def build_manifest(dataset: Dataset, defects: list[Defect]) -> dict[str, object]:
    """Serialisable manifest, deterministic apart from caller-supplied dates."""
    counts = Counter(defect.code for defect in defects)
    return {
        "site_id": dataset.site_id,
        "seed": dataset.seed,
        "as_of": dataset.as_of.isoformat(),
        "total_findings": len(defects),
        "counts": dict(sorted(counts.items())),
        "defects": [asdict(defect) for defect in defects],
        "notes": [
            "A03 is injected as duplicate description+location; duplicate asset numbers "
            "cannot exist in Maximo and are covered by a dedicated unit test.",
            "A06 (orphan/cycle) may be rejected by the Maximo API; verify in Phase 0.",
        ],
    }


def _defect(
    defects: list[Defect],
    code: str,
    record_type: str,
    record_id: str,
    field: str | None = None,
    note: str = "",
    live_risk: str | None = None,
) -> None:
    serial = sum(1 for defect in defects if defect.code == code) + 1
    defects.append(
        Defect(
            defect_id=f"{code}-{serial:02d}",
            code=code,
            record_type=record_type,
            record_id=record_id,
            field=field,
            note=note,
            live_risk=live_risk,
        )
    )


def _rename_asset(dataset: Dataset, asset: Asset, new_num: str) -> None:
    old_num = asset.asset_num
    asset.asset_num = new_num
    for other in dataset.assets:
        if other.parent == old_num:
            other.parent = new_num
    for pm in dataset.pms:
        if pm.asset_num == old_num:
            pm.asset_num = new_num
    for wo in dataset.workorders:
        if wo.asset_num == old_num:
            wo.asset_num = new_num


def inject_defects(dataset: Dataset) -> tuple[Dataset, list[Defect]]:
    """Return a dirty copy of ``dataset`` plus the expected finding manifest."""
    dirty = dataset.model_copy(deep=True)
    defects: list[Defect] = []

    modules = [asset for asset in dirty.assets if asset.asset_type == "MODULE"]
    if len(modules) < 40:
        raise ValueError("dataset is too small for the standard defect set")

    # ---------------------------------------------------------------- assets
    for index in (0, 5, 10):
        asset = modules[index]
        asset.location = None
        _defect(defects, "A01", "asset", asset.asset_num, "location", "asset has no location")

    for index in (1, 6, 11):
        asset = modules[index]
        asset.parent = None
        _defect(defects, "A02", "asset", asset.asset_num, "parent", "required parent missing")

    for first_index, second_index in ((2, 3), (7, 8)):
        first, second = modules[first_index], modules[second_index]
        if first.location != second.location:
            raise AssertionError("A03 pair must share a location")
        second.description = first.description
        _defect(
            defects,
            "A03",
            "asset",
            first.asset_num,
            "description",
            "duplicate description+location",
        )
        _defect(
            defects,
            "A03",
            "asset",
            second.asset_num,
            "description",
            "duplicate description+location",
        )

    for index, field in ((15, "manufacturer"), (16, "serial_num"), (17, "install_date")):
        asset = modules[index]
        setattr(asset, field, None)
        _defect(defects, "A04", "asset", asset.asset_num, field, "mandatory field missing")

    for index in (20, 21, 22):
        asset = modules[index]
        new_num = f"BAD-MODULE-{index:03d}"
        _rename_asset(dirty, asset, new_num)
        _defect(defects, "A05", "asset", new_num, "asset_num", "violates naming convention")

    for index, parent in ((25, "MISSING-PARENT-01"), (26, "MISSING-PARENT-02")):
        asset = modules[index]
        asset.parent = parent
        _defect(
            defects,
            "A06",
            "asset",
            asset.asset_num,
            "parent",
            "orphaned parent reference",
            live_risk="Maximo may reject an unknown PARENT value",
        )

    first, second = modules[30], modules[31]
    first_num, second_num = first.asset_num, second.asset_num
    first.parent, second.parent = second_num, first_num
    for asset in (first, second):
        _defect(
            defects,
            "A06",
            "asset",
            asset.asset_num,
            "parent",
            "hierarchy cycle",
            live_risk="Maximo may reject a hierarchy cycle",
        )

    # ------------------------------------------------------------------- PMs
    pms = dirty.pms
    if len(pms) < 40:
        raise ValueError("dataset is too small for the standard defect set")

    for index in (0, 1, 2):
        pm = pms[index]
        pm.jobplan_num = None
        _defect(defects, "P01", "pm", pm.pm_num, "jobplan_num", "PM has no job plan")

    for index, field in ((20, "frequency_days"), (21, "next_due"), (22, "frequency_days")):
        pm = pms[index]
        setattr(pm, field, None)
        _defect(defects, "P02", "pm", pm.pm_num, field, "PM has no frequency/next-due date")

    decommissioned_assets = [
        asset
        for asset in dirty.assets
        if asset.asset_num
        in {
            "BB1-HVAC1",
            "BB2-HVAC1",
            "BB3-HVAC1",
        }
    ]
    if len(decommissioned_assets) != 3:
        raise AssertionError("expected three HVAC assets for P03")
    for asset in decommissioned_assets:
        asset.status = "DECOMMISSIONED"
        targeting = [pm for pm in pms if pm.asset_num == asset.asset_num]
        if len(targeting) != 1:
            raise AssertionError(f"expected one PM for {asset.asset_num}, got {len(targeting)}")
        pm = targeting[0]
        _defect(
            defects,
            "P03",
            "pm",
            pm.pm_num,
            "asset_num",
            f"PM targets decommissioned asset {asset.asset_num}",
        )

    used_pms = {defect.record_id for defect in defects if defect.record_type == "pm"}
    overdue_candidates = [
        pm
        for pm in pms
        if pm.next_due is not None
        and pm.next_due > dirty.as_of
        and pm.pm_num not in used_pms
        and not any(
            wo.pm_num == pm.pm_num and wo.status in OPEN_WO_STATUSES for wo in dirty.workorders
        )
    ]
    if len(overdue_candidates) < 3:
        raise ValueError("not enough future-due PMs to inject P04 defects")
    for offset, pm in enumerate(overdue_candidates[:3], start=1):
        pm.next_due = dirty.as_of - dt.timedelta(days=15 * offset)
        _defect(
            defects,
            "P04",
            "pm",
            pm.pm_num,
            "next_due",
            "PM overdue with no open work order",
        )

    # ------------------------------------------------------------------- WOs
    workorders = dirty.workorders
    used_wos: set[str] = set()

    closed = [
        wo
        for wo in workorders
        if wo.status in CLOSED_WO_STATUSES and wo.actual_finish and (wo.labor_hours or 0) > 0
    ]
    if len(closed) < 12:
        raise ValueError("not enough closed work orders for W01-W03 defects")

    for wo in closed[:3]:
        used_wos.add(wo.wonum)
        wo.asset_num = None
        _defect(defects, "W01", "workorder", wo.wonum, "asset_num", "WO has no asset")

    for wo in closed[3:5]:
        used_wos.add(wo.wonum)
        wo.actual_finish = None
        _defect(
            defects,
            "W02",
            "workorder",
            wo.wonum,
            "actual_finish",
            "closed WO has no actual finish",
        )

    wo = closed[5]
    used_wos.add(wo.wonum)
    wo.labor_hours = 0.0
    _defect(defects, "W02", "workorder", wo.wonum, "labor_hours", "closed WO has no actual labour")

    for days, wo in zip((10, 20), closed[6:8], strict=True):
        used_wos.add(wo.wonum)
        wo.actual_finish = dirty.as_of + dt.timedelta(days=days)
        _defect(
            defects,
            "W03",
            "workorder",
            wo.wonum,
            "actual_finish",
            "closed WO has a future finish date",
        )

    in_progress = [wo for wo in workorders if wo.status == "INPROG" and wo.wonum not in used_wos]
    if not in_progress:
        raise ValueError("no in-progress work order for the W03 defect")
    wo = in_progress[0]
    used_wos.add(wo.wonum)
    wo.actual_finish = dirty.as_of - dt.timedelta(days=5)
    _defect(
        defects,
        "W03",
        "workorder",
        wo.wonum,
        "actual_finish",
        "open WO already has an actual finish",
    )

    open_wos = [
        wo
        for wo in workorders
        if wo.status in OPEN_WO_STATUSES
        and wo.wonum not in used_wos
        and wo.reported_date >= dirty.as_of - dt.timedelta(days=60)
    ]
    if len(open_wos) < 3:
        raise ValueError("not enough recent open work orders for W04 defects")
    for days, wo in zip((120, 150, 200), open_wos[:3], strict=True):
        wo.reported_date = dirty.as_of - dt.timedelta(days=days)
        _defect(
            defects,
            "W04",
            "workorder",
            wo.wonum,
            "reported_date",
            f"open WO older than 90 days ({days} days)",
        )

    return dirty, defects
