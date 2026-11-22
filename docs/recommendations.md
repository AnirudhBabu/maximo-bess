# Recommendations: the top five data-quality fixes

Each recommendation maps to checks and KPIs in this project, and to a concrete Maximo
control a maintenance team could put in place. The point is not to clean data once — it is
to stop the same defects coming back.

## 1. Make the asset register complete at the point of creation

**Problem (A04, Asset_Completeness).** Manufacturer, serial number, install date and
criticality are optional in practice, so they are missing where they matter — warranty
claims, spares, criticality-based prioritisation.

**Fix.** Make these four fields required in the asset application/import template, add a
completeness check to the weekly report, and refuse to close a new-asset request until the
record is complete. Track completeness per asset type, as the report does, so the gap is
visible rather than argued about.

**Why it recurs.** People create assets under time pressure during commissioning. If the
system accepts an incomplete record, an incomplete record is what you get.

## 2. Enforce location and parent for every container and module

**Problem (A01, A02, A06).** Assets with no location cannot be found by a technician;
modules with no parent fall out of the hierarchy; orphans and cycles break roll-ups,
reporting and PM inheritance.

**Fix.** Require LOCATION for every asset and PARENT for container/module classes. Add a
nightly orphan/cycle check (the A06 logic) and block decommissioning a parent while active
children exist. Keep the location hierarchy shallow and standard: site → block → container
→ rack.

**Why it recurs.** Bulk imports and manual creation both skip parent when the parent record
does not exist yet. Load parents first (the loader enforces this dependency order).

## 3. Control asset numbers and duplicate descriptions

**Problem (A03, A05).** Duplicate or non-standard asset numbers split maintenance history:
two records for one physical asset, neither with the full work-order story. Free-text
descriptions duplicate the same equipment at the same location.

**Fix.** Put the naming convention in the import template and validate it before import
(regex per asset class). Match on serial number and description+location during
acceptance; treat a hit as a merge, not a create. Keep one numbering authority.

**Why it recurs.** Numbering is delegated to whoever commissions the equipment, and
imports are trusted. Validate at the boundary.

## 4. Keep PMs schedulable and relevant

**Problem (P01–P04, PM compliance, overdue PM).** A PM with no job plan is not executable;
a PM with no frequency or next-due date never generates work; a PM pointing at a
decommissioned asset creates ghost work. Overdue PMs with no work order are invisible in a
compliance percentage.

**Fix.** Require job plan, frequency/unit and next-due date on PM creation (and on change).
When an asset is decommissioned, review and deactivate its PMs in the same workflow. Report
the four numbers together — due, completed, on-time, open-overdue — so a high compliance
percentage cannot hide a growing overdue queue. Provide a one-click "generate work order
for overdue PM" action.

**Why it recurs.** PMs are copied from templates and never re-baselined; assets leave
service without anyone owning the PM cleanup.

## 5. Do not let work orders close without actuals, and review the ageing backlog

**Problem (W01–W04, backlog ageing).** A closed WO with no finish date or no labour makes
cost and reliability analysis fiction. A WO with no asset cannot be traced to equipment.
Open WOs older than 90 days tend to be either forgotten or blocked.

**Fix.** Enforce at close: actual finish, actual labour and a valid asset. Run a weekly
backlog-ageing review with the 31–90 and 90+ buckets, assigning an owner to every 90+ WO.
Make WAPPR/APPR WOs auto-escalate or auto-cancel after a defined period.

**Why it recurs.** Closing is treated as an administrative step rather than a data-quality
gate; nobody owns the long tail.

---

## Process guardrails to add alongside the fixes

- A weekly data-quality scorecard with the 14 check counts by severity (this report).
- One owner for the asset register; one for PMs; one for the WO close gate.
- Import templates validated in a spreadsheet or script before touching Maximo.
- "Fix the source, not the report": when a finding recurs, change the field rule or the
  workflow that created it, not the spreadsheet.
