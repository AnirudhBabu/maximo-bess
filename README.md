# Maximo BESS data-quality and maintenance reporting

**A self-directed project by Anirudh Babu**

I built this to practise the data and reporting side of a functional Maximo role at a
battery energy storage (BESS) site: keeping the asset register clean, keeping preventive
maintenance schedulable, controlling the work-order backlog, and turning the result into a
report a maintenance manager can actually use.

It generates a realistic synthetic site, plants a known set of data defects, finds them
with 14 automated checks, and produces a formatted Excel workbook. Because I could not get
access to a live Maximo instance, the verified path is **file mode**: Maximo Data Import
CSVs in, checks and report out. The REST client and loader are implemented and tested
against a mock only — I do not claim live Maximo API experience.

---

## Results at a glance

| Area | Result |
|---|---|
| Asset register | 77 locations, **359 assets** across site → block → container → rack → module |
| Preventive maintenance | 14 job plans, 68 PM records, 6 safety-critical PM types |
| Work orders | 203 over the prior 12 months, all six standard statuses, PM and corrective |
| Data quality | 14 checks; **44 planted defects; 100% found, 0 false positives** |
| Reporting | 5-sheet Excel workbook: Summary, Findings, PM Compliance, Backlog, Asset Completeness |
| Engineering | 156 tests collected (152 offline, 4 live placeholders), ~93% coverage, ruff clean |
| Fallback | Maximo-format CSVs plus a runbook for the Data Import application |

The checked-in output is [docs/sample-report.xlsx](docs/sample-report.xlsx); the defect
manifest is reproducible with one command.

## Why I built it

A Maximo functional role is mostly about the data behind the screens: whether an asset has
a location and a parent, whether a PM has a job plan and a next-due date, whether a closed
work order has actual labour, and whether the weekly report reconciles with the system.
Writing another CRUD demo would not show any of that, so I built the dataset, the quality
rules, the work-order history and the report as one coherent maintenance story.

The deliverable I care about is the clean asset/PM/work-order data and the report built from
it; the Python is the means.

## How this maps to the role

| Role duty | Where it shows up in the project |
|---|---|
| Work-order management | 203 WOs through the full lifecycle; W01–W04 checks; backlog and ageing KPIs; Backlog sheet |
| Preventive maintenance | 14 PM plans and job plans; PM compliance, overdue-PM check; PM Compliance sheet |
| Asset records and hierarchy | Five-level hierarchy and a documented numbering convention; A01–A06 checks |
| Data quality | The whole checker, plus per-field completeness and a definition of “complete” |
| Regular reports | The Excel workbook, formatted for a maintenance manager, with filters and number formats |
| Process improvement | [Top five fixes and how to prevent recurrence](docs/recommendations.md) |
| HSE / compliance | Fire detection, fire suppression, DC torque, transformer, switchgear and E-stop PMs flagged safety-critical |
| BESS / energy | PCS, MV transformer, HVAC, BMS, fire systems and battery modules, with realistic inspection types |

## What the site contains

```
BISHA-BESS (site)
└── BB1..BB4 (blocks)
    ├── PCS, MV transformer, HVAC1/2, fire detection,
    │   fire suppression, BMS                     (7 assets per block)
    └── BB1-CT1..CT2 (containers, also assets)
        └── racks RK01..RK08 (locations)
            └── modules MD01..MD05 (assets)
```

359 assets in total: 320 modules, 8 container assets, 28 block equipment, 3 site assets.
Asset numbers follow a documented convention (`BB1-CT2-RK03-MD04`, `BB1-PCS`, `SITE-SCADA`).
The full field dictionary, PM plan table and defect catalogue are in the
[data dictionary](docs/data-dictionary.md).

Work orders mix PM-generated work with corrective faults (`ELEC`, `HVAC`, `FIRE`, `BMS`,
`PCS`, `COMMS`, `MECH`) and carry realistic dates, priorities and labour hours. The dataset
is deterministic for a given seed and as-of date, so every number in this README can be
reproduced.

## Data-quality checks

