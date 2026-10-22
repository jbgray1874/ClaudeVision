# AI Estimating — how to use it

**This is a draft, not a quote.** Do not send anything from here to a customer or into the
ERP until you and John have agreed it is right. You are running it in parallel with your
normal estimate, and your estimate is still the one that counts.

---

## What to do

1. Open the **SDI Intelligence** portal.
2. Pick the job. Press **Run**.
3. When it finishes, open the spreadsheet it produces. It is the estimating sheet you
   already use, in the format you already use.
4. Work down the **yellow cells** — those are the ones it needs from you.
5. Compare the total with your own. Where they differ, the sheet says where its number
   came from.

That is the whole workflow. Everything below is only for when something on the sheet looks
wrong.

---

## Reading the sheet

Every number carries **where it came from**. That is the point of the tool — not to be
right about everything, but to tell you which numbers to argue with.

| If the source says | It came from | Do you need to check it? |
|---|---|---|
| `solidworks_api` | The 3D model | **No.** This is the strongest evidence there is |
| `dxf` / `dxf_flat_pattern` | A measured flat pattern | **No** |
| `mirror_of_measured` | The measured opposite hand | Only that the two really are handed |
| `drawing_deterministic` / `title_block` | Printed on the drawing, read exactly | Rarely |
| `pdf_overall_dims` | The drawing's stated overall size, read as a blank | **Yes if the part folds** — a folded part unfolds longer |
| `bom_tree` | The parts list on the drawing | Spot-check the quantity |
| `llm_extract` | The AI reading the drawing | **Yes** |
| `inference` | Worked out, not read | **Yes** |

**Rule of thumb: the further down that list, the more it is worth your time.**
Re-checking the top two is time taken away from the ones that need it.

---

## Flags you will see, and what they mean

| Flag | Plain English | What to do |
|---|---|---|
| `B_RECOVERED` | The AI found a BOM line the normal reader missed | **Check this line exists.** It usually does |
| `B_OVERRIDE` | The two readers disagreed about a code or quantity | **Look at the drawing.** Often the drawing itself is inconsistent |
| `A_ONLY` | Only the normal reader found it | Sanity-check the quantity |
| `the sheets disagree` | Two sheets give the same item number a different part | **Resolve it.** One is a real part and one is not |
| `blank_source_not_recorded` | We have a size but nothing measured it | Confirm the size |
| `estimator to price` | Recognised, deliberately not priced | Price it from the enquiry |
| Anything saying **BLOCKER** | It refused to price something | Tell John. Do not work around it |

---

## What it will not do, and that is deliberate

- **It will not leave a blank.** If it cannot find a real price it estimates one and marks
  it low confidence. A labelled guess you can correct in seconds beats an empty cell you
  have to fill from scratch.
- **It will not price something impossible.** If the geometry could not have been cut, it
  refuses and says so rather than producing a number that looks fine.
- **It will not give you two different answers.** Same pack, same run, same total. If you
  ever see it change on a re-run with nothing else changed, that is a bug — tell John.

---

## Things it is still not good at

Say so when you hit these. They are the list we are working from.

- **Bought-in items** — fasteners, purchased parts, packaging. Expect to correct these.
- **Margin and pack costs** — yours, always.
- **Which assembly owns what**, on some packs. If a part looks orphaned on the sheet,
  it probably is.
- **Route steps it could not find stated on the drawing.** It will tell you how much of
  the labour nobody asked for in writing.

---

## What we need back from you

One tick per job, and a sentence if it is not a Y:

- **Y** — draft was usable
- **Y with fixes** — usable after I corrected things
- **N** — faster to do it myself

And if you complain about anything, complain about **a line on the spreadsheet**: a BOM
line, a labour row, a material line, a yellow input. That is what we can fix and turn into
a rule so it is right on the next job too.

---

*Questions, or anything that says BLOCKER: John Gray.*
