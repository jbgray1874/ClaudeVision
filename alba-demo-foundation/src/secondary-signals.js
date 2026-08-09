/**
 * Scenarios 2 and 3, surfaced as command-centre alerts.
 *
 * The demo specification builds scenarios 1 and 4 first and adds cash runway
 * then margin deterioration afterwards. These two are built here to alert
 * strength — a correct insight card with real evidence, drawn from the same
 * series — but not yet to full drill-down depth. That is deliberate: an empty
 * portfolio behind the two primary scenarios reads as a mock-up, while two
 * further signals that survive inspection read as a working system.
 */

import { getCompany, SOURCES, AS_OF } from './portfolio.js';
import { runway, lastMonthAboveRunway, marginMovement, last, revenueGrowthYoY } from './kpis.js';
import { makeInsight, CONFIDENCE, formatMoney, formatPct } from './insight.js';

/** Scenario 2 — cash runway and liquidity risk (Meridian SaaS). */
export function buildCashRunwaySignal() {
  const company = getCompany('meridian');
  const now = runway(company.series);
  const wasAt14 = lastMonthAboveRunway(company.series, 14);
  const cur = company.currency;

  const monthsSince = wasAt14
    ? company.series.findIndex((r) => r.month === last(company.series).month) -
      company.series.findIndex((r) => r.month === wasAt14.month)
    : null;

  return makeInsight({
    id: 'meridian-runway-2026q3',
    type: 'risk',
    companyId: company.id,
    companyName: company.name,
    raisedOn: AS_OF,
    headline: `Cash runway down to ${now.months.toFixed(1)} months`,
    whatHappened:
      `Runway has fallen from ${wasAt14 ? wasAt14.months.toFixed(1) : 'over 14'} months in ` +
      `${wasAt14 ? wasAt14.month : 'the prior year'} to ${now.months.toFixed(1)} months today` +
      `${monthsSince ? `, a deterioration over ${monthsSince} months` : ''}. ` +
      `Net burn is now ${formatMoney(now.avgMonthlyBurn, cur)} per month against ` +
      `${formatMoney(company.series[0].netBurn, cur)} at the start of the period.`,
    whyItMatters:
      `The latest board pack presents the company as adequately funded. On the current trajectory the ` +
      `minimum-cash threshold is reached before a funding process could realistically complete, which ` +
      `turns a management decision into an urgent one.`,
    evidence: [
      {
        label: 'Closing cash',
        value: formatMoney(now.cash, cur),
        source: SOURCES.bank.system,
        refreshedAt: SOURCES.bank.refreshedAt,
        detail: { liveConnection: company.liveSource },
      },
      {
        label: 'Net monthly burn (trailing three months)',
        value: formatMoney(now.avgMonthlyBurn, cur),
        source: SOURCES.financials.system,
        refreshedAt: SOURCES.financials.refreshedAt,
        detail: { window: now.burnWindow, method: now.method },
      },
      {
        label: 'Runway at the last review',
        value: wasAt14 ? `${wasAt14.months.toFixed(1)} months in ${wasAt14.month}` : 'not reached in the period',
        source: 'Alba calculation',
        refreshedAt: AS_OF,
      },
      {
        label: 'Headcount against plan',
        value: `${last(company.series).headcount} against a plan of ${last(company.series).planHeadcount}`,
        source: SOURCES.people.system,
        refreshedAt: SOURCES.people.refreshedAt,
      },
    ],
    impact: {
      measure: 'Months of runway remaining',
      value: now.months,
      unit: 'months',
      currency: cur,
      horizon: 'Rolling',
      direction: 'downside',
    },
    confidence: CONFIDENCE.HIGH,
    methodology: `Runway is ${now.method}. Cash is read from the live accounting connection.`,
    actions: [
      {
        action: 'Collections push on invoices over 60 days',
        owner: 'Chief Financial Officer',
        due: '2026-09-15',
        rationale: 'Fastest available lever on runway and entirely within management control.',
      },
      {
        action: 'Pause non-critical hiring pending the next cash review',
        owner: 'Chief Executive Officer',
        due: '2026-09-08',
        rationale: 'Headcount is running ahead of plan while burn is rising.',
      },
      {
        action: 'Model a funding requirement and agree a decision deadline with the board',
        owner: 'Chief Financial Officer',
        due: '2026-09-30',
        rationale: 'A funding decision taken at four months of runway is materially worse than one taken now.',
      },
    ],
  });
}

