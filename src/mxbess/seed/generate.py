"""Deterministic synthetic BESS site generator.

The generator is a pure function of ``(seed, as_of, spec)``: the same inputs
always produce byte-identical JSON.  Nothing depends on the wall clock unless
the caller explicitly passes ``date.today()``.
"""

from __future__ import annotations

import datetime as dt
import random
from dataclasses import dataclass, field

from ..models import PM, Asset, Dataset, JobPlan, Location, WorkOrder

SITE_ID = "BISHA-BESS"
ORG_ID = "BISHA"
DEFAULT_SEED = 20260101

#: Fixed anchor used by tests and the checked-in sample report.  The CLI passes
#: ``date.today()`` by default so a live load contains recent work orders.
REFERENCE_AS_OF = dt.date(2026, 11, 1)

SITE_LOCATION = "BISHA-BESS"

_MANUFACTURERS: dict[str, tuple[str, ...]] = {
    "PCS": ("Sungrow", "SMA", "Power Electronics"),
    "MVT": ("ABB", "Siemens Energy", "Hitachi Energy"),
    "HVAC": ("Daikin", "Vertiv", "CoolIT"),
    "FIRE": ("Hochiki", "Siemens", "Honeywell"),
    "BMS": ("Nuvation", "Wartsila", "Fluence"),
    "MODULE": ("CATL", "BYD", "EVE Energy"),
    "SCADA": ("Siemens", "Schneider Electric"),
    "AUX": ("ABB", "Eaton"),
    "SWG": ("Schneider Electric", "ABB", "Siemens"),
}

_CRITICALITY: dict[str, int] = {
    "PCS": 1,
    "MVT": 1,
    "HVAC": 3,
    "FDA": 1,
    "FSS": 1,
    "BMS": 2,
    "SCADA": 1,
    "AUX": 3,
    "SWG": 2,
    "CONTAINER": 2,
    "MODULE": 2,
}

_PROBLEM_CODES = ("ELEC", "HVAC", "COMMS", "MECH", "FIRE", "BMS", "PCS")
_FAILURE_CODES = ("OVERTEMP", "EARTHFAULT", "SENSORFAIL", "FANFAIL", "COMMLOSS", "TRIP")


@dataclass(frozen=True)
class SiteSpec:
    """Size and identity of the site.

    The plan's illustrative hierarchy uses six modules per rack, which yields
    ~423 assets and overshoots the 300-400 target.  Five modules per rack keeps
    every level of the hierarchy while landing at 359 assets; raise
    ``modules_per_rack`` to six if the exact plan example is preferred.
    """

    blocks: int = 4
    containers_per_block: int = 2
    racks_per_container: int = 8
    modules_per_rack: int = 5
    site_id: str = SITE_ID
    org_id: str = ORG_ID


@dataclass(frozen=True)
class PMPlan:
    """A PM *plan* (10-14 of these), fanned out to many PM records."""

    code: str
    name: str
    frequency_days: int
    safety_critical: bool
    tasks: tuple[str, ...]
    equipment_types: tuple[str, ...] = ()
    location_level: str | None = None


