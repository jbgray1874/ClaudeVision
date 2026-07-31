# Canonical BOM and route cutover

This branch turns the reviewed job-level route compiler into the workbook authority. Its
single purpose is to prepare the BOM hierarchy and manufacturing route accurately for an
estimator to validate and finish.

The canonical repository at `C:\ClaudeVision` has not been modified. This implementation
is in the isolated writable copy:

```text
C:\Users\james.gray\Documents\Codex\2026-07-29\can\ClaudeVision-route-cutover
branch: route-compiler-cutover
```

## Authority model

```text
GA/BOM hierarchy + LLM/DXF/SolidWorks/rule evidence
    -> PartNode graph
    -> ranked OperationClaims
    -> one OperationDecision per job event
    -> canonical workbook BOM and labour rows
```

- Assemblies, fabricated leaves and bought-ins are classified from the hierarchy.
- Assembly operations belong to an assembly target and are charged once per assembly
  occurrence; participant count does not become operation quantity.
- Part operations may share a tooling setup, but every source decision ID stays attached.
- Required, ruled-out, not-applicable and unverified claims are arbitrated before costing.
- The workbook renders required decisions only. It does not reconstruct a route from raw
  operation words.
- Missing fabricated BOM leaves, unverified decisions, missing required rows, resurrected
  negative decisions and duplicate decision joins block release.

## Workbook behaviour

`SDI_CANONICAL_ROUTE_WORKBOOK` defaults to enabled on this branch. Set it to `0` only for
an explicit legacy comparison run.

When enabled:

- canonical BOM identity and hierarchy quantity replace generated aliases and flat guesses;
- explicit unpriced bought-ins remain visible for estimator pricing;
- assembly nodes never enter sheet-material blocks;
- fabricated leaves without estimate records are not invented and become blockers;
- inserted hardware is routed before folding;
- welding, dressing, powder coating and assembly use their job-level event multiplicity;
- different powder finishes remain separate setup rows;
- each workbook route row carries its canonical decision ID(s);
- workbook failure does **not** invoke the legacy fallback builder.

The output workbook also receives `Canonical BOM` and `Canonical Route` audit sheets.

## Files changed

- `src/route_compiler.py`: job graph, identity reconciliation, hierarchy quantities,
  claim arbitration, deterministic hardware/assembly events and stable decisions.
- `src/config.py`: canonical workbook cutover switch.
- `src/estimator.py`: existing proposal integration preserves route context and stamps the
  compiled graph after estimation.
- `src/wb_populate.py`: canonical BOM normalisation and decision-only workbook rendering.
- `src/invariants.py`: blocking cutover checks and one-to-one decision/workbook joins.
- `src/main.py`: stamps cutover mode and fails closed instead of writing a legacy fallback.
- `tests/test_estimating_rules.py`: 2085, 12120, hierarchy, quantity, finish, missing BOM,
  arbitration and render-boundary regression contracts.

## Validation

```text
162 regression fixtures
0 failures
```

The suite was run with `C:\Python314\python.exe -B`. Existing invalid-escape
`SyntaxWarning`s in unrelated documentation strings remain.

Direct projection of the latest saved job JSONs produced:

- **2085:** one assembly Weld, one Dress, one Powder event; Laser only on the plate;
  `tube_cut` on both tubes; no per-part handling resurrection.
- **12120:** seven leaf Laser events; one hardware-insertion event before Fold; one Weld
  and Dress event on assembly 101; assembly events on 103, SA01 and GA; no required
  Laser/Fold on assembly parents.

The saved 12120 JSON also contains the old disconnected `BI-SCREENCABLE` record, so the
compiler correctly reports a blocker on that stale artefact. A fresh run containing the
already-landed reference-only cable fix should remove it.

An actual `.xlsx` render was not executed in this restricted review environment because
the available validation interpreter does not contain the project workbook dependency.
Run 2085 and 12120 through the normal project venv before merging.

## Acceptance runs

Run 2085 twice unchanged, then 12120:

1. Confirm the second 2085 run reuses both LLM cache passes and produces identical labour.
2. Confirm every canonical workbook row has decision ID(s).
3. Confirm no required decision is missing and no negative decision is priced.
4. Confirm assemblies are absent from sheet-material blocks.
5. Confirm 12120 hardware quantities and insertion-before-fold sequence.
6. Have an estimator validate rate basis, powder rate, section rate, packaging, delivery
   and margin. Those commercial inputs are intentionally outside this structural cutover.
