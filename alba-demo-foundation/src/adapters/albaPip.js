/**
 * Adapters onto the platform's real contracts.
 *
 * Verified against `jbgray1874/alba-pip` at 2c591dc — `src/lib/financeData.js`
 * and `api/ai/boardpack.js`. An earlier version of this file was written from
 * the prose description in the source-code handover and got every array element
 * shape wrong: `arAging` rows are `{bucket, val, color}` not `{label, value}`,
 * the bridge discriminator is `kind` not `type`, and `burnCats`, `byProduct`
 * and `opexLines` each carry a `series` that `FinanceDrilldown.jsx` reads to
 * draw its sparklines. Emitting the guessed shapes would have blanked the
 * drill-down.
 *
 * What this adds is not shape but substance. The platform synthesises each
 * sparkline with `trend(end, 6, growth)` — an independent straight line drawn
 * back from every metric's current value, so the payroll trend and the R&D
 * trend have no common origin and cannot be reconciled against each other.
 * Here every series is a slice of one eighteen-month ledger, so they do.
 *
 * Units follow the platform exactly, including its internal inconsistency:
 * `balance`, `burn`, `value` fields are in GBP thousands, while `amount` and
 * `val` fields are in whole pounds. This package works in millions; the
 * conversion happens here and nowhere else.
 */

import { getCompany, getPortfolio, FIN_SEED, SOURCES, AS_OF } from '../portfolio.js';
import { last, runway } from '../kpis.js';
import { buildScenario1 } from '../scenario1-revenue-miss.js';
import { buildScenario4 } from '../scenario4-expansion.js';
import { buildCashRunwaySignal, buildMarginSignal } from '../secondary-signals.js';

/** Millions → thousands, the platform's working unit. */
const k = (millions) => millions * 1000;
/** Millions → whole pounds, for the `amount` and `val` fields. */
const pounds = (millions) => Math.round(millions * 1_000_000);

const round1 = (n) => Math.round(n * 10) / 10;

// ── Constants mirrored from src/lib/financeData.js ──────────────────────────
// Kept identical, including the colours, so nothing already on screen moves.

export const BURN_SPLIT = [
  { key: 'payroll', label: 'Payroll & Benefits', prop: 0.59, color: '#3d8bff' },
  { key: 'marketing', label: 'Sales & Marketing', prop: 0.15, color: '#9b6dff' },
  { key: 'overheads', label: 'Overheads & Facilities', prop: 0.16, color: '#f5a524' },
  { key: 'saas', label: 'Software & SaaS', prop: 0.10, color: '#00c97a' },
];

export const REV_PRODUCTS = [
  { key: 'core', label: 'Core Platform', prop: 0.60 },
  { key: 'addons', label: 'Add-on Modules', prop: 0.24 },
  { key: 'services', label: 'Professional Services', prop: 0.16 },
];

export const REV_REGIONS = [
  { key: 'uk', label: 'United Kingdom', prop: 0.57 },
  { key: 'eu', label: 'Europe', prop: 0.27 },
  { key: 'na', label: 'North America', prop: 0.16 },
];

const CUSTOMERS = [
  'Acme Corporation', 'Beta Holdings', 'TechVentures Ltd', 'Delta Systems',
  'Gamma Industries', 'Orion Retail', 'Vertex Group', 'Halo Logistics',
];

const DEBTOR_SPLIT = [0.33, 0.245, 0.20, 0.13, 0.095];
const DEBTOR_DAYS = [47, 38, 52, 33, 41];
const OVERDUE_RATIO = 0.28;

const AR_BANDS = [
  { bucket: 'Current (0–30)', color: '#00c97a' },
  { bucket: '31–60 days', color: '#f5a524' },
  { bucket: '61–90 days', color: '#ff8a3d' },
  { bucket: '90+ days', color: '#ff3d5a' },
];

