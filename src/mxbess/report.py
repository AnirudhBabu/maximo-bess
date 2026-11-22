"""Excel status report.

Five sheets, matching the brief: Summary, Findings, PM_Compliance, Backlog,
Asset_Completeness.  Tables are formatted for a non-technical maintenance
manager: frozen header, sensible widths, dates and percentages formatted.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from . import kpis
from .checks import Finding
from .models import OPEN_WO_STATUSES, Dataset

SHEET_NAMES = ("Summary", "Findings", "PM_Compliance", "Backlog", "Asset_Completeness")

_HEADER_FILL = PatternFill("solid", fgColor="1F3864")
_HEADER_FONT = Font(bold=True, color="FFFFFF")
_TITLE_FONT = Font(bold=True, size=14, color="1F3864")
_SECTION_FONT = Font(bold=True, size=11, color="1F3864")
_THIN = Side(style="thin", color="BFBFBF")
_BORDER = Border(bottom=_THIN)
_DATE_FORMAT = "yyyy-mm-dd"


def summary_metrics(dataset: Dataset, findings: list[Finding]) -> list[tuple[str, Any]]:
    """Summary rows, exposed so tests can assert the workbook ties to the KPIs."""
    compliance = kpis.pm_compliance(dataset)
    ageing = kpis.backlog_ageing(dataset)
    ratio = kpis.corrective_vs_preventive(dataset)
    severity = kpis.findings_by_severity(findings)
    return [
        ("Assets", len(dataset.assets)),
        ("Locations", len(dataset.locations)),
        ("Job plans", len(dataset.jobplans)),
        ("PM plans", len(dataset.pms)),
        ("Work orders", len(dataset.workorders)),
        ("PM compliance %", compliance.compliance_pct),
        ("PM WOs due", compliance.due),
        ("PM WOs completed", compliance.completed),
        ("PM WOs on time", compliance.on_time),
        ("PM WOs open overdue", compliance.open_overdue),
        ("Open backlog", len(kpis.open_backlog(dataset))),
        ("Backlog 0-30 days", ageing["0-30"]),
        ("Backlog 31-90 days", ageing["31-90"]),
        ("Backlog 90+ days", ageing["90+"]),
        ("Corrective work orders", ratio.corrective),
        ("Preventive work orders", ratio.preventive),
        ("Corrective:preventive ratio", ratio.corrective_per_preventive),
        ("Findings total", len(findings)),
        ("Findings HIGH", severity["HIGH"]),
        ("Findings MEDIUM", severity["MEDIUM"]),
        ("Findings LOW", severity["LOW"]),
    ]


def _style_header(ws: Worksheet, row: int, columns: int) -> None:
    for column in range(1, columns + 1):
        cell = ws.cell(row=row, column=column)
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT
        cell.alignment = Alignment(vertical="center", wrap_text=True)
        cell.border = _BORDER


def _autosize(ws: Worksheet, min_width: int = 10, max_width: int = 60) -> None:
    for column_cells in ws.columns:
        letter = get_column_letter(column_cells[0].column)
        longest = max(
            (len(str(cell.value)) for cell in column_cells if cell.value is not None),
            default=0,
        )
        ws.column_dimensions[letter].width = max(min_width, min(max_width, longest + 2))


def _write_table(
    ws: Worksheet,
    headers: list[str],
    rows: list[list[Any]],
    *,
    date_columns: set[int] | None = None,
    number_columns: set[int] | None = None,
    percent_columns: set[int] | None = None,
    autofilter: bool = True,
    freeze: str = "A2",
) -> None:
    ws.append(headers)
    _style_header(ws, 1, len(headers))
    for row in rows:
        ws.append(row)
    date_columns = date_columns or set()
    number_columns = number_columns or set()
    percent_columns = percent_columns or set()
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row):
        for column_index, cell in enumerate(row, start=1):
            if column_index in date_columns and isinstance(cell.value, (dt.date, dt.datetime)):
                cell.number_format = _DATE_FORMAT
            elif column_index in percent_columns:
                cell.number_format = "0.0"
            elif column_index in number_columns:
                cell.number_format = "0"
            cell.alignment = Alignment(vertical="top", wrap_text=column_index >= 5)
    if autofilter and ws.max_row >= 1:
        ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{ws.max_row}"
    ws.freeze_panes = freeze
    _autosize(ws)


def _summary_sheet(ws: Worksheet, dataset: Dataset, findings: list[Finding]) -> None:
    ws["A1"] = "BESS maintenance status and data-quality report"
    ws["A1"].font = _TITLE_FONT
    ws.merge_cells("A1:C1")

    metadata = [
        ("Site", dataset.site_id),
        ("As of", dataset.as_of),
        ("Seed", dataset.seed),
    ]
    for offset, (label, value) in enumerate(metadata, start=3):
        ws.cell(row=offset, column=1, value=label).font = Font(bold=True)
        cell = ws.cell(row=offset, column=2, value=value)
        if isinstance(value, dt.date):
            cell.number_format = _DATE_FORMAT

    row = 3 + len(metadata) + 1
    ws.cell(row=row, column=1, value="Maintenance KPIs").font = _SECTION_FONT
    row += 1
    header_row = row
    ws.cell(row=row, column=1, value="Metric")
    ws.cell(row=row, column=2, value="Value")
    _style_header(ws, row, 2)
    row += 1
    for label, value in summary_metrics(dataset, findings):
        ws.cell(row=row, column=1, value=label)
        cell = ws.cell(row=row, column=2, value=value)
        if label.endswith("%") and isinstance(value, (int, float)):
            cell.number_format = "0.0"
        elif isinstance(value, float):
            cell.number_format = "0.00"
        elif isinstance(value, int):
            cell.number_format = "0"
        row += 1

    row += 1
    ws.cell(row=row, column=1, value="Findings by severity").font = _SECTION_FONT
    row += 1
    ws.cell(row=row, column=1, value="Severity")
    ws.cell(row=row, column=2, value="Count")
    _style_header(ws, row, 2)
    row += 1
    for severity, count in kpis.findings_by_severity(findings).items():
        ws.cell(row=row, column=1, value=severity)
        ws.cell(row=row, column=2, value=count).number_format = "0"
        row += 1

    row += 1
    ws.cell(row=row, column=1, value="Findings by check code").font = _SECTION_FONT
    row += 1
    ws.cell(row=row, column=1, value="Check")
    ws.cell(row=row, column=2, value="Count")
    _style_header(ws, row, 2)
    row += 1
    for code, count in kpis.findings_by_code(findings).items():
        ws.cell(row=row, column=1, value=code)
        ws.cell(row=row, column=2, value=count).number_format = "0"
        row += 1

    ws.column_dimensions["A"].width = 32
    ws.column_dimensions["B"].width = 18
    ws.column_dimensions["C"].width = 18
    ws.freeze_panes = f"A{header_row + 1}"


def _findings_sheet(ws: Worksheet, findings: list[Finding]) -> None:
    headers = ["Code", "Severity", "Record type", "Record ID", "Message", "Details"]
    rows = [
        [
            finding.code,
            finding.severity.value,
            finding.record_type,
            finding.record_id,
            finding.message,
            json.dumps(finding.details, sort_keys=True) if finding.details else "",
        ]
        for finding in findings
    ]
    if not rows:
        rows = [["", "", "", "", "No findings - all checks passed", ""]]
    _write_table(ws, headers, rows)


def _pm_compliance_sheet(ws: Worksheet, dataset: Dataset) -> None:
    open_pm_nums = {
        wo.pm_num for wo in dataset.workorders if wo.pm_num and wo.status in OPEN_WO_STATUSES
    }
    headers = [
        "PM",
        "Description",
        "Asset",
        "Location",
        "Job plan",
        "Frequency (days)",
        "Last done",
        "Next due",
        "Days overdue",
        "Status",
        "Safety critical",
        "Open WO?",
    ]
    rows = []
    for pm in sorted(dataset.pms, key=lambda item: item.pm_num):
        overdue = 0
        if pm.next_due is not None and pm.next_due < dataset.as_of:
            overdue = (dataset.as_of - pm.next_due).days
        rows.append(
            [
                pm.pm_num,
                pm.description,
                pm.asset_num or "",
                pm.location or "",
                pm.jobplan_num or "",
                pm.frequency_days,
                pm.last_done,
                pm.next_due,
                overdue,
                pm.status,
                "Yes" if pm.safety_critical else "No",
                "Yes" if pm.pm_num in open_pm_nums else "No",
            ]
        )
    _write_table(
        ws,
        headers,
        rows,
        date_columns={7, 8},
        number_columns={6, 9},
    )


def _backlog_sheet(ws: Worksheet, dataset: Dataset) -> None:
    headers = [
        "WO",
        "Description",
        "Status",
        "Work type",
        "Asset",
        "Location",
        "Reported",
        "Age (days)",
        "Bucket",
        "Priority",
    ]
    rows = []
    for wo in sorted(kpis.open_backlog(dataset), key=lambda item: item.reported_date):
        age = max((dataset.as_of - wo.reported_date).days, 0)
        bucket = "0-30" if age <= 30 else ("31-90" if age <= 90 else "90+")
        rows.append(
            [
                wo.wonum,
                wo.description,
                wo.status,
                wo.work_type,
                wo.asset_num or "",
                wo.location or "",
                wo.reported_date,
                age,
                bucket,
                wo.priority,
            ]
        )
    if not rows:
        rows = [["", "No open work orders", "", "", "", "", None, 0, "", ""]]
    _write_table(
        ws,
        headers,
        rows,
        date_columns={7},
        number_columns={8, 10},
    )


def _completeness_sheet(ws: Worksheet, dataset: Dataset) -> None:
    headers = ["Asset type", "Field", "Populated", "Total", "Percent complete"]
    rows = [
        [row.asset_type, row.field, row.populated, row.total, row.percent]
        for row in kpis.asset_completeness(dataset)
    ]
    _write_table(
        ws,
        headers,
        rows,
        number_columns={3, 4},
        percent_columns={5},
    )


def write_report(
    dataset: Dataset,
    findings: list[Finding],
    path: str | Path,
) -> Path:
    """Write the workbook and return its path."""
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)

    workbook = Workbook()
    summary = workbook.active
    summary.title = "Summary"
    findings_sheet = workbook.create_sheet("Findings")
    pm_sheet = workbook.create_sheet("PM_Compliance")
    backlog_sheet = workbook.create_sheet("Backlog")
    completeness_sheet = workbook.create_sheet("Asset_Completeness")

    _summary_sheet(summary, dataset, findings)
    _findings_sheet(findings_sheet, findings)
    _pm_compliance_sheet(pm_sheet, dataset)
    _backlog_sheet(backlog_sheet, dataset)
    _completeness_sheet(completeness_sheet, dataset)

    workbook.properties.title = "BESS maintenance status and data-quality report"
    workbook.properties.creator = "mxbess"
    workbook.save(output)
    return output
