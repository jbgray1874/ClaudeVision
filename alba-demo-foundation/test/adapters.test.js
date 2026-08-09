/**
 * Adapters onto the platform's existing contracts.
 *
 * These tests exist to stop the package drifting away from the shapes the
 * React app already consumes. If `buildFinance`'s contract changes in the
 * platform, one of these should fail rather than a screen going blank.
 */

import test from 'node:test';
import assert from 'node:assert/strict';

import {
  toFinanceShape, toFinanceShapeAll, toBoardPackSchema, toFeedStatus,
  BURN_CATEGORIES, BOARD_PACK_PROMPT,
} from '../src/adapters/albaPip.js';
import { FIN_SEED, getPortfolio } from '../src/portfolio.js';

test('the finance shape carries every key the platform reads', () => {
  const f = toFinanceShape('meridian');

  for (const key of ['seed', 'runway', 'status', 'cash', 'revenue', 'ebitda']) {
    assert.ok(key in f, `missing top-level key "${key}"`);
  }
  for (const key of ['balance', 'burn', 'runway', 'burnCats', 'debtors', 'arAging', 'overdueTotal', 'cashProj']) {
    assert.ok(key in f.cash, `missing cash.${key}`);
  }
  for (const key of ['total', 'budget', 'byProduct', 'byRegion', 'deals']) {
    assert.ok(key in f.revenue, `missing revenue.${key}`);
  }
  for (const key of ['pct', 'value', 'bridge', 'opexLines', 'grossMargin']) {
    assert.ok(key in f.ebitda, `missing ebitda.${key}`);
  }
});

test('the finance shape reproduces the platform seed exactly', () => {
  for (const [id, seed] of Object.entries(FIN_SEED)) {
    const f = toFinanceShape(id);
    assert.equal(f.cash.balance, seed.cash, `${id} cash`);
    assert.equal(f.cash.burn, seed.burn, `${id} burn`);
    assert.equal(f.revenue.total, seed.revenue, `${id} revenue`);
    assert.equal(f.revenue.budget, seed.budget, `${id} budget`);
    assert.ok(Math.abs(f.runway - seed.cash / seed.burn) < 0.15, `${id} runway`);
    assert.ok(Math.abs(f.ebitda.grossMargin - seed.gm) < 0.3, `${id} gross margin`);
    assert.ok(Math.abs(f.ebitda.pct - seed.ebitdaPct) < 0.3, `${id} EBITDA margin`);
  }
});

test('the platform reconciliation principle holds in the adapted shape', () => {
  for (const c of getPortfolio()) {
    const f = toFinanceShape(c.id);
    const bridge = f.ebitda.bridge;

    const revenue = bridge.find((b) => b.label === 'Revenue').value;
    const cogs = -bridge.find((b) => b.label === 'Cost of sales').value;
    const grossProfit = bridge.find((b) => b.label === 'Gross profit').value;
    const ebitda = bridge.find((b) => b.label === 'EBITDA').value;
    const opex = f.ebitda.opexLines.reduce((t, l) => t + l.value, 0);

    assert.equal(revenue - cogs, grossProfit, `${c.name}: gross profit does not tie`);
    assert.equal(grossProfit - opex, ebitda, `${c.name}: EBITDA does not tie`);
    assert.equal(revenue, f.revenue.total, `${c.name}: bridge revenue differs from revenue.total`);
    assert.equal(ebitda, f.ebitda.value, `${c.name}: bridge EBITDA differs from ebitda.value`);

    // The platform's stated principle: the overdue total is the sum of its rows.
    const debtorSum = f.cash.debtors.reduce((t, d) => t + d.amount, 0);
    assert.equal(debtorSum, f.cash.overdueTotal, `${c.name}: debtors do not sum to the overdue total`);

    const burnCatSum = f.cash.burnCats.reduce((t, b) => t + b.value, 0);
    assert.ok(Math.abs(burnCatSum - f.cash.burn) <= 1,
      `${c.name}: burn categories sum to ${burnCatSum} against a burn of ${f.cash.burn}`);
  }
});

test('burn category shares are the ones the platform already uses', () => {
  const total = BURN_CATEGORIES.reduce((t, c) => t + c.share, 0);
  assert.ok(Math.abs(total - 1) < 1e-9, 'burn category shares must total 100%');
  assert.equal(BURN_CATEGORIES.find((c) => c.key === 'payroll').share, 0.59);
});

test('every company adapts without throwing', () => {
  const all = toFinanceShapeAll();
  assert.equal(Object.keys(all).length, getPortfolio().length);
  for (const [id, f] of Object.entries(all)) {
    assert.ok(f.cash.balance >= 0, `${id} has negative cash`);
    assert.equal(f.cash.cashProj.length, 9);
    assert.equal(f.revenue.deals.length, 6);
  }
});

test('the board pack schema leaves only the narrative to the model', () => {
  const bp = toBoardPackSchema('meridian');

  assert.equal(bp.executiveSummary, null, 'the summary is the model\'s job');
  assert.equal(bp.outlook, null, 'the outlook is the model\'s job');

  assert.ok(bp.keyMetrics.length >= 5);
  for (const m of bp.keyMetrics) {
    assert.ok(m.label && m.value && m.vs, `metric "${m.label}" is incomplete`);
    assert.ok(['red', 'amber', 'green'].includes(m.rag), `metric "${m.label}" has rag "${m.rag}"`);
  }

  for (const a of bp.actions) {
    assert.ok(a.owner, 'an action has no owner');
    assert.ok(/^\d{4}-\d{2}-\d{2}$/.test(a.deadline), 'an action has no deadline');
    assert.ok(['critical', 'high', 'medium', 'low'].includes(a.priority));
  }

  for (const r of bp.risks) {
    assert.ok(r.evidence.length > 0, `risk "${r.title}" carries no evidence`);
    assert.ok(['high', 'medium', 'low'].includes(r.severity));
  }

  assert.ok(bp.provenance.sources.length > 0);
});

test('the board pack prompt forbids the model inventing figures', () => {
  assert.match(BOARD_PACK_PROMPT, /executiveSummary/);
  assert.match(BOARD_PACK_PROMPT, /outlook/);
  assert.match(BOARD_PACK_PROMPT, /not introduce any figure/i);
});

test('feed status reports the demo dataset honestly', () => {
  const off = toFeedStatus();
  assert.equal(off.portfolio.status, 'simulated',
    'the demo dataset must never present itself as live');
  assert.equal(off.xero.status, 'simulated');

  const on = toFeedStatus({ xero: true });
  assert.equal(on.xero.status, 'live');
  assert.equal(on.portfolio.status, 'simulated', 'a live Xero must not relabel the seed data');
});
