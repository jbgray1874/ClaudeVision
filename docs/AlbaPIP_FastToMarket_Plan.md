# Alba — Fast to Market

**Caledonia Alba · Portfolio Intelligence Platform**
*Reconciles: `AlbaPIP_Handover.md` · `Alba_GoToMarket_Strategy_2026` (29 Jul) · `Alba_Scenario_Led_Demo_and_Technology_Requirements` (3 Aug)*
*August 2026 · Confidential*

---

## 0. The argument in one page

Three documents now describe Alba, and they disagree about what to build first.
The handover describes a **6-month, 100-integration roadmap**. The go-to-market
playbook says never to sell integration count and to build connectors only when a
signed pilot demands one. The demo specification says something more useful than
either: **do not demonstrate every feature — show one portfolio miss and one
opportunity signal exceptionally well.**

The demo specification wins, because it is the only one of the three that
identifies the actual constraint. Nothing sells until there is a scenario demo
that survives inspection, and no amount of platform hardening substitutes for it.

**The critical path is therefore:**

```
scenario demo (≈ day 14)  →  qualified demos and pilot scopes (days 11–45)
                          →  production floor before the first client's data (≈ day 45)
                          →  two paid design partners (day 90)
```

Two corrections to earlier thinking follow, and both matter.

**Pricing.** An earlier draft of this plan proposed a £7,500 pilot converting to
£24,000/year. That is materially below the playbook's researched position —
**USD 25–40k for a 12-week paid design partnership, converting to USD 75–100k
Foundation ARR** — and it was calibrated to a smaller customer than the playbook's
ICP of 10–40 portfolio companies. The playbook's numbers are right; use them.

**Sequencing.** The same draft treated authentication, a database and tenant
isolation as day-one blockers. Against the demo specification they are not:
permissions, billing and administration are explicitly listed as *may be
simulated*. They become blocking the moment a design partner's real data arrives,
which is around day 45 — not day 1. Build the demo first.

---

## 1. Where the three documents actually conflict

Worth settling now, because each conflict will otherwise be re-argued in a
meeting.

| Question | Handover says | Playbook / demo spec says | Resolve as |
|---|---|---|---|
| What to lead with | 100+ integrations, 9 screens, breadth | "Do not say *we have 100+ integrations* without the first outcome"; lead with the investment question | **Playbook.** Breadth is the thing incumbents already claim. |
| Price | £15,000–50,000/yr "total cost" | USD 25–40k pilot; USD 75–100k Foundation ARR | **Playbook.** The handover figure is cost-to-deliver — an internal number. Quoting it invites the buyer to price your margin. |
| Customer | Fund managers across SEA and the Middle East | Lower-middle-market PE, growth and investment-led family offices, 10–40 portcos, Singapore and UAE | **Playbook.** |
| Portfolio companies in the demo | 5 seed companies | 8–10 with 12–18 months of history | **Demo spec.** Now built — 10 companies, 18 months. |
| Build order | Month 1 finance/ERP, Month 2 market data, … | Scenario 1 (revenue miss) and Scenario 4 (sales expansion) first | **Demo spec.** |
| Auth, permissions, billing | Known gap, "production upgrade" | "Can be simulated" for the demo | **Both, in sequence.** Simulated for the demo; real before a design partner's data lands. |
| News feed | NewsAPI simulated on the deployed site | "No part of the demo depends on the presenter explaining away a static or inconsistent screen" | **Remove or proxy it before any prospect sees the platform.** |

---

## 2. What the demo specification asks for, against what exists

The specification's six shared components, mapped onto the platform described in
the handover. This is the real backlog.

| Component | Exists today | Gap |
|---|---|---|
| **1. Portfolio Health Command Centre** | GP Dashboard; Portfolio Analytics *Overview* tab with Attention Required + RAG heatmap | 5 companies not 8–10; no 12–18 month history; risk and opportunity alerts not separated; no movement since prior period; no fund/sector/geography filters |
| **2. Company Detail Page** | Client Portal role views; finance drill-downs | No single consistent information architecture across companies; no commercial, people or operating sections; no data-source and refresh strip |
| **3. Standard Insight Card** | AI-prioritised Attention Required panel | No standard structure — what happened, why it matters, evidence, impact, action, confidence, source |
| **4. Root-Cause Drill-Down** | **Strongest existing asset** — 3 metrics × 4 levels, reconciling | No calculation methodology shown, no source-system references, no revenue driver bridge |
| **5. Report Generator** | Grok board pack exporting to HTML | Not insight-scoped; no Exception Report or Growth Opportunity Brief; figures come from model context rather than a calculated payload |
| **6. Alert and Action Tracker** | Not built | Entire component — owner, deadline, status, subsequent metric movement, closed loop |

