/**
 * The demo acceptance criteria, as tests.
 *
 * The specification's last criterion is that no part of the demo depends on
 * the presenter explaining away an inconsistent screen. These tests are how
 * that gets enforced before a meeting rather than during one.
 */

import test from 'node:test';
import assert from 'node:assert/strict';

import {
  buildCommandCentre,
  buildScenario1,
  buildScenario4,
  buildCashRunwaySignal,
  buildMarginSignal,
} from '../src/index.js';
import { getPortfolio, MONTH_KEYS, FIN_SEED } from '../src/portfolio.js';
import { projectedQuarter, quarterOf, runway, last } from '../src/kpis.js';
import { buildExceptionReport, buildGrowthOpportunityBrief, toMarkdown } from '../src/report.js';
import { trackerFor, advance, outcome } from '../src/actions.js';

const near = (a, b, tol = 1e-9) => Math.abs(a - b) < tol;

test('the dataset is deterministic across builds', () => {
  const a = JSON.stringify(getPortfolio().map((c) => c.series));
  const b = JSON.stringify(getPortfolio().map((c) => c.series));
  assert.equal(a, b);
});

test('every company carries a full eighteen-month history', () => {
  for (const c of getPortfolio()) {
    assert.equal(c.series.length, 18, `${c.name} has ${c.series.length} months`);
    assert.deepEqual(c.series.map((r) => r.month), MONTH_KEYS);
  }
});

test('the portfolio is large enough for the command centre to look real', () => {
  const cc = buildCommandCentre();
  assert.ok(cc.companies.length >= 8, 'specification asks for eight to ten companies');
  assert.ok(cc.riskAlerts.length >= 1);
  assert.ok(cc.opportunityAlerts.length >= 1);
  assert.ok(
    cc.rollup.ragMovements.length > 0,
    'at least one company must have moved status since the prior period',
  );
});

test('gross profit, EBITDA and margins reconcile within every monthly row', () => {
  for (const c of getPortfolio()) {
    for (const r of c.series) {
      assert.ok(near(r.grossProfit, r.revenue - r.cogs, 1e-3), `${c.name} ${r.month} gross profit`);
      assert.ok(near(r.ebitda, r.grossProfit - r.opex, 1e-3), `${c.name} ${r.month} EBITDA`);
      assert.ok(near(r.grossMarginPct, r.grossProfit / r.revenue, 1e-3), `${c.name} ${r.month} margin`);
    }
  }
});

test('the portfolio table and the company drill-down quote the same quarter figure', () => {
  const cc = buildCommandCentre();
  const s1 = buildScenario1();
  const row = cc.companies.find((r) => r.id === s1.company.id);
  assert.ok(near(row.revenueQtd, s1.currentQuarter.revenue, 1e-6));
  assert.ok(near(row.variancePct, s1.currentQuarter.variancePct, 1e-6));
});

test('scenario 1: the driver bridge reconciles exactly to the forecast gap', () => {
  const s1 = buildScenario1();
  const sum = s1.bridge.reduce((t, b) => t + b.value, 0);
  assert.ok(near(sum, s1.forecastQuarter.forecastGap), 'drivers must sum to the gap');
  assert.ok(
    near(s1.forecastQuarter.planRevenue - sum, s1.forecastQuarter.forecastRevenue),
    'plan less drivers must equal the forecast',
  );
  for (const b of s1.bridge) {
    assert.ok(b.value > 0, `${b.driver} should contribute to the shortfall`);
    assert.ok(b.workings.length > 20, `${b.driver} must show its workings`);
  }
});

test('scenario 1: the miss is material and lands where the specification expects', () => {
  const s1 = buildScenario1();
  const gap = s1.forecastQuarter.forecastGap;
  assert.ok(gap > 1.0 && gap < 1.4, `forecast gap of ${gap.toFixed(3)}m should be about 1.2m`);
  const variance = Math.abs(s1.currentQuarter.variancePct);
  assert.ok(variance < 0.05, 'reported revenue must still look close to plan, or there is no story');
});

test('scenario 1: named opportunities sum to the stated open pipeline', () => {
  const s1 = buildScenario1();
  const dealTotal = s1.deals.reduce((t, d) => t + d.acv, 0);
  assert.ok(
    near(dealTotal, s1.forecastQuarter.openPipelineAcv, 0.02),
    `named deals total ${dealTotal.toFixed(3)} against a stated pipeline of ${s1.forecastQuarter.openPipelineAcv.toFixed(3)}`,
  );
});

test('scenario 4: every qualified account explains why it was selected', () => {
  const s4 = buildScenario4();
  assert.ok(s4.qualified.length >= 8, 'a cohort of fewer than eight accounts is not a campaign');
  for (const c of s4.qualified) {
    assert.ok(c.score >= 65);
    assert.ok(!c.ownsTarget, `${c.account} already owns the target product`);
    assert.equal(c.breakdown.length, 6);
    const total = c.breakdown.reduce((t, f) => t + f.points, 0);
    assert.ok(Math.abs(total - c.score) < 0.6, `${c.account} score does not match its factors`);
    for (const f of c.breakdown) {
      assert.ok(f.points <= f.of + 1e-9, `${c.account} ${f.factor} exceeds its weight`);
      assert.ok(f.basis && f.basis.length > 5, `${c.account} ${f.factor} has no stated basis`);
    }
  }
});

test('scenario 4: the opportunity total equals the sum of its accounts', () => {
  const s4 = buildScenario4();
  const sum = s4.qualified.reduce((t, c) => t + c.expectedValue, 0);
  assert.ok(near(sum, s4.totals.expected, 1e-6));
  assert.ok(s4.totals.low < s4.totals.expected && s4.totals.expected < s4.totals.high);
  assert.ok(
    s4.totals.low > 1.2 && s4.totals.high < 2.4,
    `range ${s4.totals.low.toFixed(2)}–${s4.totals.high.toFixed(2)}m should sit around the 1.5–2.0m the specification describes`,
  );
});

