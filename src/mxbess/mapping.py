"""The single place where Maximo object-structure and column names live.

Anything marked ``UNVERIFIED`` in :data:`UNVERIFIED` must be confirmed against
the live trial instance during Phase 0 and then corrected here (and in
``docs/instance-notes.md``).  Keeping these names in one module means Phase 6
is a configuration exercise, not a refactor.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Any

from . import models

#: Model kind -> Maximo object structure.  VERIFY each name in Phase 0.
OBJECT_STRUCTURES: dict[str, str] = {
    "location": "mxapilocations",
    "asset": "mxapiasset",
    "jobplan": "mxapijobplan",
    "pm": "mxapipm",
    "workorder": "mxapiwo",
}

#: Maximo column used to look up an existing record by natural key.
NATURAL_KEY_FIELDS: dict[str, str] = {
    "location": "LOCATION",
    "asset": "ASSETNUM",
    "jobplan": "JPNUM",
    "pm": "PMNUM",
    "workorder": "WONUM",
}

#: Model kind -> {model field: Maximo column or None when local-only}.
#:
#: ``None`` means the field is used for reporting/checks but is not sent to
#: Maximo.  Job-plan tasks are a separate Maximo object structure and are out
#: of scope for this project.
FIELD_MAPS: dict[str, dict[str, str | None]] = {
    "location": {
        "location": "LOCATION",
        "description": "DESCRIPTION",
        "site_id": "SITEID",
        "org_id": "ORGID",
        "parent": "PARENT",
        "location_type": "TYPE",
        "level": None,
    },
    "asset": {
        "asset_num": "ASSETNUM",
        "description": "DESCRIPTION",
        "asset_type": None,
        "equipment_type": "ASSETTYPE",
        "site_id": "SITEID",
        "org_id": "ORGID",
        "location": "LOCATION",
        "parent": "PARENT",
        "manufacturer": "MANUFACTURER",
        "serial_num": "SERIALNUM",
        "install_date": "INSTALLDATE",
        "criticality": "CRITICALITY",
        "status": "STATUS",
    },
    "jobplan": {
        "jp_num": "JPNUM",
        "description": "DESCRIPTION",
        "site_id": "SITEID",
        "org_id": "ORGID",
        "task_count": None,
        "duration_hours": None,
        "tasks": None,
    },
    "pm": {
        "pm_num": "PMNUM",
        "description": "DESCRIPTION",
        "site_id": "SITEID",
        "org_id": "ORGID",
        "asset_num": "ASSETNUM",
        "location": "LOCATION",
        "jobplan_num": "JPNUM",
        "frequency_days": "FREQUENCY",
        "next_due": "NEXTDATE",
        "last_done": "LASTCOMPDATE",
        "status": "STATUS",
        "safety_critical": None,
    },
    "workorder": {
        "wonum": "WONUM",
        "description": "DESCRIPTION",
        "site_id": "SITEID",
        "org_id": "ORGID",
        "status": "STATUS",
        "work_type": "WORKTYPE",
        "reported_date": "REPORTDATE",
        "asset_num": "ASSETNUM",
        "location": "LOCATION",
        "pm_num": "PMNUM",
        "jobplan_num": "JPNUM",
        "scheduled_start": "SCHEDSTART",
        "target_finish": "SCHEDFINISH",
        "actual_start": "ACTSTART",
        "actual_finish": "ACTFINISH",
        "labor_hours": "ACTLABHRS",
        "problem_code": "PROBLEMCODE",
        "failure_code": "FAILURECODE",
        "priority": "WOPRIORITY",
    },
}

_DATE_FIELDS = {
    "install_date",
    "next_due",
    "last_done",
    "reported_date",
    "scheduled_start",
    "target_finish",
    "actual_start",
    "actual_finish",
}

#: Documented candidates that Phase 0 must confirm.  Anything here is a known
#: assumption, never silently treated as fact.
UNVERIFIED: dict[str, str] = {
    "object-structure names": "mxapilocations, mxapiasset, mxapijobplan, mxapipm, mxapiwo",
    "auth header": "apikey: <key> (no bearer prefix) on MAS Manage",
    "paging": "responseInfo.nextPage.href in the JSON response",
    "PATCH": "partial update via PATCH /os/{object}/{key}",
    "LASTCOMPDATE": "PM last-completed date column",
    "ACTLABHRS": "actual labour hours on the WO object; live Maximo derives actual "
    "hours from LABTRANS instead, so this may need a LABTRANS load",
    "PROBLEMCODE/FAILURECODE": "problem/failure code columns on the WO object",
    "PM FREQUENCY": "frequency value interpreted together with FREQUNIT=DAYS",
    "asset CRITICALITY": "numeric 1-5 (1 = highest criticality)",
}


def to_payload(
    kind: str, record: models.DomainModel, *, include_none: bool = False
) -> dict[str, Any]:
    """Convert a domain model into the JSON body Maximo expects.

    ``include_none`` is used for updates: sending an explicit null clears a
    value that a defect fix removed (for example a missing location).
    """
    field_map = FIELD_MAPS[kind]
    payload: dict[str, Any] = {}
    for model_field, maximo_field in field_map.items():
        if maximo_field is None:
            continue
        value = getattr(record, model_field)
        if value is None:
            if include_none:
                payload[maximo_field] = None
            continue
        if model_field in _DATE_FIELDS:
            payload[maximo_field] = value.isoformat()
        else:
            payload[maximo_field] = value
    if kind == "pm" and record.frequency_days is not None:
        payload["FREQUNIT"] = "DAYS"
    return payload


def from_payload(kind: str, payload: dict[str, Any]) -> models.DomainModel:
    """Best-effort conversion of a Maximo JSON record into a domain model.

    Unknown columns are ignored.  Missing optional columns fall back to model
    defaults so that a live read never fails because a column is absent.
    """
    field_map = FIELD_MAPS[kind]
    values: dict[str, Any] = {}
    for model_field, maximo_field in field_map.items():
        if maximo_field is None or maximo_field not in payload:
            continue
        raw = payload[maximo_field]
        if raw is None or raw == "":
            continue
        if model_field in _DATE_FIELDS:
            values[model_field] = _parse_date(raw)
        elif model_field in {"criticality", "priority", "frequency_days", "task_count"}:
            values[model_field] = int(float(raw))
        elif model_field in {"duration_hours", "labor_hours"}:
            values[model_field] = float(raw)
        else:
            values[model_field] = raw
    model_cls = {
        "location": models.Location,
        "asset": models.Asset,
        "jobplan": models.JobPlan,
        "pm": models.PM,
        "workorder": models.WorkOrder,
    }[kind]
    if kind == "asset":
        _complete_asset_identity(values, payload)
    elif kind == "pm":
        # safety_critical is local reporting metadata.  Recover it from the
        # job-plan code, which Maximo does preserve.
        jobplan = str(values.get("jobplan_num") or "")
        values["safety_critical"] = jobplan in models.SAFETY_CRITICAL_JOBPLANS
    return model_cls.model_validate(values)


def _complete_asset_identity(values: dict[str, Any], payload: dict[str, Any]) -> None:
    """Fill the hierarchy level and equipment family on a live read.

    ASSETTYPE carries the engineering family.  If an export omits it, fall back
    to the documented naming convention so A02/A05 do not produce noise.
    """
    if payload.get("ASSETTYPE"):
        values.setdefault("asset_type", _infer_asset_type(str(values.get("equipment_type", ""))))
        return
    asset_type, equipment_type = _infer_from_asset_number(str(values.get("asset_num", "")))
    values.setdefault("asset_type", asset_type)
    values.setdefault("equipment_type", equipment_type)


def _infer_from_asset_number(asset_num: str) -> tuple[str, str]:
    """Best-effort hierarchy level + family from the numbering convention."""
    if asset_num.startswith("SITE-"):
        suffix = asset_num[len("SITE-") :]
        return "SITE", {"AUXPWR": "AUX"}.get(suffix, suffix)
    block = re.fullmatch(r"BB\d+-(PCS|MVT|HVAC\d+|FDA|FSS|BMS)", asset_num)
    if block:
        suffix = re.sub(r"\d+$", "", block.group(1))
        return "BLOCK", suffix
    if re.fullmatch(r"BB\d+-CT\d+", asset_num):
        return "CONTAINER", "CONTAINER"
    if re.fullmatch(r"BB\d+-CT\d+-RK\d{2}-MD\d{2}", asset_num):
        return "MODULE", "MODULE"
    return "MODULE", "GENERIC"


def _infer_asset_type(equipment_type: str) -> str:
    """Reconstruct the hierarchy level when reading live data.

    Maximo's ASSETTYPE carries the engineering family, not the hierarchy level,
    so the level is derived from the family (UNVERIFIED for unusual families).
    """
    family = equipment_type.upper()
    if family in {"PCS", "MVT", "HVAC", "FDA", "FSS", "BMS"}:
        return "BLOCK"
    if family in {"SCADA", "AUX", "SWG", "AUXPWR"}:
        return "SITE"
    if family == "CONTAINER":
        return "CONTAINER"
    return "MODULE"


def _parse_date(raw: Any) -> dt.date:
    if isinstance(raw, dt.datetime):
        return raw.date()
    if isinstance(raw, dt.date):
        return raw
    text = str(raw)
    try:
        return dt.date.fromisoformat(text[:10])
    except ValueError as exc:  # pragma: no cover - defensive
        raise ValueError(f"cannot parse Maximo date {text!r}") from exc


def natural_key_field(kind: str) -> str:
    return NATURAL_KEY_FIELDS[kind]


def where_clause_for_key(kind: str, key: str) -> str:
    """Build an ``oslc.where`` expression for one natural key.

    Maximo strings use double quotes; embedded double quotes are escaped by
    doubling them (the OSLC convention).
    """
    escaped = str(key).replace('"', '""')
    return f'{NATURAL_KEY_FIELDS[kind]}="{escaped}"'
