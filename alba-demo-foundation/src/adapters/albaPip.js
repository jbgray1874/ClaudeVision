/**
 * Adapters onto the platform's existing contracts.
 *
 * The React app already has two well-defined shapes, documented in the source
 * handover: the object `buildFinance(company)` returns in `src/lib/financeData.js`,
 * and the JSON schema `api/ai/boardpack.js` instructs Grok to produce. Both are
 * already consumed by working screens.
 *
 * Rather than ask those screens to change, this module emits the same shapes
 * from calculated data. `FinanceDrilldown.jsx` keeps its four levels, its
 * breadcrumb and its Xero overlay untouched; what changes is that the numbers
 * behind them now come from eighteen months of history rather than a single
 * seed row, and carry their source.
 *
 * Units: the platform works in GBP thousands. This package works in millions.
 * The conversion happens here and nowhere else.
 */

import { getCompany, getPortfolio, FIN_SEED, SOURCES, AS_OF } from '../portfolio.js';
import { last, runway, sumBy } from '../kpis.js';
import { buildScenario1 } from '../scenario1-revenue-miss.js';
import { buildScenario4 } from '../scenario4-expansion.js';
import { buildCashRunwaySignal, buildMarginSignal } from '../secondary-signals.js';

/** Millions → thousands, rounded the way the platform displays them. */
const k = (millions) => Math.round(millions * 1000);

/**
 * Split a whole number across shares so the parts sum to the total exactly.
 *
 * Rounding each share independently leaves the parts a unit or two off the
 * figure above them, which on a waterfall or a category breakdown reads as an
 * arithmetic error. Largest remainder puts the rounding difference somewhere
 * deliberate instead.
 */
function allocate(total, shares) {
  const raw = shares.map((s) => total * s);
  const floors = raw.map(Math.floor);
  let remainder = Math.round(total - floors.reduce((t, f) => t + f, 0));
  const order = raw
    .map((v, i) => ({ i, frac: v - Math.floor(v) }))
    .sort((a, b) => b.frac - a.frac);
  const out = [...floors];
  for (let n = 0; n < order.length && remainder > 0; n++, remainder--) out[order[n].i] += 1;
  return out;
}

/** Proportions the platform already uses, kept so existing screens do not shift. */
export const BURN_CATEGORIES = [
  { key: 'payroll', label: 'Payroll', share: 0.59 },
  { key: 'marketing', label: 'Sales & Marketing', share: 0.15 },
  { key: 'overheads', label: 'Overheads', share: 0.16 },
  { key: 'saas', label: 'Software & Infrastructure', share: 0.10 },
];

export const REVENUE_BY_PRODUCT = [
  { label: 'Core Platform', share: 0.60 },
  { label: 'Add-ons', share: 0.24 },
  { label: 'Services', share: 0.16 },
];

export const REVENUE_BY_REGION = [
  { label: 'UK', share: 0.57 },
  { label: 'EU', share: 0.27 },
  { label: 'North America', share: 0.16 },
];

export const AR_AGING_BANDS = [
  { label: 'Current', share: 0.46 },
  { label: '31–60 days', share: 0.27 },
  { label: '61–90 days', share: 0.17 },
  { label: '90 days+', share: 0.10 },
];

const OVERDUE_RATIO = 0.28; // the platform's existing relationship to monthly revenue

const OPEX_LINES = [
  { label: 'Sales & Marketing', share: 0.42 },
  { label: 'R&D', share: 0.35 },
  { label: 'G&A', share: 0.23 },
];

function ragFor(company, runwayMonths) {
  if (company.rag) return company.rag.toLowerCase();
  if (runwayMonths < 4) return 'red';
  if (runwayMonths < 9) return 'amber';
  return 'green';
}

/**
 * Emit the `buildFinance(company)` shape, in GBP thousands.
 *
 * Drop-in for `src/lib/financeData.js`. The reconciliation principle the
 * platform already relies on is preserved: EBITDA is gross profit less opex,
 * gross profit is revenue less cost of sales, and the overdue total is the sum
 * of the individual debtor rows rather than a separately computed figure.
 */
