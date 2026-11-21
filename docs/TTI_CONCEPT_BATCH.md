# One-off TTI thumbnail / description costing

This is a separate entry point, `src/tti_concept_batch.py`. It does not change
`tti_pricer.py`, the drawing-pack queue, the service, the runners, or SDI Live.
Do **not** use the old `tti_pricer.py` thumbnail path for this workbook: its
floating-picture reader cannot see the native in-cell richData pictures.

## Scope and evidence

The 21 November tracker (4), Milwaukee, has 144 eligible unpriced rows without a
drawing reference: 116 with pictures and 28 description-only. Ten rows have no
positive integral quantity and stay held: 65, 93, 94, 105, 106, 107, 208, 209,
210, 211. Drawing-reference rows and existing AiCost values are excluded. Counts
are recalculated from the workbook, not hardcoded selections. The original plan
is frozen for resume; later additions do not silently join the batch.

Reader: cell value-metadata -> rich-value metadata -> structure's image slot ->
rich-value relationship -> media relationship. No filename/order assumption.
All picture columns and normal floating row anchors are supported. Broken,
external, unsupported-format or ambiguous pictures stop the plan, not disappear.
The actual file yielded 316 picture cells. Extracted bytes are not resized.

The prompt contains the description, products, station, feedback, previous notes,
quantity, design/workflow/logistics fields and other non-price row values. All
nonempty row cells, including historical costs, are retained in source-row.json.
Historical cost/sell/margin cells are **not pricing evidence** and are not fed
back to the model as an anchor. The entire original workbook is also archived.
Text is supplied as source data, not commands or permissions. No hyperlink is
followed and no folder is searched. Unknown dimensions/materials remain explicit
assumptions in a PROVISIONAL CONCEPT costing, never a customer quotation.

## Integration, not deployment

Apply the package patch in a clean review checkout on top of `72219d95` or your
later integrated stack. All six payload files are new; there are no changes to
the earlier AiCost reconciliation module. Keep private verification artifacts,
the actual workbook, pictures, .env and engine records OUT of git.

Run with the project's configured Python environment:

```powershell
$env:SDI_TTI_CONCEPT_TRACKER = "$env:USERPROFILE\Downloads\<the tracker workbook>.xlsx"
& .\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider tests/test_tti_concept_batch.py
& .\.venv\Scripts\python.exe -B src\tti_concept_batch.py --sheet $env:SDI_TTI_CONCEPT_TRACKER --plan-output "$env:USERPROFILE\Downloads\TTI concept plan.json"
```

Those commands **do not submit jobs**. With no private workbook variable, the
actual-workbook test explicitly skips. The synthetic tests remain runnable.
Also run the existing service contract tests in an environment with FastAPI:

```powershell
& .\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider tests/test_a_brief_alone_is_a_pack.py tests/test_an_enquiry_brief_states_what_the_render_cannot.py
```

The offline auditor can exercise write-back on a **marked disposable copy**:

```powershell
& .\.venv\Scripts\python.exe -B tools\audit_tti_concept_inputs.py --workbook $env:SDI_TTI_CONCEPT_TRACKER --output "$env:USERPROFILE\Downloads\TTI concept private verification" --exercise-writeback
```

It requires a new output directory. Its synthetic 12.34 test value is NOT an
estimate. Do not publish or use that disposable workbook.

## Later execution prerequisites

Integrate and test first. Finish the drawing batch. Verify the common batch lock
owner; this tool will not remove ANY existing lock, including a stale lock. Close
Excel. Keep the VPN connected. Confirm the UNC archive path is visible to the
service/runners and within SDI_FILE_ROOTS. Mapped K: alone is not sufficient for
service accounts. Use an expected bare commit hash from the integrated checkout.
The CLI refuses tracked local edits and a checkout/build mismatch. Every online
runner must be on that build, have one process and no conflict. Default capacity
is two, with one optionally selected by `--at-once 1`.

Explicit opt-in arguments for a later authorized run:

```text
--execute
--expected-build <integrated-commit>
--shared-root \\sdi-dc01\shareddata$\Shared\Estimating\Completed\AI Estimating\AISheets\SDIIntelligenceAISheet\_held\tti_concepts
--stop-file %USERPROFILE%\Downloads\STOP-TTI-CONCEPTS.txt
```

These are not a release script. The package never publishes, restarts, unblocks
locks, queues the nine drawing jobs, or enables a server slot. Before unattended
use, the integrator must prove one image row and one description-only row against
the real service and inspect the resulting workbook and archives. No live price
quality has been established by the offline tests.

