"""Shared test fixtures and a stateful in-memory Maximo fake."""

from __future__ import annotations

import datetime as dt
import json
import re
from urllib.parse import parse_qs, unquote, urlparse

import responses

from mxbess.mapping import NATURAL_KEY_FIELDS, OBJECT_STRUCTURES
from mxbess.models import PM, Asset, Dataset, JobPlan, Location, WorkOrder

AS_OF = dt.date(2026, 11, 1)
MOCK_BASE = "https://mock.maximo.com/maximo"

_OS_TO_KIND = {os_name: kind for kind, os_name in OBJECT_STRUCTURES.items()}
_WHERE_RE = re.compile(r'([A-Z0-9_]+)="([^"]*)"')


def asset(
    asset_num: str,
    description: str,
    asset_type: str,
    equipment_type: str,
    location: str,
    parent: str | None,
    **overrides,
) -> Asset:
    values = {
        "asset_num": asset_num,
        "description": description,
        "asset_type": asset_type,
        "equipment_type": equipment_type,
        "site_id": "BISHA-BESS",
        "org_id": "BISHA",
        "location": location,
        "parent": parent,
        "manufacturer": "Acme",
        "serial_num": f"SN-{asset_num}",
        "install_date": dt.date(2024, 1, 1),
        "criticality": 2,
        "status": "OPERATING",
    }
    values.update(overrides)
    return Asset(**values)


def tiny_dataset() -> Dataset:
    """Small dataset that satisfies every check (zero findings)."""
    locations = [
        Location(
            location="BISHA-BESS",
            description="Bisha site",
            site_id="BISHA-BESS",
            org_id="BISHA",
            parent=None,
            level="SITE",
        ),
        Location(
            location="BB1",
            description="Block 1",
            site_id="BISHA-BESS",
            org_id="BISHA",
            parent="BISHA-BESS",
            level="BLOCK",
        ),
        Location(
            location="BB1-CT1",
            description="Container 1",
            site_id="BISHA-BESS",
            org_id="BISHA",
            parent="BB1",
            level="CONTAINER",
        ),
        Location(
            location="BB1-CT1-RK01",
            description="Rack 1",
            site_id="BISHA-BESS",
            org_id="BISHA",
            parent="BB1-CT1",
            level="RACK",
        ),
        Location(
            location="BB1-CT1-RK02",
            description="Rack 2",
            site_id="BISHA-BESS",
            org_id="BISHA",
            parent="BB1-CT1",
            level="RACK",
        ),
    ]
    assets = [
        asset("SITE-SCADA", "Site SCADA/EMS server", "SITE", "SCADA", "BISHA-BESS", None),
        asset("BB1-PCS", "PCS inverter block 1", "BLOCK", "PCS", "BB1", None),
        asset("BB1-HVAC1", "HVAC unit 1 block 1", "BLOCK", "HVAC", "BB1", None),
        asset(
            "BB1-CT1", "Battery container BB1-CT1", "CONTAINER", "CONTAINER", "BB1-CT1", "BB1-PCS"
        ),
        asset(
            "BB1-CT1-RK01-MD01", "Module MD01 rack 1", "MODULE", "MODULE", "BB1-CT1-RK01", "BB1-CT1"
        ),
        asset(
            "BB1-CT1-RK01-MD02", "Module MD02 rack 1", "MODULE", "MODULE", "BB1-CT1-RK01", "BB1-CT1"
        ),
        asset(
            "BB1-CT1-RK01-MD03", "Module MD03 rack 1", "MODULE", "MODULE", "BB1-CT1-RK01", "BB1-CT1"
        ),
        asset(
            "BB1-CT1-RK02-MD01", "Module MD01 rack 2", "MODULE", "MODULE", "BB1-CT1-RK02", "BB1-CT1"
        ),
    ]
    jobplan = JobPlan(
        jp_num="JP-01",
        description="Monthly visual inspection",
        site_id="BISHA-BESS",
        org_id="BISHA",
        task_count=2,
        duration_hours=1.5,
        tasks=["Inspect", "Record"],
    )
    pm = PM(
        pm_num="PM-01-001",
        description="Monthly visual inspection - MD01",
        site_id="BISHA-BESS",
        org_id="BISHA",
        asset_num="BB1-CT1-RK01-MD01",
        location="BB1-CT1-RK01",
        jobplan_num="JP-01",
        frequency_days=30,
        next_due=AS_OF + dt.timedelta(days=10),
        last_done=AS_OF - dt.timedelta(days=20),
        status="ACTIVE",
    )
    workorder = WorkOrder(
        wonum="PMWO-0001",
        description="Monthly visual inspection - completed",
        site_id="BISHA-BESS",
        org_id="BISHA",
        status="CLOSE",
        work_type="PM",
        reported_date=AS_OF - dt.timedelta(days=15),
        asset_num="BB1-CT1-RK01-MD01",
        location="BB1-CT1-RK01",
        pm_num="PM-01-001",
        jobplan_num="JP-01",
        scheduled_start=AS_OF - dt.timedelta(days=13),
        target_finish=AS_OF - dt.timedelta(days=10),
        actual_start=AS_OF - dt.timedelta(days=13),
        actual_finish=AS_OF - dt.timedelta(days=10),
        labor_hours=2.0,
        priority=3,
    )
    return Dataset(
        site_id="BISHA-BESS",
        org_id="BISHA",
        seed=1,
        as_of=AS_OF,
        locations=locations,
        assets=assets,
        jobplans=[jobplan],
        pms=[pm],
        workorders=[workorder],
    )


