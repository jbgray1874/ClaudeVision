/**
 * KPI and variance engine.
 *
 * The demo specification requires these to genuinely recalculate from the
 * underlying dataset rather than being written into the screens. Every
 * function here takes a series and returns both the number and the inputs
 * that produced it, so the drill-down can show its working.
 */

import { getPortfolio } from './portfolio.js';

/** Beyond this, a company is reported as cash generative rather than by runway. */
export const CASH_GENERATIVE_MONTHS = 60;

export function last(series, back = 0) {
  return series[series.length - 1 - back];
}

export function quarterOf(month) {
  const [y, m] = month.split('-').map(Number);
  return `${y}-Q${Math.ceil(m / 3)}`;
}

export function monthsOfQuarter(quarterKey) {
  const [y, q] = quarterKey.split('-Q').map(Number);
  const start = (q - 1) * 3 + 1;
  return [0, 1, 2].map((i) => `${y}-${String(start + i).padStart(2, '0')}`);
}

export function nextQuarter(quarterKey) {
  const [y, q] = quarterKey.split('-Q').map(Number);
  return q === 4 ? `${y + 1}-Q1` : `${y}-Q${q + 1}`;
}

export function sumBy(rows, field) {
  return rows.reduce((t, r) => t + r[field], 0);
}

/** Aggregate a quarter, including partial quarters (the current one). */
export function quarterSummary(series, quarterKey) {
  const wanted = new Set(monthsOfQuarter(quarterKey));
  const rows = series.filter((r) => wanted.has(r.month));
  const revenue = sumBy(rows, 'revenue');
  const plan = sumBy(rows, 'planRevenue');
  return {
    quarter: quarterKey,
    monthsElapsed: rows.length,
    complete: rows.length === 3,
    revenue,
    planRevenue: plan,
    varianceAbs: revenue - plan,
    variancePct: plan === 0 ? 0 : (revenue - plan) / plan,
    grossProfit: sumBy(rows, 'grossProfit'),
    ebitda: sumBy(rows, 'ebitda'),
    months: rows.map((r) => r.month),
  };
}

/**
 * A quarter closed out to three months, projecting any month not yet reported.
 *
 * The command centre and the company drill-down must quote the same number.
 * Keeping the projection here rather than inside a scenario is what stops the
 * portfolio table and the company page disagreeing by a few tenths of a point.
 */
export function projectedQuarter(series, quarterKey) {
  const summary = quarterSummary(series, quarterKey);
  if (summary.complete) return { ...summary, estimated: false };

  const monthsMissing = 3 - summary.monthsElapsed;
  const recent = series.slice(-3);
  const growth = (last(series).revenue / recent[0].revenue) ** (1 / (recent.length - 1)) - 1;
  const planGrowth = (last(series).planRevenue / recent[0].planRevenue) ** (1 / (recent.length - 1)) - 1;

  let revenue = summary.revenue;
  let planRevenue = summary.planRevenue;
  let cursor = last(series).revenue;
  let planCursor = last(series).planRevenue;
  for (let i = 0; i < monthsMissing; i++) {
    cursor *= 1 + growth;
    planCursor *= 1 + planGrowth;
    revenue += cursor;
    planRevenue += planCursor;
  }

  return {
    ...summary,
    revenue,
    planRevenue,
    varianceAbs: revenue - planRevenue,
    variancePct: (revenue - planRevenue) / planRevenue,
    estimated: true,
    estimationNote:
      `${summary.monthsElapsed} actual month(s) plus ${monthsMissing} projected at the trailing ` +
      `three-month growth rate of ${(growth * 100).toFixed(2)}% per month`,
  };
}