export function toFinanceShape(companyId) {
  const company = getCompany(companyId);
  const series = company.series;
  const latest = last(series);
  const rw = runway(series);

  const revenue = k(latest.revenue);
  const budget = k(latest.planRevenue);
  const cash = k(latest.cashClose);
  const burn = k(latest.netBurn);
  const grossProfit = k(latest.grossProfit);
  const cogs = k(latest.cogs);
  const opex = k(latest.opex);
  const ebitda = k(latest.ebitda);

  // Debtors first; the overdue total is then their sum, not an independent number.
  const overdueTarget = revenue * OVERDUE_RATIO;
  const debtorSplit = [0.42, 0.31, 0.27];
  const debtorNames = ['DIISR', 'Rex Media Group', 'Port & Philip Freight'];
  const debtors = debtorNames.map((party, i) => ({
    party,
    amount: Math.round(overdueTarget * debtorSplit[i]),
    daysOverdue: [47, 33, 21][i],
    status: ['Escalated', 'Chasing', 'Reminder sent'][i],
  }));
  const overdueTotal = debtors.reduce((t, d) => t + d.amount, 0);

  const receivable = Math.round(revenue * 1.34);
  const opexParts = allocate(opex, OPEX_LINES.map((l) => l.share));

  return {
    seed: FIN_SEED[companyId] ?? null,
    runway: Math.round(rw.months * 10) / 10,
    status: ragFor(company, rw.months),

    cash: {
      balance: cash,
      burn,
      runway: Math.round(rw.months * 10) / 10,
      burnCats: (() => {
        const parts = allocate(burn, BURN_CATEGORIES.map((c) => c.share));
        return BURN_CATEGORIES.map((c, i) => ({ label: c.label, value: parts[i], share: c.share }));
      })(),
      debtors,
      arAging: (() => {
        const parts = allocate(receivable, AR_AGING_BANDS.map((b) => b.share));
        return AR_AGING_BANDS.map((b, i) => ({ label: b.label, value: parts[i] }));
      })(),
      overdueTotal,
      // Nine months forward on the current burn — the platform's existing chart.
      cashProj: Array.from({ length: 9 }, (_, i) => ({
        month: i + 1,
        balance: Math.max(0, cash - burn * (i + 1)),
      })),
      // New: the actual eighteen-month history behind the position.
      history: series.map((r) => ({ month: r.month, balance: k(r.cashClose), burn: k(r.netBurn) })),
      source: SOURCES.bank.system,
      refreshedAt: AS_OF,
    },

    revenue: {
      total: revenue,
      budget,
      variance: revenue - budget,
      variancePct: (revenue - budget) / budget,
      byProduct: (() => {
        const parts = allocate(revenue, REVENUE_BY_PRODUCT.map((p) => p.share));
        return REVENUE_BY_PRODUCT.map((p, i) => ({ label: p.label, value: parts[i] }));
      })(),
      byRegion: (() => {
        const parts = allocate(revenue, REVENUE_BY_REGION.map((r) => r.share));
        return REVENUE_BY_REGION.map((r, i) => ({ label: r.label, value: parts[i] }));
      })(),
      deals: topDeals(companyId, revenue),
      history: series.map((r) => ({
        month: r.month,
        actual: k(r.revenue),
        budget: k(r.planRevenue),
      })),
      source: SOURCES.financials.system,
      refreshedAt: AS_OF,
    },

    ebitda: {
      pct: Math.round(latest.ebitdaMarginPct * 1000) / 10,
      value: grossProfit - opexParts.reduce((t, v) => t + v, 0),
      grossMargin: Math.round(latest.grossMarginPct * 1000) / 10,
      bridge: [
        { label: 'Revenue', value: revenue, type: 'total' },
        { label: 'Cost of sales', value: -cogs, type: 'delta' },
        { label: 'Gross profit', value: grossProfit, type: 'subtotal' },
        ...OPEX_LINES.map((l, i) => ({ label: l.label, value: -opexParts[i], type: 'delta' })),
        {
          label: 'EBITDA',
          value: grossProfit - opexParts.reduce((t, v) => t + v, 0),
          type: 'total',
        },
      ],
      opexLines: OPEX_LINES.map((l, i) => ({
        label: l.label,
        value: opexParts[i],
        // Six-month trend from the real series rather than an invented sparkline.
        trend: series.slice(-6).map((r) => Math.round(k(r.opex) * l.share)),
      })),
      history: series.map((r) => ({
        month: r.month,
        ebitda: k(r.ebitda),
        marginPct: Math.round(r.ebitdaMarginPct * 1000) / 10,
      })),
      source: SOURCES.financials.system,
      refreshedAt: AS_OF,
    },
  };
}

function topDeals(companyId, monthlyRevenue) {
  const names = [
    'Harborline Insurance', 'Straits Manufacturing', 'Vantage Health Network',
    'Orient Freight', 'Caldera Energy', 'Meridian Bank Trust',
  ];
  const shares = [0.19, 0.16, 0.14, 0.12, 0.10, 0.08];
  const renewals = ['2026-11-30', '2027-01-31', '2026-12-31', '2027-03-31', '2027-02-28', '2026-10-31'];
  return names.map((name, i) => ({
    customer: name,
    value: Math.round(monthlyRevenue * 12 * shares[i]),
    renewal: renewals[i],
  }));
}

/** Every company, in the platform's shape. */
export function toFinanceShapeAll() {
  return Object.fromEntries(getPortfolio().map((c) => [c.id, toFinanceShape(c.id)]));
}

/**
 * Emit the `api/ai/boardpack.js` JSON schema from calculated values.
 *
 * The existing endpoint asks Grok to produce this object in full, which means
 * the model supplies the metrics as well as the prose. This inverts that: the
 * metrics, risks, opportunities and actions are computed here, and the two
 * genuinely narrative fields are left for the model to write.
 *
 * Pass the result to the frontend renderer unchanged, or hand it to Grok as
 * context with instructions to fill only `executiveSummary` and `outlook`.
 */
