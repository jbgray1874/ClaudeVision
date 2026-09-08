# Frozen-evidence replays — the fast layer of the two-layer harness

Each subdirectory is one estimator-REVIEWED job. It holds:

- `summary.json` — the run's saved record, copied verbatim from
  `output/json/<job>.json` **of the accepted run** (the one the estimator signed off,
  never "whichever run last passed"). Not committed for every job by default — copy it
  in from the box; a directory without one is reported as skipped, loudly.
- `accepted_facts.json` — the estimator-reviewed STRUCTURE the engine must reproduce:
  BOM identities and quantities, operations per part with the ruled-out set, decisions
  expected, names that must appear nowhere. **Structure, not money** — rates move,
  identities and routes must not.

`test_frozen_replays.py` drives each frozen summary through the costed record and both
HTML deliverable builders — everything downstream of extraction that runs without Excel —
and diffs the result against `accepted_facts.json`. It gates every push in the Linux
environment; the full Windows runs (extraction, SolidWorks, Excel, read-back) are the
second layer and run on the box.

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
      "decisions_expected": 2,                   // open manufacturing decisions
      "forbidden_names_everywhere": ["1100997755-E0P2D-GM0", "BI-CELLTAPE"],
      "phrase_counts": {"prices_missing": 3, "market_figures": 1, "manufacturing": 2}
    }

Every key is optional; only what an estimator has actually reviewed gets pinned.
