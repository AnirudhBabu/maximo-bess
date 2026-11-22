"""Command line: ``mxbess seed|load|check|report|all``."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

from . import __version__, kpis, report
from .checks import Finding, Severity, run_checks
from .client import MaximoClient
from .config import ConfigError, Settings, load_settings
from .loader import LoadReport, load_dataset
from .models import Dataset
from .repository import (
    ApiRepository,
    CsvRepository,
    FixtureRepository,
    Repository,
    WritableRepository,
    save_dataset_csv,
    save_maximo_import_csv,
)
from .seed.defects import build_manifest, inject_defects
from .seed.generate import DEFAULT_SEED, generate_site
from .verify import ManifestVerification, verify_manifest

DEFAULT_OUT = Path("build")
DATASET_FILE = "dataset.json"
MANIFEST_FILE = "defects_manifest.json"
FINDINGS_FILE = "findings.json"
REPORT_FILE = "report.xlsx"
LOAD_REPORT_FILE = "load_report.json"


# --------------------------------------------------------------------- helpers
def _parse_date(raw: str) -> dt.date:
    try:
        return dt.date.fromisoformat(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"expected YYYY-MM-DD, got {raw!r}") from exc


def _load_dataset(path: Path) -> Dataset:
    return Dataset.model_validate_json(path.read_text(encoding="utf-8"))


def _save_dataset(dataset: Dataset, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dataset.model_dump_json(indent=2), encoding="utf-8")


def _save_findings(findings: list[Finding], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [finding.as_dict() for finding in findings]
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    with path.with_suffix(".csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["code", "severity", "record_type", "record_id", "message", "details"])
        for finding in findings:
            writer.writerow(
                [
                    finding.code,
                    finding.severity.value,
                    finding.record_type,
                    finding.record_id,
                    finding.message,
                    json.dumps(finding.details, sort_keys=True),
                ]
            )


def _load_findings(path: Path) -> list[Finding]:
    records = json.loads(path.read_text(encoding="utf-8"))
    return [
        Finding(
            code=record["code"],
            severity=Severity(record["severity"]),
            record_type=record["record_type"],
            record_id=record["record_id"],
            message=record["message"],
            details=record.get("details") or {},
        )
        for record in records
    ]


def _settings(args: argparse.Namespace) -> Settings:
    env_file = Path(args.env_file) if getattr(args, "env_file", None) else Path(".env")
    return load_settings(dotenv_path=env_file)


def _repository_from_args(args: argparse.Namespace, settings: Settings) -> Repository:
    if getattr(args, "api", False):
        settings.require_live()
        client = MaximoClient(
            settings.api_root,
            settings.api_key.get_secret_value() if settings.api_key else "",
            timeout=settings.timeout_seconds,
            max_retries=settings.max_retries,
            page_size=settings.page_size,
        )
        return ApiRepository(
            client,
            site_id=settings.site_id,
            org_id=settings.org_id,
            as_of=args.as_of,
        )
    csv_dir = getattr(args, "csv_dir", None)
    if csv_dir:
        return CsvRepository(
            Path(csv_dir),
            site_id=settings.site_id,
            org_id=settings.org_id,
            as_of=getattr(args, "as_of", None),
        )
    data_path = Path(getattr(args, "data", None) or DEFAULT_OUT / DATASET_FILE)
    return FixtureRepository(_load_dataset(data_path))


def _writable_repository(args: argparse.Namespace, settings: Settings) -> WritableRepository:
    target = args.target
    if target == "api":
        settings.require_live()
        client = MaximoClient(
            settings.api_root,
            settings.api_key.get_secret_value() if settings.api_key else "",
            timeout=settings.timeout_seconds,
            max_retries=settings.max_retries,
            page_size=settings.page_size,
        )
        return ApiRepository(
            client,
            site_id=settings.site_id,
            org_id=settings.org_id,
            as_of=args.as_of,
        )
    if target == "csv":
        return CsvRepository(Path(args.csv_dir))
    # A fixture load is an in-memory dry run: start empty so created counts are
    # meaningful, but keep the snapshot metadata (site/org/as-of/seed).
    if getattr(args, "data", None):
        source = _load_dataset(Path(args.data))
        base = Dataset(
            site_id=source.site_id,
            org_id=source.org_id,
            seed=source.seed,
            as_of=source.as_of,
        )
    else:
        base = generate_site(as_of=args.as_of)
    return FixtureRepository(base)


def _print_findings_summary(findings: list[Finding]) -> None:
    severity = kpis.findings_by_severity(findings)
    print(
        f"Findings: {len(findings)} total "
        f"({severity['HIGH']} HIGH, {severity['MEDIUM']} MEDIUM, {severity['LOW']} LOW)"
    )
    for code, count in kpis.findings_by_code(findings).items():
        print(f"  {code}: {count}")


def _print_verification(verification: ManifestVerification) -> None:
    print("Manifest verification: " + verification.summary())
    if verification.missing:
        print("  Missing findings:")
        for item in verification.missing:
            print(f"    {item['code']} {item['record_id']} x{item['count']}")
    if verification.unexpected:
        print("  Unexpected findings (false positives):")
        for item in verification.unexpected:
            print(f"    {item['code']} {item['record_id']} x{item['count']}")


# -------------------------------------------------------------------- commands
def cmd_seed(args: argparse.Namespace) -> int:
    out = Path(args.out)
    dataset = generate_site(seed=args.seed, as_of=args.as_of)
    manifest = None
    if not args.clean:
        dataset, defects = inject_defects(dataset)
        manifest = build_manifest(dataset, defects)
    _save_dataset(dataset, out / DATASET_FILE)
    if manifest is not None:
        (out / MANIFEST_FILE).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    save_dataset_csv(dataset, out / "csv")
    save_maximo_import_csv(dataset, out / "maximo-import")
    print(
        f"Seeded {dataset.site_id} as of {dataset.as_of}: "
        f"{len(dataset.locations)} locations, {len(dataset.assets)} assets, "
        f"{len(dataset.jobplans)} job plans, {len(dataset.pms)} PMs, "
        f"{len(dataset.workorders)} work orders."
    )
    if manifest is not None:
        print(
            f"Injected {manifest['total_findings']} known defects: "
            + ", ".join(f"{code}={count}" for code, count in manifest["counts"].items())
        )
        print(f"Wrote {out / MANIFEST_FILE}")
    print(f"Wrote {out / DATASET_FILE}, {out / 'csv'} and {out / 'maximo-import'}")
    return 0


def cmd_load(args: argparse.Namespace) -> int:
    settings = _settings(args)
    data_path = Path(args.data)
    dataset = _load_dataset(data_path)
    try:
        repository = _writable_repository(args, settings)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    result = load_dataset(dataset, repository)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / LOAD_REPORT_FILE).write_text(json.dumps(result.as_dict(), indent=2), encoding="utf-8")
    _print_load_report(result)
    return 0 if result.ok else 1


def _print_load_report(result: LoadReport) -> None:
    totals = result.as_dict()["totals"]
    print(
        f"Load complete: {totals['created']} created, {totals['updated']} updated, "
        f"{totals['unchanged']} unchanged, {totals['failed']} failed."
    )
    for kind, counts in result.counts.items():
        if sum(vars(counts).values()) == 0:
            continue
        print(
            f"  {kind:10s} created={counts.created} updated={counts.updated} "
            f"unchanged={counts.unchanged} failed={counts.failed}"
        )
    if result.failures:
        print("Failures (re-run to resume; natural-key upserts make this safe):")
        for failure in result.failures[:20]:
            print(f"  {failure.kind} {failure.key}: {failure.error}")


def cmd_check(args: argparse.Namespace) -> int:
    settings = _settings(args)
    try:
        repository = _repository_from_args(args, settings)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    findings = run_checks(repository)
    out = Path(args.out)
    findings_path = out / FINDINGS_FILE
    _save_findings(findings, findings_path)
    _print_findings_summary(findings)
    print(f"Wrote {findings_path} and {findings_path.with_suffix('.csv')}")

    exit_code = 0
    if args.verify:
        manifest_path = Path(args.verify)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        verification = verify_manifest(findings, manifest)
        _print_verification(verification)
        if not verification.exact:
            exit_code = 1
    return exit_code


def cmd_report(args: argparse.Namespace) -> int:
    settings = _settings(args)
    try:
        repository = _repository_from_args(args, settings)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    dataset = repository.dataset()
    findings_path = Path(args.findings) if args.findings else None
    if findings_path and findings_path.is_file():
        findings = _load_findings(findings_path)
    else:
        findings = run_checks(repository)
    output = Path(args.output)
    report.write_report(dataset, findings, output)
    print(f"Wrote {output} ({len(findings)} findings, {len(dataset.assets)} assets)")
    return 0


def cmd_all(args: argparse.Namespace) -> int:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    dataset = generate_site(seed=args.seed, as_of=args.as_of)
    manifest: dict[str, Any] | None = None
    if not args.clean:
        dataset, defects = inject_defects(dataset)
        manifest = build_manifest(dataset, defects)
        (out / MANIFEST_FILE).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    _save_dataset(dataset, out / DATASET_FILE)
    save_dataset_csv(dataset, out / "csv")
    save_maximo_import_csv(dataset, out / "maximo-import")
    print(
        f"Seeded {len(dataset.assets)} assets, {len(dataset.pms)} PMs, "
        f"{len(dataset.workorders)} work orders."
    )

    settings = _settings(args)
    if args.target == "api":
        try:
            writable = _writable_repository(args, settings)
        except ConfigError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        result = load_dataset(dataset, writable)
        (out / LOAD_REPORT_FILE).write_text(
            json.dumps(result.as_dict(), indent=2), encoding="utf-8"
        )
        _print_load_report(result)
        repository: Repository = writable  # type: ignore[assignment]
        dataset = repository.dataset()
        if not result.ok:
            print("warning: some records failed to load; reporting live state anyway")
    elif args.target == "file":
        # File mode: read the generated Maximo-format CSVs back through the
        # repository, exactly as the checker would read UI exports.
        # (The `csv` snapshot is also available; it preserves local metadata.)
        repository = CsvRepository(
            out / "maximo-import",
            site_id=dataset.site_id,
            org_id=dataset.org_id,
            as_of=dataset.as_of,
            seed=dataset.seed,
        )
        dataset = repository.dataset()
        print(
            "File mode: import build/maximo-import/*.csv via Maximo Data Import "
            "in order locations -> assets -> jobplans -> pms -> workorders."
        )
    else:
        repository = FixtureRepository(dataset)

    findings = run_checks(repository)
    _save_findings(findings, out / FINDINGS_FILE)
    _print_findings_summary(findings)
    exit_code = 0
    if manifest is not None:
        verification = verify_manifest(findings, manifest)
        _print_verification(verification)
        if not verification.exact:
            exit_code = 1
    report_path = out / REPORT_FILE if args.target != "api" else out / "report_live.xlsx"
    report.write_report(dataset, findings, report_path)
    print(f"Wrote {report_path}")
    return exit_code


# ----------------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mxbess",
        description="Maximo BESS data-quality, load and reporting toolkit.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_common(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("--env-file", default=".env", help="path to .env (default: .env)")
        sub.add_argument("--as-of", type=_parse_date, default=None, help="reporting date")

    seed_parser = subparsers.add_parser("seed", help="generate the synthetic site")
    seed_parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    seed_parser.add_argument(
        "--as-of",
        type=_parse_date,
        default=None,
        help="reporting anchor date (default: today; use 2026-11-01 for the sample)",
    )
    seed_parser.add_argument("--out", default=str(DEFAULT_OUT))
    seed_parser.add_argument(
        "--clean", action="store_true", help="do not inject the known defect set"
    )
    seed_parser.set_defaults(func=cmd_seed)

    load_parser = subparsers.add_parser("load", help="idempotently load a dataset")
    add_common(load_parser)
    load_parser.add_argument("--data", default=str(DEFAULT_OUT / DATASET_FILE))
    load_parser.add_argument("--target", choices=("fixture", "csv", "api"), default="fixture")
    load_parser.add_argument("--csv-dir", default=str(DEFAULT_OUT / "csv"))
    load_parser.add_argument("--out", default=str(DEFAULT_OUT))
    load_parser.set_defaults(func=cmd_load)

    for name, function, help_text in (
        ("check", cmd_check, "run the 14 data-quality checks"),
        ("report", cmd_report, "write the Excel report"),
    ):
        sub = subparsers.add_parser(name, help=help_text)
        add_common(sub)
        sub.add_argument("--data", default=str(DEFAULT_OUT / DATASET_FILE))
        sub.add_argument("--csv-dir", default=None)
        sub.add_argument("--api", action="store_true", help="read from Maximo (Phase 6)")
        sub.add_argument("--out", default=str(DEFAULT_OUT))
        if name == "check":
            sub.add_argument("--verify", default=None, help="compare findings to a manifest")
        else:
            sub.add_argument("--findings", default=str(DEFAULT_OUT / FINDINGS_FILE))
            sub.add_argument("--output", default=str(DEFAULT_OUT / REPORT_FILE))
        sub.set_defaults(func=function)

    all_parser = subparsers.add_parser("all", help="seed, optionally load, check and report")
    add_common(all_parser)
    all_parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    all_parser.add_argument("--out", default=str(DEFAULT_OUT))
    all_parser.add_argument(
        "--target",
        choices=("offline", "file", "api"),
        default="file",
        help=(
            "offline uses the in-memory fixture; file reads the export CSVs; api needs live access"
        ),
    )
    all_parser.add_argument("--clean", action="store_true")
    all_parser.set_defaults(func=cmd_all)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "as_of", None) is None:
        args.as_of = dt.date.today()
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
