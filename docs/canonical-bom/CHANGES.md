# Every change, file by file

Five commits on `claude/codebase-improvements-jcl03i`, base `9a3be89`.

```
9e3501f  A BOM line is (parent, code); the merge only knew the code
f966c37  The BOM states parents, and an enquiry can ship more than one thing
f72d3ec  An assembly is not a blank, and the label arrives spelled differently
bb0c82b  The ownership was never recorded, so nothing downstream could recover it
(this)   One predicate for "is this a parent", and a check that says when it is charged as a blank
```

---

## `src/file_scan.py`

**`_page_drawing_number(page)` — new.** The drawing a page IS, from its own title block.
Deliberately the title block and nothing else: a drawing number elsewhere on a sheet is
usually a reference to another sheet, and taking one would make a detail claim to own the
assembly that references it. A region that caught two `DWG NO` matches names neither —
there is no way to tell a cross-reference from the sheet's own number, and naming the wrong
one gives every row on the page the wrong owner.

**`attribute_bom_rows_to_source_pages(rows, pages)` — new.** Stamps `source_page` and
`bom_parent` on each row. Does **not** change which rows are read: the joined-text pass
produces exactly the rows it always did, and this walks them afterwards, matching each to
the page whose BOM region names it. Each page's occurrences are consumed as claimed, so a
fastener on two sheets gets one row per sheet. Returns how many were placed.

**Called from `summarise_document`**, which now prints:

```
[bom] 14/14 row(s) traced to a sheet; 14 carry the drawing that owns them
```

and says explicitly when no title block named a drawing — a gate nobody asks reports
nothing, and this one silently not firing is exactly how the defect reached a customer
price.

**`merge_job_pdf_summaries`** keyed `bom_by_key` on the normalised part number across the
whole folder. It now keys `(parent, code, description)`. This is the earliest of the three
collapses and the one that ran before anything else could see the rows.

**`apply_canonical_evidence_to_parts` call site** now passes the BOM rows and the job's own
drawing numbers.

## `src/bay_rollup.py`

**`_row_parent(row)` — new.** Reads `bom_parent` / `parent` / `parent_code`, falling back to
`source_pdf` — the folder merge stamps that on every row, so even a reader that records no
page label still tells two drawings apart. Distinguishing two lines needs only a
discriminator; naming an owner needs a part, which is why the compiler does **not** accept
`source_pdf`.

**`dedupe_bom_rows_for_bay_rollup`** was one row per code. Now one row per `(code, parent)`.
An unparented row joins the first parented line for the same code rather than becoming a
second line — it cannot be shown to be separate, and keying it on `""` would count the part
twice. Announces any code owned by more than one assembly.

## `src/route_compiler.py`

**`_code_spellings(value)` — new.** The near-miss. `merge_boms` takes the parent from the
title block verbatim — its own docstring gives `"1282 - GA"` — while this module's
`clean_part_number` only uppercases and collapses whitespace, so the reader produces
`12392-04 - GA` and the graph holds `12392-04-GA`. Every test for the new hierarchy source
was written in the graph's spelling and passed while the source would have matched nothing
on a real drawing. Both spellings are offered; the matcher takes whichever names something
it already knows, which is safe because the identity still has to exist. Fixed at the match,
not at `clean_part_number` — changing the canonical spelling would move every identity in
the graph.

**`_bom_stated_edges(...)` — new.** `(child, parent, qty)` for every BOM row naming an owner
we already know. Three refusals, each documented at the point it is enforced: no parent is
created from an unknown label except a drawing we opened; nothing another source placed is
re-parented; `source_pdf` is not an owner.

**`job_drawing_numbers(summary)` — new.** The drawing numbers the job opened, from the file
names it read. A GA can produce no part record of its own — it is the sheet that lists the
parts — and on 12392 that is exactly what happened to the second drawing. No assembly code
is derived from a descriptive file name.

**Forest roots.** `top_ids` is every node that owns children and that nothing owns, plus any
explicitly declared top. Each cascades at one per unit: two GAs on one enquiry are two
things that ship. `top_assembly` unchanged; `top_assemblies` added.

**`_roots_that_ship(graph)` — new.** Three readers asked `== graph["top_assembly"]` when
their real question was "is this something that ships, and therefore packed and sequenced
last". On a two-GA job the second could own a weld, lose its assembly event, and leave the
sheet with no Assemble/pack row for something somebody still has to box.

**BOM edges accumulate among themselves.** Refusing any child that already had a parent also
refused the *second* BOM line, so the panel's 16 screws became an edge and the bracket set's
4 became nothing — the cascade summed 16 where the drawings say 20. Another source still
wins outright; two BOM rows naming two owners are not in conflict.

**Leaf-op strip wired.** `apply_canonical_evidence_to_parts` has written *"its material and
leaf-only fabrication belong to its children"* onto assembly parents for as long as it has
existed, and nothing read it. It now also stamps `canonical_kind` so later passes read one
answer.

**Disconnected-node issue** carries `bom_stated_parent` — when an edge is refused, the label
that was refused is the most actionable fact about why the node is still there.

## `src/bought_in_policy.py`

**`LEAF_ONLY_OPS` — new.** A deliberate subset of `FABRICATION_OPS`. Joining stays (welding
and bonding are what an assembly IS); finishing stays (a welded frame is coated as one thing
after joining). What remains cuts, forms or dresses a single blank.

**`strip_leaf_operations(part)` — new.** Mirrors `strip_fabrication_ops`, the same mistake in
the other direction. Does nothing unless the record is already classified an assembly — that
is the graph's question and this never second-guesses it.

**`is_assembly` / `assembly_reason` — new.** One predicate for the four field names that mean
the same thing, plus the graph's fifth. A union, so no consumer recognises fewer parents than
before.

**The bought-in default** now yields to SDI's numbering convention as well as to a stated
family. `12392-04-01M` is not a name; it is the convention for a part we cut in metal.

## `src/json_normaliser.py`

The part-number suffix rule asked whether the material text was **absent** when it means
whether the text **said anything**. Those differ on a noisy drawing, which is the common
case: `"Card 2mm"`, `"N/A"`, `"TBC"` are non-empty and resolve to nothing, and each silently
outranked the numbering convention. The four-token blacklist it relied on was a sample of
that rule, one entry per job that had gone wrong.

The text is deliberately **not** blanked: `PMMA` and `DISPA` also resolve to nothing and are
read as substrings further down.

## `src/part_code_conventions.py`

**`material_suffix(identity)` — new.** `base_code` has always *stripped* the material letter;
nothing could ask what it said.

## `src/estimator.py`

`_is_weldment_parent` knew four field names and not `canonical_kind`. Asked through the
shared predicate now, unioned — it can only recognise more parents, and the failure direction
it guards is a parent charged as a leaf, which books material and fabrication twice.

## `src/invariants.py`

**`check_bom_lines_survive_the_merge`** — compares the two lists the engine has held all
along. Claims only codes the readers recorded under several parents that reach costing under
fewer; a code that vanishes whole has other causes.

**`check_an_assembly_is_not_charged_as_a_blank`** — asks the question at the end, where four
spellings have collapsed into one observable fact. A measured flat still outranks a
transcribed tree. Joining and finishing are not asked about.
