/**
 * Scenario 2 — the interactive cash engine.
 *
 * The specification's requirement is that changing an assumption immediately
 * changes the output. The risk is subtler: that the recomputed forecast quietly
 * stops agreeing with the runway the portfolio table reports. These tests hold
 * the two together.
 */

import test from 'node:test';
import assert from 'node:assert/strict';

import { cashBaseline, buildCashScenario, buildManagementCases, ASSUMPTIONS } from '../src/scenario2-cash.js';
import { getCompany } from '../src/portfolio.js';
import { runway, last } from '../src/kpis.js';

const near = (a, b, tol = 1e-6) => Math.abs(a - b) < tol;

test('the baseline reproduces the reported cash position exactly', () => {
  const base = cashBaseline();
  const company = getCompany(ASSUMPTIONS.companyId);
  const reported = runway(company.series);

  assert.ok(near(base.openingCash, last(company.series).cashClose));
  assert.ok(near(base.monthlyBurn, reported.avgMonthlyBurn));

  // The identity the whole model hangs on.
  assert.ok(
    near(base.monthlyOutflow - base.monthlyReceipts, reported.avgMonthlyBurn),
    'outflow less receipts must equal the burn the company reports',
  );
  assert.ok(
    near(base.monthlyPayroll + base.monthlySuppliers + base.monthlyDebtService, base.monthlyOutflow),
    'the outflow components must sum to total outflow',
  );
});

test('cost composition stays plausible rather than merely arithmetic', () => {
  const { composition } = cashBaseline();
  assert.ok(composition.payrollShare > 0.35 && composition.payrollShare < 0.70,
    `payroll at ${(composition.payrollShare * 100).toFixed(0)}% of outflow is not credible for a SaaS business`);
  assert.ok(composition.supplierShare > 0, 'derived supplier spend must not go negative');
});

test('every lever moves the forecast in the right direction', () => {
  const base = buildCashScenario({});
  const collections = buildCashScenario({ collectionsDaysImprovement: 15 });
  const pause = buildCashScenario({ hiringPause: true });
  const cut = buildCashScenario({ discretionaryCutPct: 0.2 });

  assert.ok(collections.runwayMonths > base.runwayMonths, 'collections must extend runway');
  assert.ok(pause.runwayMonths > base.runwayMonths, 'a hiring pause must extend runway');
  assert.ok(cut.runwayMonths > base.runwayMonths, 'a supplier cut must extend runway');

  // Collections is a one-off release, so it must not reduce the ongoing burn.
  assert.ok(near(collections.monthlyBurn, base.monthlyBurn),
    'a DSO improvement must not be modelled as a permanent reduction in burn');
  assert.ok(pause.monthlyBurn < base.monthlyBurn, 'a hiring pause must reduce ongoing burn');
});

test('levers compose rather than fight', () => {
  const all = buildCashScenario({ collectionsDaysImprovement: 15, hiringPause: true, discretionaryCutPct: 0.2 });
  const some = buildCashScenario({ collectionsDaysImprovement: 15, hiringPause: true });
  assert.ok(all.runwayMonths > some.runwayMonths);
  assert.equal(all.breachWeek, null, 'the full management case should clear the minimum-cash floor');
});

test('the weekly forecast is internally consistent', () => {
  const s = buildCashScenario({ collectionsDaysImprovement: 15 });
  assert.equal(s.weeks.length, ASSUMPTIONS.weeks);

  for (const w of s.weeks) {
    const expected = w.opening + w.receipts - w.payroll - w.suppliers - w.debtService;
    assert.ok(near(expected, w.closing, 1e-3), `week ${w.week} does not tie`);
    assert.equal(w.belowMinimum, w.closing < s.minimumCash);
  }

  for (let i = 1; i < s.weeks.length; i++) {
    assert.ok(near(s.weeks[i].opening, s.weeks[i - 1].closing, 1e-3),
      `week ${i + 1} does not open where week ${i} closed`);
  }

  assert.ok(near(s.weeks[0].opening, s.openingCash, 1e-3));
  assert.ok(near(s.weeks.at(-1).closing, s.closingCash, 1e-3));
});

test('the working-capital release is bounded and time-limited', () => {
  const s = buildCashScenario({ collectionsDaysImprovement: 15 });
  const base = cashBaseline();
  assert.ok(near(s.workingCapitalRelease, base.annualRevenue * (15 / 365), 1e-3));

  const boosted = s.weeks.filter((w) => w.week <= ASSUMPTIONS.collectionsReleaseWeeks);
  const after = s.weeks.filter((w) => w.week > ASSUMPTIONS.collectionsReleaseWeeks);
  assert.ok(boosted[0].receipts > after[0].receipts, 'the release must stop once collected');
});

test('the gap between reported and forward runway is stated, not hidden', () => {
  const cases = buildManagementCases();
  const f = cases.forwardVsReported;

  assert.ok(f.reportedMonths > f.forwardMonths,
    'funding planned hires should shorten the forward view');
  assert.ok(near(f.differenceMonths, f.forwardMonths - f.reportedMonths, 0.15));
  assert.ok(f.note.includes(String(ASSUMPTIONS.plannedHires)),
    'the note must say what causes the difference');
});

test('management cases are ordered by increasing intervention and effect', () => {
  const { comparison } = buildManagementCases();
  assert.equal(comparison.length, 4);
  for (let i = 1; i < comparison.length; i++) {
    assert.ok(comparison[i].runwayMonths >= comparison[i - 1].runwayMonths,
      `case "${comparison[i].name}" is not at least as good as the one before it`);
  }
  assert.equal(comparison[0].improvementMonths, 0);
  assert.ok(comparison.at(-1).headroomAtHorizon > 0);
});
