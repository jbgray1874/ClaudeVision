/**
 * Scenario 1 — Revenue miss identified before the board pack.
 * Build priority 1 (primary demo).
 *
 * Kestrel Analytics is still reporting growth, but its forward commercial
 * indicators are deteriorating together. Alba forecasts a next-quarter
 * shortfall and decomposes it into drivers that reconcile exactly with the
 * forecast gap — no black box, and no number on the screen that the user
 * cannot open.
 */

import { getCompany, SOURCES, AS_OF } from './portfolio.js';
import { projectedQuarter, quarterOf, nextQuarter, last, sumBy } from './kpis.js';
import { makeInsight, CONFIDENCE, formatMoney, formatPct } from './insight.js';
import { rngFor, between } from './rng.js';

const COMPANY_ID = 'kestrel';

/**
 * Scenario parameters. Every displayed figure is derived from these — nothing
 * downstream is hard-coded, so changing a parameter moves the whole story
 * consistently.
 */
export const PARAMS = {
  planStepUp: 1.22,          // Q4 plan is an aggressive step on the Q3 run rate
  winRatePlan: 0.31,
  winRateCurrent: 0.22,
  churnPlanPerQuarter: 0.0159,
  churnActualPerQuarter: 0.0420,
  coverageNow: 1.90,
  coveragePrior: 3.20,
  recognitionFactor: 0.55,   // share of a won deal's ACV recognised in the closing quarter
  slippedDeals: [
    { name: 'Pacific Trust Bank — platform expansion', acv: 1.55, wasDue: '2026-11', nowDue: '2027-02' },
    { name: 'Grantham Retail Group — analytics tier', acv: 1.10, wasDue: '2026-12', nowDue: '2027-01' },
  ],
  salesHires: { plan: 12, actual: 9, quotaPerRepPerQuarter: 0.30, inQuarterRamp: 0.188 },
  salesCycleDaysPrior: 74,
  salesCycleDaysNow: 96,
};

/** Build the named opportunity list that sums to the modelled pipeline. */
function buildPipeline(openAcvTarget) {
  const accounts = [
    'Harborline Insurance', 'Straits Manufacturing', 'Vantage Health Network',
    'Orient Freight', 'Caldera Energy', 'Meridian Bank Trust', 'Blue Ridge Utilities',
    'Sentinel Assurance', 'Northbay Media', 'Aurum Wealth', 'Cobalt Logistics',
    'Fairwater Property',
  ];
  const stages = [
    { name: 'Proposal', probability: 0.55 },
    { name: 'Negotiation', probability: 0.72 },
    { name: 'Qualified', probability: 0.28 },
    { name: 'Discovery', probability: 0.12 },
  ];

  const raw = accounts.map((name, i) => {
    const r = rngFor(`deal:${name}`);
    return {
      name,
      stage: stages[i % stages.length].name,
      probability: stages[i % stages.length].probability,
      weight: between(r, 0.5, 1.8),
      closeMonth: ['2026-10', '2026-11', '2026-12'][i % 3],
      daysInStage: Math.round(between(r, 18, 96)),
    };
  });

  const weightTotal = sumBy(raw, 'weight');
  return raw.map((d) => {
    const acv = (d.weight / weightTotal) * openAcvTarget;
    return {
      account: d.name,
      stage: d.stage,
      stageProbability: d.probability,
      acv: Math.round(acv * 1000) / 1000,
      expectedQuarterRevenue: Math.round(acv * PARAMS.recognitionFactor * 1000) / 1000,
      closeMonth: d.closeMonth,
      daysInStage: d.daysInStage,
      source: SOURCES.pipeline.system,
      refreshedAt: SOURCES.pipeline.refreshedAt,
    };
  });
}