/** Scenario 3 — margin deterioration masked by revenue growth (ForgeTech). */
export function buildMarginSignal() {
  const company = getCompany('forgetech');
  const series = company.series;
  const movement = marginMovement(series, series[0].month, last(series).month);
  const growth = revenueGrowthYoY(series);
  const cur = company.currency;

  const latest = last(series);
  const marginAtStart = series[0].grossMarginPct;
  const annualisedRevenue = latest.revenue * 12;
  const ebitdaEffect = annualisedRevenue * (marginAtStart - latest.grossMarginPct);

  return makeInsight({
    id: 'forgetech-margin-2026q3',
    type: 'risk',
    companyId: company.id,
    companyName: company.name,
    raisedOn: AS_OF,
    headline: `Gross margin down ${Math.abs(movement.movementPts).toFixed(1)} points while revenue grows ${formatPct(growth.growthPct)}`,
    whatHappened:
      `Revenue is growing ${formatPct(growth.growthPct)} year on year, which reads as a strong result. ` +
      `Gross margin has fallen from ${formatPct(marginAtStart)} to ${formatPct(latest.grossMarginPct)} over the ` +
      `same period, so gross profit is growing materially more slowly than revenue.`,
    whyItMatters:
      `At the current revenue run rate the margin decline is worth approximately ` +
      `${formatMoney(ebitdaEffect, cur)} of annualised gross profit. The company can meet its revenue plan ` +
      `and still miss its EBITDA plan, which is the outcome that affects the exit multiple.`,
    evidence: [
      {
        label: 'Revenue growth, year on year',
        value: formatPct(growth.growthPct),
        source: SOURCES.financials.system,
        refreshedAt: SOURCES.financials.refreshedAt,
        detail: { recentQuarter: growth.recent, priorYearQuarter: growth.priorYear },
      },
      {
        label: 'Gross margin movement',
        value: `${formatPct(marginAtStart)} → ${formatPct(latest.grossMarginPct)} (${movement.movementPts.toFixed(1)} points)`,
        source: SOURCES.financials.system,
        refreshedAt: SOURCES.financials.refreshedAt,
        detail: movement,
      },
      {
        label: 'Annualised gross-profit effect',
        value: formatMoney(ebitdaEffect, cur),
        source: 'Alba calculation',
        refreshedAt: AS_OF,
        detail: { basis: 'current monthly revenue × 12 × margin decline in percentage points' },
      },
    ],
    impact: {
      measure: 'Annualised gross profit against the prior margin',
      value: ebitdaEffect,
      currency: cur,
      horizon: 'Annualised',
      direction: 'downside',
    },
    confidence: CONFIDENCE.HIGH,
    methodology:
      'Margin movement is read directly from the monthly ledger. The impact figure holds revenue constant ' +
      'and applies the margin decline, so it isolates the mix and pricing effect from the growth effect.',
    actions: [
      {
        action: 'Rank customers and products by contribution margin and identify the loss-makers',
        owner: 'Chief Financial Officer',
        due: '2026-09-19',
        rationale: 'The decline is unlikely to be evenly spread; the recovery plan needs the ranking first.',
      },
      {
        action: 'Review discounting authority and the current price list',
        owner: 'Commercial Director',
        due: '2026-09-26',
        rationale: 'Discounting is one of the few drivers management can change within a quarter.',
      },
    ],
  });
}
