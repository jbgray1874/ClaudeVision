/**
 * Report generator.
 *
 * Produces the two outputs named in the demo specification — the Portfolio
 * Performance Exception Report and the Growth Opportunity Brief — as
 * structured payloads plus a Markdown rendering.
 *
 * The payload is the contract: the React app, a PDF writer or a Word export
 * can all consume it. Nothing here calls a language model. The narrative
 * fields on an insight are written from calculated values, so a report can be
 * produced with the AI layer switched off and remain correct.
 */

import { formatMoney, formatPct } from './insight.js';
import { PARAMS } from './scenario4-expansion.js';

function metricAppendix(insight) {
  return insight.evidence.map((e) => ({
    metric: e.label,
    value: e.value,
    source: e.source,
    asOf: e.refreshedAt,
  }));
}

export function buildExceptionReport(scenario) {
  const { company, currentQuarter, forecastQuarter, bridge, insight } = scenario;
  const cur = company.currency;

  return {
    kind: 'Portfolio Performance Exception Report',
    company: company.name,
    fund: company.fund,
    preparedAt: insight.raisedOn,
    executiveSummary:
      `${company.name} is forecast to miss its ${forecastQuarter.quarter} revenue plan by ` +
      `${formatMoney(forecastQuarter.forecastGap, cur)} (${formatPct(forecastQuarter.forecastGap / forecastQuarter.planRevenue)} of plan). ` +
      `Reported revenue is currently ${formatPct(Math.abs(currentQuarter.variancePct))} below plan, so the deterioration ` +
      `is not yet apparent in standard reporting. The shortfall is driven by conversion and deal timing rather than demand.`,
    sizeAndTiming: {
      quarter: forecastQuarter.quarter,
      plan: forecastQuarter.planRevenue,
      forecast: forecastQuarter.forecastRevenue,
      gap: forecastQuarter.forecastGap,
      currency: cur,
      decisionWindow:
        'Approximately six weeks before quarter end, after which in-quarter recovery is not credible.',
    },
    supportingEvidence: insight.evidence,
    rootCauses: bridge.map((b) => ({
      driver: b.driver,
      value: b.value,
      shareOfGap: b.value / forecastQuarter.forecastGap,
      workings: b.workings,
    })),
    forecastImpact: {
      measure: insight.impact.measure,
      value: insight.impact.value,
      currency: cur,
      confidence: insight.confidence.label,
    },
    recommendedActions: insight.actions,
    accountableExecutive: 'Chief Revenue Officer (with CEO sponsorship on the re-dated accounts)',
    reviewDate: '2026-09-30',
    sourceData: metricAppendix(insight),
    methodology: insight.methodology,
  };
}

export function buildGrowthOpportunityBrief(scenario) {
  const { company, qualified, totals, insight } = scenario;
  const cur = company.currency;

  return {
    kind: 'Growth Opportunity Brief',
    company: company.name,
    fund: company.fund,
    preparedAt: insight.raisedOn,
    opportunity:
      `A cross-sell cohort of ${qualified.length} existing customers matches the profile of accounts that ` +
      `previously adopted the second product. Estimated additional recurring revenue of ` +
      `${formatMoney(totals.low, cur)} to ${formatMoney(totals.high, cur)} over the next four quarters.`,
    estimatedValue: {
      expected: totals.expected,
      low: totals.low,
      high: totals.high,
      gross: totals.gross,
      currency: cur,
    },
    prioritisedCustomers: qualified.slice(0, 12).map((c) => ({
      account: c.account,
      segment: c.segment,
      currentArr: c.arr,
      score: c.score,
      renewalDate: c.renewalDate,
      conversionProbability: c.conversionProbability,
      expectedValue: c.expectedValue,
      whySelected: c.breakdown
        .slice()
        .sort((a, b) => b.points - a.points)
        .slice(0, 3)
        .map((f) => f.basis),
    })),
    supportingEvidence: insight.evidence,
    conversionAssumptions: {
      attachRate: `${formatPct(PARAMS.attachUplift, 0)} of each account's current ARR`,
      conversionModel: `Linear in the account score, floored at ${formatPct(PARAMS.conversionFloor, 0)} and capped at ${formatPct(PARAMS.conversionCeiling, 0)}`,
      sensitivity: `±${formatPct(PARAMS.rangeSensitivity, 0)} applied to conversion for the reported range`,
    },
    recommendedCampaign: insight.actions,
    valuationEffect: {
      note:
        'Illustrative only. At the sector multiple used in the last valuation, the expected ARR uplift ' +
        'implies an enterprise-value effect that should be confirmed by the deal team before circulation.',
    },
    sourceData: metricAppendix(insight),
    methodology: insight.methodology,
  };
}