| Code | Severity | Rule |
|---|---|---|
| A01 | MEDIUM | Asset has no location |
| A02 | MEDIUM | Container/module asset has no parent |
| A03 | HIGH | Duplicate asset number, or duplicate description + location |
| A04 | MEDIUM | Missing manufacturer, serial number, install date or criticality |
| A05 | LOW | Asset number violates its type's naming convention |
| A06 | HIGH | Orphaned parent reference or hierarchy cycle |
| P01 | MEDIUM | PM has no job plan, or references a missing one |
| P02 | HIGH | PM has no frequency or next-due date |
| P03 | HIGH | PM targets a decommissioned or non-operating asset |
| P04 | MEDIUM | PM is overdue with no open work order |
| W01 | MEDIUM | Work order has no asset |
| W02 | HIGH | Closed WO without an actual finish or actual labour |
| W03 | MEDIUM | WO status contradicts its dates (for example a future finish on a closed WO) |
| W04 | LOW | Open WO older than 90 days |

The test I care most about is the two-sided one: **clean data produces zero findings**, and
**dirty data produces exactly the 44 planted defects** — compared as a multiset of
`(code, record id)`, not eyeballed. That catches over-broad rules as well as missed defects.

## KPIs and report

* **PM compliance** = PM work orders completed on time ÷ PM work orders due by the as-of
  date. The report deliberately shows due, completed, on-time and open-overdue counts next
  to it, because a compliance percentage can look healthy while overdue PMs accumulate.
* **Backlog** = waiting-approval, approved and in-progress work orders.
* **Ageing** = 0–30, 31–90 and 90+ days from report date.
* **Corrective:preventive ratio** across all work orders.
* **Asset completeness** = populated ÷ applicable records per mandatory field.

The workbook has a frozen header and autofilter on every table, ISO dates, one-decimal
percentages, and column widths chosen for reading rather than raw export. The Summary page
is generated from the same KPI functions the tests assert, so the numbers cannot drift from
the checks.

## How it works

1. **Generate** a deterministic site from `(seed, as-of)` — hierarchy, PM schedule, work-order
   history.
2. **Inject** a known defect set and write `defects_manifest.json`; this is the ground truth.
3. **Write** two CSV surfaces: an internal snapshot and Maximo-column import files.
4. **Read** the files back through a `Repository` abstraction (fixture, CSV or API — the
   checks know nothing about HTTP or files).
5. **Check and verify** against the manifest, then **report** to Excel.

Design choices I would defend in a review:

- **The manifest is the contract.** Data quality is tested as exact recall/precision, not
  by looking at a spreadsheet and saying it seems better.
- **One mapping module.** Every Maximo object-structure and column name is in
  [`mapping.py`](src/mxbess/mapping.py) and marked UNVERIFIED until an instance confirms it.
  Adapting to a real instance is a one-file change, not a refactor.
- **Repository boundary.** The same checks run on generated data, Maximo-format CSVs and a
  live API without duplication — which is exactly what made the file fallback possible.
- **Natural-key, dependency-ordered upserts.** Loading parents before children and looking
  up before create makes a second run a no-op and a partial failure resumable.
- **Secrets stay out of code.** API key and host come from `.env`/environment, `.env` is
  git-ignored, and the client never logs headers.

## Run it

Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

