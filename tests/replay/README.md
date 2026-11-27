# Frozen-evidence replays — the fast layer of the two-layer harness

Each subdirectory is one estimator-REVIEWED job. It holds:

- `summary.json` — the run's saved record, copied verbatim from
  `output/json/<job>.json` **of the accepted run** (the one the estimator signed off,
  never "whichever run last passed"). **A directory without one FAILS the suite.** It used
  to skip with a loud message and the message was not loud: four skips inside a 4,600-test
  run is indistinguishable from four passes, and both packs here sat unprotected for weeks
  while every push reported green. Set `SDI_REPLAY_ALLOW_MISSING=1` to downgrade that to a
  skip while working on a checkout without the packs; **CI must never set it**.
- `provenance.json` — who accepted this record, when, and where it came from. Required
  whenever `summary.json` is present; see `provenance.template.json`. A baseline nobody can
  attribute cannot be audited.

**Freeze with `tools/freeze_replay_fixture.py`, not by copying by hand.** It CHECKS that the
record is the run you say it is: `processed_at` is stamped by the run itself, so it is
evidence, and a mismatch against `--accepted-on` stops the freeze with nothing written. A
fixture frozen by hand was once labelled "the 14:17 pack, 7 Sep" while the record inside
carried 10 September 18:59 — a different run wearing the accepted baseline's numbers. **Typing
an older date does not make the input that run.** If a newer run genuinely is the new baseline,
pass `--accept-new-baseline` and its own date is recorded.

Pass `--source` pointing at an **archived** copy. `output/json/<job>.json` is rewritten by the
next run of that job, so provenance pointing there names a path whose contents will not be what
was frozen. Keep the full record archived: the tool records its sha256, and fingerprint equality
proves equivalence only for the checks that exist today.
- `accepted_facts.json` — the estimator-reviewed STRUCTURE the engine must reproduce:
  BOM identities and quantities, operations per part with the ruled-out set, decisions
  expected, names that must appear nowhere. **Structure, not money** — rates move,
  identities and routes must not.

`test_frozen_replays.py` runs three tiers against each frozen summary:

1. **the record and the deliverables** — `costed_facts` plus both HTML builders, diffed
   against `accepted_facts.json`.
2. **the workbook canonicalisation stage** — re-executes the identity gates, the
   multiplicity roll and the missing-bought-in mint on the frozen RAW population.
3. **routing and material costing** — re-executes `route_compiler.compile_job_route` and
   `estimator.estimate_material`, so a required route is **re-derived** from the inputs
   rather than read back off the stored record, and a part the facts say carries material
   still prices above zero when costed from scratch. Rendering an already-costed JSON
   catches reporting drift and nothing else.

It gates every push in the Linux environment; the full Windows runs (extraction,
SolidWorks, Excel, read-back) are the second layer and run on the box. **Money is never
pinned here** — rates move. The accepted numbers live in `provenance.json` for the Windows
reconciliation.

## Freezing a job

    copy output\json\10975-02.json  tests\replay\10975-02\summary.json

then commit. Keep the accepted-facts file under estimator review: a change to it is a
POLICY change, not a test fix.

## accepted_facts.json format

    {
      "bom_identities": ["10975-02-A01", ...],   // exactly these lines, no more
      "quantities": {"10975": 3},                // spot-pins, not exhaustive
      "required_operations": {"10975-02-A01": ["linebend", "laser_cutting"]},
      "forbidden_operations": {"10975-02-A01": ["folding", "hole_machining"]},
      "forbidden_operations_anywhere": ["powder_coating"],   // on ANY part, not one
      "material_charged": ["7332-01-002"],       // material money must REACH this line
      "no_minted_children": ["7332-01-002"],     // no stock-child invented under it
      "decisions_expected": 2,                   // open manufacturing decisions
      "forbidden_names_everywhere": ["1100997755-E0P2D-GM0", "BI-CELLTAPE"],
      "phrase_counts": {"prices_missing": 3, "market_figures": 1, "manufacturing": 2}
    }

Three of those need a word on why they exist:

- `forbidden_operations_anywhere` — a per-part forbid misses a finish that reappears on a
  DIFFERENT part. Ruling powder off 7332-01-002 would not have caught it landing on 101.
- `material_charged` — presence, not a rate. A line can be present and correctly routed and
  still carry no material money; identity and route checks both pass on it.
- `no_minted_children` — rather than charging a leg's own tube, a child node gets minted
  beneath it to carry the stock, so the money lands twice or on a node no estimator has seen.

Every key is optional; only what an estimator has actually reviewed gets pinned. A key no
check reads is rejected by `tests/test_the_replay_gate_is_a_gate.py` — a pin nobody executes
reads as protection and is not. That file also proves each check against a synthetic record,
so the pins are executable even while no pack is frozen.

Every key is optional; only what an estimator has actually reviewed gets pinned.
