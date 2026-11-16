# Open, and deliberate divergences

## Against the proposed invariants

| ID | State |
| --- | --- |
| E1 | occurrences are stamped with source page and parent before any merge — **held**, without a separate ledger schema |
| E2 | **diverged, deliberately** — see below |
| E3 | no merge deletes an occurrence or an edge; both merge points key the line — **held** |
| E4 | repeated generic codes stay scoped occurrences — **held** |
| E5 | zero, one or many roots — **held** |
| E6 | assembly carries no leaf material (`estimator.py:1751`, pre-existing) and no leaf ops (new) — **held**, and now checked |
| E7 | `RAW` is an explicit negative (`finish_rules` `bare` family, pre-existing); the GA note only fills a finish the part does not state — **held** |
| E8 | priced rows joining to canonical decisions — **not assessed** |
| E9 | parent/child duplicate-op checks reading calculated rows — **not assessed** |
| E10 | the disconnected-node issue now carries `bom_stated_parent` and whether it named a known node — **partly**; still reported as an issue rather than reclassified as a compiler defect |

### The E2 divergence

> Every non-empty `bom_parent` produces an explicit ownership edge.

Not done as stated, and it should not be. `merge_boms` sets the parent label to the title
block when a reader found one and falls back to `"<file>#<page>"` when none did. An edge
made from that would create a phantom assembly carrying real children — a node named
`12392-04-GA.PDF#0` at the head of a tree, costed and packed.

What is implemented: every parent that names something the job already knows becomes an
edge, where "knows" includes the job's own drawing numbers — an assembly whose drawing we
opened exists, which is evidence rather than inference. A label matching neither makes no
edge and the child stays visibly disconnected, carrying the label that was refused.

A missing edge can be seen. A wrong one cannot.

## The four-layer contract

I would not build the observation ledger as a separate layer. Its value is E1 and E3 —
occurrences immutable before any merge — and that is now true at both merge points without a
new schema, compatibility adapters or a migration. The remaining layers largely describe what
the code already does once the parent survives.

That is a judgement about cost, not a disagreement about the design. If the ledger is wanted
for reasons beyond these four contracts — replay, audit trail, cross-job learning — it is a
different case and a good one.

## Genuinely open

**Finish ownership at the leaf.** `01M` RAW while only `02M` takes panel powder. `RAW` already
rules powder out for a part that states it; what is untested is whether `01M` on the real job
*carries* `RAW` or carries nothing. If it carries nothing, the GA's powder note applies and
the part is coated. That is a reading question, not a rules question, and it needs the run.

**E8 / E9.** Whether every priced workbook row joins to a canonical decision, and whether the
existing `check_an_operation_is_not_charged_on_a_parent_and_its_child` reads calculated rows
rather than shadow decisions. Neither examined.

**A synthetic enquiry root.** Not added. The forest works without one and an extra costed node
is a liability. Worth adding only if reporting wants a single header per enquiry.

**`SDI_DUALPATH_BOM` still defaults OFF.** Contract 1's attribution now supplies `bom_parent`
without it, so the compiler works either way — but the dual-path reader is the better source
(it reconciles a deterministic table read against vision, per page, and does not deduplicate).
Turning it on is a separate decision with its own regression cost.

## Warning: concurrent work

The explorer agent reported it was also implementing this in the live source. Two agents on
the same merge path will conflict, and the conflicts will be silent — both will produce
plausible code in `file_scan`, `bay_rollup` and `route_compiler`. Everything in this bundle is
on `claude/codebase-improvements-jcl03i` at `bb0c82b` and later. Confirm which branch the
other work landed on before merging either.