And the five scenarios:

| Scenario | Priority | Coverage today |
|---|---|---|
| 1 · Revenue miss | **1 — primary** | HubSpot pipeline is live. No forecast, no driver bridge, no commercial KPIs. |
| 4 · Sales expansion | **1 — primary** | Nothing. |
| 2 · Cash runway | 2 | **Closest to complete.** Finance drill-down plus the Scenario Planning tab's sliders and 6-month projection. Needs a 13-week view and side-by-side management cases. |
| 3 · Margin deterioration | 3 | Margin bridge waterfall exists inside the EBITDA drill-down. Needs customer and product profitability. |
| 5 · Portfolio procurement | 4 — phase 2 | Nothing. Correctly deferred. |

> **The finding that matters:** the two **priority-1** scenarios are the two with
> the **least** existing coverage, while the well-built parts of the platform
> serve scenarios 2 and 3. The prototype's maturity does not shorten the path to
> the primary demo as much as it appears to.

---

## 3. What has been built here

`alba-demo-foundation/` in this repository — the shared product foundation, as a
dependency-free ES module package. It is the part of the specification's
"must genuinely work" list that can be built without the React app.

```
npm run demo            walk the eight-minute demo on the command line
npm run demo:reports    the same, plus both generated reports
npm test                16 tests — the acceptance criteria, enforced
```

| Specification requirement | Status |
|---|---|
| Common data foundation — 8–10 companies, 12–18 months | **Built.** 10 companies, 18 months, deterministic. |
| KPI and variance calculations must work | **Built.** Variance, quarter projection, runway, margin movement, fund rollup. |
| Alert logic must be transparent and repeatable | **Built.** Every threshold is a named parameter. |
| Root-cause drill-down must be inspectable | **Built.** Every figure carries source system and refresh date; construction throws without them. |
| Scenario calculations must work | **Scenario 1 and 4 built.** 2 and 3 at alert strength; their primitives are tested. |
| Action assignment and status must work | **Built,** through to closed-loop metric movement. |
| Report generation must work | **Built.** Exception Report and Growth Opportunity Brief, as payload plus Markdown. |
| AI explanation must reflect calculated facts | **Enforced by design.** Every number is calculated; the model writes narrative only. Reports render correctly with the AI layer switched off. |

The figures land where the specification asks:

| Specification | Produced |
|---|---|
| Revenue ~3% below plan | 3.0% |
| Next-quarter miss ~USD 1.2m | USD 1.20m |
| Pipeline coverage 3.2x → 1.9x | 3.20x → 1.90x |
| Win rate 31% → 22% | 31% → 22% |
| Cash runway 14 months → ~8 | 14.2 months (2026-04) → 8.5 |
| Gross margin 42% → 34% | 42.0% → 34.0% |
| Cross-sell opportunity USD 1.5–2.0m ARR | USD 1.49m – 2.01m |

These are derived, not written in. The driver bridge reconciles as an identity —
forecast *is* plan less the sum of drivers — so it cannot silently stop adding up.

**One data change to flag:** Meridian SaaS now carries 8.5 months of runway
rather than the handover's 4.8, because the demo specification's scenario 2 calls
for a deterioration from roughly 14 months to roughly 8. Meridian remains the
live-Xero company.

**What remains on James's side:** wiring these payloads to screens. The package
renders nothing and fetches nothing by design.

---

## 4. Build track — three sprints

### Sprint A · to day 14 — the scenario demo
The single deadline that governs everything else.

1. Wire the command centre to `buildCommandCentre()` — portfolio table, rollup
   banner, separated risk and opportunity alert lists, movement since prior period,
   filters by fund, sector, geography and status.
2. Company detail page with one information architecture for all ten companies,
   including the data-source and refresh strip.
3. Insight card component, rendered from the standard structure.
4. Scenario 1 screens: company drill-down, pipeline trends, forecast, driver
   bridge, recommended actions.
5. Scenario 4 screens: opportunity radar, customer expansion list, score
   explanation, commercial action list.
6. Report generation from both insights, into the existing branded HTML template.
7. **Remove the simulated news feed.**

Rehearse against `npm run demo` before wiring, and after. The CLI exists so a
number that does not reconcile is found at a desk rather than in a meeting.