def workorder(
    wonum: str,
    *,
    status: str = "CLOSE",
    work_type: str = "PM",
    reported_date: dt.date | None = None,
    target_finish: dt.date | None = None,
    actual_start: dt.date | None = None,
    actual_finish: dt.date | None = None,
    labor_hours: float | None = 2.0,
    asset_num: str | None = "BB1-CT1-RK01-MD01",
    pm_num: str | None = None,
) -> WorkOrder:
    return WorkOrder(
        wonum=wonum,
        description=f"Work order {wonum}",
        site_id="BISHA-BESS",
        org_id="BISHA",
        status=status,
        work_type=work_type,
        reported_date=reported_date or AS_OF - dt.timedelta(days=10),
        asset_num=asset_num,
        location="BB1-CT1-RK01",
        pm_num=pm_num,
        target_finish=target_finish,
        actual_start=actual_start,
        actual_finish=actual_finish,
        labor_hours=labor_hours,
    )


def _matches(record: dict, where: str | None) -> bool:
    if not where:
        return True
    return all(str(record.get(field, "")) == value for field, value in _WHERE_RE.findall(where))


class FakeMaximo:
    """Stateful fake implementing the subset of the API the loader uses.

    Registered as a ``responses`` callback for GET, POST and PATCH under
    ``https://mock.maximo.com/maximo/api/os/...``.  Supports injected
    one-shot failures for resumability tests and records write order.
    """

    def __init__(self) -> None:
        self.records: dict[str, dict[str, dict]] = {kind: {} for kind in NATURAL_KEY_FIELDS}
        self.events: list[tuple[str, str, str]] = []
        self.fail_once: set[tuple[str, str, str]] = set()

    def install(self, rsps: responses.RequestsMock) -> None:
        for method in ("GET", "POST", "PATCH"):
            rsps.add_callback(
                method,
                re.compile(r"https://mock\.maximo\.com/maximo/api/os/.*"),
                callback=self.handle,
            )

    def snapshot(self) -> dict[str, dict[str, dict]]:
        return {
            kind: {key: dict(value) for key, value in records.items()}
            for kind, records in self.records.items()
        }

    def handle(self, request):
        method = request.method
        parsed = urlparse(request.url)
        parts = parsed.path.strip("/").split("/")
        # maximo / api / os / <objectstructure> [/ <key>]
        os_name = parts[3]
        key = unquote(parts[4]) if len(parts) > 4 else None
        kind = _OS_TO_KIND[os_name]

        if method == "GET":
            if key is not None:
                record = self.records[kind].get(key)
                if record is None:
                    return self._json(404, {"Error": "not found"})
                return self._json(200, record)
            where = parse_qs(parsed.query).get("oslc.where", [None])[0]
            members = [record for record in self.records[kind].values() if _matches(record, where)]
            return self._json(200, {"member": members})

        if method == "POST":
            payload = json.loads(request.body or b"{}")
            natural = str(payload[NATURAL_KEY_FIELDS[kind]])
            self.events.append(("POST", kind, natural))
            if self._consume_failure("POST", kind, natural):
                return self._json(500, {"Error": "injected failure"})
            if natural in self.records[kind]:
                return self._json(400, {"Error": "duplicate key"})
            self.records[kind][natural] = payload
            return self._json(201, payload)

        if method == "PATCH":
            assert key is not None
            self.events.append(("PATCH", kind, key))
            if self._consume_failure("PATCH", kind, key):
                return self._json(500, {"Error": "injected failure"})
            record = self.records[kind].get(key)
            if record is None:
                return self._json(404, {"Error": "not found"})
            record.update(json.loads(request.body or b"{}"))
            return self._json(200, record)

        return self._json(405, {"Error": "method not allowed"})

    def _consume_failure(self, method: str, kind: str, key: str) -> bool:
        signature = (method, kind, key)
        if signature in self.fail_once:
            self.fail_once.remove(signature)
            return True
        return False

    @staticmethod
    def _json(status: int, payload: dict):
        return status, {"Content-Type": "application/json"}, json.dumps(payload)
