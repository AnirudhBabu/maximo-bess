from __future__ import annotations

from collections import Counter

from mxbess.checks import run_checks
from mxbess.repository import FixtureRepository
from mxbess.seed.defects import build_manifest, inject_defects
from mxbess.seed.generate import REFERENCE_AS_OF, generate_site
from mxbess.verify import verify_manifest


def _bundle():
    clean = generate_site(seed=99, as_of=REFERENCE_AS_OF)
    dirty, defects = inject_defects(clean)
    return clean, dirty, build_manifest(dirty, defects)


def test_dirty_findings_exactly_match_manifest():
    _clean, dirty, manifest = _bundle()
    findings = run_checks(FixtureRepository(dirty))
    expected = Counter((defect["code"], defect["record_id"]) for defect in manifest["defects"])
    actual = Counter((finding.code, finding.record_id) for finding in findings)
    assert actual == expected
    assert len(findings) == manifest["total_findings"] == 44


def test_clean_findings_are_zero():
    clean, _dirty, _manifest = _bundle()
    assert run_checks(FixtureRepository(clean)) == []


def test_verification_reports_perfect_recall_and_precision():
    _clean, dirty, manifest = _bundle()
    verification = verify_manifest(run_checks(FixtureRepository(dirty)), manifest)
    assert verification.exact
    assert verification.recall == 1.0
    assert verification.precision == 1.0
    assert verification.missing == []
    assert verification.unexpected == []


def test_verification_detects_false_positives():
    clean, _dirty, manifest = _bundle()
    verification = verify_manifest(run_checks(FixtureRepository(clean)), manifest)
    assert not verification.exact
    assert verification.recall == 0.0
    assert verification.false_positive_count == 0
    assert len(verification.missing) > 0