/** Trailing cash runway. Burn is a three-month average to damp single-month noise. */
export function runway(series, atIndex = series.length - 1) {
  const row = series[atIndex];
  const window = series.slice(Math.max(0, atIndex - 2), atIndex + 1);
  const avgBurn = sumBy(window, 'netBurn') / window.length;
  return {
    month: row.month,
    cash: row.cashClose,
    avgMonthlyBurn: avgBurn,
    months: avgBurn <= 0 ? Infinity : row.cashClose / avgBurn,
    burnWindow: window.map((r) => ({ month: r.month, netBurn: r.netBurn })),
    method: 'closing cash ÷ trailing three-month average net burn',
  };
}

export function runwayHistory(series) {
  return series.map((_, i) => runway(series, i)).map((r) => ({ month: r.month, months: r.months }));
}

/**
 * The most recent month at which runway was still at or above `threshold`.
 * Used to state the deterioration honestly — "14.0 months in April" — rather
 * than asserting a comparison the data does not support.
 */
export function lastMonthAboveRunway(series, threshold) {
  const history = runwayHistory(series);
  for (let i = history.length - 1; i >= 0; i--) {
    if (history[i].months >= threshold) return history[i];
  }
  return null;
}

/** Gross margin movement between two months, in percentage points. */
export function marginMovement(series, fromMonth, toMonth) {
  const from = series.find((r) => r.month === fromMonth);
  const to = series.find((r) => r.month === toMonth);
  if (!from || !to) throw new Error('marginMovement: month not in series');
  return {
    from: { month: from.month, grossMarginPct: from.grossMarginPct },
    to: { month: to.month, grossMarginPct: to.grossMarginPct },
    movementPts: (to.grossMarginPct - from.grossMarginPct) * 100,
  };
}

/** Year-on-year revenue growth using the trailing three months against the same period a year earlier. */
export function revenueGrowthYoY(series) {
  if (series.length < 15) return null;
  const recent = series.slice(-3);
  const priorYear = series.slice(-15, -12);
  const a = sumBy(recent, 'revenue');
  const b = sumBy(priorYear, 'revenue');
  return { recent: a, priorYear: b, growthPct: (a - b) / b };
}

/** Fund-level rollup for the Portfolio Health Command Centre banner. */
export function portfolioRollup(portfolio = getPortfolio()) {
  const rows = portfolio.map((c) => {
    const latest = last(c.series);
    const rw = runway(c.series);
    return { company: c, latest, runway: rw };
  });

  // A company whose burn is negligible produces an arithmetically true but
  // meaningless runway. Treat anything beyond five years as cash generative so
  // the portfolio average stays a number an investor would recognise.
  const burning = rows.filter((r) => r.runway.months < CASH_GENERATIVE_MONTHS);
  const currentQuarter = quarterOf(last(portfolio[0].series).month);

  const quarters = portfolio.map((c) => quarterSummary(c.series, currentQuarter));
  const revenue = sumBy(quarters, 'revenue');
  const planRevenue = sumBy(quarters, 'planRevenue');

  return {
    asOf: last(portfolio[0].series).month,
    companies: portfolio.length,
    averageHealthScore:
      Math.round((portfolio.reduce((t, c) => t + c.healthScore, 0) / portfolio.length) * 10) / 10,
    ragCounts: portfolio.reduce(
      (acc, c) => ({ ...acc, [c.rag]: (acc[c.rag] || 0) + 1 }),
      { RED: 0, AMBER: 0, GREEN: 0 },
    ),
    ragMovements: portfolio
      .filter((c) => c.rag !== c.prevRag)
      .map((c) => ({ id: c.id, name: c.name, from: c.prevRag, to: c.rag })),
    totalCash: rows.reduce((t, r) => t + r.latest.cashClose, 0),
    cashConsumingCompanies: burning.length,
    averageRunwayMonths:
      burning.length === 0
        ? Infinity
        : burning.reduce((t, r) => t + r.runway.months, 0) / burning.length,
    quarterRevenue: revenue,
    quarterPlanRevenue: planRevenue,
    quarterVariancePct: (revenue - planRevenue) / planRevenue,
    source: 'Aggregated across all connected company sources',
  };
}
