/**
 * Adapters onto the platform's real contracts.
 *
 * Verified against jbgray1874/alba-pip at 2c591dc. The field names below are
 * transcribed from `src/lib/financeData.js` and `api/ai/boardpack.js` — not
 * from documentation. An earlier version of these tests was written against a
 * prose description and passed while the adapter emitted nine wrong shapes.
 *
 * `FinanceDrilldown.jsx` reads `.kind`, `.series` and `.prop` directly, so a
 * missing key here is a blank screen there.
 */

import test from 'node:test';
import assert from 'node:assert/strict';

import {
  toFinanceShape, toFinanceShapeAll, toBoardPackSchema, toFeedStatus,
  BURN_SPLIT, REV_PRODUCTS, REV_REGIONS, BOARD_PACK_PROMPT,
} from '../src/adapters/albaPip.js';
import { FIN_SEED, getPortfolio } from '../src/portfolio.js';

/** The exact keys the platform's own buildFinance() returns. */
const CONTRACT = {
  top: ['seed', 'runway', 'status', 'cash', 'revenue', 'ebitda'],
  cash: ['balance', 'burn', 'runway', 'burnCats', 'debtors', 'arAging', 'overdueTotal', 'cashProj'],
  revenue: ['total', 'budget', 'byProduct', 'byRegion', 'deals'],
  ebitda: ['pct', 'value', 'bridge', 'opexLines', 'grossMargin'],
  rows: {
    'cash.burnCats': ['key', 'label', 'prop', 'color', 'value', 'series'],
    'cash.debtors': ['party', 'amount', 'daysOverdue', 'invoice', 'due', 'status'],
    'cash.arAging': ['bucket', 'val', 'color'],
    'cash.cashProj': ['m', 'v'],
    'revenue.byProduct': ['key', 'label', 'prop', 'value', 'series'],
    'revenue.byRegion': ['key', 'label', 'prop', 'value'],
    'revenue.deals': ['party', 'amount', 'product', 'region', 'invoice', 'date', 'status'],
    'ebitda.bridge': ['label', 'value', 'kind'],
    'ebitda.opexLines': ['label', 'value', 'series'],
  },
};

const get = (o, p) => p.split('.').reduce((a, k) => a?.[k], o);

test('every key the platform returns is present', () => {
  const f = toFinanceShape('meridian');
  for (const key of CONTRACT.top) assert.ok(key in f, `missing "${key}"`);
  for (const key of CONTRACT.cash) assert.ok(key in f.cash, `missing cash.${key}`);
  for (const key of CONTRACT.revenue) assert.ok(key in f.revenue, `missing revenue.${key}`);
  for (const key of CONTRACT.ebitda) assert.ok(key in f.ebitda, `missing ebitda.${key}`);
});

test('every array row carries the keys the drill-down reads', () => {
  const f = toFinanceShape('meridian');
  for (const [path, keys] of Object.entries(CONTRACT.rows)) {
    const rows = get(f, path);
    assert.ok(Array.isArray(rows) && rows.length > 0, `${path} is empty`);
    for (const key of keys) {
      assert.ok(key in rows[0], `${path}[0] is missing "${key}"`);
    }
  }
});

test('constants match the platform exactly', () => {
  assert.deepEqual(BURN_SPLIT.map((b) => b.prop), [0.59, 0.15, 0.16, 0.10]);
  assert.deepEqual(BURN_SPLIT.map((b) => b.key), ['payroll', 'marketing', 'overheads', 'saas']);
  assert.equal(BURN_SPLIT[0].color, '#3d8bff', 'colours drive the chart and must not shift');
  assert.deepEqual(REV_PRODUCTS.map((p) => p.prop), [0.60, 0.24, 0.16]);
  assert.deepEqual(REV_REGIONS.map((r) => r.prop), [0.57, 0.27, 0.16]);
});

test('the discriminator vocabularies are the platform\'s', () => {
  const f = toFinanceShape('meridian');
  assert.deepEqual(f.ebitda.bridge.map((b) => b.kind),
    ['start', 'neg', 'subtotal', 'neg', 'neg', 'neg', 'end']);
  for (const d of f.cash.debtors) {
    assert.ok(['critical', 'overdue', 'watch'].includes(d.status), `debtor status "${d.status}"`);
  }
});

test('the seed values are reproduced exactly', () => {
  for (const [id, seed] of Object.entries(FIN_SEED)) {
    const f = toFinanceShape(id);
    assert.equal(f.cash.balance, seed.cash, `${id} cash`);
    assert.equal(f.cash.burn, seed.burn, `${id} burn`);
    assert.equal(f.revenue.total, seed.revenue, `${id} revenue`);
    assert.equal(f.revenue.budget, seed.budget, `${id} budget`);
    assert.equal(f.ebitda.grossMargin, seed.gm, `${id} gross margin`);
    assert.equal(f.ebitda.pct, seed.ebitdaPct, `${id} EBITDA margin`);
    assert.equal(f.runway, +(seed.cash / seed.burn).toFixed(1), `${id} runway`);
    assert.deepEqual(f.seed, seed, `${id} seed passthrough`);
  }
});

