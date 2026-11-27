# Hotel Chocolat targeted recovery — integration hand-off

27 November 2026. Base: `c9dbe4135f59852dc451ef7029d9774c03295661`.

This is an integration package, not a release. It must not restart services, alter the
running checkouts, submit jobs, overwrite estimates or write prices to a tracker.

## Included

1. **Review export** retains the full service run record, resolves the timestamped main
   estimate workbook inside `output_path`, and retains a validated service price when
   that workbook is inaccessible. Missing workbooks remain visible. A recorded price
   is not treated as approval or proof of complete manufacturing costs. Zero is retained
   as zero, not confused with an absent value. Review makes GET requests only.
2. **Supplier identity joins** bind stock codes and differently punctuated drawing
   references using unique own-sheet evidence. Conventional `nc1-` filenames can identify
   a raster sheet's BOM owner. A filename/printed-title disagreement is recorded, not
   silently substituted. Numeric catalogue references do not become drawing numbers.
3. **Nested quantities** use those joins in the existing canonical graph. Both saved
   Wall of Chocolate layouts have 30 boxes. Their top panels become 60, shelves 120,
   spacers 150 and ticket surrounds 120 per completed layout, without multiplying the
   whole estimate or adding the alternate library products indiscriminately.
4. **Plinth component blanks** bind exact side/top/base captions to their own dimensions,
   preserving quantities and stronger measured/confirmed geometry. The independent
   pypdf text avoids reversed rotated dimensions in pdfplumber. This also runs before
   costing on a saved-record replay. No blanket change to every panel's dimensions.
5. **Offline saved-evidence preparation** rebuilds a selected product's population from
   its saved readers, with an audit of additions, set-asides and canonical per-product
   quantities. It strips stale final totals. This does not calculate a corrected price.
6. **Explicit manufacturing allowances** can add a missing subassembly's provisional
   material and operations from a reviewed, job-scoped decision. Supported operations
   become required route decisions, not just review notes. Existing component detail,
   wrong-job inputs, unknown operations and partial decisions cannot silently add a
   duplicate bill. Nothing is activated by default or automatically loaded from a share.
7. **Saved replay** refreshes its part-list reference after pre-costing replaces that
   population. Existing costing and workbook calculation routines remain the authority.

## What this does not claim

- The 35 old estimates are not certified as correct by this patch. A completed run and
  `price_validated` do not establish BOM completeness, labour coverage or market value.
- No new prices have been calculated or filed, and no estimate has been rerun.
- The private tests establish the stated identity, quantities, blanks and route inputs.
  They do not establish Excel totals, current supplier rates or finishing-cycle times.
- No internet benchmark is substituted for drawing-specific manufacturing costs.
- The three original zero-byte shelf products remain explicitly provisional allowances
  unless usable source drawings are supplied. Signage is still a separate scope.

## Recover selectively, not all 35

Start by reviewing the corrected schedule against the ORIGINAL 26 November 13:22 plan.
Do not replan and queue the entire pack: a corrected product identity changes its source
fingerprint, and does not authorise a second job for an already completed product.

Priority saved evidence:

| Product | Targeted correction |
| --- | --- |
| B.33792, 2 m desk | Join its own stock-code root to its drawing so manufactured children are retained. Do not accept the old five-record population as a full counter. |
| A.33446 and A.34225 | Correct box membership and nested counts. Inspect alternate-layout members and missing purchased costs separately. |
| B.34487, B.34490, B.34493 | Keep the whole plinth root, including ballast. Bind the tower stock aliases listed in the private decision inputs; recover each panel's own blank. |
| B.34471 folder | This is a shelving product whose assembly is B.34473. B.34471 alone is the shelf panel. Changing the estimate's scope requires the explicit basis. |
| B.33519 and B.34082 | Missing carcase/worktop detail can take a reviewed equivalent-material and fabrication allowance, rather than a zero-cost placeholder. First check that the recovered bill does not already contain the detail. |

## Safe integration sequence

In a clean, isolated integration checkout at the exact base above:

```powershell
git apply --check <package>\targeted-recovery.patch
git apply <package>\targeted-recovery.patch
git diff --check
```

Reconcile against newer commits explicitly if the base has moved. Do not apply payload
files over a running checkout. Run the focused tests below and the normal full suite in
the integration environment, including its private acceptance/replay fixtures and native
dependencies. Review the diff, then commit through the normal integration process.
This document deliberately contains no deployment or queue command.

Focused tests:

```powershell
python -m pytest -q tests/test_supplier_sheet_identity.py tests/test_component_caption_blanks.py tests/test_reviewed_manufacturing_allowances.py tests/test_hc_saved_scope_private.py tests/test_the_hotel_chocolat_planner_never_submits_twice.py
```

The private fixture is deliberately not a repository file. Install the package's
`private-evidence/hc_saved_scope.json` as `private-fixtures/hc_saved_scope.json` in the
integration checkout, or set `HC_SAVED_SCOPE_FIXTURE` to its absolute path. Do not commit
it. The public tests are synthetic and contain no customer drawings.

## Prepare selected saved evidence only

`tools/estimating/prepare_saved_scope_recovery.py` reads one saved `_record.json` and writes
a NEW input. It opens no PDFs, contacts no service and runs no estimate. Existing targets
are refused. Its output includes `saved_scope_recovery.priced: false` and a source digest.
Per-parent `quantity` and canonical `quantities_per_finished_product` are different scopes;
do not copy the latter into local BOM edges and multiply it again.

```powershell
python tools/estimating/prepare_saved_scope_recovery.py <saved-record.json> --out <new-prepared-input.json>
```

For an explicit assembly identity decision, add `--identity-aliases <aliases.json>` and
`--scope-basis <drawing evidence>`. For the shelf scope correction add `--scope B.34473`
and its basis. For a reviewed missing-detail allowance add `--allowances <decision.json>`.
Examples are private inputs in the package, not automatically installed config or quotes.

Only after approval should a selected prepared input go through the normal saved replay
and workbook checks. Replay performs costing; preparation does not. Keep its output
separate, check materials, operations, allowances, final Excel totals and commercial scope,
then approve the replacement price with its audit trail. No blanket rerun is required.
