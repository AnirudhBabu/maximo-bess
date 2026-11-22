# Instance notes — Phase 0 and file-mode status

**Status (2026-11-22): live instance access is NOT AVAILABLE. File mode is the active
path. The 14-day trial clock has not been started.**

Decision: do not attempt API/live work. Generate Maximo Data Import CSVs, run the checker
and report through `CsvRepository`, and keep the REST client/loader mock-tested only.
`mxbess all --target file` is the reproducible end-to-end fallback.

Fill in the Phase 0 answers below **only if access becomes available**; until then they are
marked N/A. Anything not confirmed stays flagged **UNVERIFIED** and behind the mock.

## 1. Phase 0 checklist

| # | Question | Answer | Date | Evidence |
|---|---|---|---|---|
| 1 | Can an API key be created for the trial user? | N/A — no instance access | 2026-11-22 | — |
| 2 | How is the key sent? (`apikey: <key>`?) | UNVERIFIED | — | — |
| 3 | Base URL pattern? (`https://<host>/maximo/api/os/<objectstructure>`?) | UNVERIFIED | — | — |
| 4 | Which object structures exist and are writable: locations, assets, work orders, PM, job plans? | UNVERIFIED | — | — |
| 5 | Are Data Import / CSV import and export available in the UI? | Not checked — no instance | 2026-11-22 | — |
| 6 | Site and organisation IDs to use | File mode uses `BISHA-BESS` / `BISHA` | 2026-11-22 | — |
| 7 | Trial start date / expiry date | Not started | 2026-11-22 | — |
| 8 | Which API version / docs link applies to this instance | N/A | — | — |

Suggested object structures to test (VERIFY each only if access appears):

| Model | Assumed object structure | Read | Create | Update |
|---|---|---|---|---|
| Location | `mxapilocations` | | | |
| Asset | `mxapiasset` | | | |
| Job plan | `mxapijobplan` | | | |
| PM | `mxapipm` | | | |
| Work order | `mxapiwo` | | | |

For each writable structure, test one create, one read-back and one update in the UI or
with `curl` before changing code. Record the exact JSON field names that come back.

## 2. Calls and assumptions marked UNVERIFIED

From `mxbess.mapping.UNVERIFIED` (keep the two lists in sync):

- **Auth header** — `apikey: <key>`, no bearer prefix.
- **Paging** — `responseInfo.nextPage.href` in the JSON response (source also accepts an
  OSLC `Link: <...>; rel="next"` header).
- **PATCH** — partial update via `PATCH /api/os/<os>/<key>`.
- **Object-structure names** — `mxapilocations`, `mxapiasset`, `mxapijobplan`, `mxapipm`,
  `mxapiwo`.
- **PM last-completed column** — `LASTCOMPDATE`.
- **Actual labour hours** — `ACTLABHRS` on the WO object. Maximo normally derives actual
  hours from LABTRANS; if `ACTLABHRS` is not writable, decide whether to load LABTRANS or
  drop actual hours from the live dataset (W02 then needs a live-specific rule).
- **Problem/failure codes** — `PROBLEMCODE` / `FAILURECODE` on the WO object.
- **PM frequency** — `FREQUENCY` interpreted with `FREQUNIT=DAYS`.
- **Criticality** — numeric 1–5, 1 = highest.
- **Asset hierarchy level** — inferred from ASSETTYPE on live reads; unusual equipment
  families default to MODULE. Consider a custom attribute if the instance provides one.
- **PM safety-critical flag** — currently local-only/report metadata; decide whether a
  custom Maximo attribute is available.
- **Job-plan tasks** — local-only; loading task rows needs a separate object structure.
- **Site filtering** — reads use `SITEID="<site>"` in `oslc.where`; confirm the syntax.

## 3. Live constraints to test early

These affect which injected defects can exist in the instance and are called out in the
manifest / README:

1. **Unique ASSETNUM** — Maximo should reject duplicate asset numbers. A03 is therefore
   injected as duplicate description+location; the duplicate-number branch remains an
   offline unit test.
2. **PARENT validation** — does the API allow an unknown parent (A06 orphan)? Does it
   prevent a cycle? If both are rejected, record that live A06 coverage is limited to the
   unit tests and CSV fallback. Mark the manifest's `live_risk` note as resolved.
3. **Required-field rules** — does the instance enforce manufacturer/serial/criticality?
   If so, A04 defects may be rejected on create. Possible workaround: create complete
   records, then clear fields via PATCH if allowed; if not, A04 is offline-only.
