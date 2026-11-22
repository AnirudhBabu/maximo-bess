"""Repository abstraction.

Checks, KPIs and the report depend only on :class:`Repository`.  Three
implementations exist:

* :class:`FixtureRepository` - in-memory, used by tests and ``seed`` demos;
* :class:`CsvRepository` - the fallback when the trial exposes no API;
* :class:`ApiRepository` - MAS Manage through :class:`mxbess.client.MaximoClient`.

Only the API implementation talks to ``requests``.
"""

from __future__ import annotations

import datetime as dt
import json
from enum import StrEnum
from pathlib import Path
from typing import Protocol, runtime_checkable

import pandas as pd

from . import mapping
from .client import MaximoClient
from .models import PM, Asset, Dataset, DomainModel, JobPlan, Location, WorkOrder

_KIND_MODELS: dict[str, type[DomainModel]] = {
    "location": Location,
    "asset": Asset,
    "jobplan": JobPlan,
    "pm": PM,
    "workorder": WorkOrder,
}

_CSV_NAMES = {
    "location": "locations.csv",
    "asset": "assets.csv",
    "jobplan": "jobplans.csv",
    "pm": "pms.csv",
    "workorder": "workorders.csv",
}

_META_FILE = "dataset_meta.json"
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
_LIST_FIELDS = {"tasks"}


class UpsertOutcome(StrEnum):
    CREATED = "created"
    UPDATED = "updated"
    UNCHANGED = "unchanged"


@runtime_checkable
class Repository(Protocol):
    """Read-only repository surface used by checks, KPIs and the report."""

    def dataset(self) -> Dataset: ...


@runtime_checkable
class WritableRepository(Repository, Protocol):
    """Upsert surface used by the loader.  Lookup-before-create is mandatory."""

    def upsert_location(self, location: Location) -> UpsertOutcome: ...

    def upsert_asset(self, asset: Asset) -> UpsertOutcome: ...

    def upsert_jobplan(self, jobplan: JobPlan) -> UpsertOutcome: ...

    def upsert_pm(self, pm: PM) -> UpsertOutcome: ...

    def upsert_workorder(self, workorder: WorkOrder) -> UpsertOutcome: ...


class FixtureRepository:
    """In-memory writable repository backed by a :class:`Dataset`."""

    def __init__(self, dataset: Dataset) -> None:
        self._dataset = dataset.model_copy(deep=True)

    def dataset(self) -> Dataset:
        return self._dataset

    # ----------------------------------------------------------------- helpers
    def _upsert(self, kind: str, record: DomainModel) -> UpsertOutcome:
        attr = {
            "location": "locations",
            "asset": "assets",
            "jobplan": "jobplans",
            "pm": "pms",
            "workorder": "workorders",
        }[kind]
        records: list[DomainModel] = getattr(self._dataset, attr)
        for index, existing in enumerate(records):
            if existing.natural_key == record.natural_key:  # type: ignore[attr-defined]
                if existing.model_dump() == record.model_dump():
                    return UpsertOutcome.UNCHANGED
                records[index] = record.model_copy(deep=True)
                return UpsertOutcome.UPDATED
        records.append(record.model_copy(deep=True))
        return UpsertOutcome.CREATED

    def upsert_location(self, location: Location) -> UpsertOutcome:
        return self._upsert("location", location)

    def upsert_asset(self, asset: Asset) -> UpsertOutcome:
        return self._upsert("asset", asset)

    def upsert_jobplan(self, jobplan: JobPlan) -> UpsertOutcome:
        return self._upsert("jobplan", jobplan)

    def upsert_pm(self, pm: PM) -> UpsertOutcome:
        return self._upsert("pm", pm)

    def upsert_workorder(self, workorder: WorkOrder) -> UpsertOutcome:
        return self._upsert("workorder", workorder)


