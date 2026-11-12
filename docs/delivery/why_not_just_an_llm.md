# Why this is not "an LLM against a drawing"

**Audience:** the estimating team, the MD, and anyone who asks why we did not just paste the
pack into a chat window.
**Status:** every claim below names the file that implements it. Where something is not yet
true, it says so.

---

## The one-sentence version

An LLM reading a drawing produces **an answer**. This produces **an answer, the evidence
behind it, the rank of that evidence, and a refusal to release when the evidence is not there**
— and it produces the same answer twice.

Those are not degrees of the same thing. An estimate is a commercial commitment. What
distinguishes a quotable number from a plausible one is not accuracy on a good day; it is
whether you can tell the good day from the bad one **without already knowing the answer**.

---

## 1. The test that matters is not accuracy. It is *knowing when you are wrong*.

Ask an LLM for the blank size of a folded bracket from a PDF. It will give you one. It will
give you one when the drawing states it, when the drawing states only the folded overall,
when the dimension is on a sheet that did not render, and when the drawing is of something
else. Four situations, one confident format.

The failure is not that it is sometimes wrong. Everything is sometimes wrong. The failure is
that **the four cases are indistinguishable in the output**, so the estimator cannot triage.
They must check everything, which means they check nothing, which is how the current process
already fails.

This engine separates them structurally:

- The blank came off a SolidWorks flat pattern → `solidworks_flat_pattern`, rank 90.
- Measured off a DXF → `dxf_flat_pattern`, rank 80.
- Mirrored from a measured opposite hand → `mirror_of_measured`, rank 75.
- Read from the drawing's stated overalls → `pdf_overall_dims`, rank 65, and every consumer
  is required to keep showing it as inferred.
- Reasoned from the part's family → `inference`, rank 20.
- Not derivable → **no number, and a blocker.**

`src/source_precedence.py`. Six different answers to "where did this come from", carried on
the datum itself, all the way to the workbook. The estimator sorts by rank and spends their
attention on the bottom of the list. That is the entire product.

## 2. Precedence is an arbitration engine, not a label

Labelling provenance is easy and nearly useless — an LLM will happily label its own output
"from the drawing". The value is in what the labels *do*.

A dozen passes write to one part record. Nothing arbitrated between them, so **the last writer
won regardless of what it knew** — and the last writer is usually the weakest, because models
and DXFs are read early and inference runs late. Two live examples from this codebase:

- the PDF GA-tree pass overwrote quantities that had come from the SolidWorks assembly BOM —
  the structure the shop actually builds from;
- knowledge-base and rule overrides replaced native material, because the reliability test
  listed only `knowledge_base` and `override_rule` as strong and had never heard of the model.

Both silent. A silent overwrite of the best available source is the worst failure this
codebase can have, because **the result looks exactly like a correct answer**.

`apply_field` (`src/source_precedence.py`) makes this structurally impossible: a weaker source
may FILL a datum, never REPLACE a stronger one. Three details are worth naming because each
one was a real bug:

- **A recorded zero is a value.** `if cut_out_count:` read a model's explicit *zero* — a plain
  blank with one outer profile — as no data, and let a weaker PDF count survive. "The model
  says none" and "nobody looked" must never resolve the same way. Hence `MISSING`, compared by
  identity, because `0 == False` and `"" == ""` make the obvious check unreliable on exactly
  the cases this has to get right.
- **Equal rank does not settle.** Two title-block readings disagreeing is not refinement, it is
  a conflict. Letting the later one win makes the answer depend on **page order**, silently.
  The first is kept, the disagreement recorded, and a person decides.
- **Agreement upgrades provenance.** Callers used to skip the resolver when values matched —
  "nothing to change" — so the datum kept the *weaker* source's name and a later mid-ranked
  pass could still displace a figure the model had independently confirmed.

No prompt does this. This is not a prompt-engineering problem; it is a write-ordering problem
across a dozen passes, and it is solved with a resolver.

## 3. Two independent readers, and the disagreement is the output

Every BOM page is read twice: a deterministic word-geometry reader off the PDF's text layer
(`_bom_words_reader`) and a Grok vision pass at 300 DPI (`_bom_vision_reader`). Not for
redundancy — **for the disagreement**.