4. **Status domains** — confirm OPERATING/DECOMMISSIONED/DOWN for assets, ACTIVE/INACTIVE
   for PMs, WAPPR/APPR/INPROG/COMP/CLOSE/CAN for WOs. Map to local domain values if the
   instance uses different codes.
5. **Location/asset sharing** — confirm a container can be both a location and an asset
   with the same identifier, or adjust the model.
6. **Work-order status transitions** — Maximo may reject setting COMP/CLOSE directly;
   the loader may need `_action`/status-change calls. If so, keep the loader create-only
   for WOs and let a small transition helper close them.

Whatever the outcome, record it here and update `mapping.py` in the same commit.

## 4. Recorded answers / adaptations

**2026-11-22:** no live instance access; no object-structure or field mapping could be
confirmed. File mode selected. The tables below remain for a future attempt.

### Object structure mapping after Phase 0

| Model | Confirmed object structure | Notes |
|---|---|---|
| Location | Not confirmed | assumed `mxapilocations` |
| Asset | Not confirmed | assumed `mxapiasset` |
| Job plan | Not confirmed | assumed `mxapijobplan` |
| PM | Not confirmed | assumed `mxapipm` |
| Work order | Not confirmed | assumed `mxapiwo` |

### Field mapping changes

| Our field | Live column | Change made |
|---|---|---|
| — | — | none; file mode uses the mapping as-is |

### Trial dates

- Trial started: **not started**
- Trial expires: —
- Export/screenshots saved: N/A (no instance)

## 5. File mode — the active path

Because there is no instance, the fallback is the primary workflow:

```bash
# one command: seed -> Maximo import CSVs -> read them back -> check -> verify -> report
mxbess all --target file --out build --as-of 2026-11-01
```

This proves the file pipeline end to end: 44/44 injected defects found from the CSV
repository, zero false positives, `build/report.xlsx` written. The internal snapshot
(`build/csv`) and the Maximo-format files (`build/maximo-import`) are both produced.

To use the files manually in Maximo (if an instance becomes available):

1. Open the Maximo **Data Import** / CSV import application.
2. Import in dependency order: `locations.csv` → `assets.csv` → `jobplans.csv` →
   `pms.csv` → `workorders.csv` (see `maximo-import/README.txt`).
3. Export the same objects from the UI as CSV and run:

```bash
mxbess check  --csv-dir <export-dir> --verify build/defects_manifest.json \
              --as-of YYYY-MM-DD --out build
mxbess report --csv-dir <export-dir> --output build/report.xlsx
```

`CsvRepository` reads either the internal snake_case snapshot (`build/csv`) or Maximo
exports with the mapped uppercase columns (`ASSETNUM`, `DESCRIPTION`, `SITEID`, …). Keep
the export filenames as `locations.csv`, `assets.csv`, `jobplans.csv`, `pms.csv` and
`workorders.csv`; rows from other sites are filtered out when `SITEID` is present. If a
required column (for example `ASSETTYPE`) is missing, add it to the export or record the
adaptation here. Safety-critical is recovered from the `JP-03/04/05/08/09/14` codes;
job-plan tasks and the location level are not recoverable from an export.

4. Record in this file which import/export objects were used and any column renames.
   Phases 3–5 need no code change because they read through `Repository`.

## 6. Phase 6 run checklist (only if access appears)

- [x] Phases 1–5 green offline (`pytest`, `mxbess all --target file`)
- [ ] `.env` filled; `MAXIMO_LIVE_ENABLED=true` only for the live commands
- [ ] `mapping.py` updated from Phase 0 answers; `UNVERIFIED` notes reconciled
- [ ] `MXBESS_LIVE=1 pytest -m live` smoke test passes
- [ ] `mxbess load --target api` shows 0 failures (or every failure understood)
- [ ] Re-run shows **created 0, updated 0**
- [ ] `mxbess check --api --verify build/defects_manifest.json` — expected recall/precision
      recorded below; note any defects the API refused to accept
- [ ] `mxbess report --api` opens; at least five numbers spot-checked against the UI
- [ ] End-to-end `mxbess all --target api` under 5 minutes
- [ ] Manual UI demo captured: approve/close a WO, edit a PM, fix one finding, re-run and
      show it gone
- [ ] Export + screenshots saved in `docs/screenshots/`; report copied to `docs/`

### Live run results

| Item | Result |
|---|---|
| Assets / PMs / WOs loaded | |
| Load time | |
| Defects found / manifest total | |
| False positives | |
| Numbers spot-checked | |
| Manual fixes demonstrated | |