class CsvRepository:
    """CSV-backed repository (Maximo import/export fallback).

    Reads ``dataset_meta.json`` for site/org/seed/as-of and one CSV per record
    type.  Writes go through in-memory merges and rewrite the affected CSV.
    """

    def __init__(
        self,
        directory: str | Path,
        *,
        site_id: str = "BISHA-BESS",
        org_id: str = "BISHA",
        as_of: dt.date | None = None,
        seed: int = 0,
    ) -> None:
        self.directory = Path(directory)
        self._site_id = site_id
        self._org_id = org_id
        self._as_of = as_of or dt.date.today()
        self._seed = seed
        meta_path = self.directory / _META_FILE
        if meta_path.is_file():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            self._site_id = meta.get("site_id", self._site_id)
            self._org_id = meta.get("org_id", self._org_id)
            self._seed = meta.get("seed", self._seed)
            if meta.get("as_of"):
                self._as_of = dt.date.fromisoformat(meta["as_of"])
        self._cache: Dataset | None = None

    # ------------------------------------------------------------------ read
    def dataset(self) -> Dataset:
        if self._cache is None:
            self._cache = Dataset(
                site_id=self._site_id,
                org_id=self._org_id,
                seed=self._seed,
                as_of=self._as_of,
                locations=self._read_kind("location"),
                assets=self._read_kind("asset"),
                jobplans=self._read_kind("jobplan"),
                pms=self._read_kind("pm"),
                workorders=self._read_kind("workorder"),
            )
        return self._cache

    def _read_kind(self, kind: str) -> list:
        path = self.directory / _CSV_NAMES[kind]
        if not path.is_file():
            return []
        frame = pd.read_csv(path, dtype=str, keep_default_na=False)
        model_cls = _KIND_MODELS[kind]
        columns = set(frame.columns)
        internal_fields = set(model_cls.model_fields)
        maximo_columns = {column for column in mapping.FIELD_MAPS[kind].values() if column}

        if internal_fields & columns:
            return self._read_internal(kind, frame, model_cls)
        if maximo_columns & columns:
            return self._read_maximo_export(kind, frame)
        raise ValueError(
            f"{path} has neither the internal nor the Maximo column headers for {kind}"
        )

    def _read_internal(self, kind: str, frame: pd.DataFrame, model_cls: type) -> list:
        records = []
        allowed = set(model_cls.model_fields)
        for row in frame.to_dict(orient="records"):
            values: dict[str, object] = {}
            for field, raw in row.items():
                if field not in allowed:
                    continue
                if raw == "":
                    continue
                if field in _DATE_FIELDS:
                    values[field] = dt.date.fromisoformat(str(raw)[:10])
                elif field in _LIST_FIELDS:
                    values[field] = json.loads(raw) if raw else []
                else:
                    values[field] = raw
            records.append(model_cls.model_validate(values))
        return records

    def _read_maximo_export(self, kind: str, frame: pd.DataFrame) -> list:
        """Accept a CSV exported from Maximo (uppercase column headers)."""
        mapped_columns = {column for column in mapping.FIELD_MAPS[kind].values() if column}
        records = []
        for row in frame.to_dict(orient="records"):
            if "SITEID" in row and row["SITEID"] not in ("", self._site_id):
                continue
            payload = {
                column: value
                for column, value in row.items()
                if column in mapped_columns and value != ""
            }
            payload.setdefault("SITEID", self._site_id)
            payload.setdefault("ORGID", self._org_id)
            records.append(mapping.from_payload(kind, payload))
        return records

    # ------------------------------------------------------------------ write
    def save(self, dataset: Dataset) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        self._site_id = dataset.site_id
        self._org_id = dataset.org_id
        self._seed = dataset.seed
        self._as_of = dataset.as_of
        self._cache = dataset.model_copy(deep=True)
        meta = {
            "site_id": dataset.site_id,
            "org_id": dataset.org_id,
            "seed": dataset.seed,
            "as_of": dataset.as_of.isoformat(),
        }
        (self.directory / _META_FILE).write_text(json.dumps(meta, indent=2), encoding="utf-8")
        for kind, filename in _CSV_NAMES.items():
            records = self._records_for(kind, dataset)
            rows = [
                {
                    field: _csv_value(getattr(record, field))
                    for field in _KIND_MODELS[kind].model_fields
                }
                for record in records
            ]
            frame = pd.DataFrame(rows, columns=list(_KIND_MODELS[kind].model_fields))
            frame.to_csv(self.directory / filename, index=False)

    @staticmethod
    def _records_for(kind: str, dataset: Dataset) -> list:
        return {
            "location": dataset.locations,
            "asset": dataset.assets,
            "jobplan": dataset.jobplans,
            "pm": dataset.pms,
            "workorder": dataset.workorders,
        }[kind]

    def _upsert(self, kind: str, record: DomainModel) -> UpsertOutcome:
        current = self.dataset()
        outcome = _merge_into_dataset(current, kind, record)
        if outcome is not UpsertOutcome.UNCHANGED:
            self.save(current)
        return outcome

    def upsert_location(self, location: Location) -> UpsertOutcome:
        return self._upsert("location", location)

    def upsert_asset(self, asset: Asset) -> UpsertOutcome:
        return self._upsert("asset", asset)

    def upsert_jobplan(self, jobplan: JobPlan) -> UpsertOutcome:
        return self._upsert("jobplan", jobplan)

    def upsert_pm(self, pm: PM) -> UpsertOutcome:
        return self._upsert("pm", pm)

    def upsert_workorder(self, workorder: WorkOrder) -> UpsertOutcome:
        return self._upsert("workorder", workorder)