PM_PLANS: tuple[PMPlan, ...] = (
    PMPlan(
        "01",
        "Monthly visual and thermal inspection",
        30,
        False,
        (
            "Walk the container and check for damage or leaks",
            "Thermal scan of DC busbars",
            "Record findings",
        ),
        equipment_types=("CONTAINER",),
    ),
    PMPlan(
        "02",
        "Monthly HVAC filter and airflow check",
        30,
        False,
        (
            "Replace or clean filters",
            "Measure supply and return air temperatures",
            "Check condensate drain",
        ),
        equipment_types=("HVAC",),
    ),
    PMPlan(
        "03",
        "Quarterly DC busbar torque check",
        90,
        True,
        (
            "Isolate DC string",
            "Torque busbar connections to specification",
            "Restore and record readings",
        ),
        location_level="CONTAINER",
    ),
    PMPlan(
        "04",
        "Semi-annual fire suppression inspection",
        180,
        True,
        (
            "Inspect cylinders and pressure gauges",
            "Check nozzles and pipework",
            "Verify manual release",
        ),
        equipment_types=("FSS",),
    ),
    PMPlan(
        "05",
        "Annual fire detection system test",
        365,
        True,
        ("Test each detector", "Verify panel annunciation", "Check battery backup"),
        equipment_types=("FDA",),
    ),
    PMPlan(
        "06",
        "Annual electrical thermography",
        365,
        False,
        ("Thermal scan of terminations", "Compare phases", "Raise corrective work for hot spots"),
        equipment_types=("PCS", "MVT", "SWG"),
    ),
    PMPlan(
        "07",
        "Annual BMS calibration and firmware review",
        365,
        False,
        (
            "Review alarm log",
            "Calibrate temperature and voltage sensors",
            "Check firmware baseline",
        ),
        equipment_types=("BMS",),
    ),
    PMPlan(
        "08",
        "Annual transformer inspection",
        365,
        True,
        ("Inspect bushings and oil level", "Check earthing", "Review dissolved gas analysis"),
        equipment_types=("MVT",),
    ),
    PMPlan(
        "09",
        "Quarterly switchgear inspection",
        90,
        True,
        ("Inspect breaker condition", "Check interlocks and labels", "Verify protection settings"),
        equipment_types=("SWG",),
    ),
    PMPlan(
        "10",
        "Monthly PCS performance check",
        30,
        False,
        ("Review efficiency trends", "Check cooling fans", "Verify grid-code parameters"),
        equipment_types=("PCS",),
    ),
    PMPlan(
        "11",
        "Semi-annual battery capacity and state-of-health test",
        180,
        False,
        ("Run capacity test", "Record cell balance", "Compare against warranty curve"),
        location_level="BLOCK",
    ),
    PMPlan(
        "12",
        "Annual auxiliary power inspection",
        365,
        False,
        ("Test UPS transfer", "Inspect distribution board", "Check battery age"),
        equipment_types=("AUX",),
    ),
    PMPlan(
        "13",
        "Annual SCADA/EMS backup verification",
        365,
        False,
        ("Verify configuration backup", "Test restore to spare host", "Check time synchronisation"),
        equipment_types=("SCADA",),
    ),
    PMPlan(
        "14",
        "Semi-annual E-stop and safety interlock test",
        180,
        True,
        ("Test each E-stop", "Verify interlock trip", "Record response time"),
        equipment_types=("FSS", "PCS"),
    ),
)


@dataclass
class _Family:
    """Names for one piece of block equipment."""

    suffix: str
    description: str
    manufacturer_key: str
    criticality_key: str
    equipment_type: str = ""


_BLOCK_EQUIPMENT: tuple[_Family, ...] = (
    _Family("PCS", "PCS inverter", "PCS", "PCS", "PCS"),
    _Family("MVT", "MV transformer", "MVT", "MVT", "MVT"),
    _Family("HVAC1", "HVAC unit 1", "HVAC", "HVAC", "HVAC"),
    _Family("HVAC2", "HVAC unit 2", "HVAC", "HVAC", "HVAC"),
    _Family("FDA", "Fire detection panel", "FIRE", "FDA", "FDA"),
    _Family("FSS", "Fire suppression system", "FIRE", "FSS", "FSS"),
    _Family("BMS", "BMS controller", "BMS", "BMS", "BMS"),
)

_SITE_EQUIPMENT: tuple[_Family, ...] = (
    _Family("SCADA", "Site SCADA/EMS server", "SCADA", "SCADA", "SCADA"),
    _Family("AUXPWR", "Auxiliary power distribution", "AUX", "AUX", "AUX"),
    _Family("SWG", "Site MV switchgear", "SWG", "SWG", "SWG"),
)


@dataclass
class _NameRegistry:
    """Small deterministic counter used for serial numbers."""

    index: int = 0
    used: set[str] = field(default_factory=set)


