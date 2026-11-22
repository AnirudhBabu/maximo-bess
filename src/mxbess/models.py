"""Pydantic domain models for the synthetic BESS site.

The field names here are deliberately Maximo-agnostic (snake_case).  The
translation to Maximo column names lives in :mod:`mxbess.mapping`, so a field
rename discovered during Phase 0 is a one-file change.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

AssetType = Literal["SITE", "BLOCK", "CONTAINER", "MODULE"]
LocationLevel = Literal["SITE", "BLOCK", "CONTAINER", "RACK"]
AssetStatus = Literal["OPERATING", "DECOMMISSIONED", "DOWN"]
PMStatus = Literal["ACTIVE", "INACTIVE"]
WOStatus = Literal["WAPPR", "APPR", "INPROG", "COMP", "CLOSE", "CAN"]
WorkType = Literal["PM", "CM"]

#: Asset types that must carry a parent reference to be considered complete.
PARENT_REQUIRED_TYPES: frozenset[str] = frozenset({"CONTAINER", "MODULE"})

#: Work-order statuses that count as open backlog.
OPEN_WO_STATUSES: frozenset[str] = frozenset({"WAPPR", "APPR", "INPROG"})
#: Work-order statuses that require actual finish date + actual labour.
CLOSED_WO_STATUSES: frozenset[str] = frozenset({"COMP", "CLOSE"})
ALL_WO_STATUSES: tuple[str, ...] = ("WAPPR", "APPR", "INPROG", "COMP", "CLOSE", "CAN")

#: Job-plan codes that carry HSE/compliance significance.  Safety-critical is a
#: local reporting flag (Maximo has no standard column), but the job-plan code
#: is preserved by Maximo import/export, so it is used to recover the flag when
#: reading live or exported data.
SAFETY_CRITICAL_JOBPLANS: frozenset[str] = frozenset(
    {"JP-03", "JP-04", "JP-05", "JP-08", "JP-09", "JP-14"}
)


class DomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class Location(DomainModel):
    """A Maximo location.  The location hierarchy is site -> block -> container -> rack."""

    location: str
    description: str
    site_id: str
    org_id: str
    parent: str | None = None
    location_type: str = "OPERATING"
    level: LocationLevel = "SITE"

    @property
    def natural_key(self) -> str:
        return self.location


class Asset(DomainModel):
    """A physical asset in the register.

    ``asset_type`` is the hierarchy level (site/block/container/module) and is
    used by the checks and completeness report.  ``equipment_type`` is the
    engineering family (PCS, HVAC, FSS, ...); it maps to Maximo's ASSETTYPE.
    """

    asset_num: str
    description: str
    asset_type: AssetType
    equipment_type: str = "GENERIC"
    site_id: str
    org_id: str
    location: str | None = None
    parent: str | None = None
    manufacturer: str | None = None
    serial_num: str | None = None
    install_date: date | None = None
    criticality: int | None = Field(default=None, ge=1, le=5)
    status: AssetStatus = "OPERATING"

    @property
    def natural_key(self) -> str:
        return self.asset_num


class JobPlan(DomainModel):
    """A job plan.  Tasks are held as short descriptions to keep the mock simple."""

    jp_num: str
    description: str
    site_id: str
    org_id: str
    task_count: int = Field(default=0, ge=0)
    duration_hours: float = Field(default=0.0, ge=0.0)
    tasks: list[str] = Field(default_factory=list)

    @property
    def natural_key(self) -> str:
        return self.jp_num


class PM(DomainModel):
    """A preventive-maintenance plan record.

    ``asset_num`` is None for location-scoped plans (for example a rack-level
    DC torque inspection); ``location`` is used in that case.
    """

    pm_num: str
    description: str
    site_id: str
    org_id: str
    asset_num: str | None = None
    location: str | None = None
    jobplan_num: str | None = None
    frequency_days: int | None = Field(default=None, gt=0)
    next_due: date | None = None
    last_done: date | None = None
    status: PMStatus = "ACTIVE"
    safety_critical: bool = False

    @property
    def natural_key(self) -> str:
        return self.pm_num


class WorkOrder(DomainModel):
    """A work order, either PM-generated (``work_type == "PM"``) or corrective."""

    wonum: str
    description: str
    site_id: str
    org_id: str
    status: WOStatus
    work_type: WorkType
    reported_date: date
    asset_num: str | None = None
    location: str | None = None
    pm_num: str | None = None
    jobplan_num: str | None = None
    scheduled_start: date | None = None
    target_finish: date | None = None
    actual_start: date | None = None
    actual_finish: date | None = None
    labor_hours: float | None = Field(default=None, ge=0.0)
    problem_code: str | None = None
    failure_code: str | None = None
    priority: int = Field(default=3, ge=1, le=5)

    @property
    def natural_key(self) -> str:
        return self.wonum


class Dataset(DomainModel):
    """A complete, self-contained snapshot of the site's records."""

    site_id: str
    org_id: str
    seed: int
    as_of: date
    locations: list[Location] = Field(default_factory=list)
    assets: list[Asset] = Field(default_factory=list)
    jobplans: list[JobPlan] = Field(default_factory=list)
    pms: list[PM] = Field(default_factory=list)
    workorders: list[WorkOrder] = Field(default_factory=list)

    def asset_by_num(self, asset_num: str | None) -> Asset | None:
        """Return the first asset with ``asset_num`` (duplicates are possible in dirty data)."""
        if not asset_num:
            return None
        for asset in self.assets:
            if asset.asset_num == asset_num:
                return asset
        return None

    def location_by_id(self, location: str | None) -> Location | None:
        if not location:
            return None
        for loc in self.locations:
            if loc.location == location:
                return loc
        return None

    def jobplan_by_num(self, jp_num: str | None) -> JobPlan | None:
        if not jp_num:
            return None
        for jp in self.jobplans:
            if jp.jp_num == jp_num:
                return jp
        return None

    def pm_by_num(self, pm_num: str | None) -> PM | None:
        if not pm_num:
            return None
        for pm in self.pms:
            if pm.pm_num == pm_num:
                return pm
        return None

    def workorders_for_pm(self, pm_num: str | None) -> list[WorkOrder]:
        if not pm_num:
            return []
        return [wo for wo in self.workorders if wo.pm_num == pm_num]
