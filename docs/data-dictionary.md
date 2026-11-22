# Data dictionary

Everything here describes the **synthetic** dataset. No real or confidential data is used.

## 1. Site and identifiers

| Item | Value |
|---|---|
| Site | `BISHA-BESS` |
| Organisation | `BISHA` |
| Default seed | `20260101` |
| Reference as-of (tests, sample report) | `2026-11-01` |
| Default hierarchy | 4 blocks × 2 containers × 8 racks × 5 modules |

`as_of` is the reporting date. Work orders cover the 12 months before it; ages, overdue
days and compliance are all measured against it. The CLI uses today's date unless
`--as-of` is supplied, so a live load contains recent work orders.

## 2. Hierarchy

```
BISHA-BESS                     location, level SITE
└── BB1..BB4                   location, level BLOCK
    ├── BBn-PCS                asset,   type BLOCK,     equipment PCS
    ├── BBn-MVT                asset,   type BLOCK,     equipment MVT
    ├── BBn-HVAC1 / HVAC2      assets,  type BLOCK,     equipment HVAC
    ├── BBn-FDA                asset,   type BLOCK,     equipment FDA
    ├── BBn-FSS                asset,   type BLOCK,     equipment FSS
    ├── BBn-BMS                asset,   type BLOCK,     equipment BMS
    └── BBn-CT1..CT2           location, level CONTAINER
        ├── (same id)          asset,   type CONTAINER, equipment CONTAINER, parent BBn-PCS
        └── BBn-CTc-RK01..RK08 location, level RACK
            └── ...-MD01..MD05 asset,   type MODULE,    equipment MODULE, parent BBn-CTc
```

A container is deliberately **both a location and an asset** (a common Maximo pattern):
modules sit at the rack location and hang off the container asset, which in turn hangs off
the block's PCS. This gives the parent checks and the hierarchy a real shape.

Site-level assets: `SITE-SCADA` (SCADA/EMS), `SITE-AUXPWR` (auxiliary power),
`SITE-SWG` (MV switchgear).

Default counts: 77 locations; 359 assets = 320 modules + 8 containers + 28 block + 3 site.

## 3. Asset numbering convention

| Type | Pattern | Example |
|---|---|---|
| SITE | `^SITE-[A-Z0-9]+$` | `SITE-SCADA` |
| BLOCK | `^BB\d+-(PCS\|MVT\|HVAC\d+\|FDA\|FSS\|BMS)$` | `BB2-HVAC1` |
| CONTAINER | `^BB\d+-CT\d+$` | `BB1-CT2` |
| MODULE | `^BB\d+-CT\d+-RK\d{2}-MD\d{2}$` | `BB1-CT2-RK03-MD04` |

Invariant for clean data: descriptions are unique within a location, so A03's
description+location rule has no false positives on the generated site.

## 4. Asset fields

| Field | Meaning | Mandatory? |
|---|---|---|
| `asset_num` | Unique asset number, see convention | Yes |
| `description` | Human description; unique per location in clean data | Yes |
| `asset_type` | Hierarchy level: SITE / BLOCK / CONTAINER / MODULE | Yes |
| `equipment_type` | Engineering family (PCS, MVT, HVAC, FDA, FSS, BMS, SCADA, AUX, SWG, CONTAINER, MODULE); maps to Maximo ASSETTYPE | Yes |
| `location` | Location id the asset sits at | Yes (A01) |
| `parent` | Parent asset number; required for CONTAINER and MODULE | Type-dependent (A02) |
| `manufacturer` | OEM | Yes (A04) |
| `serial_num` | Serial number, unique in the fixture | Yes (A04) |
| `install_date` | Commissioning/install date | Yes (A04) |
| `criticality` | 1 (highest) to 5 | Yes (A04) |
| `status` | OPERATING / DECOMMISSIONED / DOWN | Yes |
| `site_id`, `org_id` | Maximo site and organisation | Yes |

A04 checks only the four fields listed in the brief (manufacturer, serial number, install
date, criticality). The completeness sheet additionally reports description, location,
parent (where required) and status.

**Criticality by family:** PCS/MVT/FDA/FSS/SCADA = 1; BMS/SWG/containers/modules = 2;
HVAC/AUX = 3.

## 5. Location fields