test('the platform reconciliation principle holds', () => {
  for (const c of getPortfolio()) {
    const f = toFinanceShape(c.id);
    const b = f.ebitda.bridge;
    const near = (x, y) => Math.abs(x - y) < 0.01;

    const revenue = b[0].value;
    const cogs = -b[1].value;
    const grossProfit = b[2].value;
    const ebitda = b.at(-1).value;
    const opex = f.ebitda.opexLines.reduce((t, l) => t + l.value, 0);

    assert.ok(near(revenue - cogs, grossProfit), `${c.name}: gross profit`);
    assert.ok(near(grossProfit - opex, ebitda), `${c.name}: EBITDA`);
    assert.ok(near(revenue, f.revenue.total), `${c.name}: bridge revenue`);
    assert.ok(near(ebitda, f.ebitda.value), `${c.name}: bridge EBITDA`);

    // The platform's stated principle: debtors sum to the overdue total.
    // Note the unit shift — amounts are in pounds, the total in thousands.
    const debtorSum = f.cash.debtors.reduce((t, d) => t + d.amount, 0);
    assert.ok(near(debtorSum / 1000, f.cash.overdueTotal), `${c.name}: debtors vs overdue total`);

    const burnCatSum = f.cash.burnCats.reduce((t, x) => t + x.value, 0);
    assert.ok(near(burnCatSum, f.cash.burn), `${c.name}: burn categories`);

    const productSum = f.revenue.byProduct.reduce((t, x) => t + x.value, 0);
    assert.ok(near(productSum, f.revenue.total), `${c.name}: revenue by product`);
  }
});

test('sparkline series are drawn from the ledger, not synthesised', () => {
  const f = toFinanceShape('meridian');
  const company = getPortfolio().find((c) => c.id === 'meridian');
  const recent = company.series.slice(-6);

  for (const path of ['cash.burnCats', 'revenue.byProduct', 'ebitda.opexLines']) {
    for (const row of get(f, path)) {
      assert.equal(row.series.length, 6, `${path} series length`);
    }
  }

  // The last point of each series must be the current value.
  const payroll = f.cash.burnCats[0];
  assert.ok(Math.abs(payroll.series.at(-1) - payroll.value) < 0.1,
    'the series must end where the metric currently stands');

  // And it must move with the ledger, not along a straight line to it.
  const burnPath = recent.map((r) => Math.round(r.netBurn * 1000 * 0.59 * 10) / 10);
  assert.deepEqual(payroll.series, burnPath, 'payroll series must be the real burn × its share');
});

test('the signature accepts a company object or an id', () => {
  const byId = toFinanceShape('meridian');
  const byObject = toFinanceShape({ id: 'meridian', status: 'amber' });
  assert.equal(byObject.status, 'amber', 'a passed-in status wins, as the platform expects');
  assert.equal(byId.cash.balance, byObject.cash.balance);
});

test('every company adapts without throwing', () => {
  const all = toFinanceShapeAll();
  assert.equal(Object.keys(all).length, getPortfolio().length);
  for (const [id, f] of Object.entries(all)) {
    assert.ok(f.cash.balance >= 0, `${id} negative cash`);
    assert.ok(f.cash.cashProj.length > 0 && f.cash.cashProj.length <= 9, `${id} cashProj length`);
    assert.equal(f.revenue.deals.length, 6, `${id} deals`);
    assert.equal(f.cash.debtors.length, 5, `${id} debtors`);
  }
});

test('the board pack leaves only the narrative to the model', () => {
  const bp = toBoardPackSchema('meridian');
  assert.equal(bp.executiveSummary, null);
  assert.equal(bp.outlook, null);

  for (const key of ['keyMetrics', 'risks', 'opportunities', 'actions']) {
    assert.ok(Array.isArray(bp[key]), `${key} must be an array`);
  }
  for (const m of bp.keyMetrics) {
    assert.ok(m.label && m.value && m.vs);
    assert.ok(['red', 'amber', 'green'].includes(m.rag), `rag "${m.rag}"`);
  }
  for (const a of bp.actions) {
    assert.ok(a.owner);
    assert.match(a.deadline, /^\d{1,2} [A-Z][a-z]{2} \d{4}$/,
      `deadline "${a.deadline}" must use the platform's "30 Jun 2026" format`);
    assert.ok(['critical', 'high', 'medium', 'low'].includes(a.priority));
  }
  for (const r of bp.risks) {
    assert.ok(['high', 'medium', 'low'].includes(r.severity));
    assert.ok(r.evidence.length > 0, `risk "${r.title}" has no evidence`);
  }
});

test('the board pack prompt forbids the model inventing figures', () => {
  assert.match(BOARD_PACK_PROMPT, /executiveSummary/);
  assert.match(BOARD_PACK_PROMPT, /outlook/);
  assert.match(BOARD_PACK_PROMPT, /not introduce any figure/i);
});

test('feed status never relabels seed data as live', () => {
  assert.equal(toFeedStatus().portfolio.status, 'simulated');
  assert.equal(toFeedStatus({ xero: true }).xero.status, 'live');
  assert.equal(toFeedStatus({ xero: true }).portfolio.status, 'simulated');
});
