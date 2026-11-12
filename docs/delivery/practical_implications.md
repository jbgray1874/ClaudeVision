# Practical implications — what the estimator actually does differently

**Audience:** the estimating team, on the day they start using the SDI Intelligence portal.

Not a feature list. Each row is a situation that arises on a real pack, what the engine does
about it, **what appears on the estimator's screen**, and what the estimator is expected to do
next. The last column is the point of the table: a signal nobody acts on is a signal that costs
attention and returns nothing.

---

## A. Where a number came from

| Situation | What the engine does | What the estimator sees | What they do |
|---|---|---|---|
| Model or DXF present | Reads the geometry the shop cuts — flat pattern, bend count, cut path, pierce count | Source `solidworks_api` / `dxf_flat_pattern`, rank 80–90 | **Nothing.** This is the strongest evidence available. Do not re-check it |
| One hand measured, the other not | Mirrors the measured flat onto the opposite hand | `mirror_of_measured`, rank 75 | Confirm the two really are handed. If they are, accept |
| PDF only, overall size stated | Reads the stated overalls as a blank, with a fold guardrail | `pdf_overall_dims`, rank 65, shown as **inferred** | Check the part is flat. If it folds, the blank is bigger than the overall |
| PDF only, nothing stated | Infers from family, or refuses | `inference` rank 20, or a blocker | Supply the dimension, or accept a low-confidence figure |
| Two sources disagree | Stronger kept, disagreement recorded with **both** values and **both** sources | Review flag naming both readings | Decide which is right. Nothing else in the run can settle it |
| Two sources of **equal** rank disagree | First kept — never "whichever ran last" | Flag: *neither outranks the other; a person must decide* | **Decide.** This one genuinely cannot be automated |

> **The rule underneath all six:** a weaker source may fill a gap, never replace a stronger
> one. A recorded **zero** is a value and is defended — "the model says no cut-outs" is an
> answer, not an opening.

## B. Reading the BOM

| Situation | What the engine does | What the estimator sees | What they do |
|---|---|---|---|
| Clean table, text layer intact | Deterministic reader; vision corroborates | source `BOTH`, confidence HIGH | Nothing |
| Vision found a line the reader missed | Emitted anyway | `B_RECOVERED` — *LLM-recovered, review* | **Check this line.** It is real often enough to matter and wrong often enough to check |
| Reader found a line vision missed | Emitted anyway | `A_ONLY` — *vision did not corroborate* | Sanity-check the quantity |
| The two disagree on code or quantity | Vision wins; both readings recorded | `B_OVERRIDE`, confidence LOW, *possible drawing inconsistency* | **Look at the drawing.** This often means the drawing itself is inconsistent |
| One reader read a column the other could not | Merged field by field — the gap fills, stamped with the source that filled it | `merge_notes` on the line | Nothing. This used to be lost silently |
| Parts list continues onto a second sheet | Rows gathered under the parent, not per-sheet | *parts list read from N sheets* | Nothing |
| A fixings table repeated for the fitter | Same line, counted once, both sheets recorded | `also_on_sheets` | Nothing. This used to double the fixings |
| Same item number, **different** code on two sheets | **Both emitted**, both costed, flagged | *the sheets disagree; both are costed until someone says which is right* | **Resolve.** One of them is a real part and one is not |
| One line printed on two drawings in a folder | Primary GA's row wins; the other fills its blanks | `merge_notes` naming the other drawing | Nothing. The quantity used to be lost to the primary's blank column |
| Page has no text layer | Vision reads it | *no text layer — a scanned sheet is what vision is for* | Nothing |
| Neither reader could open a page | Recorded as **unread** | A finding, not silence | **Chase the file.** An unread page is not a clean page |

## C. Route and labour

| Situation | What the engine does | What the estimator sees | What they do |
|---|---|---|---|
| Operation stated on the drawing | Claim carries the quoted text and where it was found | `evidence` + `evidence_where` | Nothing |
| Operation inferred from geometry | Recorded as uncorroborated | Counted into the uncorroborated share | Scan these first |
| Uncorroborated labour ≥ 40% of charged value | **Blocks release** | BLOCKER with the % and the £ | **Review the route before quoting.** This is a gate, not advice |
| Uncorroborated below 40% | Warning with the same numbers | The % and the £ | Spend attention proportionally |

