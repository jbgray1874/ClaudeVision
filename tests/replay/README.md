# Frozen-evidence replays — the fast layer of the two-layer harness

Each subdirectory is one estimator-REVIEWED job. It holds:

- `summary.json` — the run's saved record, copied verbatim from
  `output/json/<job>.json` **of the accepted run** (the one the estimator signed off,
  never "whichever run last passed"). **A directory without one FAILS the suite.** It used
  to skip with a loud message and the message was not loud: four skips inside a 4,600-test
  run is indistinguishable from four passes, and both packs here sat unprotected for weeks
  while every push reported green. Set `SDI_REPLAY_ALLOW_MISSING=1` to downgrade that to a
  skip while working on a checkout without the packs. **A frozen record is job data and is
  never committed** (SCRUM-137), so GitHub CI cannot hold one: it sets the opt-out and
  prints every such skip by name (`-rs`). The laptop's acceptance run, which holds the
  records, must never set it: there a missing record is a failure (SCRUM-134, SCRUM-135).
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

## Making a baseline, start to finish (SCRUM-134)

All on the laptop, against the run an estimator has ACCEPTED:

1. List the job's saved records, each with the date it says it ran, and pick the accepted one.
   If it is only in `output\json`, copy it into `output\archive` first: the next run of the job
   rewrites `output\json`.

       python tools\freeze_replay_fixture.py 9439-07-04 --find

2. Draft the facts from it. The draft is read by the same readers the gate runs, so every pin it
   proposes holds on the accepted run; it pins structure only, never money:

       python tools\draft_accepted_facts.py 9439-07-04 --source output\archive\9439-07-04_accepted.json

3. An estimator reviews `accepted_facts.draft.json`: strikes any pin that is not a rule for this
   job, trims each material to the words that would show a swap, confirms or strikes each
   allowed repeat, and replaces the DRAFT notice in `_reviewed` with who accepted the run and
   when. Then rename it `accepted_facts.json`. The gate refuses a file still marked DRAFT, and
   draft files are never committed.
4. Freeze the record (below). Then run every baseline:

       python tools\run_replay_baselines.py

   It prints one line per job, PASS, FAIL, NOT FROZEN or DRAFT ONLY, and exits 0 only when every
   reviewed job passes. It clears `SDI_REPLAY_ALLOW_MISSING` itself: this machine holds the
   records, so a missing one is a hole, not a skip.
5. Send the reviewed `accepted_facts.json` to the cloud session to commit, so both repositories
   carry it. The frozen record, provenance and fingerprint stay on the laptop.

The order the ticket sets: 9439-07-04 and 9287-10-GA first, then 0320730, 401918 and 0351292.

## Freezing a job

    python tools\freeze_replay_fixture.py 10975-02 --find

then freeze the accepted run with `--source` and its run, person, date and figures (the tool's
own help has a complete example). It writes `summary.json`, `provenance.json` and
`fingerprint.json` into the pack. **They stay on the laptop and are never committed**: they are
job data (SCRUM-134, SCRUM-137), and `.gitignore` ignores all three (D-624). Only
`accepted_facts.json` is committed. Keep it under estimator review: a change to it is a POLICY
change, not a test fix.

## accepted_facts.json format

    {
      "bom_identities": ["10975-02-A01", ...],   // exactly these lines, no more
      "quantities": {"10975": 3},                // spot-pins, not exhaustive
      "required_operations": {"10975-02-A01": ["linebend", "laser_cutting"]},
      "forbidden_operations": {"10975-02-A01": ["folding", "hole_machining"]},
      "forbidden_operations_anywhere": ["powder_coating"],   // on ANY part, not one
      "material_charged": ["7332-01-002"],       // material money must REACH this line
      "materials": {"7332-01-002": "STAINLESS 304"},   // every word must be on the line
      "no_duplicate_operations": true,           // no op charged on two rows of one part
      "allowed_repeats": {"7332-01-002": ["folding"]}, // ...except these, reviewed
      "no_minted_children": ["7332-01-002"],     // no stock-child invented under it
      "decisions_expected": 2,                   // open manufacturing decisions
      "forbidden_names_everywhere": ["1100997755-E0P2D-GM0", "BI-CELLTAPE"],
      "phrase_counts": {"prices_missing": 3, "market_figures": 1, "manufacturing": 2}
    }

Some of those need a word on why they exist:

- `forbidden_operations_anywhere` — a per-part forbid misses a finish that reappears on a
  DIFFERENT part. Ruling powder off 7332-01-002 would not have caught it landing on 101.
- `material_charged` — presence, not a rate. A line can be present and correctly routed and
  still carry no material money; identity and route checks both pass on it.
- `no_minted_children` — rather than charging a leg's own tube, a child node gets minted
  beneath it to carry the stock, so the money lands twice or on a node no estimator has seen.
- `materials` — a swapped material keeps every identity, quantity and route intact. Each word
  of the pin must appear in the line's material, so print differences pass and a swap fails.
- `no_duplicate_operations` with `allowed_repeats` — a line names each operation once whatever
  the rows say, so the record also counts the priced rows per operation
  (`operation_charges`). A repeat the estimator accepted is listed and passes; any other
  fails.

`_reviewed`, `_review` and `_money_note` are commentary: no check reads them, and they may
quote the accepted numbers.

CI cannot hold a record, so `tests/test_the_replay_gate_is_a_gate.py` builds, for every
committed pack, the smallest synthetic record that keeps its pins, proves it passes, then plants
each break the pins claim to catch (a missing part, a wrong quantity, a swapped material, a
duplicate operation, a lost required operation, a ruled-out operation charged, a made part
with no material money) and proves each one fails. A pin that could never fail is found there.

Every key is optional; only what an estimator has actually reviewed gets pinned. A key no
check reads is rejected by `tests/test_the_replay_gate_is_a_gate.py` — a pin nobody executes
reads as protection and is not. That file also proves each check against a synthetic record,
so the pins are executable even while no pack is frozen.
