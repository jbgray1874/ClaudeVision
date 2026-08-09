/**
 * Common portfolio data model.
 *
 * Ten fictional portfolio companies with eighteen months of monthly financial
 * and people history. This is the "common data foundation" from the demo
 * specification — every scenario reads from it, so figures reconcile wherever
 * the user drills.
 *
 * Every series carries its source label and refresh date because the demo
 * acceptance criteria require the user to be able to inspect where a number
 * came from.
 */

import { rngFor, jitter } from './rng.js';

/** Fixed demo clock. Nothing here reads the wall clock — reruns must match. */
export const AS_OF = '2026-08-31';
export const MONTHS = 18; // 2025-03 .. 2026-08

export function monthKeys(count = MONTHS, endMonth = '2026-08') {
  const [ey, em] = endMonth.split('-').map(Number);
  const keys = [];
  for (let i = count - 1; i >= 0; i--) {
    const total = ey * 12 + (em - 1) - i;
    const y = Math.floor(total / 12);
    const m = (total % 12) + 1;
    keys.push(`${y}-${String(m).padStart(2, '0')}`);
  }
  return keys;
}

export const MONTH_KEYS = monthKeys();

/**
 * Company definitions.
 *
 * `arc` fields describe the intended trajectory. They are inputs to generation,
 * not the displayed numbers — everything shown is computed from the series.
 */