test('every insight carries evidence with a source and a refresh date', () => {
  const insights = [
    buildScenario1().insight,
    buildScenario4().insight,
    buildCashRunwaySignal(),
    buildMarginSignal(),
  ];
  for (const i of insights) {
    assert.ok(i.evidence.length >= 3, `${i.id} has thin evidence`);
    for (const e of i.evidence) {
      assert.ok(e.source, `${i.id}: "${e.label}" has no source`);
      assert.ok(/^\d{4}-\d{2}-\d{2}$/.test(e.refreshedAt), `${i.id}: "${e.label}" has no refresh date`);
    }
    assert.ok(i.methodology.length > 40, `${i.id} does not explain how it was calculated`);
    assert.ok(i.actions.length >= 2, `${i.id} ends without actions`);
    for (const a of i.actions) {
      assert.ok(a.owner, `${i.id}: an action has no owner`);
      assert.ok(/^\d{4}-\d{2}-\d{2}$/.test(a.due), `${i.id}: an action has no date`);
    }
  }
});

test('an insight cannot be built without evidence', async () => {
  const { makeInsight } = await import('../src/insight.js');
  const base = {
    id: 'x', type: 'risk', companyId: 'a', companyName: 'A', headline: 'h',
    whatHappened: 'w', whyItMatters: 'y', impact: {}, confidence: {}, methodology: 'm',
  };

  assert.throws(() => makeInsight({ ...base, evidence: [] }), /at least one evidence row/);
  assert.throws(
    () => makeInsight({ ...base, evidence: [{ label: 'no source', value: '1' }] }),
    /has no source or refresh date/,
  );
  assert.throws(() => makeInsight({ ...base, evidence: undefined }), /missing "evidence"/);
});

test('the runway signal states a comparison the data actually supports', () => {
  const insight = buildCashRunwaySignal();
  const meridian = getPortfolio().find((c) => c.id === 'meridian');
  const now = runway(meridian.series);

  // The platform shows 663k of cash against 138k of burn. This must agree.
  const expected = FIN_SEED.meridian.cash / FIN_SEED.meridian.burn;
  assert.ok(Math.abs(now.months - expected) < 0.5,
    `runway of ${now.months.toFixed(1)} months must match the platform's ${expected.toFixed(1)}`);

  const prior = insight.evidence.find((e) => e.label === 'Runway at the last review');
  assert.ok(prior.value.includes('months in 20'), 'the prior reading must name its month');
});

test('every company already in the platform reproduces its live seed values', () => {
  for (const [id, seed] of Object.entries(FIN_SEED)) {
    const company = getPortfolio().find((c) => c.id === id);
    assert.ok(company, `${id} is missing from the portfolio`);
    const latest = last(company.series);

    const check = (label, got, want, tol = 0.6) =>
      assert.ok(Math.abs(got - want) < tol,
        `${id} ${label}: generated ${got.toFixed(1)}k against the platform's ${want}k`);

    check('revenue', latest.revenue * 1000, seed.revenue);
    check('budget', latest.planRevenue * 1000, seed.budget);
    check('cash', latest.cashClose * 1000, seed.cash);
    check('burn', latest.netBurn * 1000, seed.burn);
    check('gross margin', latest.grossMarginPct * 100, seed.gm, 0.3);
    check('EBITDA margin', latest.ebitdaMarginPct * 100, seed.ebitdaPct, 0.3);
  }
});

test('reports render from the payload without a language model', () => {
  const exception = buildExceptionReport(buildScenario1());
  const brief = buildGrowthOpportunityBrief(buildScenario4());

  for (const report of [exception, brief]) {
    assert.ok(report.sourceData.length >= 3);
    assert.ok(report.methodology);
    const md = toMarkdown(report);
    assert.ok(md.startsWith(`# ${report.kind}`));
    assert.ok(md.includes('Metric appendix'));
    assert.ok(md.includes('Recommended actions'));
    assert.ok(!md.includes('undefined'), 'a rendered report must not contain undefined');
    assert.ok(!md.includes('NaN'), 'a rendered report must not contain NaN');
  }

  const shares = exception.rootCauses.reduce((t, r) => t + r.shareOfGap, 0);
  assert.ok(near(shares, 1, 1e-9), 'root-cause shares must total the whole gap');
});

test('actions can be tracked through to a closed-loop outcome', () => {
  const insight = buildScenario1().insight;
  const rows = trackerFor(insight, 'Pipeline coverage');
  assert.ok(rows.length >= 3);
  assert.equal(rows[0].status, 'Open');

  let row = advance(rows[0], { on: '2026-09-01', status: 'In progress', note: 'Review scheduled', metricValue: 1.90 });
  assert.equal(outcome(row).measurable, false);

  row = advance(row, { on: '2026-10-01', status: 'Complete', note: 'Coverage rebuilt', metricValue: 2.44 });
  const result = outcome(row);
  assert.equal(result.measurable, true);
  assert.ok(near(result.change, 0.54, 1e-9));
  assert.equal(result.metric, 'Pipeline coverage');
});

test('quarter projection is used consistently and is labelled as projected', () => {
  const meridian = getPortfolio().find((c) => c.id === 'meridian');
  const q = projectedQuarter(meridian.series, quarterOf(last(meridian.series).month));
  assert.equal(q.estimated, true);
  assert.ok(q.estimationNote.includes('projected'));
  assert.ok(q.monthsElapsed < 3);
});