export function buildScenario1() {
  const company = getCompany(COMPANY_ID);
  const series = company.series;

  const currentQuarterKey = quarterOf(last(series).month);
  const current = projectedQuarter(series, currentQuarterKey);
  const forecastQuarterKey = nextQuarter(currentQuarterKey);

  // --- Plan for the forecast quarter -------------------------------------
  const planRevenue = current.revenue * PARAMS.planStepUp;

  // Recurring revenue expected to carry forward if churn ran at plan.
  const retainedAtPlanChurn = current.revenue * (1 - PARAMS.churnPlanPerQuarter);

  // New business the plan therefore depends on, and the bookings quota implied.
  const newRevenueRequired = planRevenue - retainedAtPlanChurn;
  const bookingsQuota = newRevenueRequired / PARAMS.recognitionFactor;

  // Pipeline is stated by coverage against that quota — the way a sales
  // organisation actually reports it.
  const openPipelineAcv = bookingsQuota * PARAMS.coverageNow;
  const priorPipelineAcv = bookingsQuota * PARAMS.coveragePrior;
  const deals = buildPipeline(openPipelineAcv);
  const openQuarterRevenueAtFullWin = sumBy(deals, 'expectedQuarterRevenue');

  // --- Driver bridge ------------------------------------------------------
  const conversionEffect =
    openQuarterRevenueAtFullWin * (PARAMS.winRatePlan - PARAMS.winRateCurrent);

  const slippedAcv = PARAMS.slippedDeals.reduce((t, d) => t + d.acv, 0);
  const slipEffect = slippedAcv * PARAMS.recognitionFactor * PARAMS.winRatePlan;

  const churnEffect =
    current.revenue * (PARAMS.churnActualPerQuarter - PARAMS.churnPlanPerQuarter);

  const { plan: repPlan, actual: repActual, quotaPerRepPerQuarter, inQuarterRamp } = PARAMS.salesHires;
  const capacityEffect =
    (repPlan - repActual) * quotaPerRepPerQuarter * inQuarterRamp * PARAMS.recognitionFactor;

  const bridge = [
    {
      driver: 'Lower conversion',
      value: conversionEffect,
      workings:
        `${formatMoney(openQuarterRevenueAtFullWin, company.currency)} of in-quarter pipeline revenue ` +
        `× (${formatPct(PARAMS.winRatePlan)} plan win rate − ${formatPct(PARAMS.winRateCurrent)} current win rate)`,
    },
    {
      driver: 'Deals moved to a later quarter',
      value: slipEffect,
      workings:
        `${formatMoney(slippedAcv, company.currency)} of ACV re-dated out of the quarter ` +
        `× ${formatPct(PARAMS.recognitionFactor, 0)} in-quarter recognition × ${formatPct(PARAMS.winRatePlan)} plan win rate`,
    },
    {
      driver: 'Higher customer churn',
      value: churnEffect,
      workings:
        `${formatMoney(current.revenue, company.currency)} recurring base ` +
        `× (${formatPct(PARAMS.churnActualPerQuarter)} actual − ${formatPct(PARAMS.churnPlanPerQuarter)} plan quarterly churn)`,
    },
    {
      driver: 'Sales capacity behind plan',
      value: capacityEffect,
      workings:
        `${repPlan - repActual} unfilled quota-carrying roles × ${formatMoney(quotaPerRepPerQuarter, company.currency)} quarterly quota ` +
        `× ${formatPct(inQuarterRamp, 1)} in-quarter ramp × ${formatPct(PARAMS.recognitionFactor, 0)} recognition`,
    },
  ];

  const forecastGap = bridge.reduce((t, b) => t + b.value, 0);
  const forecastRevenue = planRevenue - forecastGap;

  const insight = makeInsight({
    id: 'kestrel-revenue-miss-2026q4',
    type: 'risk',
    companyId: company.id,
    companyName: company.name,
    raisedOn: AS_OF,
    headline: `${forecastQuarterKey} revenue forecast to miss plan by ${formatMoney(forecastGap, company.currency)}`,
    whatHappened:
      `${company.name} is still growing, but four forward commercial indicators have deteriorated together ` +
      `since the last review: win rate, pipeline coverage, deal timing and churn. Reported revenue is only ` +
      `${formatPct(Math.abs(current.variancePct))} below plan, so the deterioration is not yet visible in the board pack.`,
    whyItMatters:
      `The ${forecastQuarterKey} plan depends on ${formatMoney(newRevenueRequired, company.currency)} of new revenue. ` +
      `At the current win rate the open pipeline supports ${formatMoney(openQuarterRevenueAtFullWin * PARAMS.winRateCurrent, company.currency)}. ` +
      `The gap becomes unrecoverable roughly six weeks before quarter end, which is after the next board meeting.`,
    evidence: [
      {
        label: 'Revenue versus plan, quarter to date',
        value: `${formatMoney(current.revenue, company.currency)} against ${formatMoney(current.planRevenue, company.currency)} (${formatPct(current.variancePct)})`,
        source: SOURCES.financials.system,
        refreshedAt: SOURCES.financials.refreshedAt,
        detail: { months: current.months, estimated: current.estimated, note: current.estimationNote },
      },
      {
        label: 'Pipeline coverage',
        value: `${PARAMS.coverageNow.toFixed(2)}x, down from ${PARAMS.coveragePrior.toFixed(2)}x`,
        source: SOURCES.pipeline.system,
        refreshedAt: SOURCES.pipeline.refreshedAt,
        detail: {
          openPipelineAcv,
          priorPipelineAcv,
          bookingsQuota,
          definition: 'open in-quarter pipeline ACV ÷ quarterly bookings quota',
        },
      },
      {
        label: 'Win rate',
        value: `${formatPct(PARAMS.winRateCurrent)}, down from ${formatPct(PARAMS.winRatePlan)}`,
        source: SOURCES.pipeline.system,
        refreshedAt: SOURCES.pipeline.refreshedAt,
        detail: { basis: 'trailing two quarters of closed opportunities' },
      },
      {
        label: 'Average sales cycle',
        value: `${PARAMS.salesCycleDaysNow} days, up from ${PARAMS.salesCycleDaysPrior}`,
        source: SOURCES.pipeline.system,
        refreshedAt: SOURCES.pipeline.refreshedAt,
      },
      {
        label: 'Opportunities re-dated out of the quarter',
        value: `${PARAMS.slippedDeals.length} opportunities, ${formatMoney(slippedAcv, company.currency)} ACV`,
        source: SOURCES.pipeline.system,
        refreshedAt: SOURCES.pipeline.refreshedAt,
        detail: { deals: PARAMS.slippedDeals },
      },
      {
        label: 'Quarterly customer churn',
        value: `${formatPct(PARAMS.churnActualPerQuarter)} against a plan of ${formatPct(PARAMS.churnPlanPerQuarter)}`,
        source: SOURCES.billing.system,
        refreshedAt: SOURCES.billing.refreshedAt,
      },
      {
        label: 'Quota-carrying headcount',
        value: `${repActual} in seat against a plan of ${repPlan}`,
        source: SOURCES.people.system,
        refreshedAt: SOURCES.people.refreshedAt,
      },
    ],
    impact: {
      measure: `${forecastQuarterKey} revenue against plan`,
      value: forecastGap,
      currency: company.currency,
      horizon: forecastQuarterKey,
      direction: 'downside',
    },
    confidence: CONFIDENCE.MEDIUM,
    methodology:
      'Forecast = plan less the sum of four quantified drivers. Each driver is calculated from ' +
      'current CRM, billing and HRIS data against the figures the plan assumed. No driver is estimated ' +
      'by the language model; the model writes the narrative only.',
    actions: [
      {
        action: 'Run a deal-by-deal review of the eight largest open opportunities',
        owner: 'Chief Revenue Officer',
        due: '2026-09-12',
        rationale: `Lower conversion accounts for ${formatPct(conversionEffect / forecastGap)} of the gap.`,
      },
      {
        action: 'Recovery plan for the two re-dated enterprise opportunities, with executive sponsorship',
        owner: 'Chief Executive Officer',
        due: '2026-09-19',
        rationale: `${formatMoney(slipEffect, company.currency)} — ${formatPct(slipEffect / forecastGap)} of the gap — sits in two accounts.`,
      },
      {
        action: 'Retention review of accounts renewing within 90 days',
        owner: 'VP Customer Success',
        due: '2026-09-26',
        rationale: 'Quarterly churn is running at more than twice plan.',
      },
      {
        action: 'Weekly pipeline inspection cadence until coverage returns above 2.5x',
        owner: 'Chief Revenue Officer',
        due: '2026-09-05',
        rationale: 'Coverage has fallen for three consecutive months.',
      },
      {
        action: `Re-forecast ${forecastQuarterKey} and brief the board before the scheduled meeting`,
        owner: 'Chief Financial Officer',
        due: '2026-09-30',
        rationale: 'A revised forecast presented early is a materially better board conversation.',
      },
    ],
    drillDown: {
      series: series.map((r) => ({
        month: r.month,
        revenue: r.revenue,
        planRevenue: r.planRevenue,
        variancePct: (r.revenue - r.planRevenue) / r.planRevenue,
      })),
      deals,
    },
  });

  return {
    company,
    currentQuarter: current,
    forecastQuarter: {
      quarter: forecastQuarterKey,
      planRevenue,
      forecastRevenue,
      forecastGap,
      retainedAtPlanChurn,
      newRevenueRequired,
      bookingsQuota,
      openPipelineAcv,
      priorPipelineAcv,
      openQuarterRevenueAtFullWin,
    },
    bridge,
    deals,
    insight,
  };
}
