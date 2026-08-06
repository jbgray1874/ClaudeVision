# What was verified, and what was not

**365 tests pass in any order** (309 before this work, 56 added).

```
tests/test_bom_occurrence.py     15   where each row came from, and the cross-PDF merge
tests/test_bom_line_identity.py  18   line identity, material reading, make/buy
tests/test_bom_forest.py         23   the forest, the refusals, assembly scope
```

Run from the repo root:

```
python -m pytest tests -q
```

---

## Mutation testing

A test that cannot produce the condition it asserts on has proved nothing. Every guard was
disabled in turn and the original defect had to return.

| Guard disabled | Defect that returned |
| --- | --- |
| `bay_rollup._row_parent` → `""` | rollup keeps one FIXING line of 16; the 4-off line is dropped |
| `_bom_stated_edges` → `[]` | `12392-04-01M` and `-02M` are disconnected nodes again |
| forest roots → single | `12392-04-GA` is not a root; its subtree never cascades; it is reported as an orphan |
| `_code_spellings` → one spelling | the title-block form `12392-04 - GA` matches nothing; the whole hierarchy source silently does nothing |
| leaf-op strip, on a leaf | a non-assembly keeps every operation — so the classification decides, not the operation names |

The `_code_spellings` mutation is the one worth dwelling on: **all 23 forest tests passed
before that guard existed**, because they were written in the graph's spelling rather than
the reader's. It was caught by checking what `merge_boms` actually emits, not by a test.

## The end-to-end case

The configuration an estimator will actually run — two PDFs in a folder, `SDI_DUALPATH_BOM`
unset, no LLM extract for the second drawing, no native model:

```
roots            ['12392-02-GA', '12392-04-GA']
parents          12392-02-201 <- 12392-02-GA
                 12392-04-01M <- 12392-04-GA
                 FIXING       <- 12392-02-GA, 12392-04-GA
FIXING quantity  20.0            (the drawings say 16 + 4)
disconnected     none
```

This is `test_the_tree_is_built_from_drawings_alone_with_every_flag_off` and
`test_a_fastener_both_drawings_use_is_owned_by_both_and_summed`.

---

## What has NOT been verified

**No real job has been run.** This clone has no drawings, no shares and no `output/json`, so
every result above is against fixtures built from the 12392 evidence. The fixtures are
faithful to the shape — page regions, title-block text, the row fields the extractor emits —
but they are not the job.

Two things need a real run before this is trusted:

### 1. Re-run 12422-24 at 10 off — the regression baseline

£117.35 unit, £44.11 material, £65.02 labour, 0 blocking. **The leaf-operation strip is the
only change here that can move a number on an existing job.** If 12422 moves, the cause will
be in the `removed_operations` stamps on the affected records and the `review_flags` sentence
next to them.

### 2. Re-run 12392-02 and -04 in one folder — the case this was built for

Now a supported shape. Watch the console for:

```
[bom] N/M row(s) traced to a sheet; K carry the drawing that owns them
```

- **K = 0** — no title block on any BOM page named a drawing. The hierarchy will not build
  and everything else here is inert. Send the console output; the `DWG NO` pattern needs
  widening for these drawings.
- **N < M** — some rows could not be matched back to a page. Those rows carry no parent and
  will show as disconnected if nothing else claims them.
- **N = M, K = M** — working. Expect two roots, both fastener owners, and no
  `bom_node_disconnected` for anything the BOM parented.

Then:

```
[canonical-part-graph] applied before costing: N node(s); 2 assemblies ship on this enquiry (12392-02-GA, 12392-04-GA)
```

### 3. Regression set

2085, 12120, 11350, 12422 — all single-root jobs, all of which should be **unchanged**. That
is the claim the safety property makes and it is the one worth falsifying.