> **The question this answers:** *how much of what we are charging for did nothing on the
> drawing ask for?* Currently **8.6%** on job 12392 — but with **zero evidence quotes on 19
> required operations**, because the extract emits one route for the whole job. The channel is
> plumbed and the source is thin. Treat route evidence as *not yet delivered*.

## D. Pricing

| Situation | What the engine does | What the estimator sees | What they do |
|---|---|---|---|
| UDEF has the material | Live price | Real cost, high confidence | Nothing |
| UDEF unreachable | Falls through; says so | The fallback that was used | Nothing — but note it if out-of-hours |
| No catalogue price anywhere | Supplier lookup, then generated estimate | Low confidence, **never blank** | Accept or correct. Estimating asked for a number, not a gap |
| Generated price re-run | Content-addressed cache on the driving spec | **Identical** figure | Nothing. Same pack, same price |
| Blank could not physically have been cut | **Refuses to price it** | Blocker naming the impossible geometry | **Fix the geometry.** A priced impossibility is worse than a gap |
| Commercial line (packaging, delivery) | Passes through unpriced by design | £0, *estimator to price* | Price it from the enquiry |

## E. What blocks a release

Four gates. Each can stop a pack going out.

| Gate | Trips when | Why it is a blocker and not a warning |
|---|---|---|
| Blank credibility | Cut path is absurd for the blank (>3× ), or cut spacing < 1.0 mm | The number is not merely uncertain, it is impossible |
| Uncorroborated labour | ≥ 40% of charged labour value | Above this the route is our opinion, not the drawing's |
| Both readers ran | Either BOM reader did not run | An unread BOM is not an empty BOM |
| Attribution | An attributed field carries no attribution | Provenance that is absent reads as provenance that is strong |

## F. What the estimator should NOT do

| Temptation | Why not |
|---|---|
| Re-check `solidworks_api` / `dxf` figures | Rank 80–90. Re-checking these spends the attention the flagged lines need |
| Treat a low-confidence price as an error | It is a labelled estimate. Correcting it is a minute; re-deriving it is an hour |
| Ignore `B_OVERRIDE` because vision "won" | It won by rule, not by evidence. **Confidence is LOW and the flag says so** |
| Read a blank flag column as "checked and fine" | It means *nothing disagreed*, which on a single-source field means *nothing corroborated it either* |
| Assume three matching provenance blocks are three confirmations | Within one run the three pools hold **one** record. `tools/where_did_this_come_from.py` now says so explicitly |

---

## Verifying any of this on a real job

```
.venv\Scripts\python.exe tools\three_numbers.py 12392
```
Ownership, corroboration, material — the three signals, printed identically every run so two
runs compare by reading rather than by remembering.

```
.venv\Scripts\python.exe tools\where_did_this_come_from.py 12392-02-01M --job 12392
```
Every attributed field on one part, with its source and rank, from all three pools; what the
merge did where two readings existed; and which pools the part never reached.

```
.\run-job.ps1 '<job folder>' -Twice
```
The reproducibility check. Two totals, printed together. They should be identical.

---

## Honest status, as of this writing

| Item | State |
|---|---|
| Provenance waterfall and arbitration | Live, enforced, tested |
| Dual-path BOM, field-by-field merge | Live, on by default (`SDI_DUALPATH_BOM=0` to disable) |
| Blank credibility gate | Live |
| Reproducibility | Verified — 12392 identical across three consecutive runs |
| Price everything, no gaps | Live |
| Route **evidence quotes** | Plumbed; source thin. **Not yet delivered** |
| Bought-in ownership on 12392 | Root cause found and fixed; **not yet confirmed on a full run** |
| `bom_table_extractor._normalize_bom_code` private identity rule | Outstanding — the last private copy |
| `sdi-intelligence-backend/.env` tracked in git | **Outstanding and urgent.** Rotate the SQL Server and BrightHR secrets, then `git rm --cached` |