const OPEX_SPLIT = [
  { bridgeLabel: 'Sales & Mktg', label: 'Sales & Marketing', prop: 0.34 },
  { bridgeLabel: 'R&D', label: 'Research & Development', prop: 0.35 },
  { bridgeLabel: 'G&A', label: 'General & Admin', prop: 0.31 },
];

const MONTH_ABBR = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/** Six-month series for a metric, taken from the ledger rather than synthesised. */
function seriesFrom(series, field, prop) {
  return series.slice(-6).map((r) => round1(k(r[field]) * prop));
}

function debtorStatus(days) {
  return days > 45 ? 'critical' : days > 35 ? 'overdue' : 'watch';
}

/**
 * Emit the `buildFinance(co)` shape.
 *
 * Signature-compatible: accepts the company object the platform passes, or an
 * id. Every key the platform returns is present with the same name, type and
 * unit; `history`, `source` and `refreshedAt` are added, which existing
 * consumers ignore and the evidence trail needs.
 */
export function toFinanceShape(co) {
  const id = typeof co === 'string' ? co : co.id;
  const company = getCompany(id);
  const series = company.series;
  const latest = last(series);
  const rw = runway(series);

  const revenue = k(latest.revenue);
  const budget = k(latest.planRevenue);
  const cash = k(latest.cashClose);
  const burn = k(latest.netBurn);
  const gm = Math.round(latest.grossMarginPct * 100);
  const ebitdaPct = Math.round(latest.ebitdaMarginPct * 100);

  // ── Burn categories ──
  const burnCats = BURN_SPLIT.map((b) => ({
    ...b,
    value: burn * b.prop,
    series: seriesFrom(series, 'netBurn', b.prop),
  }));

  // ── AR and overdue debtors ──
  const overdueTotal = +(revenue * OVERDUE_RATIO).toFixed(0);
  const debtors = DEBTOR_SPLIT.map((p, i) => ({
    party: CUSTOMERS[i],
    amount: Math.round(overdueTotal * p * 1000),
    daysOverdue: DEBTOR_DAYS[i],
    invoice: `INV-${2400 + i * 7}`,
    due: `${5 + i * 4} Apr 2026`,
    status: debtorStatus(DEBTOR_DAYS[i]),
  }));

  const arAging = [
    { ...AR_BANDS[0], val: Math.round(revenue * 0.57 * 1000) },
    { ...AR_BANDS[1], val: Math.round(overdueTotal * 0.70 * 1000) },
    { ...AR_BANDS[2], val: Math.round(overdueTotal * 0.22 * 1000) },
    { ...AR_BANDS[3], val: Math.round(overdueTotal * 0.08 * 1000) },
  ].map(({ bucket, val, color }) => ({ bucket, val, color }));

  // ── Cash projection, forward from the as-of month ──
  const asOfMonth = Number(AS_OF.slice(5, 7)) - 1;
  const cashProj = Array.from({ length: 9 }, (_, i) => ({
    m: MONTH_ABBR[(asOfMonth + i) % 12],
    v: Math.round(cash - burn * i),
  })).filter((p) => p.v > -burn);

  // ── Revenue breakdowns ──
  const byProduct = REV_PRODUCTS.map((p) => ({
    ...p,
    value: revenue * p.prop,
    series: seriesFrom(series, 'revenue', p.prop),
  }));
  const byRegion = REV_REGIONS.map((r) => ({ ...r, value: revenue * r.prop }));

  const deals = CUSTOMERS.slice(0, 6).map((c, i) => ({
    party: c,
    amount: Math.round(revenue * [0.16, 0.13, 0.11, 0.09, 0.07, 0.05][i] * 1000),
    product: REV_PRODUCTS[i % 3].label,
    region: REV_REGIONS[i % 3].label,
    invoice: `INV-${2500 + i * 5}`,
    date: `${2 + i * 3} May 2026`,
    status: 'paid',
  }));

  // ── EBITDA bridge ──
  const grossProfit = (revenue * gm) / 100;
  const cogs = revenue - grossProfit;
  const ebitda = (revenue * ebitdaPct) / 100;
  const opexTotal = grossProfit - ebitda;

  const bridge = [
    { label: 'Revenue', value: revenue, kind: 'start' },
    { label: 'Cost of Sales', value: -cogs, kind: 'neg' },
    { label: 'Gross Profit', value: grossProfit, kind: 'subtotal' },
    ...OPEX_SPLIT.map((o) => ({ label: o.bridgeLabel, value: -opexTotal * o.prop, kind: 'neg' })),
    { label: 'EBITDA', value: ebitda, kind: 'end' },
  ];

  const opexLines = OPEX_SPLIT.map((o) => ({
    label: o.label,
    value: opexTotal * o.prop,
    series: seriesFrom(series, 'opex', o.prop),
  }));

  return {
    seed: FIN_SEED[id] ?? null,
    runway: rw.months === Infinity ? Infinity : +(cash / burn).toFixed(1),
    status: typeof co === 'object' && co.status ? co.status : (company.rag ?? '').toLowerCase(),

    cash: {
      balance: cash, burn, runway: +(cash / burn).toFixed(1),
      burnCats, debtors, arAging, overdueTotal, cashProj,
      // Additive: the ledger the series above are drawn from.
      history: series.map((r) => ({ month: r.month, balance: k(r.cashClose), burn: k(r.netBurn) })),
      source: SOURCES.bank.system,
      refreshedAt: AS_OF,
    },

    revenue: {
      total: revenue, budget, byProduct, byRegion, deals,
      history: series.map((r) => ({ month: r.month, actual: k(r.revenue), budget: k(r.planRevenue) })),
      source: SOURCES.financials.system,
      refreshedAt: AS_OF,
    },

    ebitda: {
      pct: ebitdaPct, value: ebitda, bridge, opexLines, grossMargin: gm,
      history: series.map((r) => ({
        month: r.month,
        ebitda: k(r.ebitda),
        marginPct: round1(r.ebitdaMarginPct * 100),
      })),
      source: SOURCES.financials.system,
      refreshedAt: AS_OF,
    },
  };
}

