/**
 * Scenario 5 — cross-portfolio procurement.
 *
 * The savings figure is the number a CFO will attack first, so the tests are
 * mostly about what the figure is *not* allowed to include.
 */

import test from 'node:test';
import assert from 'node:assert/strict';

import {
  buildScenario5, buildProcurementReport, normaliseVendorName, matchQuality,
  CATEGORIES, PARAMS,
} from '../src/scenario5-procurement.js';
import { toMarkdown } from '../src/report.js';

const near = (a, b, tol = 1e-9) => Math.abs(a - b) < tol;

test('vendor name normalisation handles real ledger variants', () => {
  const variants = [
    'Northwind Cloud Services Ltd',
    'NORTHWIND CLOUD SVCS (SG) PTE LTD',
    'northwind cloud services pte ltd',
    'Northwind Cloud Services (DMCC)',
    'Northwind Cloud Services FZ-LLC',
  ];
  const keys = new Set(variants.map((v) => normaliseVendorName(v).key));
  assert.equal(keys.size, 1, `expected one key, got ${[...keys].join(' | ')}`);
});

test('match grading separates confident merges from candidates', () => {
  assert.equal(matchQuality('Grantly & Co LLP', 'Grantly and Co (Singapore)'), 'exact');
  assert.equal(matchQuality('Atlas Collaboration Suite', 'Atlas Collab Suite (APAC)'), 'prefix');
  assert.equal(matchQuality('Talentbridge Recruitment Ltd', 'Talentbridge Search & Selection'), 'review');
  assert.equal(matchQuality('Orbit Telecom', 'Sentinel Cyber Defence'), 'different');
});

test('a short qualifier does not merge on a coincidental prefix', () => {
  // "co" is three characters or fewer once suffixes are stripped, so it must
  // not silently absorb an unrelated supplier.
  assert.notEqual(matchQuality('Vertex Co', 'Vertex Consulting Partners'), 'prefix');
});

test('spend pending review is excluded from the headline saving', () => {
  const s = buildScenario5();
  assert.ok(s.reviewQueue.length > 0, 'the fixture must exercise the review path');
  assert.ok(s.totals.pendingSpend > 0);
  assert.ok(
    near(s.totals.confirmedSpend + s.totals.pendingSpend, s.totals.addressableSpend, 1e-6),
    'confirmed plus pending must account for all addressable spend',
  );

  const categorySpend = s.byCategory.reduce((t, c) => t + c.spend, 0);
  assert.ok(
    near(categorySpend, s.totals.confirmedSpend, 1e-6),
    'the saving must be computed on confirmed spend only',
  );
  assert.ok(s.totals.additionalIfConfirmed > 0, 'the held-back upside must be stated, not hidden');
});

test('only spend shared across enough companies is treated as addressable', () => {
  const s = buildScenario5();
  for (const v of s.addressable) {
    assert.ok(v.companies >= PARAMS.minCompaniesForAction, `${v.canonical} has ${v.companies} companies`);
  }
  const excluded = s.vendors.filter((v) => !v.addressable);
  assert.ok(excluded.length > 0, 'the fixture must include unshared suppliers to exclude');
  assert.ok(s.totals.addressableSpend < s.totals.totalSpend);
});

test('every category saving traces to a named, quotable assumption', () => {
  const s = buildScenario5();
  for (const c of s.byCategory) {
    assert.ok(CATEGORIES[c.category], `${c.category} has no declared assumption`);
    assert.equal(c.rate, CATEGORIES[c.category].rate);
    assert.ok(c.basis.length > 15, `${c.category} rate has no stated basis`);
    assert.ok(near(c.saving, c.spend * c.rate, 1e-9));
  }
  const total = s.byCategory.reduce((t, c) => t + c.saving, 0);
  assert.ok(near(total, s.totals.expected, 1e-9));
});

test('the saving lands in the range the specification describes', () => {
  const { low, high } = buildScenario5().totals;
  assert.ok(low > 0.75 && low < 0.95, `low of ${low.toFixed(3)}m should sit near 0.8m`);
  assert.ok(high > 1.0 && high < 1.25, `high of ${high.toFixed(3)}m should sit near 1.1m`);
});

test('every consolidation action is anchored to a contract renewal date', () => {
  const s = buildScenario5();
  const renewals = new Set(s.renewalWindow.map((r) => r.renewal));
  for (const a of s.insight.actions) {
    assert.ok(/^\d{4}-\d{2}-\d{2}$/.test(a.due));
    assert.ok(renewals.has(a.due), `action due ${a.due} does not match any contract renewal`);
  }
});

test('the procurement report renders cleanly', () => {
  const report = buildProcurementReport(buildScenario5());
  const md = toMarkdown(report);
  assert.ok(md.startsWith('# Portfolio Procurement Opportunity Report'));
  assert.ok(md.includes('Metric appendix'));
  assert.ok(!md.includes('undefined'));
  assert.ok(!md.includes('NaN'));
  assert.ok(report.renewalTimetable.length > 0);
  assert.ok(report.sharedVendors.every((v) => v.companies >= PARAMS.minCompaniesForAction));
});