`location`, `description`, `parent`, `level` (SITE/BLOCK/CONTAINER/RACK), `site_id`,
`org_id`, `location_type` (OPERATING). `level` is local reporting metadata and is not sent
to Maximo; the hierarchy comes from `PARENT`.

## 6. Job plans and PM plans

14 job plans (`JP-01` … `JP-14`), each with 3 tasks and 2.25 estimated hours. Job-plan
tasks are local metadata (loading task rows is a separate Maximo object structure and out
of scope).

| JP | PM plan | Frequency | Scope (PM records) | Safety-critical |
|---|---|---|---|---|
| JP-01 | Monthly visual and thermal inspection | 30 d | 8 container assets | No |
| JP-02 | Monthly HVAC filter and airflow check | 30 d | 8 HVAC assets | No |
| JP-03 | Quarterly DC busbar torque check | 90 d | 8 container locations (location-scoped) | **Yes** |
| JP-04 | Semi-annual fire suppression inspection | 180 d | 4 FSS assets | **Yes** |
| JP-05 | Annual fire detection system test | 365 d | 4 FDA assets | **Yes** |
| JP-06 | Annual electrical thermography | 365 d | 4 PCS + 4 MVT + 1 SWG | No |
| JP-07 | Annual BMS calibration and firmware review | 365 d | 4 BMS assets | No |
| JP-08 | Annual transformer inspection | 365 d | 4 MVT assets | **Yes** |
| JP-09 | Quarterly switchgear inspection | 90 d | 1 SWG asset | **Yes** |
| JP-10 | Monthly PCS performance check | 30 d | 4 PCS assets | No |
| JP-11 | Semi-annual battery capacity and SoH test | 180 d | 4 block locations (location-scoped) | No |
| JP-12 | Annual auxiliary power inspection | 365 d | 1 AUX asset | No |
| JP-13 | Annual SCADA/EMS backup verification | 365 d | 1 SCADA asset | No |
| JP-14 | Semi-annual E-stop and safety interlock test | 180 d | 4 FSS + 4 PCS assets | **Yes** |

Safety-critical plans are the ones a BESS site would treat as HSE/compliance work
(fire suppression/detection, DC torque, transformer, switchgear, E-stop).

**PM record fields:** `pm_num`, description, target `asset_num` or `location`, `jobplan_num`,
`frequency_days`, `next_due`, `last_done`, `status` (ACTIVE/INACTIVE), `safety_critical`,
site/org.

`safety_critical` is local reporting metadata, not a standard Maximo column. The
safety-critical plans are exactly JP-03, JP-04, JP-05, JP-08, JP-09 and JP-14; when data is
read from a Maximo import/export or the API, the flag is recovered from that job-plan code.
Job-plan task text and the location `level` are also local metadata and are not recovered
from an export.

Scheduling: each PM's previous due date is `next_due - frequency`. About 30% of PMs are
currently due/overdue; clean data always gives an overdue PM an open PM work order, so P04
is zero on the clean fixture. The historical occurrence is closed/complete (85% on time,
15% 1–10 days late), which is what the PM-compliance KPI measures.

## 7. Work orders

| Field | Meaning |
|---|---|
| `wonum` | `PMWO-####` for PM-generated, `CM-####` for corrective |
| `status` | WAPPR (waiting approval), APPR (approved), INPROG, COMP, CLOSE, CAN |
| `work_type` | PM or CM |
| `reported_date`, `scheduled_start`, `target_finish` | reported / planned dates |
| `actual_start`, `actual_finish` | execution dates |
| `labor_hours` | actual labour hours |
| `asset_num`, `location`, `pm_num`, `jobplan_num` | references |
| `problem_code`, `failure_code` | failure hierarchy codes for corrective work |
| `priority` | 1–5 |

Default mix: ~83 PM work orders (historical + open overdue) and 120 corrective WOs across
all six statuses. Open WOs are reported within the last 90 days in clean data, so W04 is
zero before injection.

## 8. Defect catalogue (ground truth)

`seed/defects.py` injects this set into a clean dataset and returns one manifest entry per
expected finding. Counts are exact.