def build_locations(spec: SiteSpec) -> list[Location]:
    locations = [
        Location(
            location=spec.site_id,
            description="Bisha battery energy storage site",
            site_id=spec.site_id,
            org_id=spec.org_id,
            parent=None,
            level="SITE",
        )
    ]
    for b in range(1, spec.blocks + 1):
        block = f"BB{b}"
        locations.append(
            Location(
                location=block,
                description=f"BESS block {block}",
                site_id=spec.site_id,
                org_id=spec.org_id,
                parent=spec.site_id,
                level="BLOCK",
            )
        )
        for c in range(1, spec.containers_per_block + 1):
            container = f"{block}-CT{c}"
            locations.append(
                Location(
                    location=container,
                    description=f"Battery container {container}",
                    site_id=spec.site_id,
                    org_id=spec.org_id,
                    parent=block,
                    level="CONTAINER",
                )
            )
            for r in range(1, spec.racks_per_container + 1):
                rack = f"{container}-RK{r:02d}"
                locations.append(
                    Location(
                        location=rack,
                        description=f"Battery rack {rack}",
                        site_id=spec.site_id,
                        org_id=spec.org_id,
                        parent=container,
                        level="RACK",
                    )
                )
    return locations


def _serial(rng: random.Random, manufacturer: str, registry: _NameRegistry) -> str:
    prefix = "".join(ch for ch in manufacturer.upper() if ch.isascii() and ch.isalpha())[:3]
    while True:
        serial = f"{prefix or 'SN'}-{rng.randrange(100_000, 999_999)}"
        if serial not in registry.used:
            registry.used.add(serial)
            return serial


def _install_date(rng: random.Random, as_of: dt.date, kind: str) -> dt.date:
    if kind == "SITE":
        low, high = 700, 900
    elif kind == "MODULE":
        low, high = 380, 650
    else:
        low, high = 500, 800
    return as_of - dt.timedelta(days=rng.randint(low, high))


def _make_asset(
    *,
    asset_num: str,
    description: str,
    asset_type: str,
    equipment_type: str,
    location: str,
    parent: str | None,
    manufacturer_key: str,
    criticality_key: str,
    spec: SiteSpec,
    rng: random.Random,
    as_of: dt.date,
    registry: _NameRegistry,
) -> Asset:
    manufacturers = _MANUFACTURERS[manufacturer_key]
    manufacturer = manufacturers[registry.index % len(manufacturers)]
    registry.index += 1
    return Asset(
        asset_num=asset_num,
        description=description,
        asset_type=asset_type,
        equipment_type=equipment_type,
        site_id=spec.site_id,
        org_id=spec.org_id,
        location=location,
        parent=parent,
        manufacturer=manufacturer,
        serial_num=_serial(rng, manufacturer, registry),
        install_date=_install_date(rng, as_of, asset_type),
        criticality=_CRITICALITY[criticality_key],
        status="OPERATING",
    )


def build_assets(
    spec: SiteSpec, locations: list[Location], rng: random.Random, as_of: dt.date
) -> list[Asset]:
    """Build block equipment, site equipment, container assets and modules.

    Containers are both a location and an asset (a common Maximo pattern); that
    gives modules a real parent and keeps the hierarchy meaningful.
    """
    registry = _NameRegistry()
    assets: list[Asset] = []

    for b in range(1, spec.blocks + 1):
        block = f"BB{b}"
        for family in _BLOCK_EQUIPMENT:
            assets.append(
                _make_asset(
                    asset_num=f"{block}-{family.suffix}",
                    description=f"{family.description} {block}",
                    asset_type="BLOCK",
                    equipment_type=family.equipment_type,
                    location=block,
                    parent=None,
                    manufacturer_key=family.manufacturer_key,
                    criticality_key=family.criticality_key,
                    spec=spec,
                    rng=rng,
                    as_of=as_of,
                    registry=registry,
                )
            )

    for family in _SITE_EQUIPMENT:
        assets.append(
            _make_asset(
                asset_num=f"SITE-{family.suffix}",
                description=family.description,
                asset_type="SITE",
                equipment_type=family.equipment_type,
                location=spec.site_id,
                parent=None,
                manufacturer_key=family.manufacturer_key,
                criticality_key=family.criticality_key,
                spec=spec,
                rng=rng,
                as_of=as_of,
                registry=registry,
            )
        )

    for b in range(1, spec.blocks + 1):
        block = f"BB{b}"
        pcs = f"{block}-PCS"
        for c in range(1, spec.containers_per_block + 1):
            container = f"{block}-CT{c}"
            assets.append(
                _make_asset(
                    asset_num=container,
                    description=f"Battery container {container}",
                    asset_type="CONTAINER",
                    equipment_type="CONTAINER",
                    location=container,
                    parent=pcs,
                    manufacturer_key="MODULE",
                    criticality_key="CONTAINER",
                    spec=spec,
                    rng=rng,
                    as_of=as_of,
                    registry=registry,
                )
            )
            for r in range(1, spec.racks_per_container + 1):
                rack = f"{container}-RK{r:02d}"
                for m in range(1, spec.modules_per_rack + 1):
                    module = f"{rack}-MD{m:02d}"
                    assets.append(
                        _make_asset(
                            asset_num=module,
                            description=f"Battery module MD{m:02d} in {rack}",
                            asset_type="MODULE",
                            equipment_type="MODULE",
                            location=rack,
                            parent=container,
                            manufacturer_key="MODULE",
                            criticality_key="MODULE",
                            spec=spec,
                            rng=rng,
                            as_of=as_of,
                            registry=registry,
                        )
                    )
    return assets


