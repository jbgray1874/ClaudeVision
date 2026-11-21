# Quantity-one ruling: amendment to the concept package

User instruction, 21 November 2026: "if no quantities, price as 1".

This supersedes the ten quantity holds ONLY when the integrator supplies the
explicit `--assume-missing-quantity-one` option to the concept batch. Add the
option to BOTH the planning/proof command and the subsequent full-batch command.
Without the option the original strict behaviour remains unchanged.

The authorised scope includes the ten previously identified blank/zero rows:
65, 93, 94, 105, 106, 107, 208, 209, 210, 211. It does not convert negative,
fractional, nonnumeric, boolean or non-finite quantities. Drawing rows remain
excluded. Effective quantity becomes one, while source Quantity cells stay as
provided. The prompt and C/K source/request/price audit identify the assumption.

The original workbook now plans 154 eligible concept rows under this option,
not 144. No live prices were produced to verify this amendment. No jobs started,
services changed, stale locks cleared, or production workbook written.

## Price meaning (unchanged)

AiCost is **GBP per unit at the requested order quantity**, never the row total.
For a quantity-four run with a unit cost of 12.34, AiCost is 12.34 and the order
total is 49.36. The price audit now records both `unit_gbp` and `order_total_gbp`
with an explicit AiCost basis. It does not add/alter another spreadsheet column.
Blank/zero source quantities have an effective order quantity of one for this
calculation, without editing the source N cell. Existing workbook total formulas
are preserved; they are not converted into AI-total formulas by this amendment.

## Integration and resume

Apply this amendment on top of the original six-file concept package, not on
top of the bare engine. The patch changes five existing concept files and adds
this document. Its payload copies are supplied for comparison, not a second
application. Keep tests/actual workbooks and verification private as before.

If no concept batch has started: integrate now, run the tests, regenerate the
plan with the option, then use the same option for the later authorised pilot
and full batch. The 144 original valid-quantity row fingerprints are unchanged.

If a concept plan has already been archived under the old hold policy, the
amendment deliberately STOPS on a policy mismatch. It does not silently extend
an in-progress batch or erase state. Ask the integrator to reconcile that plan
before adding the ten rows. Do NOT delete the old archive or create another full
batch to bypass this guard; that risks duplicate jobs.

This is an integration-only amendment. Existing drawing jobs and all release
decisions remain separate. The real two-row image/description proof is still
required. The original README's 144-row/ten-held count describes strict mode;
this document governs the newly authorised quantity-one mode.
