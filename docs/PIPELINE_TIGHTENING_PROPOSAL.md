# SDI Intelligence — bounded pipeline-tightening proposal

Date: 2026-09-08 · Based on `docs/PIPELINE_WRITER_INVENTORY.md` (audit at `416acbb`).
No production code has been changed by the audit. Each item below names its files, its
size (S/M/L), and whether it changes behaviour. Sequenced in three tranches; nothing in a
later tranche blocks an earlier one shipping.

The organising fact from the inventory: **the "final" graph refresh is not final.** After
it, the bay rollup ADDS BOM rows, the workbook gate MINTS up to three kinds of priced
line, a labour group can be injected, and the totals fold rewrites every headline. Each
of those is individually defensible; collectively they are why a rejected record kept
reappearing on 10975 until three separate gates were stacked. The fix is not more gates —
it is making the additions an explicit stage *before* the seal, and the seal real.

---

## Tranche 1 — the seal (Priority 2/3): ~4 files, no new subsystems

**1.1 An explicit commercial stage, then the refresh, then nothing.** (M, behaviour: order only)
Move the post-boundary ADDERS to a named stage that runs *before*
`refresh_canonical_route_after_reconciliation`:
- `bay_rollup.synthesize_folder_job_bom_rows` + `inject_missing_bay_rows` + catalogue
  rows (`file_scan.py:3312-3330`) move above the refresh call (`file_scan.py:3304`).
- The three-branch missing-bought-in mint (`wb_populate.py:1769-1871`) moves out of
  `canonicalise_part_estimates_for_workbook` into the same pre-refresh commercial stage
  (it needs the graph's bought-in nodes, which exist by then). What remains at the
  workbook gate is enforcement only: quarantine, fold, alias, rewrite — no creation.
- PACKAGING/DELIVERY injection already runs pre-refresh (estimator:6714) — unchanged.
Result: everything the sheet prices has passed through the final compile; the last gate
stops being load-bearing and becomes the tripwire it was meant to be.
Files: `file_scan.py`, `wb_populate.py`, `route_compiler.py` (stage comment), tests.

**1.2 One published population.** (M, behaviour: readers converge)
`wb_populate.py:2888` publishes `canonical_part_estimates` beside `part_estimates` — two
populations. After 1.1, write the canonicalised list back over
`estimate_summary["part_estimates"]` (keeping the raw list as
`part_estimates_pre_canonical` for audit) and migrate the six direct readers named in the
inventory (`job_report_html.py:144/:1952`, `client_quote_html.py:926`,
`estimation_report.py:277`, `main.py:1040`, `estimator.py:7172/:7229`) to
`costed_facts.job_parts`. Files: 7. Mostly mechanical.

**1.3 The seal invariant.** (S, new BLOCKING check)
`invariants.py`: every identity on the workbook's BOM/labour rows must exist as a node in
the published graph, and no identity in the quarantine/fold ledgers may appear on any
row. This is the check that would have caught the chimera on run one and the BI
fragments on every run since. Exceptions (per the reviewer's correction 3): the
commercial class-words (PACKAGING/DELIVERY), and rows the estimator added by hand
post-run.

**1.4 Run-identity stamp.** (S, release rule)
`main.py` mints `run_id` (job + timestamp + git rev) once; every deliverable footer, the
workbook banner cell, the variant banners and the covering-email subject carry it plus
quantity and the pricing-snapshot totals. `costed_facts.release` gains
`run_id`; the release rule ("customer-ready requires…") checks the five conditions the
reviewer listed. Files: `main.py`, 4 deliverable writers, `quantity_sweep.py`,
`costed_facts.py`.

**1.5 Delete the dead reconcile block.** (S) `file_scan.py:1929-2043` (`if False and …`).

## Tranche 2 — the harness (Priority 4): new files only

**2.1 Fast frozen-evidence replays.** (M)
`tests/replay/<job>/` holds the frozen inputs (run JSON, cached LLM extract, DXF
fixtures — 10975 first, then 7332, 12349, 11350, 12392, 8352) plus an
`accepted_facts.json` of estimator-reviewed facts: BOM identities + quantities, route per
part with ruled-out ops and reasons, decisions expected, block per material line. A
runner (`tests/replay/test_replays.py`) drives reconciliation → costing → costed record →
HTML deliverables (everything except Excel) and diffs structure, not money. Gates every
push in this environment. Accepted facts are written from the *reviewed* pack, never from
whichever run last passed.

**2.2 Full Windows replays.** (S, script only)
`tools/replay/run_nightly.ps1`: re-run each frozen pack end-to-end (SolidWorks, Excel,
read-back) at quantities 1, 10, 50 with rates pinned; diff against accepted outputs;
write one summary file the portal can show. Scheduled task on 10.0.0.5.

## Tranche 3 — contracts and memory (Priorities 5/6): the compounding work

**3.1 One geometry accessor.** (M→L, staged)
`costed_facts.geometry_of(part)` returning the reconciled view (`_BLANK_HOLDERS` already
does the hard half); migrate the ~45 reader sites module by module (invariants and
route_compiler first — they gate money; estimator last — it has the estimator-only
`manufacturing_features` family). New readers are forbidden from touching the raw
spellings by a source-scan test, the same pattern as `test_one_writer_per_arbitrated_fact`.

**3.2 One identity ledger.** (L, staged)
Seventeen merge mechanisms across six modules today. Step one is not a rewrite: make
every pass RECORD into a single `summary["identity_resolutions"]` ledger
(alias → survivor, pass name, evidence) and make `costed_facts.canonical_identity` read
only the ledger. Step two folds the four token-set implementations into
`part_identity`. Step three retires per-module lookups. Each step ships alone.

**3.3 Persisted estimator decisions.** (M)
`decisions/<job>.json`: {part, field, value, author, date, source, drawing_revision}.
Read at arbitration as the top-rank source `estimator_decision`; invalidated
automatically when the drawing revision changes (the record carries the revision it was
made against). Round one covers exactly the 10975 set: gauge, tape length, a supplied
price, a confirmed operation. This is also where the bought-in price book (task #11)
finally gets its writer: an accepted price is a decision.

**3.4 Formula-cache repair** stays open pending the first `.log` that shows whether
`recache_workbooks` runs and fails or never runs — no code until the log says which.

---

## What this deliberately does NOT do

No estimator/costing rule changes; no new manufacturing vocabulary; no rewrite of the
alias passes (3.2 wraps before it replaces); no change to how drawings are read. The
target, as agreed: a misreading must not be able to silently become an apparently
finished estimate.

## Sequencing against live work

Tranche 1 after the 10975 acceptance run and the 7332 replay are green — it moves stage
order and must be validated by 2.1's replays, so 2.1 (10975 + 7332 packs) lands FIRST,
then 1.1-1.5 behind it, then the remaining packs, then tranche 3 as background work
between jobs.