export function toFinanceShapeAll() {
  return Object.fromEntries(getPortfolio().map((c) => [c.id, toFinanceShape(c.id)]));
}

// ── Board pack ──────────────────────────────────────────────────────────────

/** The platform formats deadlines as "30 Jun 2026". */
function ukDate(iso) {
  const [y, m, d] = iso.split('-').map(Number);
  return `${d} ${MONTH_ABBR[m - 1]} ${y}`;
}

/**
 * Emit the `api/ai/boardpack.js` JSON schema from calculated values.
 *
 * The endpoint currently asks Grok to return this object whole — metrics
 * included — and falls back to a hardcoded pack when the key is absent. Both
 * paths put figures in the model's gift. Here every metric, risk, opportunity
 * and action is computed, and only `executiveSummary` and `outlook` are left
 * null for the model to write.
 */
export function toBoardPackSchema(co) {
  const id = typeof co === 'string' ? co : co.id;
  const company = getCompany(id);
  const latest = last(company.series);
  const rw = runway(company.series);
  const sym = { GBP: '£', USD: '$' }[company.currency] ?? '';
  const kk = (m) => `${sym}${Math.round(m * 1000)}k`;
  const rag = (good, ok) => (good ? 'green' : ok ? 'amber' : 'red');

  const insights = insightsFor(id);

  return {
    executiveSummary: null,
    outlook: null,

    keyMetrics: [
      {
        label: 'MRR',
        value: kk(latest.revenue),
        vs: `target ${kk(latest.planRevenue)}`,
        rag: rag(latest.revenue >= latest.planRevenue, latest.revenue >= latest.planRevenue * 0.95),
      },
      {
        label: 'Runway',
        value: Number.isFinite(rw.months) ? `${rw.months.toFixed(1)}mo` : 'Cash generative',
        vs: 'target 6mo',
        rag: rag(rw.months >= 12, rw.months >= 6),
      },
      {
        label: 'Gross Margin',
        value: `${Math.round(latest.grossMarginPct * 100)}%`,
        vs: `${Math.round(company.series[0].grossMarginPct * 100)}% 18 months ago`,
        rag: rag(
          latest.grossMarginPct >= company.series[0].grossMarginPct,
          latest.grossMarginPct >= company.series[0].grossMarginPct - 0.03,
        ),
      },
      {
        label: 'EBITDA Margin',
        value: `${(latest.ebitdaMarginPct * 100).toFixed(1)}%`,
        vs: `${kk(latest.ebitda)} this month`,
        rag: rag(latest.ebitda > 0, latest.ebitdaMarginPct > -0.1),
      },
      {
        label: 'Headcount',
        value: String(latest.headcount),
        vs: `plan ${latest.planHeadcount}`,
        rag: rag(latest.headcount >= latest.planHeadcount, true),
      },
    ],

    risks: insights
      .filter((i) => i.type === 'risk')
      .map((i) => ({
        title: i.headline,
        detail: `${i.whatHappened} ${i.whyItMatters}`,
        severity: i.confidence.label === 'High' ? 'high' : 'medium',
        evidence: i.evidence.map((e) => ({ metric: e.label, value: e.value, source: e.source })),
      })),

    opportunities: insights
      .filter((i) => i.type === 'opportunity')
      .map((i) => ({
        title: i.headline,
        detail: `${i.whatHappened} ${i.whyItMatters}`,
        evidence: i.evidence.map((e) => ({ metric: e.label, value: e.value, source: e.source })),
      })),

    actions: insights.flatMap((i) =>
      i.actions.map((a) => ({
        action: a.action,
        owner: a.owner,
        deadline: ukDate(a.due),
        priority: i.type === 'risk' ? 'high' : 'medium',
        rationale: a.rationale,
      })),
    ),

    provenance: {
      note:
        'Every metric, risk, opportunity and action here is calculated from the portfolio data ' +
        'model. The language model is asked only for executiveSummary and outlook.',
      sources: [...new Set(insights.flatMap((i) => i.evidence.map((e) => e.source)))],
      refreshedAt: AS_OF,
    },
  };
}