def build_jobplans(spec: SiteSpec) -> list[JobPlan]:
    return [
        JobPlan(
            jp_num=f"JP-{plan.code}",
            description=plan.name,
            site_id=spec.site_id,
            org_id=spec.org_id,
            task_count=len(plan.tasks),
            duration_hours=round(len(plan.tasks) * 0.75, 2),
            tasks=list(plan.tasks),
        )
        for plan in PM_PLANS
    ]


def _representative_asset(assets: list[Asset], location_id: str) -> Asset | None:
    candidates = [asset for asset in assets if asset.location == location_id]
    if not candidates:
        return None
    for preferred in ("CONTAINER", "BLOCK", "SITE", "MODULE"):
        for asset in candidates:
            if asset.asset_type == preferred:
                return asset
    return candidates[0]


def build_pms(
    spec: SiteSpec,
    assets: list[Asset],
    locations: list[Location],
    rng: random.Random,
    as_of: dt.date,
) -> list[PM]:
    """Create one PM record per (plan, target) pair and schedule it deterministically."""
    pms: list[PM] = []
    for plan in PM_PLANS:
        seq = 0
        targets: list[tuple[Asset | None, str | None, str]] = []
        if plan.location_level:
            for loc in locations:
                if loc.level == plan.location_level:
                    targets.append((None, loc.location, loc.description))
        else:
            for asset in assets:
                if asset.equipment_type in plan.equipment_types:
                    targets.append((asset, asset.location, asset.description))

        for seq, (asset, location, label) in enumerate(targets, start=1):
            pm_num = f"PM-{plan.code}-{seq:03d}"

            if rng.random() < 0.30:
                next_due = as_of - dt.timedelta(days=rng.randint(1, 60))
            else:
                future_window = min(180, max(plan.frequency_days - 1, 1))
                next_due = as_of + dt.timedelta(days=rng.randint(1, future_window))
            prev_due = next_due - dt.timedelta(days=plan.frequency_days)
            delay = 0 if rng.random() < 0.85 else rng.randint(1, 10)
            last_done = min(prev_due + dt.timedelta(days=delay), as_of)

            pms.append(
                PM(
                    pm_num=pm_num,
                    description=f"{plan.name} - {asset.asset_num if asset else label}",
                    site_id=spec.site_id,
                    org_id=spec.org_id,
                    asset_num=asset.asset_num if asset else None,
                    location=location,
                    jobplan_num=f"JP-{plan.code}",
                    frequency_days=plan.frequency_days,
                    next_due=next_due,
                    last_done=last_done,
                    status="ACTIVE",
                    safety_critical=plan.safety_critical,
                )
            )
    return pms


def _wo_number(prefix: str, index: int) -> str:
    return f"{prefix}-{index:04d}"


