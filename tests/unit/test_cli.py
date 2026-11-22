from __future__ import annotations

import json

from mxbess.cli import main


def _seed(tmp_path):
    out = tmp_path / "build"
    assert main(["seed", "--out", str(out), "--as-of", "2026-11-01"]) == 0
    return out


def test_seed_writes_dataset_manifest_and_csv(tmp_path):
    out = _seed(tmp_path)
    assert (out / "dataset.json").is_file()
    assert (out / "defects_manifest.json").is_file()
    assert (out / "csv" / "assets.csv").is_file()
    assert (out / "maximo-import" / "assets.csv").is_file()
    manifest = json.loads((out / "defects_manifest.json").read_text(encoding="utf-8"))
    assert manifest["total_findings"] == 44


def test_seed_clean_has_no_manifest(tmp_path):
    out = tmp_path / "build"
    assert main(["seed", "--clean", "--out", str(out), "--as-of", "2026-11-01"]) == 0
    assert not (out / "defects_manifest.json").exists()


def test_check_verifies_manifest(tmp_path):
    out = _seed(tmp_path)
    exit_code = main(
        [
            "check",
            "--data",
            str(out / "dataset.json"),
            "--out",
            str(out),
            "--verify",
            str(out / "defects_manifest.json"),
            "--env-file",
            str(tmp_path / "missing.env"),
        ]
    )
    assert exit_code == 0
    findings = json.loads((out / "findings.json").read_text(encoding="utf-8"))
    assert len(findings) == 44
    assert (out / "findings.csv").is_file()


def test_check_returns_one_on_manifest_mismatch(tmp_path):
    out = _seed(tmp_path)
    manifest = json.loads((out / "defects_manifest.json").read_text(encoding="utf-8"))
    manifest["defects"].append({"code": "A01", "record_id": "DOES-NOT-EXIST"})
    bad_manifest = tmp_path / "bad_manifest.json"
    bad_manifest.write_text(json.dumps(manifest), encoding="utf-8")
    exit_code = main(
        [
            "check",
            "--data",
            str(out / "dataset.json"),
            "--out",
            str(out),
            "--verify",
            str(bad_manifest),
            "--env-file",
            str(tmp_path / "missing.env"),
        ]
    )
    assert exit_code == 1


def test_check_on_maximo_import_csv_export(tmp_path):
    out = _seed(tmp_path)
    exit_code = main(
        [
            "check",
            "--csv-dir",
            str(out / "maximo-import"),
            "--out",
            str(out),
            "--verify",
            str(out / "defects_manifest.json"),
            "--as-of",
            "2026-11-01",
            "--env-file",
            str(tmp_path / "missing.env"),
        ]
    )
    assert exit_code == 0
    findings = json.loads((out / "findings.json").read_text(encoding="utf-8"))
    assert len(findings) == 44


def test_report_writes_workbook(tmp_path):
    out = _seed(tmp_path)
    assert (
        main(
            [
                "report",
                "--data",
                str(out / "dataset.json"),
                "--out",
                str(out),
                "--output",
                str(out / "report.xlsx"),
                "--env-file",
                str(tmp_path / "missing.env"),
            ]
        )
        == 0
    )
    assert (out / "report.xlsx").is_file()


def test_all_offline_runs_end_to_end(tmp_path):
    out = tmp_path / "build"
    assert (
        main(
            [
                "all",
                "--target",
                "offline",
                "--out",
                str(out),
                "--as-of",
                "2026-11-01",
                "--env-file",
                str(tmp_path / "missing.env"),
            ]
        )
        == 0
    )
    assert (out / "report.xlsx").is_file()
    assert (out / "findings.json").is_file()


def test_all_file_mode_runs_checks_from_export_csv(tmp_path):
    out = tmp_path / "build"
    assert (
        main(
            [
                "all",
                "--target",
                "file",
                "--out",
                str(out),
                "--as-of",
                "2026-11-01",
                "--env-file",
                str(tmp_path / "missing.env"),
            ]
        )
        == 0
    )
    assert (out / "maximo-import" / "README.txt").is_file()
    findings = json.loads((out / "findings.json").read_text(encoding="utf-8"))
    assert len(findings) == 44
    assert (out / "report.xlsx").is_file()


def test_load_to_fixture_and_csv(tmp_path):
    out = _seed(tmp_path)
    assert (
        main(
            [
                "load",
                "--data",
                str(out / "dataset.json"),
                "--target",
                "fixture",
                "--out",
                str(out),
            ]
        )
        == 0
    )
    load_report = json.loads((out / "load_report.json").read_text(encoding="utf-8"))
    assert load_report["ok"]
    assert load_report["totals"]["created"] > 0

    csv_dir = tmp_path / "loaded-csv"
    assert (
        main(
            [
                "load",
                "--data",
                str(out / "dataset.json"),
                "--target",
                "csv",
                "--csv-dir",
                str(csv_dir),
                "--out",
                str(out),
            ]
        )
        == 0
    )
    assert (csv_dir / "assets.csv").is_file()


def test_api_commands_refuse_when_live_is_disabled(tmp_path, monkeypatch):
    for name in (
        "MAXIMO_HOST",
        "MAXIMO_APIKEY",
        "MAXIMO_LIVE_ENABLED",
        "MAXIMO_SITE_ID",
        "MAXIMO_ORG_ID",
    ):
        monkeypatch.delenv(name, raising=False)
    out = _seed(tmp_path)
    exit_code = main(
        [
            "check",
            "--api",
            "--out",
            str(out),
            "--env-file",
            str(tmp_path / "missing.env"),
        ]
    )
    assert exit_code == 2
