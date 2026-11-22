# Drawing-priority preparation

This package is prepared for integration only. It does not release code, stop a
batch, submit estimates, retry held concepts, edit a ledger, or write AiCost.

## Corrections

* `route_compiler`: a late, inferred cutting operation cannot reclassify two
  separately purchased handed parts as manufactured assemblies. Measured flat
  geometry still prevents the purchase reclassification. Both identities and
  their own BOM counts are retained.
* `purchase_evidence` and `estimator`: an exact supplier article printed against
  that exact BOM identity reaches the existing price chain. A handed article
  never inherits a supplier reference or price just because its base matches.
  Conflicting or missing current BOM evidence clears only this reader's stale
  alias. Missing purchase prices become visible manufacturing questions; a small
  material/fitting charge does not stand in for buying the article. No supplier
  quote, catalogue rate, calculator rate or currency conversion is invented.
* `batch_job_changes` and `tti_pricer --job-changes JSON`: explicitly accepted,
  client/drawing/part-specific material, gauge and finish instructions reach the
  service's existing customer-change mechanism. Decisions are included in reuse
  fingerprints. Adding, changing or removing a decision invalidates that reuse.
  An unresolved prior run prevents a changed instruction starting another job.
  Old-result collection is explicitly labelled as reuse, not a fresh estimate.
  `--replace-costs` alone does not promise a new engine run.
* The separate `job-instructions/tti-12757-confirmed-gauge.json`: James Gray's instruction to cost three
  display-board parts at 2 mm. The drawing actually states 1 mm; preserve both
  values as a customer change, not a supposed correction of the drawing read.
  Keep this private job instruction with the job, not in the source repository.

## Recovery report, never an executor

`tools/prepare_drawing_recovery.py` reads local service history and the drawing
ledger. It requires exact client, drawing, quantity, method and recorded brief
scope. The service's completed/price/workbook gate is preserved. It will not
accept running, errored, manually stopped or cancelled results.

Only exact timestamped record/workbook pairs declared by that run are inspected.
The saved record must name the exact service run and drawing, with matching
submitted scope and quantity. The cached Excel price at the record's own
`final_estimate.totals.unit_cell` and `Estimate!D6` must agree with the record and
service price. The tool never launches Excel, recalculates, fills a blank with
zero, uses the generic latest JSON, or assumes totals always remain at M105.

Example, report-only (not a pricing command):

```powershell
python -B tools/prepare_drawing_recovery.py --ledger OLD_LEDGER.json --runs-dir LOCAL_RUN_HISTORY --records-root MAIN_ESTIMATES --records-root SLOT2_ESTIMATES --rows 124,126,138 --output NEW_REPORT.json
```

The report hashes evidence and lists candidates. It does not approve estimate
quality or prove pack bytes match. Recheck tracker identity, quantity and pack
binding before collection. Row numbers refer to tracker copy (2), not copy (4).
Never copy row numbers between those sheets.

## Collection and release boundaries

1. No blanket reruns. Do not add the eleven no-pack fallbacks again: they already
   belong to the concept queue.
2. Do not change production while a batch is active. The user's existing waiting
   release/retry window is separate and has not been altered by this package.
3. After an explicitly authorised drain, reconcile saved completed results before
   considering submissions. Do not revive the failed earlier run when a later
   successful run exists.
4. Rebuild the final AiCost reconciliation plan from fresh state. Map by exact
   drawing, quantity and row scope, and keep corrected prices and concept results.
   Work on a new output copy, not the working tracker used by the concept queue.
5. This package contains no apply-to-production, restart, queue, release or
   automatic-collection command. Integration and the final focused/full suites
   belong in a separate checkout. Deploy only in a user-approved quiet window.
6. These are costing changes, not a reporting-only release. Do not automatically
   carry concept proofs forward using the old reporting-only justification.
   Preserve completed prices. Any later concept continuation must satisfy the
   existing proof/build policy on the integrated build.

## Remaining business decisions

The code cannot issue missing PDFs, approve revision C over B, or fabricate LED,
charging-module or PSU prices. The priority case report records these as specific
blocks. A provisional number is not a complete or approved estimate.
