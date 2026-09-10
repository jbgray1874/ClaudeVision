# 0359342 — what was read off the sheets, and what still needs a person

Source: `0359342_PDF_Edition_Sunglasses_Stand_REV_4.pdf`, 29 pages.
Read on 2026-09-10 by looking at each rendered sheet.

**Pack structure.** Pages 8–28 are one part per sheet and the title block names that part, so
ownership is not in doubt on this pack. Pages 1, 3, 4, 5, 6 are parts lists; page 2 (A62271),
page 7 (J13149) and page 29 (A60890) are single-part sheets outside the 8–28 run.

**Why this file exists.** The dimension extractor cannot read these sheets — it returns
countersink angles, thicknesses and noise where the printed overalls should be. Two attempts to
fix that failed (task #54 has the detail). Meanwhile every part fell back to a category-default
envelope, and the board panels were nesting from 400 × 300 against real sizes up to 1680 × 560.
That is a three-to-nine-times **under**-charge on the board.

---

## 1. Sizes confirmed (in the JSON, 17 parts)

| Part | Sheet | Blank (mm) | Thk | Material | Was (engine default) |
|---|---|---|---|---|---|
| JAE820 Plinth Top | p8 | 638 × 538 | 18 | MDF | 400 × 300 |
| JAE821 Plinth Side | p9 | 638 × 75 | 18 | MDF | 400 × 300 |
| JAE822 Gondola Plinth Cover End | p10 | 502 × 75 | 18 | MDF | 400 × 300 |
| JAE825 Plinth Castor Block | p13 | 190 × 110 | 9 | MDF | 350 × 250 |
| JAE826 Shroud Back Panel | p14 | **1680 × 560** | 18 | MDF | 400 × 300 |
| JAE828 Shroud Top Panel Outside | p16 | 500 × 250 | 12 | MDF | 400 × 300 |
| JAE829 Shroud Top Panel Inside | p17 | 500 × 250 | 12 | MDF | 400 × 300 |
| JAE830 Shroud Side Panel Outside | p18 | **1649 × 250** | 12 | MDF | 400 × 300 |
| JAE831 Shroud Side Panel Inside | p19 | **1649 × 250** | 12 | MDF | 400 × 300 |
| JAE832 Back Panel | p20 | **1670 × 546** | 18 | MDF | 400 × 300 |
| JAE833 Shelf Top | p21 | 494 × 199 | 9 | MDF | 350 × 250 |
| JAE834 Shelf Bottom | p22 | 494 × 199 | 9 | MDF | 350 × 250 |
| MBY434 Prong Backplate | p26 | Ø24 → 24 × 24 env. | 2 | CR4 | 350 × 250 |
| MBY435 Shelf Bracket | p27 | **418 × 212.5** (flat pattern) | 2 | CR4 | 350 × 250 |
| MBY439 Mirror Plate | p28 | **1578 × 188** | 2 | Mild Steel | 350 × 250 |
| A62271 Mirror | p2 | 1556 × 166 | 6 | Mirror, 6mm | — |
| J13149 Sunglasses Plinth | p7 | 155 × 155 | 15 | MDF | — |

Two that need saying out loud:

- **MBY435** — the sheet prints BOTH the formed size (418 × 142 × 74 high) and an explicit
  **FLAT PATTERN 418 × 212.5**. The flat pattern is the blank. Costing the formed size would
  under-charge the steel by a third.
- **MBY434** — Ø24 disc. 24 × 24 is the square nesting envelope for a round blank, not a
  printed rectangle. Stated that way in the file so nobody later reads it as a measurement.

---

## 2. Deliberately NOT in the file — six parts a rectangle would misprice

These need your figure, not mine. In each case I could compute something plausible, and a
plausible number entered at rank 100 is unchallengeable — which is exactly the failure mode
this whole exercise is about.

| Part | Sheet | What it actually is | What it needs |
|---|---|---|---|
| **JAE823** Plinth Overlay | p11 | **Corian 6mm, thermoformed.** Plan 650 × 550, sides 95 high, 24 returns, R14 typ. | The developed blank. The sheet prints no flat pattern. Adding the sides and returns gives roughly 888 × 788 — that is *my arithmetic, not the drawing*, so it is not in the file. Also note the sheet is stamped "DETAIL FOR REFERENCE ONLY", and the finish is Corian Cameo White (China local match) with an 800-grit all-faces requirement. |
| **JAE824** Plinth Corner Block | p12 | **Solid MDF block 40 × 40 × 50 high.** Title block says "MDF" with no gauge. | Not a sheet part. 50mm tall cannot come from any single MDF board in the list — it is laminated up or cut from thick stock. Needs a make method before it can be costed. |
| **JAE827** Shroud Corner | p15 | **Flexi MDF 6mm AND 9mm, curved laminate.** Envelope 250 × 170 × 149 high; section shows R49/R25, 100 × 100 legs, 6.0 and 8.0/9.0 laminations. | Two materials on one part, formed over a radius. The engine has no representation for this. Needs a laminating build-up and a developed length. |
| **JAE835** Shelf Edging | p23 | **Linear edging, 1.0 thick**, U-shape round three sides: 496 + 2 × 200. | A per-metre item ≈ 0.9 m per shelf, not a sheet blank. Title block material reads "Lamainate Edging" — that typo is on the drawing and is why the material never resolved to a rate. |
| **MBY432** Prong | p24 | **Ø8 mild steel wire × 219.6 long**, turned spigot one end. | Wire/bar costing, not sheet. Est mass 0.09 kg is printed and is the reliable figure. |
| **MBY433** Prong Assembly | p25 | **An assembly**, not a part: MBY432 + MBY434, puddle welded both sides, faces dressed flush. | No blank at all. It needs the weld and dress operation — see the quantity note below, because this is where the labour is. |

---

## 3. Quantities — check these against the sheet before you send

**Not stamped in the file**, deliberately: I don't know whether the engine's `quantity` field
means per-parent or per-job, and a wrong reading of that at rank 100 could not be argued with.
These are read straight off the printed parts lists — verify against what the workbook shows.

Top level **A61636** (page 1) carries **J13094 Back Panel Assembly × 2**. That multiplier is the
one most likely to have been missed, and it doubles the busiest sub-assembly in the job.

| Item | Per parent | Parent qty | **Per unit** |
|---|---|---|---|
| J13092 Plinth Cover Assembly | 1 | 1 | 1 |
| J13093 Shroud Assembly | 1 | 1 | 1 |
| J13094 Back Panel Assembly | 2 | 1 | **2** |
| JAE832 Back Panel | 1 | 2 | **2** |
| MBY433 Prong Assembly | 28 | 2 | **56** |
| → MBY432 Prong / MBY434 Backplate | 1 each | 56 | **56 each** |
| MBY435 Shelf Bracket | 4 | 2 | **8** |
| J13095 Shelf Assembly | 4 | 2 | **8** |
| → JAE833 / JAE834 / JAE835 | 1 each | 8 | **8 each** |
| MBY439 Mirror Plate | 2 | 1 | **2** |
| A62271 Mirror | 2 | 1 | **2** |
| J13149 Sunglasses Plinth | 8 | 1 | **8** |
| JAE821 / JAE822 Plinth Side / Cover End | 2 each | 1 | 2 each |
| JAE824 / JAE825 Corner / Castor Block | 4 each | 1 | 4 each |
| JAE827..JAE831 Shroud panels | 2 each | 1 | 2 each |
| R04611 #4 woodscrew | 72 | 2 | **144** |

**56 puddle-welded prong assemblies** is the single biggest labour line implied by this pack,
and each one is "puddle weld on either side of Prong, dress front and back faces flush"
(printed on p25). If the estimate does not carry 56 weld-and-dress operations, that is the
first thing to look at.

---

## 4. Finishes stated on the sheets

Worth checking these are all landing, since finish drives a lot of the money:

- J13092 Plinth Cover Assembly — Corian Cameo White (China Local Match)
- J13093 Shroud Assembly — **Wet Sprayed RAL 7021 30%** (not powder)
- J13094 Back Panel Assembly — Laminated + Powdercoated, RAL9010G30
- MBY439 Mirror Plate — Powdercoated RAL 7021 30%
- MBY435 Shelf Bracket — Powdercoated RAL9010G30
- J13149 Plinth — Laminated to match RAL 9010, 1mm edging all sides
- JAE823 — 800 grit sandpaper all faces, no visible swirl marks

---

## 5. Standing caveat

Every sheet in this pack is stamped **"FOR PROTOTYPE MANUFACTURE ONLY"**, and the general notes
say "Flat Pattern details provided are based on generic bending data and should be adjusted to
suit tooling and processes." Whatever goes to the estimators should carry that on its face.

Every figure above is a reading of a drawing by eye. It is better than the category defaults it
replaces by a wide margin, and it is not a measurement.