/** Render any report payload as Markdown — enough to paste into a pack. */
export function toMarkdown(report) {
  const lines = [`# ${report.kind}`, '', `**${report.company}** · ${report.fund} · prepared ${report.preparedAt}`, ''];

  const section = (title, body) => {
    lines.push(`## ${title}`, '', body, '');
  };

  if (report.executiveSummary) section('Executive summary', report.executiveSummary);
  if (report.opportunity) section('Opportunity', report.opportunity);

  if (report.sizeAndTiming) {
    const s = report.sizeAndTiming;
    section(
      'Size and timing',
      [
        `| Measure | Value |`,
        `|---|---|`,
        `| Quarter | ${s.quarter} |`,
        `| Plan | ${formatMoney(s.plan, s.currency)} |`,
        `| Forecast | ${formatMoney(s.forecast, s.currency)} |`,
        `| Gap | ${formatMoney(s.gap, s.currency)} |`,
        `| Decision window | ${s.decisionWindow} |`,
      ].join('\n'),
    );
  }

  if (report.estimatedValue) {
    const v = report.estimatedValue;
    section(
      'Estimated value',
      [
        `| Measure | Value |`,
        `|---|---|`,
        `| Expected | ${formatMoney(v.expected, v.currency)} |`,
        `| Range | ${formatMoney(v.low, v.currency)} – ${formatMoney(v.high, v.currency)} |`,
        `| Gross before conversion | ${formatMoney(v.gross, v.currency)} |`,
      ].join('\n'),
    );
  }

  if (report.rootCauses) {
    section(
      'Root causes',
      [
        `| Driver | Value | Share of gap | Workings |`,
        `|---|---|---|---|`,
        ...report.rootCauses.map(
          (r) =>
            `| ${r.driver} | ${formatMoney(r.value, report.sizeAndTiming.currency)} | ${formatPct(r.shareOfGap)} | ${r.workings} |`,
        ),
      ].join('\n'),
    );
  }

  if (report.prioritisedCustomers) {
    section(
      'Prioritised accounts',
      [
        `| Account | Segment | Current ARR | Score | Renewal | Expected |`,
        `|---|---|---|---|---|---|`,
        ...report.prioritisedCustomers.map(
          (c) =>
            `| ${c.account} | ${c.segment} | ${formatMoney(c.currentArr, report.estimatedValue.currency)} | ${c.score} | ${c.renewalDate} | ${formatMoney(c.expectedValue, report.estimatedValue.currency)} |`,
        ),
      ].join('\n'),
    );
  }

  const actions = report.recommendedActions ?? report.recommendedCampaign ?? [];
  if (actions.length) {
    section(
      'Recommended actions',
      [
        `| Action | Owner | Due | Rationale |`,
        `|---|---|---|---|`,
        ...actions.map((a) => `| ${a.action} | ${a.owner} | ${a.due} | ${a.rationale} |`),
      ].join('\n'),
    );
  }

  section(
    'Metric appendix',
    [
      `| Metric | Value | Source | As of |`,
      `|---|---|---|---|`,
      ...report.sourceData.map((s) => `| ${s.metric} | ${s.value} | ${s.source} | ${s.asOf} |`),
    ].join('\n'),
  );

  section('Methodology', report.methodology);

  return lines.join('\n');
}
