# Real saved jobs, replayed as regressions

Drop an `output/json/<job>.json` here and the replay fixture in
`test_the_pipeline_builds_the_record_these_rules_read` asserts the structural
properties against it: every BOM node has an owner, and a part that mirrors a
measured part does not reach costing with no blank.

This exists because every defect found on 11350 was invisible to hand-written
fixtures. A dict written by the same person who wrote the rule cannot disagree
with it about the shape of a record — and three times in a row that is exactly
what went wrong. A saved job can disagree, and did.

Nothing here is required for the suite to pass. What is here is replayed.
