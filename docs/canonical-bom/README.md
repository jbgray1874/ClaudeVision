# Canonical BOM contract — what changed, and why

**Branch:** `claude/codebase-improvements-jcl03i`
**Scope:** the four code contracts behind the recurring hierarchy failures.

This directory is the handoff bundle. The changes themselves are in `src/` — nothing here
is a patch to apply, it is the record of what was done and how to verify it.

| File | Contents |
| --- | --- |
| `README.md` | this — the four contracts and their state |
| `CHANGES.md` | every change, file by file, with the reasoning |
| `VERIFICATION.md` | what was tested, what was mutation-tested, what was not |
| `OPEN.md` | what is deliberately not done, and the divergences from the spec |

---

## The four contracts

### 1. `file_scan.py` and `bay_rollup.py` globally collapse BOM lines by part code — CLOSED

Both did, at three separate points, and one of them ran before anything else could see the
rows. All three now key on the **line** — `(parent, code, description)` — not the code.

The root, though, was one layer earlier than the contract states. `summarise_document`
joins every page's BOM region into a single string and runs one regex over the lot, so a
row arrived with an item number, a code, a description, a quantity and **no idea which
sheet printed it**. The parent was not collapsed later; it was never captured. Every
downstream attempt to rebuild the tree was reconstructing something the first read had
discarded, which is why each attempt half-worked and the next drawing surfaced the same
class again.

`attribute_bom_rows_to_source_pages` records it at the only point it is still knowable,
without changing which rows are read.

### 2. `bom_pipeline.py` records `bom_parent`, `route_compiler.py` never consumes it — CLOSED

It does now, as a third hierarchy source alongside the description rule and the extract.

**A live near-miss worth knowing about.** `bom_pipeline` sits behind `SDI_DUALPATH_BOM`,
which **defaults OFF** — its own comment reads *"Flag OFF => byte-identical to baseline"*.
So the field the compiler was taught to read did not exist on an ordinary run. The fix was
correct, tested, and would have been a silent no-op on every real job. Contract 1's
attribution is what makes contract 2 fire, and neither is sufficient alone.

### 3. The graph assumes one root — CLOSED

`build_part_graph` asked for **the** top assembly, singular. With two general arrangements
the second was not the top, had no parent, and was reported as a disconnected node; had the
extract read neither, `top_id` would have been blank and the quantity cascade would not have
run at all, leaving every part at its own drawing quantity.

A root is now any node that owns children and that nothing owns. `top_assembly` keeps its
old meaning for every existing reader; `top_assemblies` is the forest.

### 4. Finish, operations and priced rows use separate ownership rules — CLOSED

Not what it looked like from outside. Two of the three were already implemented:

- **Material** — `estimator.py:1751` already zeroes material on a parent and carries it on
  the children.
- **Finish** — `finish_rules.FINISH_FAMILIES` already has a `bare` family (`RAW`, `SELF
  COLOUR`, `MILL FINISH`…) that rules powder out, and the GA's general finish note only
  fills a finish the part does not state. `RAW` is already an explicit negative.
- **Operations** — was genuinely missing, and is the 12392 symptom.

What the contract actually describes is that each pass keys on a **different field name**
for the same idea. `estimator.py` says so in its own comment:

> both suppressions here and in estimate_part keyed on `is_assembly_parent`, a different
> name for the same idea

and the canonical graph then added a fifth spelling, `canonical_kind`. There is now one
predicate, `bought_in_policy.is_assembly`, a union of every spelling, so no pass can
recognise fewer parents than it did before.

---

## The safety property

Every change is additive **by construction**, not by a flag. That is what lets it run on
every job rather than behind a switch nobody turns on:

- **Splitting a line requires two RECORDED parents.** No parent evidence anywhere → the key
  falls back to the code and the behaviour is identical to the dictionary it replaced.
- **A BOM edge is only ever made where nothing else claimed the part.** An extract or a
  model that placed it still wins outright.
- **A parent naming nothing we know makes no edge.** `merge_boms` falls back to
  `<file>#<page>` when no title block was read, and a node invented from that would be a
  phantom assembly carrying real children.
- **A one-GA job resolves to the same single root** and compiles identically with and
  without BOM rows.
- **The op strip does nothing** unless the graph already classified the record as an
  assembly, and never touches joining or finishing.

The one change that can move a number on an existing job is the leaf-operation strip. See
`VERIFICATION.md` for what to re-run before trusting it.