function insightsFor(id) {
  const out = [];
  const s1 = buildScenario1();
  if (s1.company.id === id) out.push(s1.insight);
  const s4 = buildScenario4();
  if (s4.company.id === id) out.push(s4.insight);
  if (id === 'meridian') out.push(buildCashRunwaySignal());
  if (id === 'forgetech') out.push(buildMarginSignal());
  return out;
}

export const BOARD_PACK_PROMPT =
  'You are given a board pack object in which every metric, risk, opportunity and action has ' +
  'already been calculated from source systems. Return the same object with only two fields ' +
  'changed: write `executiveSummary` (2-3 sentences) and `outlook` (2 sentences). Do not add, ' +
  'remove, reorder or alter any other field. Do not introduce any figure that does not already ' +
  'appear in the object. If a figure you want to cite is not present, write around it. ' +
  'UK English, direct, commercially minded, no waffle.';

/** The `FEED_STATUS` shape from src/lib/dataFeeds.js, extended for the demo dataset. */
export function toFeedStatus({ xero = false, stripe = false, hubspot = false } = {}) {
  return {
    portfolio: { status: 'simulated', label: 'Alba demo dataset', detail: '10 companies, 18 months' },
    xero: { status: xero ? 'live' : 'simulated', label: 'Xero' },
    stripe: { status: stripe ? 'live' : 'simulated', label: 'Stripe' },
    hubspot: { status: hubspot ? 'live' : 'simulated', label: 'HubSpot' },
  };
}