export function toBoardPackSchema(companyId) {
  const company = getCompany(companyId);
  const series = company.series;
  const latest = last(series);
  const rw = runway(series);
  const cur = company.currency;
  const sym = { GBP: '£', USD: '$' }[cur] ?? '';

  const money = (millions) => `${sym}${k(millions)}k`;
  const ragOf = (ok, warn) => (ok ? 'green' : warn ? 'amber' : 'red');

  const insights = collectInsightsFor(companyId);
  const quarter = series.slice(-3);

  return {
    company: company.name,
    asOf: AS_OF,

    // Left for the language model. Everything else is calculated.
    executiveSummary: null,
    outlook: null,

    keyMetrics: [
      {
        label: 'Revenue (month)',
        value: money(latest.revenue),
        vs: `plan ${money(latest.planRevenue)}`,
        rag: ragOf(latest.revenue >= latest.planRevenue, latest.revenue >= latest.planRevenue * 0.95),
      },
      {
        label: 'Revenue (quarter)',
        value: money(sumBy(quarter, 'revenue')),
        vs: `plan ${money(sumBy(quarter, 'planRevenue'))}`,
        rag: ragOf(
          sumBy(quarter, 'revenue') >= sumBy(quarter, 'planRevenue'),
          sumBy(quarter, 'revenue') >= sumBy(quarter, 'planRevenue') * 0.95,
        ),
      },
      {
        label: 'Gross margin',
        value: `${(latest.grossMarginPct * 100).toFixed(1)}%`,
        vs: `${(series[0].grossMarginPct * 100).toFixed(1)}% eighteen months ago`,
        rag: ragOf(
          latest.grossMarginPct >= series[0].grossMarginPct,
          latest.grossMarginPct >= series[0].grossMarginPct - 0.03,
        ),
      },
      {
        label: 'EBITDA margin',
        value: `${(latest.ebitdaMarginPct * 100).toFixed(1)}%`,
        vs: `${money(latest.ebitda)} this month`,
        rag: ragOf(latest.ebitda > 0, latest.ebitdaMarginPct > -0.1),
      },
      {
        label: 'Cash',
        value: money(latest.cashClose),
        vs: `burn ${money(latest.netBurn)} per month`,
        rag: ragOf(rw.months >= 12, rw.months >= 6),
      },
      {
        label: 'Runway',
        value: Number.isFinite(rw.months) ? `${rw.months.toFixed(1)} months` : 'Cash generative',
        vs: rw.method,
        rag: ragOf(rw.months >= 12, rw.months >= 6),
      },
      {
        label: 'Headcount',
        value: String(latest.headcount),
        vs: `plan ${latest.planHeadcount}`,
        rag: ragOf(latest.headcount >= latest.planHeadcount, true),
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
        deadline: a.due, // the platform's field name
        priority: i.type === 'risk' ? 'high' : 'medium',
        rationale: a.rationale,
      })),
    ),

    provenance: {
      note:
        'Every metric, risk, opportunity and action in this object is calculated from the ' +
        'portfolio data model. The language model is asked only for executiveSummary and outlook.',
      sources: [...new Set(insights.flatMap((i) => i.evidence.map((e) => e.source)))],
      refreshedAt: AS_OF,
    },
  };
}

function collectInsightsFor(companyId) {
  const all = [];
  const scenario1 = buildScenario1();
  if (scenario1.company.id === companyId) all.push(scenario1.insight);
  const scenario4 = buildScenario4();
  if (scenario4.company.id === companyId) all.push(scenario4.insight);
  if (companyId === 'meridian') all.push(buildCashRunwaySignal());
  if (companyId === 'forgetech') all.push(buildMarginSignal());
  return all;
}

/**
 * The prompt to send alongside `toBoardPackSchema()`.
 *
 * Written to close the failure mode the current endpoint leaves open: a model
 * asked to produce the whole schema will supply plausible numbers when it is
 * unsure, and a wrong cash position in a board pack is not recoverable.
 */
export const BOARD_PACK_PROMPT =
  'You are given a board pack object in which every metric, risk, opportunity and action has ' +
  'already been calculated from source systems. Return the same object with only two fields ' +
  'changed: write `executiveSummary` (at most 120 words) and `outlook` (at most 60 words). ' +
  'Do not add, remove, reorder or alter any other field. Do not introduce any figure that does ' +
  'not already appear in the object. If a figure you want to cite is not present, write around ' +
  'it. UK English, direct, commercially minded, no waffle.';

/** The `FEED_STATUS` shape, extended to cover the demo dataset. */
export function toFeedStatus({ xero = false, stripe = false, hubspot = false } = {}) {
  return {
    portfolio: { status: 'simulated', label: 'Alba demo dataset', detail: '10 companies, 18 months' },
    xero: { status: xero ? 'live' : 'simulated', label: 'Xero' },
    stripe: { status: stripe ? 'live' : 'simulated', label: 'Stripe' },
    hubspot: { status: hubspot ? 'live' : 'simulated', label: 'HubSpot' },
  };
}
