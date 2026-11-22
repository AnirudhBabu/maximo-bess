from __future__ import annotations

import datetime as dt

from openpyxl import load_workbook

from mxbess.checks import run_checks
from mxbess.report import SHEET_NAMES, summary_metrics, write_report
from mxbess.repository import FixtureRepository
from tests.support import tiny_dataset


def _dirty_dataset():
    dataset = tiny_dataset()
    dataset.assets[4].location = None
    dataset.workorders[0].asset_num = None
    return dataset


def _summary_values(worksheet):
    values = {}
    for row in worksheet.iter_rows(min_row=1, max_row=worksheet.max_row, max_col=2):
        label, value = row[0].value, row[1].value
        if label:
            values[str(label)] = value
    return values


def test_workbook_has_required_sheets_and_headers(tmp_path):
    dataset = _dirty_dataset()
    findings = run_checks(FixtureRepository(dataset))
    path = write_report(dataset, findings, tmp_path / "report.xlsx")
    workbook = load_workbook(path)

    assert tuple(workbook.sheetnames) == SHEET_NAMES
    expected_headers = {
        "Findings": ["Code", "Severity", "Record type", "Record ID", "Message", "Details"],
        "PM_Compliance": [
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
        ],
        "Backlog": [
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
        ],
        "Asset_Completeness": [
            "Asset type",
            "Field",
            "Populated",
            "Total",
            "Percent complete",
        ],
    }
    for sheet, headers in expected_headers.items():
        worksheet = workbook[sheet]
        assert [cell.value for cell in worksheet[1]] == headers
        assert worksheet.freeze_panes == "A2"
        assert worksheet.max_row > 1  # no empty sheet
    assert workbook["Findings"].auto_filter.ref is not None


def test_summary_ties_to_kpis(tmp_path):
    dataset = _dirty_dataset()
    findings = run_checks(FixtureRepository(dataset))
    path = write_report(dataset, findings, tmp_path / "report.xlsx")
    workbook = load_workbook(path, data_only=True)
    values = _summary_values(workbook["Summary"])

    for label, value in summary_metrics(dataset, findings):
        assert values[label] == value, label
    assert values["Assets"] == 8
    assert values["PM compliance %"] == 100.0
    assert values["Findings total"] == 2
    assert values["Findings HIGH"] == 0


def test_findings_sheet_contents_and_order(tmp_path):
    dataset = _dirty_dataset()
    dataset.pms[0].frequency_days = None
    findings = run_checks(FixtureRepository(dataset))
    path = write_report(dataset, findings, tmp_path / "report.xlsx")
    worksheet = load_workbook(path)["Findings"]
    rows = list(worksheet.iter_rows(min_row=2, values_only=True))
    assert [row[0] for row in rows] == ["A01", "P02", "W01"]
    assert rows[0][1] == "MEDIUM"
    assert rows[1][1] == "HIGH"


def test_empty_findings_still_produces_a_readable_sheet(tmp_path):
    dataset = tiny_dataset()
    findings = run_checks(FixtureRepository(dataset))
    assert findings == []
    path = write_report(dataset, findings, tmp_path / "report.xlsx")
    worksheet = load_workbook(path)["Findings"]
    assert worksheet.max_row == 2
    assert "No findings" in str(worksheet["E2"].value)


def test_backlog_sheet_sorted_oldest_first(tmp_path):
    from tests.support import AS_OF, workorder

    dataset = tiny_dataset()
    dataset.workorders = [
        workorder(
            "WO-NEW", status="APPR", reported_date=AS_OF, actual_start=None, actual_finish=None
        ),
        workorder(
            "WO-OLD",
            status="APPR",
            reported_date=AS_OF - dt.timedelta(days=100),
            actual_start=None,
            actual_finish=None,
        ),
    ]
    path = write_report(dataset, [], tmp_path / "report.xlsx")
    worksheet = load_workbook(path)["Backlog"]
    assert worksheet["A2"].value == "WO-OLD"
    assert worksheet["A3"].value == "WO-NEW"
    assert worksheet["I2"].value == "90+"