export const COMPANIES = [
  {
    id: 'kestrel',
    name: 'Kestrel Analytics',
    sector: 'B2B Software',
    stage: 'Series B',
    region: 'Singapore',
    currency: 'USD',
    fund: 'Alba Growth I',
    scenario: 'revenue-miss',
    healthScore: 74,
    rag: 'AMBER',
    prevRag: 'GREEN',
    arc: {
      revenueStart: 2.62,
      revenueGrowth: 0.0135,
      planPremium: 0.0215, // plan drifts ~3% above the run rate over the period
      gmStart: 0.78,
      gmEnd: 0.76,
      opexRatio: 0.71,
      cashStart: 18.4,
      headcountStart: 168,
      headcountGrowth: 1.6,
      headcountPlanGap: 3,
    },
  },
  {
    id: 'meridian',
    name: 'Meridian SaaS',
    sector: 'B2B SaaS',
    stage: 'Series A',
    region: 'United Kingdom',
    currency: 'GBP',
    fund: 'Alba Growth I',
    scenario: 'cash-runway',
    healthScore: 62,
    rag: 'AMBER',
    prevRag: 'AMBER',
    liveSource: 'Xero — Demo Company (UK)',
    arc: {
      revenueStart: 0.41,
      revenueGrowth: 0.009,
      planPremium: 0.085,
      gmStart: 0.71,
      gmEnd: 0.69,
      opexRatio: 1.34, // spends well ahead of revenue — this is the cash story
      cashStart: 8.6,
      burnStart: 0.19,
      burnRamp: 0.0124,
      headcountStart: 48,
      headcountGrowth: 0.9,
      headcountPlanGap: -2, // hiring ahead of plan, part of the burn problem
    },
  },
  {
    id: 'payflo',
    name: 'PayFlo',
    sector: 'FinTech',
    stage: 'Growth PE',
    region: 'Singapore',
    currency: 'USD',
    fund: 'Alba Growth I',
    scenario: 'expansion',
    healthScore: 88,
    rag: 'GREEN',
    prevRag: 'GREEN',
    arc: {
      revenueStart: 3.05,
      revenueGrowth: 0.0161,
      planPremium: 0.002, // tracking plan closely — nothing here draws attention
      gmStart: 0.74,
      gmEnd: 0.755,
      opexRatio: 0.62,
      cashStart: 26.2,
      headcountStart: 214,
      headcountGrowth: 2.1,
      headcountPlanGap: 1,
    },
  },
  {
    id: 'forgetech',
    name: 'ForgeTech',
    sector: 'Manufacturing',
    stage: 'PE Growth',
    region: 'United Kingdom',
    currency: 'GBP',
    fund: 'Alba Growth I',
    scenario: 'margin',
    healthScore: 84,
    rag: 'GREEN',
    prevRag: 'GREEN',
    arc: {
      revenueStart: 4.10,
      revenueGrowth: 0.0139, // ~18% annualised
      planPremium: -0.012,
      gmStart: 0.42,
      gmEnd: 0.34, // the quality-of-earnings story
      opexRatio: 0.29,
      cashStart: 11.9,
      headcountStart: 340,
      headcountGrowth: 1.4,
      headcountPlanGap: 0,
    },
  },
  {
    id: 'careos',
    name: 'CareOS',
    sector: 'HealthTech',
    stage: 'Series A',
    region: 'United Kingdom',
    currency: 'GBP',
    healthScore: 34,
    rag: 'RED',
    prevRag: 'RED',
    arc: {
      revenueStart: 0.22,
      revenueGrowth: 0.004,
      planPremium: 0.22,
      gmStart: 0.61,
      gmEnd: 0.55,
      opexRatio: 1.9,
      cashStart: 5.1,
      burnStart: 0.21,
      burnRamp: 0.004,
      headcountStart: 31,
      headcountGrowth: 0.2,
      headcountPlanGap: 4,
    },
  },
  {
    id: 'swiftlogix',
    name: 'SwiftLogix',
    sector: 'Logistics',
    stage: 'Series B',
    region: 'Singapore',
    currency: 'USD',
    healthScore: 71,
    rag: 'AMBER',
    prevRag: 'AMBER',
    arc: {
      revenueStart: 1.84,
      revenueGrowth: 0.0102,
      planPremium: 0.048,
      gmStart: 0.38,
      gmEnd: 0.36,
      opexRatio: 0.55,
      cashStart: 9.4,
      headcountStart: 122,
      headcountGrowth: 0.7,
      headcountPlanGap: 2,
    },
  },
  {
    id: 'northgate',
    name: 'Northgate Facilities',
    sector: 'Business Services',
    stage: 'PE Buyout',
    region: 'United Kingdom',
    currency: 'GBP',
    healthScore: 79,
    rag: 'GREEN',
    prevRag: 'AMBER',
    arc: {
      revenueStart: 5.60,
      revenueGrowth: 0.0071,
      planPremium: -0.006,
      gmStart: 0.31,
      gmEnd: 0.325,
      opexRatio: 0.24,
      cashStart: 7.8,
      headcountStart: 610,
      headcountGrowth: 1.1,
      headcountPlanGap: 0,
    },
  },
  {
    id: 'lumen',
    name: 'Lumen Diagnostics',
    sector: 'HealthTech',
    stage: 'Growth PE',
    region: 'United Arab Emirates',
    currency: 'USD',
    healthScore: 66,
    rag: 'AMBER',
    prevRag: 'GREEN',
    arc: {
      revenueStart: 1.28,
      revenueGrowth: 0.0118,
      planPremium: 0.072,
      gmStart: 0.52,
      gmEnd: 0.485,
      opexRatio: 0.49,
      cashStart: 6.4,
      headcountStart: 96,
      headcountGrowth: 0.8,
      headcountPlanGap: 3,
    },
  },
  {
    id: 'solstice',
    name: 'Solstice Energy Services',
    sector: 'Energy Services',
    stage: 'PE Buyout',
    region: 'United Arab Emirates',
    currency: 'USD',
    healthScore: 81,
    rag: 'GREEN',
    prevRag: 'GREEN',
    arc: {
      revenueStart: 6.90,
      revenueGrowth: 0.0086,
      planPremium: -0.018,
      gmStart: 0.27,
      gmEnd: 0.285,
      opexRatio: 0.20,
      cashStart: 14.6,
      headcountStart: 480,
      headcountGrowth: 1.3,
      headcountPlanGap: -1,
    },
  },
  {
    id: 'verdant',
    name: 'Verdant Foods',
    sector: 'Consumer',
    stage: 'PE Growth',
    region: 'Singapore',
    currency: 'USD',
    healthScore: 58,
    rag: 'AMBER',
    prevRag: 'GREEN',
    arc: {
      revenueStart: 3.42,
      revenueGrowth: 0.0049,
      planPremium: 0.115,
      gmStart: 0.34,
      gmEnd: 0.305,
      opexRatio: 0.32,
      cashStart: 5.9,
      headcountStart: 265,
      headcountGrowth: 0.4,
      headcountPlanGap: 5,
    },
  },
];