# file mode: generate Maximo import CSVs, read them back, check, verify, report
mxbess all --target file --out build --as-of 2026-11-01
```

Expected result:

```
Seeded 359 assets, 68 PMs, 203 work orders.
File mode: import build/maximo-import/*.csv via Maximo Data Import in order
locations -> assets -> jobplans -> pms -> workorders.
Findings: 44 total (17 HIGH, 21 MEDIUM, 6 LOW)
Manifest verification: expected 44, found 44, matched 44,
recall 100.0%, precision 100.0%, false positives 0
Wrote build/report.xlsx
```

Outputs: `build/dataset.json`, `build/defects_manifest.json`, `build/csv/`,
`build/maximo-import/` (with a short import README), `build/findings.json`/`.csv`,
`build/report.xlsx`. The fixed seed and `--as-of 2026-11-01` reproduce
[docs/sample-report.xlsx](docs/sample-report.xlsx) exactly.

For manual use in Maximo, import `build/maximo-import/` in the order
`locations → assets → jobplans → pms → workorders`; after export, run the checker and
report with `--csv-dir`.

> On this Windows machine, Application Control blocked the project virtualenv's
> executables, so I ran the tests in WSL (Ubuntu). The commands are the same there.

## Verification and testing

```bash
ruff check .
ruff format --check .
pytest --cov=mxbess --cov-report=term-missing
```

- **156 tests collected**; 152 run offline and 4 live tests skip without an instance.
- **~93% coverage**, above the 85% gate, with `checks/`, `kpis.py` and `loader.py` all
  above it.
- Tests cover: determinism, clean-data zero findings, exact manifest match, every check
  with a clean and a defective record, KPI arithmetic, workbook structure and values,
  client auth/paging/retry/error mapping, loader idempotency, dependency order and partial
  failure recovery.
- CI is defined for Python 3.11–3.13 (`.github/workflows/ci.yml`).

## File mode vs live API — what is actually verified

**Verified:** the generator, the 14 checks, the KPIs, the Excel report, the CSV repository,
Maximo-format import/export round-trip, the client against a stateful mock, and loader
idempotency against that mock.

**Not verified:** anything that needs a real Maximo instance — the auth header, object
structure names, PATCH support, paging response shape, status domains, parent/cycle
validation, `ACTLABHRS`/`LASTCOMPDATE`/problem-code columns. These are isolated in
[`mapping.py`](src/mxbess/mapping.py) and listed in the
[instance notes](docs/instance-notes.md). Live access was unavailable, so I did not start a
trial, and I describe the project as file-mode work, not live API experience.

## Limitations I would raise myself

- **No live run.** File mode runs on CSVs generated by this project; the same repository
  accepts a real Maximo export, but I have not tested it against one.
- **Duplicate asset number (A03)** is checked and unit-tested but not planted: Maximo
  enforces unique ASSETNUM, so that defect cannot exist in a live load. A03 is planted as
  duplicate description + location instead.
- **A06 orphan/cycle** may be rejected by a real API; the manifest marks that risk.
- **Actual labour hours** map to `ACTLABHRS`; Maximo normally derives actual hours from
  LABTRANS. A live run would decide whether to load LABTRANS or adapt W02.
- **Safety-critical** is local reporting metadata (recovered from the safety job-plan codes
  on read, not stored as a Maximo attribute), and job-plan task text is not loaded.
- The PM Compliance sheet is per PM record, not per historical occurrence.

## What I learned / what I would do next

The main lesson is that **definitions are the hard part**. “PM compliance” has at least
three plausible definitions, and the one that looks best can hide a growing overdue queue.
The second is that data quality must be prevented at source: the
[recommendations](docs/recommendations.md) describe the field rules, workflow gates and
weekly review that would stop these defects recurring, rather than cleaning them up
forever.

With live access I would run the Phase 0 checklist, confirm the mapping, import the files,
spot-check at least five report numbers against the UI, approve/close a work order and fix
one defect by hand, then re-run the checker to show that finding disappearing. That manual
walkthrough is the part this repository cannot prove today.

## Repository map and further reading

```
src/mxbess/
  seed/       deterministic site generator and known-defect injector
  checks/     14 checks and the Finding type
  kpis.py     compliance, backlog, ageing, ratios, completeness
  repository.py  fixture / CSV / API repositories
  mapping.py  the single place with Maximo names (UNVERIFIED until confirmed)
  report.py   the Excel workbook
  client.py   REST client (mock-tested)
  loader.py   idempotent, dependency-ordered upserts (mock-tested)
  cli.py      mxbess seed|load|check|report|all
```

* [Data dictionary](docs/data-dictionary.md) — hierarchy, naming, fields, PM plans, defect catalogue, KPI definitions
* [Instance notes](docs/instance-notes.md) — Phase 0 checklist, file-mode runbook, unverified assumptions
* [Recommendations](docs/recommendations.md) — top five data-quality fixes and prevention
* [Learnings](docs/learnings.md) — what this project does and does not prove about Maximo
* [Sample report](docs/sample-report.xlsx) — generated by file mode from the seeded dirty site
* [Screenshots](docs/screenshots/) — placeholder; Maximo UI evidence needs instance access

---

*This is a self-directed project using synthetic data, built to demonstrate maintenance-data
and reporting skills. It is not employment experience and does not represent a year of
Maximo experience. The honest CV line is: “Maximo BESS data-quality project: generated a
synthetic battery-storage asset hierarchy, PMs and work orders; produced Maximo import CSVs,
14 automated data-quality checks and an Excel PM/backlog report.”*