### Sprint B · days 15–30 — evidence, actions, trust
8. Root-cause drill-down showing calculation methodology and source-system
   references on every figure.
9. Action tracker with assignment, dates, status and subsequent metric movement.
10. Ground the AI layer: agents summarise the calculated payload and are never
    the source of a number. Board packs read from `metric_snapshots`, not prose.
11. Security and data FAQ v1 — architecture, permissions, hosting, retention,
    deletion, AI use, incident process. The playbook puts this on day 5; treat it
    as a written deliverable, not an engineering one, and it fits.

### Sprint C · days 31–45 — the production floor
Required before Design Partner 1's data arrives, not before the demo.

12. **Persistent database and tenancy.** Supabase (Postgres, auth and row-level
    security in one service) over Vercel Postgres + Auth.js, for one-engineer speed.
    Tenant isolation enforced in the database — "we filter in the frontend" ends a
    security review.

    ```
    funds            id, name, region
    users            id, fund_id, email, role
    companies        id, fund_id, name, sector, stage, currency
    connections      id, company_id, provider, access_token_enc, refresh_token_enc,
                     expires_at, tenant_ref, status
    metric_snapshots id, company_id, as_of, metric, value, source, raw_ref
    actions          id, insight_id, company_id, owner, due, status, watch_metric
    audit_log        id, fund_id, user_id, action, target, at
    ```

13. **Authentication and roles** — magic link or Google SSO; GP admin, GP analyst,
    portfolio-company user.
14. **Xero tokens out of the cookie** into `connections`, encrypted, with a refresh
    worker, multiple organisations per fund, and a visible reconnect state rather
    than a blank chart. Today's cookie breaks the moment two people from the same
    fund log in, and it expires mid-demo.
15. **Self-serve company onboarding** — GP adds a portfolio company, invites its
    finance lead, they authorise their own Xero organisation. This flow *is* the
    product; everything currently hangs off one hard-wired Demo Company.
16. **Nightly snapshot job** writing `metric_snapshots`. This is what makes the
    handover's claim true — that any integration can go offline without breaking a
    screen.

> **Xero certification — a correction.** An earlier draft called the ~25-organisation
> limit on uncertified apps a week-one emergency. It is not: two design partners
> at two to three portfolio companies each sit well inside it. It becomes binding
> at Foundation and Growth tier (10–25 portcos per customer), so start
> certification around month 3. Verify the current limit on developer.xero.com
> rather than trusting the number here.

### Deliberately not in any sprint
Bloomberg, Refinitiv, PitchBook, Morningstar, Citi Velocity, Nomura Connexus,
Goldman Marquee, SWIFT gpi, FIX, the regional banks, Workday, Salesforce,
Zendesk, D&B, Sustainalytics, DocuSign, Datasite, the full autonomous agent
layer, multi-turn chat, AWS migration, TimescaleDB, multi-region standby. The
playbook is explicit: **prioritise integrations driven by signed pilots, not logo
count.** Build a connector when a design partner's portfolio requires it, under a
paid statement of work.

---

## 5. Commercial track

The playbook is the operating plan and does not need restating. What follows is
only the dependency map — where the commercial plan needs something from James,
and where its assumptions need adjusting.

| Playbook expectation | Reality | Adjustment |
|---|---|---|
| Scenario demo built and rehearsed by day 4–5 | The primary scenarios are the least-built parts of the platform. Realistically day 14. | Days 1–10 are discovery, which needs no demo. The playbook itself puts scenario demos at 2–3 per week from day 11. **Demo deadline is day 14.** |
| Security and data FAQ v1 by day 5 | A writing task, not a build task | Achievable. Do it. |
| Discovery before demo, always | Correct, and worth defending | The temptation with a good platform is to open with it. Don't. |
| Paid pilot, never open-ended free | Correct | An earlier draft of this plan proposed a free two-week trial as the closer. The playbook names the free-pilot trap as a risk. **Withdrawn.** |
| USD 25–40k pilot, 12 weeks, 2–3 portcos | Consistent with the floor being ready by day 45 | Hold packaging stable across both design partners so the two are comparable. |

**The proof gate that matters** — from the playbook's own delivery plan: *first
trusted signal within 30 days of pilot start.* Sprint C exists to make that
possible. If the floor is not ready when Design Partner 1 signs, that gate is
missed at the first attempt, and the pilot's credibility does not recover.

---

## 6. Reconciled 90 days

Both tracks on one clock. Playbook phases in the left column, engineering in the right.