export const SOURCES = {
  financials: { system: 'Accounting (Xero / NetSuite connector)', refreshedAt: AS_OF },
  pipeline: { system: 'CRM (HubSpot connector)', refreshedAt: AS_OF },
  people: { system: 'HRIS (BambooHR connector)', refreshedAt: AS_OF },
  billing: { system: 'Billing (Stripe connector)', refreshedAt: AS_OF },
  bank: { system: 'Banking (Xero bank feed)', refreshedAt: AS_OF },
};

function round(n, dp = 3) {
  const f = 10 ** dp;
  return Math.round(n * f) / f;
}

/**
 * Build the monthly series for one company.
 *
 * Values are in millions of the company's reporting currency. Cash follows
 * EBITDA less working-capital movement, except where a company defines an
 * explicit burn ramp (the cash-story companies), in which case burn is the
 * driver and cash is its running consequence.
 */
export function buildSeries(company) {
  const rng = rngFor(`series:${company.id}`);
  const a = company.arc;
  const months = MONTH_KEYS;
  const rows = [];

  let cash = a.cashStart;

  for (let i = 0; i < months.length; i++) {
    const month = months[i];
    const trend = a.revenueStart * (1 + a.revenueGrowth) ** i;

    // Round the primitives first and derive everything else from the rounded
    // values. A drill-down that shows gross profit less operating cost must
    // equal the EBITDA on the row above it — reconciling only to within a
    // rounding error is exactly the inconsistency the demo cannot afford.
    const revenue = round(trend * (1 + jitter(rng, 0.012)));

    // The plan was set once at the start of the year and does not wobble.
    const planRevenue = round(a.revenueStart * (1 + a.revenueGrowth + a.planPremium / 12) ** i);

    const gm = a.gmStart + ((a.gmEnd - a.gmStart) * i) / (months.length - 1);
    const cogs = round(revenue * (1 - gm));
    const grossProfit = round(revenue - cogs, 6);
    const opex = round(revenue * a.opexRatio * (1 + jitter(rng, 0.008)));
    const ebitda = round(grossProfit - opex, 6);

    const headcount = Math.round(a.headcountStart + a.headcountGrowth * i);
    const planHeadcount = headcount + a.headcountPlanGap;

    let netBurn;
    if (a.burnStart != null) {
      netBurn = a.burnStart + a.burnRamp * i;
      cash -= netBurn;
    } else {
      const workingCapital = revenue * 0.035 * jitter(rng, 0.6);
      const capex = revenue * 0.018;
      const delta = ebitda - capex - workingCapital;
      cash += delta;
      netBurn = -delta;
    }

    rows.push({
      month,
      revenue,
      planRevenue,
      cogs,
      grossProfit,
      grossMarginPct: round(grossProfit / revenue, 5),
      opex,
      ebitda,
      ebitdaMarginPct: round(ebitda / revenue, 5),
      cashClose: round(cash),
      netBurn: round(netBurn),
      headcount,
      planHeadcount,
      source: SOURCES.financials.system,
      refreshedAt: SOURCES.financials.refreshedAt,
    });
  }

  return rows;
}

let cache = null;

/** The whole portfolio, generated once and memoised. */
export function getPortfolio() {
  if (cache) return cache;
  cache = COMPANIES.map((c) => ({ ...c, series: buildSeries(c) }));
  return cache;
}

export function getCompany(id) {
  const found = getPortfolio().find((c) => c.id === id);
  if (!found) throw new Error(`Unknown company: ${id}`);
  return found;
}
