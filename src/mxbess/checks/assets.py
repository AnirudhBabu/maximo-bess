"""Asset-register checks A01-A06."""

from __future__ import annotations

import re
from collections import defaultdict

from ..models import PARENT_REQUIRED_TYPES, Asset, Dataset
from ._core import Finding, check, make_finding

NAMING_PATTERNS: dict[str, re.Pattern[str]] = {
    "SITE": re.compile(r"^SITE-[A-Z0-9]+$"),
    "BLOCK": re.compile(r"^BB\d+-(PCS|MVT|HVAC\d+|FDA|FSS|BMS)$"),
    "CONTAINER": re.compile(r"^BB\d+-CT\d+$"),
    "MODULE": re.compile(r"^BB\d+-CT\d+-RK\d{2}-MD\d{2}$"),
}

MANDATORY_ASSET_FIELDS: tuple[str, ...] = (
    "manufacturer",
    "serial_num",
    "install_date",
    "criticality",
)


@check("A01")
def check_a01_asset_without_location(dataset: Dataset) -> list[Finding]:
    return [
        make_finding("A01", "asset", asset.asset_num, "asset has no location")
        for asset in dataset.assets
        if not asset.location
    ]


@check("A02")
def check_a02_asset_without_required_parent(dataset: Dataset) -> list[Finding]:
    return [
        make_finding(
            "A02",
            "asset",
            asset.asset_num,
            f"parent is required for {asset.asset_type} assets",
        )
        for asset in dataset.assets
        if asset.asset_type in PARENT_REQUIRED_TYPES and not asset.parent
    ]


@check("A03")
def check_a03_duplicate_asset(dataset: Dataset) -> list[Finding]:
    """Flag each record involved in a duplicate asset number or description+location."""
    findings: list[Finding] = []
    flagged: set[int] = set()

    by_number: dict[str, list[int]] = defaultdict(list)
    for index, asset in enumerate(dataset.assets):
        by_number[asset.asset_num].append(index)
    for asset_num, indices in by_number.items():
        if len(indices) < 2:
            continue
        for index in indices:
            flagged.add(index)
            findings.append(
                make_finding(
                    "A03",
                    "asset",
                    asset_num,
                    f"duplicate asset number ({len(indices)} records)",
                    kind="duplicate_asset_num",
                    count=len(indices),
                )
            )

    by_description: dict[tuple[str, str], list[int]] = defaultdict(list)
    for index, asset in enumerate(dataset.assets):
        if not asset.location or not asset.description:
            continue
        key = (asset.description.strip().casefold(), asset.location)
        by_description[key].append(index)
    for (_description, location), indices in by_description.items():
        if len(indices) < 2:
            continue
        for index in indices:
            if index in flagged:
                continue
            asset = dataset.assets[index]
            findings.append(
                make_finding(
                    "A03",
                    "asset",
                    asset.asset_num,
                    f"duplicate description+location at {location} ({len(indices)} records)",
                    kind="duplicate_description_location",
                    count=len(indices),
                    location=location,
                )
            )
    return findings


@check("A04")
def check_a04_missing_mandatory_fields(dataset: Dataset) -> list[Finding]:
    findings: list[Finding] = []
    for asset in dataset.assets:
        missing = [
            field_name
            for field_name in MANDATORY_ASSET_FIELDS
            if getattr(asset, field_name) in (None, "")
        ]
        if missing:
            findings.append(
                make_finding(
                    "A04",
                    "asset",
                    asset.asset_num,
                    "missing mandatory fields: " + ", ".join(missing),
                    missing=missing,
                )
            )
    return findings


@check("A05")
def check_a05_asset_naming_convention(dataset: Dataset) -> list[Finding]:
    findings: list[Finding] = []
    for asset in dataset.assets:
        pattern = NAMING_PATTERNS.get(asset.asset_type)
        if pattern is None:  # pragma: no cover - Literal prevents this
            continue
        if pattern.fullmatch(asset.asset_num) is None:
            findings.append(
                make_finding(
                    "A05",
                    "asset",
                    asset.asset_num,
                    f"asset number does not match the {asset.asset_type} convention",
                    expected_pattern=pattern.pattern,
                )
            )
    return findings


@check("A06")
def check_a06_orphan_or_cycle(dataset: Dataset) -> list[Finding]:
    findings: list[Finding] = []
    parent_by_num: dict[str, str | None] = {}
    for asset in dataset.assets:
        parent_by_num.setdefault(asset.asset_num, asset.parent)

    known_numbers = set(parent_by_num)
    for asset in dataset.assets:
        if asset.parent and asset.parent not in known_numbers:
            findings.append(
                make_finding(
                    "A06",
                    "asset",
                    asset.asset_num,
                    f"parent {asset.parent} does not exist",
                    kind="orphan",
                    parent=asset.parent,
                )
            )

    cycle_nodes = find_cycle_nodes(parent_by_num)
    for asset in dataset.assets:
        if asset.asset_num in cycle_nodes:
            findings.append(
                make_finding(
                    "A06",
                    "asset",
                    asset.asset_num,
                    "asset is part of a hierarchy cycle",
                    kind="cycle",
                )
            )
    return findings


def find_cycle_nodes(parent_by_num: dict[str, str | None]) -> set[str]:
    """Return asset numbers that participate in a parent-reference cycle."""
    state: dict[str, int] = {}
    cycle_nodes: set[str] = set()

    for start in parent_by_num:
        if state.get(start) == 2:
            continue
        path: list[str] = []
        position: dict[str, int] = {}
        node: str | None = start
        while node is not None and state.get(node, 0) == 0:
            state[node] = 1
            position[node] = len(path)
            path.append(node)
            parent = parent_by_num.get(node)
            if parent is not None and parent not in parent_by_num:
                node = None  # orphan, not a cycle
                break
            node = parent
        if node is not None and node in position:
            cycle_nodes.update(path[position[node] :])
        for visited in path:
            state[visited] = 2
    return cycle_nodes


def is_asset_complete(asset: Asset) -> bool:
    """Used by the completeness KPI; kept next to the field definition."""
    return all(
        getattr(asset, field_name) not in (None, "") for field_name in MANDATORY_ASSET_FIELDS
    )