| Outcome | Result | Flag |
|---|---|---|
| Both agree | high confidence | none |
| Both differ | vision wins; possible drawing inconsistency | override, review |
| Deterministic only | emitted | vision did not corroborate |
| Vision only | emitted | recovered by vision |

The guarantee is *no silent miss*: anything found by either path is emitted, and anything
found by only one is flagged. A single LLM read has no second opinion to disagree with, so
it has nothing to flag — its confidence is uniform across everything it says, including the
things it invented.

**And as of this change, the merge is field-by-field.** The row-level winner used to be taken
wholesale, so a description only vision could read was discarded because the two readers
*agreed about the line* (`src/record_merge.py`). Three merge points had the same defect: the
dual-path reconcile, two drawings in a folder printing one fastener line, and a parts list
continued onto a second sheet. All three now fill gaps from the loser, stamped with the source
that filled them, and record genuine conflicts on the survivor.

Which reader wins is decided by rank, not by which ran last: Path A is `bom_tree` (rank 60,
a reading of a printed table), Path B is `llm_extract` (rank 40, a transcription of an image).
Where a rule deliberately overrides rank — vision wins the code on conflict — that field is
marked `decided` and is *noted*, never quietly reversed.

## 4. Deterministic sources exist, and an LLM cannot reach them

This is the part most easily missed. Where SolidWorks models are present, the engine reads the
**model**, not a picture of the model: cut-list bounding boxes, flat patterns, bend counts,
materials, assembly structure. Where DXFs exist, it measures actual cut path and pierce count
with `ezdxf` + `shapely`.

These are not better readings of the drawing. **They are not readings of the drawing at all.**
They are the geometry the shop cuts from. An LLM given the PDF is looking at a rendering of a
projection of that geometry, and no amount of model capability closes that gap — the
information is not in the image.

There is a hard guard here worth stating, because it protects against a failure worse than
zeros. SDI numbers sequentially, so `-01/-02/-03` collide across jobs constantly. A persistent
`SDI_SW_EXTRACT_JSON` once pointed job 2085 at job 12120's extract; it matched nothing, applied
nothing, and stamped a blocker describing 12120's model onto 2085's estimate. A colliding pair
would have written one job's bounding boxes, materials and bend counts onto another's parts
**at the highest rank in the waterfall**. The connector now refuses an extract that belongs to
another job, and distinguishes "this is our own extract and our matcher does not know this
naming convention" from "this describes a different job" — because for a whole session those
two looked identical and one was fixed as if it were the other.

## 5. The same pack costs the same twice

`run-job.ps1 -Twice`. Job 12392 returned an identical unit cost on three consecutive runs.

An LLM asked to price a part returns a different number each time. On job 11350, one part's
market estimate came back at £79.04 and then £86.04 — 97% of the entire material total,
swinging 9% between runs — while its opposite hand had been measured at 258.35 × 84.8 × 2.0
the whole time. That is what produced `mirror_of_measured`: a mirrored derivation has the same
flat pattern as the part it mirrors, and that is geometry, not a guess.

Non-determinism is not a quality problem. It is a **commercial** problem: a customer who asks
for the same quote twice, or two estimators who run the same pack, must get the same number.
Where generated pricing is genuinely the only option, it is content-addressed and cached on
the spec that drove it (`src/generated_price_cache.py`), so the same inputs return the same
price and failures are never cached.

## 6. It refuses to release

`src/invariants.py` runs checks that can BLOCK. Not warnings in a log — a gate.

- A blank that could not physically have been cut does not price
  (`blank_credibility.py`: cut spacing below 1.0 mm, cut path absurdity margin 3×).
- Attributed fields must actually carry attribution.
- Both BOM readers must have run — "the reader did not run" is a finding, not silence.
- Uncorroborated route labour is measured as a **percentage of charged value**, and blocks
  above 40%.

The last one is the sharpest instrument here. It answers: *how much of what we are charging
for did nothing on the drawing ask for?* An LLM route has no answer to that question, because
every operation it lists has exactly the same standing as every other.

