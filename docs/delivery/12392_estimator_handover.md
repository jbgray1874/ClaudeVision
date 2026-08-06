# Job 12392 — AI draft estimate for checking

**Pack:** 12392-02 (1-wide GC panel) + 12392-04 (mod bracket set), Rev A
**Quantity:** 10 off
**Sheet:** `output\estimates\12392-02_20260806_113257.xlsx`
**Status:** provisional — five things need an estimator before it is a price

---

## Where the numbers came from

The SolidWorks models were read directly, so the blanks, gauges, bend radii and cut
lengths on four of the five steel parts are the model's own cut-list figures rather than
anything read off a drawing. Material is CR4 throughout, from the model.

|              | £     |
| ------------ | ----- |
| Material     | 7.95  |
| Labour       | 38.41 |
| **Unit cost**| **49.85** |

Nothing has margin or rebate applied.

---

## Five things to check

**1. 12392-02-01M back panel — the blank is wrong.**
The sheet shows 16 × 3.7 mm. The model's bounding box is 130 × 1435 × 1.5. This is the one
part whose flat pattern the model would not give up, so the engine fell back on the drawing
and got it badly wrong. Everything downstream of that blank — its material, its laser time —
is wrong with it. **Please enter the real flat size.** The other three steel parts are
measured and need no checking.

**2. Weld and dress on 01M — probably not real.**
The model flags that part as a weldment, so the route picked up Weld (CO2) £3.53 and Dress
Welds £1.91. The drawing shows a flat RAW tapped panel with folds only. If there is no weld,
strike both rows.

**3. Is Assemble/pack charged twice?**
It appears once on 12392-02-201 (with the graphic, fixings and pocket) and again on its own
children 01M and 02M. That is either two real events — sub-assembly, then final pack — or the
same work counted twice. The engine cannot tell and has not guessed.

**4. Four lines need prices.**

| Line | What it is |
| --- | --- |
| `12392-02-17G` | header graphic — **not priced.** An AI suggested a figure but it came back £35.62, £95.62 and £75.62 on three identical runs, so it is deliberately kept off the sheet |
| `P/P` | TBM571 large leaflet pocket, 8 off |
| `PACKAGING` | per-unit share of box / pallet |
| `DELIVERY` | per-unit share of haulage |

**5. Powder — confirm the parts and the rate.**
Booked on 12392-02-02M, 12392-04-01M and 12392-04-02M — five objects per unit, 0.4388 m²,
0.0878 kg at £9.73/kg. 01M is RAW and is not coated.
The coverage rate is the template's 0.2 kg/m². Your own sheets for this job imply nearer
1.70 kg/m² on open wire and 2.7–4.9× on flat parts, so **this line under-reads.** Tell us the
real rule and it is a one-line change.

---

## Known and left alone

`BI-BOLTBZP` (Bolt Bzp, 4 off, £0.83) is priced and on the sheet, but no drawing names the
assembly it belongs to, so it is flagged rather than tidied away.

---

## One question before you spend time on this

The customer's email asks for **12392-01-GA5** (9 facing) with the McCue bump rail — end caps
`GGE-10-105`, rail `GGT-20-105`, mounting base `CGB-20UNV-400`, a painted 18 mm MDF spacer and
fixings. **None of that is in this estimate**, which covers 12392-02 and 12392-04.

If GA5 is the live enquiry, say so and we will run that pack instead — the models are in the
same folder and it is a short job now the method works. If 02 + 04 are still wanted, this
sheet stands.
