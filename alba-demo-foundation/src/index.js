/**
 * Alba demo foundation — public surface.
 *
 * Drop this directory into the React app as `src/lib/demo/` and import from
 * here. Nothing in the package touches the network, the filesystem or the wall
 * clock, so the same figures appear in a unit test, a rehearsal and a meeting.
 */

export * from './portfolio.js';
export * from './kpis.js';
export * from './insight.js';
export * from './actions.js';
export * from './report.js';

import { getPortfolio } from './portfolio.js';
import { portfolioRollup, runway, last, quarterOf, projectedQuarter, CASH_GENERATIVE_MONTHS } from './kpis.js';
import { buildScenario1 } from './scenario1-revenue-miss.js';
import { buildScenario4 } from './scenario4-expansion.js';
import { buildCashRunwaySignal, buildMarginSignal } from './secondary-signals.js';
import { buildScenario5 } from './scenario5-procurement.js';
export { buildCashScenario, buildManagementCases, cashBaseline } from './scenario2-cash.js';
import { summarise } from './insight.js';

export { buildScenario1, buildScenario4, buildScenario5, buildCashRunwaySignal, buildMarginSignal };
export { buildProcurementReport, normaliseVendorName, matchQuality } from './scenario5-procurement.js';

/**
 * Portfolio Health Command Centre.
 *
 * The specification's test is that an investment professional understands the
 * portfolio in under thirty seconds, and that risks and opportunities are
 * separated rather than mixed into one alert list.
 */
export function buildCommandCentre() {
  const portfolio = getPortfolio();
  const rollup = portfolioRollup(portfolio);
  const currentQuarter = quarterOf(last(portfolio[0].series).month);

  const rows = portfolio.map((c) => {
    const latest = last(c.series);
    const rw = runway(c.series);
    const q = projectedQuarter(c.series, currentQuarter);
    return {
      id: c.id,
      name: c.name,
      sector: c.sector,
      stage: c.stage,
      region: c.region,
      currency: c.currency,
      fund: c.fund ?? 'Alba Growth I',
      healthScore: c.healthScore,
      rag: c.rag,
      ragMoved: c.rag !== c.prevRag ? `${c.prevRag} → ${c.rag}` : null,
      revenueQtd: q.revenue,
      planQtd: q.planRevenue,
      variancePct: q.variancePct,
      ebitdaMarginPct: latest.ebitdaMarginPct,
      grossMarginPct: latest.grossMarginPct,
      cash: latest.cashClose,
      monthlyBurn: rw.avgMonthlyBurn,
      runwayMonths: rw.months,
      cashGenerative: rw.months >= CASH_GENERATIVE_MONTHS,
      quarterEstimated: q.estimated,
      headcount: latest.headcount,
      headcountVsPlan: latest.headcount - latest.planHeadcount,
      liveSource: c.liveSource ?? null,
    };
  });

  const scenario1 = buildScenario1();
  const scenario4 = buildScenario4();

  return {
    asOf: rollup.asOf,
    rollup,
    companies: rows,
    riskAlerts: [scenario1.insight, buildCashRunwaySignal(), buildMarginSignal()]
      .map((i) => ({ insight: i, line: summarise(i) })),
    opportunityAlerts: [scenario4.insight, buildScenario5().insight]
      .map((i) => ({ insight: i, line: summarise(i) })),
    filters: {
      fund: [...new Set(rows.map((r) => r.fund))],
      sector: [...new Set(rows.map((r) => r.sector))],
      region: [...new Set(rows.map((r) => r.region))],
      status: ['RED', 'AMBER', 'GREEN'],
    },
  };
}
