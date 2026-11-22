from __future__ import annotations

from mxbess.checks import make_finding
from mxbess.verify import verify_manifest


def _manifest(*entries):
    return {"defects": [{"code": code, "record_id": record_id} for code, record_id in entries]}


def test_exact_match():
    findings = [make_finding("A01", "asset", "A", "x"), make_finding("W02", "workorder", "W", "x")]
    verification = verify_manifest(findings, _manifest(("A01", "A"), ("W02", "W")))
    assert verification.exact
    assert verification.recall == 1.0
    assert verification.precision == 1.0
    assert verification.summary().startswith("expected 2, found 2, matched 2")


def test_missing_and_unexpected_are_counted():
    findings = [
        make_finding("A01", "asset", "A", "x"),
        make_finding("W02", "workorder", "OTHER", "x"),
        make_finding("W02", "workorder", "OTHER", "x"),
    ]
    verification = verify_manifest(findings, _manifest(("A01", "A"), ("P01", "P")))
    assert not verification.exact
    assert verification.missing == [{"code": "P01", "record_id": "P", "count": 1}]
    assert verification.unexpected == [{"code": "W02", "record_id": "OTHER", "count": 2}]
    assert verification.false_positive_count == 2  # two unexpected findings
    assert verification.recall == 0.5


def test_duplicate_expected_entries_are_counted():
    findings = [make_finding("A03", "asset", "A", "x")]
    verification = verify_manifest(findings, _manifest(("A03", "A"), ("A03", "A")))
    assert verification.missing == [{"code": "A03", "record_id": "A", "count": 1}]


def test_empty_inputs_are_perfect():
    verification = verify_manifest([], _manifest())
    assert verification.exact
    assert verification.recall == 1.0
    assert verification.precision == 1.0