This is also where the honesty rule bites. A gate is only worth having if it can find its data:
`check_uncorroborated_route_operations` was reading `summary["canonical_route"]`, a key nothing
writes, and reporting **clean** on a job with nineteen required operations. A check that cannot
find its data is worse than no check, because it occupies the place where somebody would have
looked. Both it and the tool measuring it had the same bug, for the same reason.

## 7. Everything is priced, and gaps are labelled rather than left

At the estimating team's direction: **no gaps.** Where a real price cannot be found, the
engine falls through UDEF → supplier lookup → generated estimate, and marks the confidence
rather than leaving a blank. Four-tier blank sizing does the same for geometry — measured,
mirrored, stated-overall, inferred — so a part with no model still gets a number, flagged as
what it is.

A blank cell forces the estimator to do the work from scratch. A low-confidence number with
its provenance attached lets them accept it or correct it in seconds. Both are honest; only
one is useful.

## 8. It inherits

This is the constraint everything above was built under, and the reason none of it is a stack
of per-drawing patches.

Every rule keys on something general — a part-code family, a stock form, a geometric property,
a source class, a drawing convention. Not a filename, not a job number, not a part number.
`part_code_conventions.py` holds the code-shape rules; `bought_in_policy.py` holds what counts
as fabricated; `source_precedence.py` holds the waterfall. **One definition each.**

The one place this was violated is instructive: `bom_table_extractor._normalize_bom_code` keeps
a private copy of the identity rule. A private copy of a rule that exists elsewhere is how two
readers of one job come to disagree about what it says — and only one of them ever gets fixed.
It is on the list, and it is the only one left.

The test suite enforces this. A guard that fired on the *text* of `merge_boms.py` failed on a
prose comment; it was rewritten to read the module's string literals, because a guard you
satisfy by rewording a comment leaves the private vocabulary it was defending against free to
arrive next week.

Credibility dies if every enquiry needs code. The next pack should need none.

---

## What an LLM against a drawing is actually good at

Nothing above is an argument that LLMs are weak. This engine calls Grok on every page where a
parts list plausibly is, and it is load-bearing:

- reading tables that defeat word-geometry clustering — merged cells, rotated headers, rules
  as graphics rather than text;
- pages with **no text layer at all** — a scan, a raster sheet — where deterministic reading
  has nothing to work with;
- free-text notes that state finishes, fasteners and processes in prose no pattern anticipates;
- recovering BOM lines the deterministic reader missed entirely.

The architecture is what makes those safe to use. Vision output enters at rank 40, is
corroborated where a second reader can see the same thing, is flagged where it cannot, is
cached so it is free and identical on re-runs, and is spent only where the deterministic
reader's own verdict says a page warrants it — *its* verdict, not a private guess about the
page, because deciding whether text extraction can be trusted by consulting the text
extraction is circular on precisely the pages that matter.

**The LLM is a reader. It is not the system.** The difference between this and pasting a
drawing into a chat window is the difference between a witness and a court: same testimony,
but one of them has rules of evidence, a second witness, and a verdict that can be appealed
to the record.

---

## Where this is not yet true

Stated plainly, because a document that claims only successes is not evidence of anything.

- **Route corroboration on job 12392 sits at 8.6%, with 19 required operations carrying zero
  evidence quotes.** The extract emits one route for the whole job, so the channel that would
  carry the quotes is nearly empty. The plumbing is in place and the source is thin.
- **`bom_table_extractor._normalize_bom_code`** still holds a private copy of the identity
  rule. Consolidating it needs a before/after run to prove nothing moves.
- **Two disconnected bought-in nodes on 12392.** The root cause is found and fixed —
  `DRAWING_NUMBER_PATTERN` required a literal `DWG NO` label, so a page headed `12392-04-GA`
  named nothing and fell back to a file stem that matched no part — but the fix has not yet
  been confirmed on a full run.
- **`sdi-intelligence-backend/.env` is tracked in git** and holds the SQL Server and BrightHR
  secrets. Rotate both, then `git rm --cached` it. This is the most urgent item on this page
  and the only one that is not an estimating concern.