| Code | Count | Injection |
|---|---|---|
| A01 | 3 | Clear `location` on three modules |
| A02 | 3 | Clear `parent` on three modules (required for MODULE) |
| A03 | 4 | Two module pairs in the same rack share a description → both records in each pair are flagged |
| A04 | 3 | Clear manufacturer / serial / install date on three modules |
| A05 | 3 | Rename three leaf modules to `BAD-MODULE-###`, updating every reference |
| A06 | 4 | Two orphan parents; one two-asset parent cycle (both members flagged) |
| P01 | 3 | Clear `jobplan_num` on three PMs |
| P02 | 3 | Clear frequency on two PMs and next-due on one |
| P03 | 3 | Decommission `BB1/2/3-HVAC1`; each has exactly one PM |
| P04 | 3 | Move three future-due PMs into the past (they have no open WO) |
| W01 | 3 | Clear `asset_num` on three closed WOs |
| W02 | 3 | Clear finish on two closed WOs; zero labour on one |
| W03 | 3 | Future finish on two closed WOs; actual finish on one INPROG WO |
| W04 | 3 | Backdate the report date of three recent open WOs past 90 days |

**A03 duplicate asset numbers** are not injected: Maximo enforces unique ASSETNUM, so such a
record could never exist in a live load. The checker's duplicate-number branch is covered
by a dedicated unit test (`test_a03_duplicate_asset_number_flags_both`).

**A06** carries a `live_risk` note in the manifest because Maximo may reject an unknown
PARENT or a hierarchy cycle. Confirm in Phase 0.

## 9. Maximo mapping (all UNVERIFIED until Phase 0)

The single source is [`src/mxbess/mapping.py`](../src/mxbess/mapping.py).

| Object | Object structure | Natural key | Notes |
|---|---|---|---|
| Location | `mxapilocations` | `LOCATION` | `PARENT`, `TYPE` |
| Asset | `mxapiasset` | `ASSETNUM` | `ASSETTYPE` carries `equipment_type`; hierarchy level is inferred on read |
| Job plan | `mxapijobplan` | `JPNUM` | task rows not loaded |
| PM | `mxapipm` | `PMNUM` | `FREQUENCY` + `FREQUNIT=DAYS`, `NEXTDATE`, `LASTCOMPDATE` |
| Work order | `mxapiwo` | `WONUM` | `WORKTYPE`, `REPORTDATE`, `SCHEDSTART/SCHEDFINISH`, `ACTSTART/ACTFINISH`, `ACTLABHRS`, `PROBLEMCODE/FAILURECODE`, `WOPRIORITY` |

Live-read reconstruction infers `asset_type` from `equipment_type` (SCADA/AUX → SITE;
PCS/MVT/HVAC/FDA/FSS/BMS → BLOCK; CONTAINER; otherwise MODULE). This is documented as
UNVERIFIED for unusual families.

## 10. KPI definitions

See README section “KPIs”. In code: `mxbess/kpis.py`. The report's Summary sheet is generated
from the same functions the tests assert, so numbers can only differ if the dataset differs.

## 11. Report sheets

| Sheet | Contents |
|---|---|
| Summary | Site/as-of/seed, maintenance KPIs, findings by severity and by code |
| Findings | Code, severity, record type, record ID, message, details (filterable) |
| PM_Compliance | One row per PM: job plan, frequency, last/next due, days overdue, safety flag, open WO? |
| Backlog | Open WOs oldest first: status, type, asset, reported, age, bucket, priority |
| Asset_Completeness | Populated/total/percent per mandatory field, overall and per asset type |

All sheets have a frozen header; Findings/Backlog/PM_Compliance/Completeness have
autofilter; dates use `yyyy-mm-dd` and percentages one decimal.

## 12. File mode

`mxbess all --target file` writes two CSV surfaces:

- `build/csv/` — internal snapshot with snake_case fields; preserves all local metadata.
- `build/maximo-import/` — Maximo column headers (`ASSETNUM`, `ASSETTYPE`, `INSTALLDATE`,
  `FREQUNIT`, …) and a `README.txt`; this is what the Data Import application consumes.
  Import order: locations → assets → jobplans → pms → workorders.

File-mode checks read `build/maximo-import/` back through `CsvRepository`, i.e. the columns
a real Maximo export would provide. `CsvRepository` also accepts a UI export with the same
uppercase mapped columns and filters rows to the configured site. Missing mapped columns
fall back where possible (asset type/equipment from the number convention, safety flag from
the job-plan code); anything not recoverable is documented above.