class ApiRepository:
    """Live repository backed by :class:`MaximoClient`."""

    def __init__(
        self,
        client: MaximoClient,
        *,
        site_id: str,
        org_id: str,
        as_of: dt.date | None = None,
    ) -> None:
        self.client = client
        self.site_id = site_id
        self.org_id = org_id
        self.as_of = as_of or dt.date.today()

    def dataset(self) -> Dataset:
        where = f'SITEID="{self.site_id}"'

        def fetch(kind: str) -> list:
            return [
                mapping.from_payload(kind, row) for row in self.client.get_all(kind, where=where)
            ]

        return Dataset(
            site_id=self.site_id,
            org_id=self.org_id,
            seed=0,
            as_of=self.as_of,
            locations=fetch("location"),
            assets=fetch("asset"),
            jobplans=fetch("jobplan"),
            pms=fetch("pm"),
            workorders=fetch("workorder"),
        )

    def _where(self, kind: str, record: DomainModel) -> str:
        clauses = [mapping.where_clause_for_key(kind, record.natural_key)]  # type: ignore[attr-defined]
        for field, column in (("site_id", "SITEID"), ("org_id", "ORGID")):
            value = getattr(record, field, None)
            if value:
                clauses.append(f'{column}="{value}"')
        return " and ".join(clauses)

    def _upsert(self, kind: str, record: DomainModel) -> UpsertOutcome:
        existing = self.client.find_one_by_key(kind, self._where(kind, record))
        if existing is None:
            self.client.create(kind, mapping.to_payload(kind, record))
            return UpsertOutcome.CREATED
        existing_model = mapping.from_payload(kind, existing)
        desired = mapping.to_payload(kind, record, include_none=True)
        current = mapping.to_payload(kind, existing_model, include_none=True)
        changes = {name: value for name, value in desired.items() if current.get(name) != value}
        if not changes:
            return UpsertOutcome.UNCHANGED
        self.client.update(kind, record.natural_key, changes)  # type: ignore[attr-defined]
        return UpsertOutcome.UPDATED

    def upsert_location(self, location: Location) -> UpsertOutcome:
        return self._upsert("location", location)

    def upsert_asset(self, asset: Asset) -> UpsertOutcome:
        return self._upsert("asset", asset)

    def upsert_jobplan(self, jobplan: JobPlan) -> UpsertOutcome:
        return self._upsert("jobplan", jobplan)

    def upsert_pm(self, pm: PM) -> UpsertOutcome:
        return self._upsert("pm", pm)

    def upsert_workorder(self, workorder: WorkOrder) -> UpsertOutcome:
        return self._upsert("workorder", workorder)


def _merge_into_dataset(dataset: Dataset, kind: str, record: DomainModel) -> UpsertOutcome:
    attr = {
        "location": "locations",
        "asset": "assets",
        "jobplan": "jobplans",
        "pm": "pms",
        "workorder": "workorders",
    }[kind]
    records: list[DomainModel] = getattr(dataset, attr)
    for index, existing in enumerate(records):
        if existing.natural_key == record.natural_key:  # type: ignore[attr-defined]
            if existing.model_dump() == record.model_dump():
                return UpsertOutcome.UNCHANGED
            records[index] = record.model_copy(deep=True)
            return UpsertOutcome.UPDATED
    records.append(record.model_copy(deep=True))
    return UpsertOutcome.CREATED


def _csv_value(value: object) -> object:
    if value is None:
        return ""
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, list):
        return json.dumps(value)
    return value


def save_dataset_csv(dataset: Dataset, directory: str | Path) -> Path:
    """Write the internal CSV snapshot used by :class:`CsvRepository`."""
    repo = CsvRepository(directory)
    repo.save(dataset)
    return repo.directory


_IMPORT_FILES = {
    "location": "locations.csv",
    "asset": "assets.csv",
    "jobplan": "jobplans.csv",
    "pm": "pms.csv",
    "workorder": "workorders.csv",
}


def save_maximo_import_csv(dataset: Dataset, directory: str | Path) -> Path:
    """Write CSVs with Maximo column headers for the Data Import application.

    This is the fallback when the trial exposes no usable REST API.  Each file
    maps one object structure; dates are ISO-8601 and PMs carry FREQUNIT=DAYS.
    """
    output = Path(directory)
    output.mkdir(parents=True, exist_ok=True)
    records_by_kind = {
        "location": dataset.locations,
        "asset": dataset.assets,
        "jobplan": dataset.jobplans,
        "pm": dataset.pms,
        "workorder": dataset.workorders,
    }
    for kind, records in records_by_kind.items():
        columns = [column for column in mapping.FIELD_MAPS[kind].values() if column]
        if kind == "pm":
            columns.append("FREQUNIT")
        rows = [mapping.to_payload(kind, record) for record in records]
        frame = pd.DataFrame(rows).reindex(columns=columns)
        frame.to_csv(output / _IMPORT_FILES[kind], index=False)
    (output / "README.txt").write_text(
        "Maximo Data Import files generated by mxbess.\n"
        f"Site: {dataset.site_id}\n"
        f"Org:  {dataset.org_id}\n"
        f"As of: {dataset.as_of.isoformat()}\n\n"
        "Import in this order (parents before children):\n"
        "  1. locations.csv\n"
        "  2. assets.csv\n"
        "  3. jobplans.csv\n"
        "  4. pms.csv\n"
        "  5. workorders.csv\n\n"
        "Headers are Maximo columns. Dates are ISO-8601. PMs carry FREQUNIT=DAYS.\n"
        "ACTLABHRS, LASTCOMPDATE and PROBLEMCODE/FAILURECODE are UNVERIFIED - see\n"
        "docs/instance-notes.md before importing. Job-plan tasks and the PM\n"
        "safety-critical flag are local metadata and are not in these files\n"
        "(safety-critical is recovered from the JP-03/04/05/08/09/14 codes on read).\n",
        encoding="utf-8",
    )
    return output