def build_workorders(
    spec: SiteSpec,
    assets: list[Asset],
    pms: list[PM],
    rng: random.Random,
    as_of: dt.date,
    corrective_count: int = 120,
) -> list[WorkOrder]:
    """Create PM-history, open-PM and corrective work orders over the prior 12 months."""
    assets_by_num = {asset.asset_num: asset for asset in assets}
    workorders: list[WorkOrder] = []
    pm_counter = 0

    for pm in pms:
        if pm.next_due is None or pm.frequency_days is None:
            continue
        target_asset = (
            assets_by_num.get(pm.asset_num)
            if pm.asset_num
            else _representative_asset(assets, pm.location or "")
        )
        if target_asset is None:
            continue
        frequency = dt.timedelta(days=pm.frequency_days)
        prev_due = pm.next_due - frequency

        # Historical, completed occurrence.
        if as_of - dt.timedelta(days=365) <= prev_due <= as_of:
            pm_counter += 1
            delay = 0 if rng.random() < 0.85 else rng.randint(1, 10)
            actual_finish = min(prev_due + dt.timedelta(days=delay), as_of)
            workorders.append(
                WorkOrder(
                    wonum=_wo_number("PMWO", pm_counter),
                    description=f"{pm.description} (completed)",
                    site_id=spec.site_id,
                    org_id=spec.org_id,
                    status="CLOSE" if rng.random() < 0.5 else "COMP",
                    work_type="PM",
                    reported_date=prev_due - dt.timedelta(days=7),
                    asset_num=target_asset.asset_num,
                    location=pm.location or target_asset.location,
                    pm_num=pm.pm_num,
                    jobplan_num=pm.jobplan_num,
                    scheduled_start=prev_due - dt.timedelta(days=1),
                    target_finish=prev_due,
                    actual_start=prev_due - dt.timedelta(days=1),
                    actual_finish=actual_finish,
                    labor_hours=round(rng.uniform(1.0, 8.0), 1),
                    priority=3,
                )
            )

        # Current occurrence: overdue PMs always have an open WO, so clean data
        # has zero P04 findings.
        if pm.next_due <= as_of:
            pm_counter += 1
            reported = max(pm.next_due - dt.timedelta(days=3), as_of - dt.timedelta(days=85))
            status = rng.choice(("WAPPR", "APPR", "INPROG"))
            actual_start = None
            if status == "INPROG":
                start = max(pm.next_due, reported + dt.timedelta(days=1))
                if start <= as_of:
                    actual_start = start
                else:
                    status = "APPR"
            workorders.append(
                WorkOrder(
                    wonum=_wo_number("PMWO", pm_counter),
                    description=f"{pm.description} (open)",
                    site_id=spec.site_id,
                    org_id=spec.org_id,
                    status=status,
                    work_type="PM",
                    reported_date=reported,
                    asset_num=target_asset.asset_num,
                    location=pm.location or target_asset.location,
                    pm_num=pm.pm_num,
                    jobplan_num=pm.jobplan_num,
                    scheduled_start=pm.next_due,
                    target_finish=pm.next_due,
                    actual_start=actual_start,
                    actual_finish=None,
                    labor_hours=None,
                    priority=2 if pm.safety_critical else 3,
                )
            )

    statuses = (
        ["COMP"] * 45
        + ["CLOSE"] * 25
        + ["INPROG"] * 15
        + ["APPR"] * 12
        + ["WAPPR"] * 12
        + ["CAN"] * 11
    )
    while len(statuses) < corrective_count:
        statuses.append("COMP")
    statuses = statuses[:corrective_count]
    rng.shuffle(statuses)

    for index, status in enumerate(statuses, start=1):
        asset = rng.choice(assets)
        problem = rng.choice(_PROBLEM_CODES)
        failure = rng.choice(_FAILURE_CODES)
        description = (
            f"Corrective {problem.lower()} repair ({failure.lower()}) on {asset.asset_num}"
        )

        if status in {"COMP", "CLOSE"}:
            age = rng.randint(10, 350)
            reported = as_of - dt.timedelta(days=age)
            actual_start = min(reported + dt.timedelta(days=rng.randint(0, 2)), as_of)
            actual_finish = min(actual_start + dt.timedelta(days=rng.randint(1, 10)), as_of)
            workorders.append(
                WorkOrder(
                    wonum=_wo_number("CM", index),
                    description=description,
                    site_id=spec.site_id,
                    org_id=spec.org_id,
                    status=status,
                    work_type="CM",
                    reported_date=reported,
                    asset_num=asset.asset_num,
                    location=asset.location,
                    scheduled_start=reported + dt.timedelta(days=2),
                    target_finish=reported + dt.timedelta(days=14),
                    actual_start=actual_start,
                    actual_finish=actual_finish,
                    labor_hours=round(rng.uniform(1.0, 16.0), 1),
                    problem_code=problem,
                    failure_code=failure,
                    priority=rng.choice((1, 2, 3, 4)),
                )
            )
        elif status == "INPROG":
            reported = as_of - dt.timedelta(days=rng.randint(2, 60))
            actual_start = min(reported + dt.timedelta(days=rng.randint(0, 2)), as_of)
            workorders.append(
                WorkOrder(
                    wonum=_wo_number("CM", index),
                    description=description,
                    site_id=spec.site_id,
                    org_id=spec.org_id,
                    status=status,
                    work_type="CM",
                    reported_date=reported,
                    asset_num=asset.asset_num,
                    location=asset.location,
                    scheduled_start=reported + dt.timedelta(days=2),
                    target_finish=reported + dt.timedelta(days=14),
                    actual_start=actual_start,
                    actual_finish=None,
                    labor_hours=None,
                    problem_code=problem,
                    failure_code=failure,
                    priority=rng.choice((1, 2, 3)),
                )
            )
        elif status in {"APPR", "WAPPR"}:
            reported = as_of - dt.timedelta(days=rng.randint(1, 45))
            workorders.append(
                WorkOrder(
                    wonum=_wo_number("CM", index),
                    description=description,
                    site_id=spec.site_id,
                    org_id=spec.org_id,
                    status=status,
                    work_type="CM",
                    reported_date=reported,
                    asset_num=asset.asset_num,
                    location=asset.location,
                    scheduled_start=reported + dt.timedelta(days=3),
                    target_finish=reported + dt.timedelta(days=21),
                    actual_start=None,
                    actual_finish=None,
                    labor_hours=None,
                    problem_code=problem,
                    failure_code=failure,
                    priority=rng.choice((2, 3, 4)),
                )
            )
        else:  # CAN
            reported = as_of - dt.timedelta(days=rng.randint(5, 200))
            workorders.append(
                WorkOrder(
                    wonum=_wo_number("CM", index),
                    description=description,
                    site_id=spec.site_id,
                    org_id=spec.org_id,
                    status="CAN",
                    work_type="CM",
                    reported_date=reported,
                    asset_num=asset.asset_num,
                    location=asset.location,
                    scheduled_start=reported + dt.timedelta(days=3),
                    target_finish=reported + dt.timedelta(days=14),
                    actual_start=None,
                    actual_finish=None,
                    labor_hours=None,
                    problem_code=problem,
                    failure_code=failure,
                    priority=rng.choice((3, 4, 5)),
                )
            )
    return workorders


def generate_site(
    seed: int = DEFAULT_SEED,
    as_of: dt.date = REFERENCE_AS_OF,
    spec: SiteSpec | None = None,
) -> Dataset:
    """Generate a complete, internally consistent site snapshot."""
    spec = spec or SiteSpec()
    rng = random.Random(seed)
    locations = build_locations(spec)
    assets = build_assets(spec, locations, rng, as_of)
    jobplans = build_jobplans(spec)
    pms = build_pms(spec, assets, locations, rng, as_of)
    workorders = build_workorders(spec, assets, pms, rng, as_of)
    return Dataset(
        site_id=spec.site_id,
        org_id=spec.org_id,
        seed=seed,
        as_of=as_of,
        locations=locations,
        assets=assets,
        jobplans=jobplans,
        pms=pms,
        workorders=workorders,
    )