Use `--rows 6,12` for that proof on this version of the tracker (row 6 is
description-only, row 12 has a picture). Then omit --rows on the same workbook
and archive paths to process the remainder without repricing those completed
rows. Held/drawing rows cannot be forced through --rows. Do not make a second
source-workbook copy to run the pilot.

## Runtime records and AiCost

- Default local archive: `C:\ClaudeVision\output\tti_concepts\<workbook-path-hash>`
  when installed in C:\ClaudeVision. Override with --local-root if required.
- Shared archive: the explicit UNC root above plus the same hash, corresponding
  to the K: estimating area. Do not choose a different archive root on resume.
- The normal service also files its DRAFT outputs through its existing filing
  route; this tool mirrors available deliverables, it does not override that route.
- On both roots: original workbook backup, immutable plan, all row data, exact
  pictures, prompt, request, per-poll service evidence, engine record, workbook,
  reports/other permitted deliverables, price/quantity/run association, state,
  journals and AiCost write-back events. File contents are hash-verified. The
  service's customer-quote release gate is respected; refused downloads are listed.
- `/api/estimate` with method=llm accepts all staged pictures; an empty image list
  with the full brief supports description-only rows. `/api/estimate/llm` is NOT
  used, because that upload endpoint requires one image.
- No email recipients are supplied. SDI_API_KEY is loaded from the existing root
  .env/environment, never printed or archived. SDI_STATE_DIR / PROGRAMDATA select
  the same global batch claim location as the drawing batch.
- AiCost gets the **unit GBP cost at exactly the row's quantity**, only after a
  done/price_validated result, a matching engine-record quantity, a readable
  workbook and the engine record are saved on BOTH roots. Zero/missing/negative
  prices, mismatches and conflicting quantity breaks hold rather than write.
- Only the existing AiCost cell is changed via a surgical worksheet-XML edit.
  Every other ZIP member is compared byte-for-byte; images/richData, formulas,
  other worksheets, styles and native objects remain intact. No openpyxl save.
  AiCost is numeric; provisional status and source/run links are in its audit
  record, not an invented extra column or a changed workbook layout.
- Recheck the row fingerprint and existing AiCost before submission/write-back.
  A conflicting value or edited row stops. A matching value following a crash
  after write-back is reconciled without another pricing call.

## Failures, duplicates and retention

The shared batch claim is exclusive. Durable state is saved before each POST.
An accepted-but-timed-out POST is never blindly repeated: a unique matching run
can be recovered; an absent or ambiguous run requires manual reconciliation.
Existing runs use stable source fingerprints, not old workbook row numbers.
C/K state disagreement stops for journal reconciliation. Do not delete ledgers
or move/copy the source workbook to make a new batch identity.

On an error, no further rows are submitted. Already accepted jobs are NOT killed;
their IDs are saved. Resolve the issue and rerun the same command/paths to collect
them. A failed/held entry is not automatically retried. A stop file also stops new
submissions without cancelling existing jobs. Console WAITING messages show
progress; event/state files remain on C and K. No service status means no assumed
success. There is no fixed completion-time promise.

This package retains its own briefs, requests, response evidence and available
engine logs without automatic deletion. It is NOT an implementation or proof of
SDI Live call/chat database retention, nor of Codex conversation backups.

## Drawing rows with no drawing pack (JG ruling, 21 Nov 2026)

A row that carries a drawing number is normally left to the drawing pricer. When that
pricer found no drawings for the number, the row can be priced here from its description
and pictures instead:

    --no-pack-rows 113,115 --no-pack-ledger "<the drawing pricer's ledger.json>"

- The proof that no pack exists is the drawing pricer's own ledger: the row's latest entry
  must be `needs drawing`, and the drawing number recorded there must be the one the row
  carries on this sheet. Anything else is reported and not priced. Nothing is searched here.
- The brief sent with the job says NO DRAWING PACK, names the drawing number, and asks for
  that to be stated in the estimate and its review notes. The filed
  `price-for-writeback.json` carries `no_drawing_pack`, the drawing number, the evidence and
  "reprice from the drawings when they are supplied".
- If the plan was already filed, each such row is added as one file under
  `plan-amendments/` on both roots. `plan.json` is never rewritten, and the row is kept on
  every later resume whether or not the option is given again.
- These rows are not proof rows. They wait for the approved proof like every other row.