| Days | Commercial (Gerard) | Engineering (James) | Gate |
|---|---|---|---|
| 1–10 | Accounts and opportunities layer; 40–60 person launch list; positioning and diagnostic; pilot one-pager and pricing; first five approaches; five introduction requests | **Sprint A** — command centre, company page, insight card, scenarios 1 and 4, report generation; news feed removed | Two discoveries run; demo build on track |
| 11–30 | 20–25 Wave 1 approaches; 10–12 discovery calls; **four qualified scenario demos**; two pilot-scope workshops; roundtable booked | **Sprint A closes day 14.** Sprint B — drill-down evidence, action tracker, grounded AI, security FAQ | A first-time viewer understands the portfolio in 30 seconds; the revenue alert traces to evidence without breaking flow |
| 31–60 | Three to four comparable design-partner proposals; **Design Partner 1 closed and launched**; Wave 2 activated; first Portfolio Intelligence Brief | **Sprint C** — database, auth, tenancy, token vault, onboarding, snapshots. Complete by day 45. | A fund that has never met you connects its own portfolio company unaided |
| 61–90 | **Design Partner 2 closed**; annual conversion scope agreed with DP1 before its pilot ends; one approved reference or proof asset | Hardening driven by pilot feedback only. Connector work only against a signed pilot. Xero certification started. | **First trusted signal delivered inside 30 days of pilot start** |

---

## 7. Risks

The playbook's risk register stands. These are the additional ones that come from
the engineering side or from the seams between the documents.

| Risk | Early warning | Mitigation |
|---|---|---|
| **Demo slips past day 14** | Sprint A still open at day 10 | Cut scenario 4's opportunity radar to a list before cutting evidence or reconciliation. A thinner demo that survives inspection beats a fuller one that does not. |
| **AI states a number it computed** | Any board-pack figure not traceable to a snapshot | Structurally prevented in the foundation package. Preserve the property when wiring: agents receive calculated payloads and write prose. |
| **Simulated news feed reaches a prospect** | It is on the deployed site now | Remove in Sprint A. One fabricated data point costs more than the feature is worth. |
| **Single-engineer dependency** | Any illness, or the raise absorbing James | Deploy and environment setup are documented in the handover. First post-raise hire is engineering. |
| **Floor not ready when DP1 signs** | Sprint C open at day 45 | Sprint C has no dependency on Sprint B; it can start early if a pilot closes ahead of schedule. |
| **Demo state lost mid-pitch** | Cookie-based Xero tokens expire silently | Reconnect immediately before every demo until Sprint C lands. The foundation package needs no connection at all — the demo dataset is self-contained. |
| **Selling the roadmap** | A prospect asks about Bloomberg and the conversation follows | The playbook's rule: lead with the outcome. Direction, never commitment. |
| **Bespoke build creep in a pilot** | A design partner asks for their ERP in week 2 | Playbook guardrail: reusable product case, or a separate paid statement of work. |

---

## 8. Decisions needed

1. **Supabase or Vercel Postgres + Auth.js?** Recommendation: Supabase, for
   one-engineer speed and database-enforced tenant isolation.
2. **Confirm the demo deadline is day 14, not day 5**, and that days 1–10 of
   outreach run discovery-only.
3. **Is Meridian's runway change acceptable** (4.8 → 8.5 months) to satisfy the
   demo specification's scenario 2?
4. **Which company fronts scenario 1?** Currently Kestrel Analytics, added as an
   eleventh name. If the existing five must be preserved exactly, say so and the
   scenario moves to SwiftLogix.
5. **Confirm the playbook's pricing is the rate card** for both design partners —
   USD 25–40k pilot, credited on conversion within 30 days.
6. **Handover items that touch the sale:** alba-pip.com DNS live; Caledonia
   branding from Gerard; what "TEAM IE" stands for.

---

## 9. The measure

The playbook sets it, and it is the right one:

> **Two paid design partners, four pilot proposals, and USD 150–250k of
> identified conversion ARR by day 90.**

The demo specification sets the gate that stands in front of it:

> **A first-time viewer understands the portfolio in thirty seconds, the revenue
> alert traces from portfolio signal to underlying evidence without breaking the
> flow, the impact reconciles with the visible driver bridge, and no part of the
> demo depends on the presenter explaining away a screen.**

Everything in section 4 exists to pass that gate. Everything on the deferred list
exists to be built after it.

---

*Alba PIP · Caledonia Alba · Portfolio Intelligence Platform*
*Confidential — not for distribution*
