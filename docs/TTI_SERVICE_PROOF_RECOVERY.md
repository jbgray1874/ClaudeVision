# Concept service dependency, proof gate and uncertain POST recovery

This cumulative integration patch includes the earlier proof-gate package. Apply
once to f09441f4 / 02da4915, not on top of the earlier patch blindly. Preserve
all private source/ledger files and backups. It does not schedule any jobs.

## Service dependency

The service requirements now include PyMuPDF>=1.24.3,<2.0. This is the SERVICE
virtualenv, not the engine virtualenv. `import pymupdf` is supported from 1.24.3:
https://pymupdf.readthedocs.io/en/latest/changes.html#changes-in-version-1-24-3

`brief_renderer.py` renders entirely in memory before staging touches a pack.
Missing/broken imports become `StagingDependencyError` and HTTP 503 with
`code=brief_renderer_unavailable`, `accepted=false`, and installation guidance.
The service creates no run on that path. Oversized briefs fail instead of silently
rendering an empty page. The original enquiry text still travels unchanged.

Publishing now checks the service interpreter's real rendering ability BEFORE
push/restart. This check does not install anything. Once all jobs are idle, the
integrator must install the dependency in the service environment, then run:

```powershell
& .\sdi-intelligence-backend\.venv\Scripts\python.exe -m pip install 'PyMuPDF>=1.24.3,<2.0'
if ($LASTEXITCODE -ne 0) { throw 'Service dependency installation failed' }
& .\sdi-intelligence-backend\.venv\Scripts\python.exe -B tools\check_service_brief_renderer.py
if ($LASTEXITCODE -ne 0) { throw 'Service renderer check failed; do not publish' }
```

Run from the integrated repository. Do not replace this interpreter with the root
engine Python. This package does not run those commands or deploy anything.

## Quantity and proof protections

Both `--assume-missing-quantity-one` and `--blank-quantity-as-one` are aliases.
With either, blank/zero/unreadable text/Excel errors use one explicitly and keep
the original source and reason. Readable negative/fractional counts remain held.
AiCost remains unit GBP at the effective quantity, not the whole-order amount.

The default pilots are 6 and 12. Every remaining-row submission requires an
explicit, matching `--approve-proof` audit, including build, run IDs, pictures,
C/K archives, exact quantity, engine record/workbook and AiCost. Pilot exit zero,
`PROOF OK` in a shell log and completion of the drawing jobs are NOT approval.
Never auto-run `--approve-proof` in a chain: a person must review the results.
See TTI_PROOF_GATE_HARDENING.md for the detailed evidence contract.

## Row 6: reconcile, do not blindly retry

The 21 Nov failed attempt stayed `submitting` with no run ID. The traceback was
in stage_brief_only before Run creation. Row 12 was not submitted by that batch.
The reviewer found no matching row-6 run in either service or 264 local history
files. K access was denied, so NO live state was changed. This is not an assertion
that C and K have already been reconciled. The packaged audit records that limit.

Use `tools/reconcile_tti_concept_submission.py` in audit mode first. Supply the
EXISTING batch archive folders (including their batch ID), authoritative runs
directory, row 6, and BOTH service URLs via repeated `--server` options. The
report must be outside archives/history and must not replace the workbook.

The tool reads every local history JSON and both complete service lists. It
refuses malformed/truncated/unavailable history. Any matching reference, even
at another quantity or with an error status, blocks reset; reconcile/attach that
run instead. It checks unchanged source facts/request, no AiCost or result files,
and identical C/K ledgers. Merely finding no run does NOT authorise resetting.

Only after reviewing the audit AND confirming the server failed before queuing,
and after every drawing job is idle, may the integrator invoke `--apply` with:

- `--reviewed-evidence` pointing to that audit;
- `--confirm-prequeue-failure` explaining the verified server traceback;
- `--claim` naming the real common batch.lock (the tool validates this path).

Apply takes the common exclusive claim; it never removes an existing stale or
live lock, never restarts a process and never calls POST. The old attempt and
state are saved to BOTH roots before moving the entry into `retired_submissions`.
Any partial C/K write blocks subsequent execution rather than guessing.
There is no workbook edit. Repeating the apply does not silently reset again.

Afterward the operator may separately authorise an explicit two-row proof run.
The former request/source archives are reused, and the new submission carries
the new execution build. The remaining 152 still require reviewed proof PASS.

Do not use the former shell chain that searches an append-only log for PROOF OK.
Do not delete state.json, create a new batch directory, or change source identities
to evade an uncertain POST. Existing approval from another build does not count.
