# Alba demo foundation

The shared product foundation from *Alba — Scenario-Led Demo and Technology
Requirements* (3 August 2026), built as a dependency-free ES module package.

The specification is explicit about which parts of the demo may be simulated
and which must genuinely work. Connectors, permissions and billing may be
simulated. **KPI and variance calculations, alert logic, root-cause drill-down,
scenario calculations, action tracking and report generation must work.** This
package is those parts.

```
npm run demo            walk the eight-minute demo on the command line
npm run demo:reports    the same, plus both generated reports in full
npm test                the demo acceptance criteria, as tests
```

No dependencies, no network, no filesystem, no wall clock. Node 18+.

## What is here

| Module | Responsibility |
|---|---|
| `src/portfolio.js` | Ten fictional companies, eighteen months of monthly financials and headcount |
| `src/kpis.js` | Variance, quarter projection, runway, margin movement, fund rollup |
| `src/insight.js` | The standard Alba insight card, and the guard that refuses one without evidence |
| `src/scenario1-revenue-miss.js` | Scenario 1 — forecast, driver bridge, named pipeline |
| `src/scenario4-expansion.js` | Scenario 4 — account scoring, cohort, expected value |
| `src/scenario2-cash.js` | Scenario 2 — 13-week forecast, management levers, side-by-side cases |
| `src/scenario5-procurement.js` | Scenario 5 — vendor resolution, cross-portfolio spend, savings |
| `src/secondary-signals.js` | Scenarios 2 and 3 at alert strength |
| `src/actions.js` | Alert and action tracker, through to closed-loop outcome |
| `src/report.js` | Exception Report and Growth Opportunity Brief, payload plus Markdown |
| `src/index.js` | Portfolio Health Command Centre and the public surface |

## Using it in the React app

Copy `src/` to `src/lib/demo/` in `alba-pip` and import from the index:

```js
import { buildCommandCentre, buildScenario1, buildScenario4 } from './lib/demo';

const cc = buildCommandCentre();          // portfolio table, rollup, split alert lists
const s1 = buildScenario1();              // forecast, bridge, deals, insight card
const s4 = buildScenario4();              // scored customers, qualified cohort, insight card
```

Every builder returns plain data. Nothing renders, nothing fetches, so the
screens stay free to present it however the brand requires.

## Design decisions worth knowing

**The bridge reconciles by construction.** The forecast is plan less the sum of
its drivers, and each driver is computed from current CRM, billing and HRIS
figures against what the plan assumed. There is no separate forecast that then
has to be explained — so `plan − drivers = forecast` is an identity, and a test
asserts it.

**Rounding happens to the primitives, not the results.** Revenue, cost of sales
and operating cost are rounded first; gross profit and EBITDA are derived from
the rounded values. A drill-down that shows gross profit less operating cost
therefore equals the EBITDA on the row above it exactly, rather than to within
a rounding error.

**The language model writes narrative, never numbers.** Every figure in an
insight card and both reports is calculated here. Reports render with the AI
layer switched off and stay correct. This is the single most important property
of the package: a hallucinated cash position in a board pack is not a bug, it
is the end of the sales conversation.

**Everything is seeded.** `Math.random` and the wall clock are unavailable by
construction — `AS_OF` is fixed at 2026-08-31 and all variation comes from a
seeded generator keyed by company name. The figures in a rehearsal are the
figures in the meeting.

**An insight cannot exist without inspectable evidence.** `makeInsight` throws
if evidence is missing, empty, or carries a row without a source system and a
refresh date. The constraint is enforced at construction rather than reviewed
later.

## Where the numbers land

Against the targets in the specification, as of the current parameters:

| Specification | Produced |
|---|---|
| Revenue ~3% below plan | 3.0% |
| Next-quarter miss ~USD 1.2m | USD 1.20m |
| Pipeline coverage 3.2x → 1.9x | 3.20x → 1.90x |
| Win rate 31% → 22% | 31% → 22% |
| Cash runway 14 months → ~8 | 13.8 months (2026-04) → 8.5 |
| Gross margin 42% → 34% | 42.0% → 34.0% |
| Cross-sell opportunity USD 1.5–2.0m ARR | USD 1.49m – 2.01m |
| Procurement saving USD 0.8–1.1m | USD 0.84m – 1.13m |

These fall out of the parameters at the top of each scenario module rather than
being written in. Change `PARAMS.planStepUp` and the whole story moves together.

## Two more design decisions

**The cash model is anchored to reported burn, not built bottom-up.** A
bottom-up build — headcount times salary, plus suppliers, plus debt service —
produces an implied burn that does not match what the company reports, and the
portfolio table then contradicts the cash screen. Instead, total outflow is
fixed by the identity *receipts less outflow equals reported burn*, payroll is
calculated from headcount, and supplier spend is the residual. The forward
baseline is legitimately shorter than the reported trailing runway because it
funds the hiring plan — so `forwardVsReported` states that in words rather than
leaving two numbers to disagree on screen.

**Vendor matching grades rather than guesses.** `Atlas Collab Suite` and
`Atlas Collaboration Suite` merge automatically on a prefix match.
`Talentbridge Search & Selection` and `Talentbridge Recruitment Ltd` are the
same supplier trading under two names, and no string operation can know that —
so that spend goes to a review queue and is **excluded from the headline saving**
until confirmed, with the held-back upside stated separately. Counting it would
be the easy route to a bigger number and the fast route to losing the room.

## Not built yet

- Scenario 3 drill-down — margin bridge decomposition and the customer/product
  profitability table. The primitive it needs (`marginMovement`) is here and tested.
- Working-capital detail for scenario 2 — AR ageing by band and customer
  concentration. The live Xero connection already returns this for Meridian.
- A benchmark set. The specification allows a small illustrative one.
- PDF and Word rendering. `toMarkdown` produces the content; the branded
  wrapper belongs with the existing HTML report templates.
