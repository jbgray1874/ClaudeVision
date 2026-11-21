# Final review hardening on 02da4915

The integrated 02da49153c59344301661c525ae4926c87e95c57 passed all 65 original
concept tests, including the actual private tracker. However, it rejected the
promised --blank-quantity-as-one spelling and had no runtime proof-approval gate.
This amendment fixes those gaps. No deployment or live pricing is included.

## Quantity ruling (latest user instruction)

Both --assume-missing-quantity-one and --blank-quantity-as-one are aliases for the
same option in the batch and offline auditor. With either option, blank, zero,
unreadable text, Excel errors, non-finite values and boolean placeholders are
priced as one. The source value is retained, an explicit reason enters the brief
and source record, and the C/K price audit records the assumption. Negative and
fractional readable numbers are still held as invalid stated quantities.
Without either switch the strict hold behaviour remains.

This supersedes the earlier 'recognised placeholders only' restriction. It does
not change the source Quantity cell, old cost/sell figures, or the meaning of
AiCost: unit GBP at the effective order quantity, not the row total.

## Proof gate

The CLI always passes a proof requirement into the scheduler. Default proof rows
are 6 and 12: one description-only and one picture row. --proof-rows can name
another pair explicitly, but must be exactly two distinct rows and the approval
requires both evidence types. Only those pilot rows may start without approval.
Any selection containing another row, including the full plan, requires a valid
proof approval BEFORE new submissions. It is checked again before each new
non-pilot submission. A zero exit status, ending the nine drawing jobs, or a text
file saying PASS cannot unlock the full batch.

Mechanical approval checks:

- Both proof entries are done, bound to run IDs and execution builds.
- Current source-row fingerprints and AiCost values match the archived results.
- The exact brief, all source pictures and submitted picture paths match.
- Both C and K hold identical source/request/evidence files.
- Inventory hashes verify the workbook, engine record and available reports.
- Engine record quantity, finished service identity, validated unit price and
  price audit match the source quantity and AiCost write-back.
- Proof approval is bound to these exact run IDs, file hashes, rows and builds.
  A changed build, missing archive, edited price, failed run or stale approval
  stops the remainder. The normal global lock and active-run checks still apply.

## Human price-quality check is deliberate

These mechanical checks do NOT prove that a concept's assumed dimensions,
materials, omissions or price are sensible. The operator must inspect BOTH
actual proof estimates and their image/description inputs, then explicitly run
the SAME command's --approve-proof mode instead of --execute. That mode validates
the evidence and writes proof-approval.json to C and K. It does not call an API,
start jobs, change AiCost, clear the batch lock, or restart anything. It can be
used while the separately authorised nine drawing jobs run.

Do NOT add --approve-proof automatically to an overnight chain. Doing so would
pretend the human review took place. Do NOT manufacture a PASS marker. The gate
is a concept-batch permission, not approval to send a customer quotation.

## Sequence for the integrator, after normal release approval

1. Integrate this patch and run the 65 existing tests plus
   tests/test_tti_concept_proof_gate.py (95 tests total at review time).
2. Plan with either quantity switch and verify 154 eligible rows. Preserve the
   exact source workbook and archive paths on every invocation.
3. Explicitly execute --rows 6,12. If that command fails, stop the chain. The
   nine drawing jobs remain a separate authorised drawing-pricer workflow.
4. While those nine run, inspect the two finished proofs. Only if acceptable,
   invoke --approve-proof with the same sheet, roots, server, expected build and
   quantity option. Omit --execute. --approve-proof and --execute are mutually
   exclusive.
5. After the nine end, invoke the full concept command with --execute and no
   --rows filter. It rechecks proof approval and all ordinary safety gates. The
   two done pilots are skipped: 152 remain on this 154-row plan. If approval is
   absent or invalid, it exits nonzero WITHOUT starting any of those rows.

The mode arguments are documented here, not a ready-to-run release/queue block.
This package does not orchestrate or restart the nine drawing jobs itself.
Any external chain must check native process exit codes and must not force past
the gate. Missing proof approval causes a safe STOP, not an unattended wait or
an assumed success.

## Existing proof/state compatibility

Older archived proof entries have no execution-build field and cannot be approved
automatically by this gate. Do not edit their ledger or delete history to bypass
the check: reconcile the existing records/build with the integrator. Likewise,
the prior quantity-policy mismatch guard remains in place. The original 144
valid-quantity row fingerprints and existing blank/zero fingerprints are retained.

## Validation boundary

The 65 baseline tests were run on the actual files fetched at the pinned commit.
The added 30 cases cover both switches, arbitrary quantity text and true Excel
errors, original-value retention, no approval, failed/partial proofs, missing or
tampered C/K evidence, changed source/AiCost, stale build, arbitrary PASS markers,
explicit approval, no pilot duplication, and mandatory CLI gate plumbing.
All service operations in these tests use a fake API. No real proof price, live
service submission, share filing, or full repository suite was run here.
