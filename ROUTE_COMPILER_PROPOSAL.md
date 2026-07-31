# ClaudeVision canonical route compiler — shadow proposal

This is an isolated review copy. The canonical repository at `C:\ClaudeVision` was not
modified.

- Source branch: `claude/codebase-improvements-jcl03i`
- Source commit: `69ed0c774cb11794c01344efd042b30d0e21827a`
- Proposal mode: **shadow only**
- Workbook cutover: **not implemented**
- Legacy raw-route rescue: **unchanged**

## Design implemented

The proposal compiles one decision per **job event**, not per participant:

```text
PartNode hierarchy
    -> OperationClaim evidence from all current record shapes
    -> OperationDecision with stable decision_id and target_id
    -> shadow PricedRouteRow joined to legacy costs
```

An assembly weld is therefore represented as:

```text
operation: welding
target_id: 12120-01-101
participants: [12120-01-02M, 12120-01-03M]
scope: assembly
qty_per_unit: 1
```

The participant count never becomes the operation quantity.

### Arbitration rules

- Stronger source rank decides status.
- Equal-rank status disagreement becomes `unverified`.
- Matching claims corroborate.
- Scope, target, participants, quantity and sequence are resolved field by field.
- Weaker compatible claims may fill metadata gaps without replacing stronger status evidence.
- Unattributed rulings remain `unknown`; they are never promoted to DXF by default.
- `ruled_out`, `not_applicable` and `unverified` decisions carry no invented quantity.
- Every claim remains in the decision audit trail.

## Files changed

### `src/route_compiler.py` — new

- Defines `PartNode`, `ChildEdge`, `OperationClaim` and `OperationDecision`.
- Builds the complete parent/child hierarchy from `llm_full_extract.assemblies`.
- Identifies the lowest common assembly for assembly-scoped participant lists.
- Compiles explicit LLM routes and existing raw part fields through a compatibility adapter.
- Creates stable `route_id` and `decision_id` values.
- Splits mixed powder routes into assembly targets and standalone leaf targets.
- Chains `dress_welds` to the owning welding event.
- Treats tube Laser/Punch/Guillotine claims as not applicable when deterministic section
  evidence identifies CHS/RHS/SHS/tube stock.
- Projects required decisions against legacy part costs without changing those costs.
- Reports resurrection, required-unpriced work, participant-costed assembly work and legacy
  costs with no canonical decision.

### `src/estimator.py`

- Adds nested `route_context` to every costed part so route evidence and negative decisions
  no longer disappear at the raw-to-costed boundary.
- Runs the compiler after legacy part estimation.
- Stamps `estimate_summary.canonical_route_shadow`.
- Catches and records compiler failures without changing legacy pricing or producing a
  fallback workbook.

### `src/invariants.py`

- Adds `check_canonical_route_shadow`.
- Reports:
  - unverified route decisions;
  - priced rows without decisions;
  - non-required decisions reaching pricing;
  - duplicate priced-row joins;
  - required-unpriced work;
  - assembly events costed on several participants;
  - legacy costs with no decision.
- Uses warning severity during shadow mode. These checks must become blocking at cutover.

### `tests/test_estimating_rules.py`

Adds six regression fixtures:

1. Ranked status arbitration with field-level metadata gap filling.
2. 12120: one weld/dress event on assembly 101, DXF negative precedence, no parent
   Laser/Fold resurrection and no powder duplication beneath assembly 103.
3. 2085: old scope-less route compiles to one assembly weld, dress and coat; tubes retain
   `tube_cut` and reject sheet Laser.
4. Costed records preserve nested route context without changing legacy top-level fields.
5. `estimate_document` executes and stamps the real shadow compiler.
6. Shadow invariant findings remain warnings until explicit cutover.

### `tools/route_shadow_compare.py` — new

Read-only comparison tool:

```powershell
python tools\route_shadow_compare.py JOB.json --out route_shadow.json
```

It never edits the source job JSON.

### Generated review artefacts

- `review/12120_route_shadow.json`
- `review/2085_route_shadow.json`

These were generated from the latest saved job JSONs in `C:\ClaudeVision\output\json`.

## Validation

```text
154 regression fixtures
0 failures
```

The suite was run with `C:\Python314\python.exe -B`. Existing invalid-escape
`SyntaxWarning`s in unrelated documentation strings remain; they are not introduced by this
proposal.

The real `estimate_document` integration was also executed against both saved job records.
Neither produced a compiler error.

## Real-job shadow findings

### 12120

Canonical interpretation now contains:

- seven leaf Laser events;
- no required Laser/Fold on assembly parents 101 or 103;
- one assembly weld on 101, quantity 1;
- one assembly Dress Welds event on 101, quantity 1;
- separate powder targets for 101, 103, 04M and 08M;
- measured Fold rulings retained on 03M, 04M and 05M;
- the unattributed weld stranded on SA01 marked `unverified`, not silently costed.

The legacy comparison exposes:

- Fold still costed on ruled-out 04M;
- Laser and Fold still costed on assembly 103;
- Weld, Dress and Powder currently costed across multiple participants;
- hole machining, tapping and some handling named but unpriced.

### 2085

Canonical interpretation now contains:

- one assembly powder event on `2085-GA`, quantity 1;
- one assembly weld on `2085-GA`, quantity 1;
- one assembly Dress Welds event on `2085-GA`, quantity 1;
- Laser only on plate 2085-01;
- `tube_cut` on 2085-02 and 2085-03;
- stale tube Laser claims retained as `not_applicable`;
- Fold on 2085-01 retained as `ruled_out`.

The comparison exposes that current legacy Weld/Dress/Powder costs are distributed across
participants and that tube-cut pricing is supplied later by the workbook rescue rather than
the estimator.

## Deliberately unchanged

The following files are not changed in this shadow proposal:

- `src/wb_populate.py`
- `src/file_scan.py`
- `src/source_connectors/llm_full_job.py`
- `src/source_connectors/solidworks.py`
- `src/config.py`

This is intentional. The workbook still renders legacy rows. Existing source writers are
adapted into claims without forcing a same-commit migration.

## Required before cutover

1. Review the two generated shadow JSON files with an estimator.
2. Run fresh 2085 and 12120 jobs from the latest committed branch, not only saved JSON.
3. Resolve every `required_operation_unpriced` and `forbidden_decision_priced` issue.
4. Confirm rate-table basis for assembly welding, dressing and powder coating.
5. Migrate SolidWorks, DXF/note rules and LLM routes to submit native claims.
6. Add an explicit cutover flag.
7. Make canonical-route invariant failures blocking.
8. Switch `wb_populate.py` to render `priced_route_rows`.
9. Delete `route_operations_by_part`, `routed_operations_without_cost`, global
   `_scope_by_op` and the raw-route rescue only after comparison acceptance.

The current proposal is safe to review because it changes no workbook row or live total.
