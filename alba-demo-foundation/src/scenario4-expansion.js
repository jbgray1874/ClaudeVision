/**
 * Scenario 4 — Sales acceleration and expansion opportunity.
 * Build priority 1 (primary demo).
 *
 * PayFlo is performing in line with plan, so nothing in conventional reporting
 * draws attention to it. Alba finds a cross-sell cohort by scoring every
 * customer against the profile of accounts that previously bought the second
 * product.
 *
 * The scoring is deliberately rule-based. The demo specification is explicit
 * that a transparent score beats an unexplained model here: the investor
 * question is "why this account?", and a weighted rule set answers it.
 */

import { getCompany, SOURCES, AS_OF } from './portfolio.js';
import { makeInsight, CONFIDENCE, formatMoney, formatPct } from './insight.js';
import { rngFor, between } from './rng.js';

const COMPANY_ID = 'halcyon';

export const PRODUCTS = {
  A: 'Payments Core',
  B: 'Reconciliation Suite', // the cross-sell target
  C: 'Treasury Insights',
};

export const SCORE_WEIGHTS = {
  usageTrend: 30,
  accountHealth: 25,
  lookalikeMatch: 15,
  sizeFit: 15,
  renewalWindow: 10,
  serviceClean: 5,
};

export const PARAMS = {
  customerCount: 42,
  qualifyingScore: 65,
  attachUplift: 0.25,      // Reconciliation Suite ACV as a share of the account's Payments Core ARR
  conversionFloor: 0.10,
  conversionCeiling: 0.70,
  rangeSensitivity: 0.15,  // ± applied to expected conversion for the reported range
};

/** Accounts that previously bought the Reconciliation Suite — the comparison set. */
export const PRIOR_WINS = [
  { account: 'Selangor Retail Bank', usageTrend90d: 0.31, arrAtPurchase: 1.42, tenureMonths: 22 },
  { account: 'Dhow Freight Holdings', usageTrend90d: 0.24, arrAtPurchase: 0.98, tenureMonths: 18 },
  { account: 'Batavia Payments Group', usageTrend90d: 0.36, arrAtPurchase: 1.85, tenureMonths: 26 },
  { account: 'Emirates Retail Partners', usageTrend90d: 0.22, arrAtPurchase: 1.20, tenureMonths: 20 },
  { account: 'Straits Micro Lending', usageTrend90d: 0.28, arrAtPurchase: 0.86, tenureMonths: 24 },
  { account: 'Cebu Commerce Bank', usageTrend90d: 0.33, arrAtPurchase: 1.61, tenureMonths: 19 },
];

const CENTROID = {
  usageTrend90d: PRIOR_WINS.reduce((t, w) => t + w.usageTrend90d, 0) / PRIOR_WINS.length,
  arr: PRIOR_WINS.reduce((t, w) => t + w.arrAtPurchase, 0) / PRIOR_WINS.length,
  tenureMonths: PRIOR_WINS.reduce((t, w) => t + w.tenureMonths, 0) / PRIOR_WINS.length,
};

const SEGMENTS = ['Banking', 'Marketplace', 'Retail', 'Logistics', 'Lending'];
const NAME_PARTS = [
  ['Andaman', 'Kinabalu', 'Sabah', 'Mekong', 'Jurong', 'Sentosa', 'Penang', 'Bintan',
   'Al Reem', 'Khalidiya', 'Yas', 'Mussafah', 'Deira', 'Jumeirah', 'Sharjah', 'Fujairah',
   'Cebu', 'Davao', 'Bandung', 'Surabaya', 'Hanoi', 'Danang', 'Chiang', 'Phuket',
   'Selayang', 'Klang', 'Ipoh', 'Malacca', 'Batam', 'Medan', 'Makati', 'Ortigas',
   'Kandal', 'Siem', 'Vientiane', 'Yangon', 'Dhaka', 'Colombo', 'Male', 'Karachi',
   'Doha', 'Manama', 'Muscat', 'Salalah', 'Riyadh', 'Jeddah', 'Dammam', 'Tabuk'],
  ['Commerce', 'Capital', 'Holdings', 'Financial', 'Retail Group', 'Logistics',
   'Payments', 'Trading', 'Ventures', 'Partners'],
];

function clamp(v, lo = 0, hi = 1) {
  return Math.max(lo, Math.min(hi, v));
}

function buildCustomers() {
  const company = getCompany(COMPANY_ID);
  const latest = company.series[company.series.length - 1];
  const targetArr = latest.revenue * 12;

  const rows = [];
  for (let i = 0; i < PARAMS.customerCount; i++) {
    const name = `${NAME_PARTS[0][i % NAME_PARTS[0].length]} ${NAME_PARTS[1][i % NAME_PARTS[1].length]}`;
    const r = rngFor(`payflo:customer:${name}`);

    const weight = between(r, 0.35, 2.6) ** 1.6;
    const usageTrend90d = between(r, -0.14, 0.44);
    const accountHealth = clamp(between(r, 0.32, 0.99));
    const tenureMonths = Math.round(between(r, 4, 40));
    const renewalInDays = Math.round(between(r, 12, 400));
    const openSevereTickets = r() < 0.18 ? Math.ceil(between(r, 1, 3)) : 0;
    const ownsB = r() < 0.22;
    const ownsC = r() < 0.3;

    rows.push({
      account: name,
      segment: SEGMENTS[i % SEGMENTS.length],
      weight,
      usageTrend90d: Math.round(usageTrend90d * 1000) / 1000,
      accountHealth: Math.round(accountHealth * 100) / 100,
      tenureMonths,
      renewalInDays,
      renewalDate: addDays(AS_OF, renewalInDays),
      openSevereTickets,
      productsOwned: [PRODUCTS.A, ownsB ? PRODUCTS.B : null, ownsC ? PRODUCTS.C : null].filter(Boolean),
    });
  }

  const weightTotal = rows.reduce((t, c) => t + c.weight, 0);
  return rows.map(({ weight, ...c }) => ({
    ...c,
    arr: Math.round(((weight / weightTotal) * targetArr) * 1000) / 1000,
    source: SOURCES.billing.system,
    refreshedAt: SOURCES.billing.refreshedAt,
  }));
}

function addDays(isoDate, days) {
  const d = new Date(`${isoDate}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

/** Transparent, additive score. Each component returns its own contribution. */
export function scoreAccount(customer) {
  const components = {
    usageTrend: {
      weight: SCORE_WEIGHTS.usageTrend,
      normalised: clamp((customer.usageTrend90d + 0.10) / 0.45),
      basis: `90-day product usage trend of ${formatPct(customer.usageTrend90d)}`,
    },
    accountHealth: {
      weight: SCORE_WEIGHTS.accountHealth,
      normalised: clamp((customer.accountHealth - 0.3) / 0.65),
      basis: `account health index of ${customer.accountHealth.toFixed(2)}`,
    },
    lookalikeMatch: {
      weight: SCORE_WEIGHTS.lookalikeMatch,
      normalised: clamp(
        1 -
          (Math.abs(customer.usageTrend90d - CENTROID.usageTrend90d) / 0.45 +
            Math.abs(customer.arr - CENTROID.arr) / 2.2 +
            Math.abs(customer.tenureMonths - CENTROID.tenureMonths) / 26) / 3,
      ),
      basis: 'similarity to the six accounts that previously adopted the Reconciliation Suite',
    },
    sizeFit: {
      weight: SCORE_WEIGHTS.sizeFit,
      normalised: clamp(1 - Math.abs(customer.arr - CENTROID.arr) / 2.2),
      basis: `annual recurring revenue of ${formatMoney(customer.arr, 'USD')}`,
    },
    renewalWindow: {
      weight: SCORE_WEIGHTS.renewalWindow,
      normalised:
        customer.renewalInDays >= 45 && customer.renewalInDays <= 200
          ? 1
          : clamp(1 - Math.abs(customer.renewalInDays - 120) / 260),
      basis: `renewal in ${customer.renewalInDays} days`,
    },
    serviceClean: {
      weight: SCORE_WEIGHTS.serviceClean,
      normalised: customer.openSevereTickets === 0 ? 1 : 0,
      basis:
        customer.openSevereTickets === 0
          ? 'no open severity-one support tickets'
          : `${customer.openSevereTickets} open severity-one support tickets`,
    },
  };

  let score = 0;
  const breakdown = [];
  for (const [key, c] of Object.entries(components)) {
    const points = c.weight * c.normalised;
    score += points;
    breakdown.push({ factor: key, points: Math.round(points * 10) / 10, of: c.weight, basis: c.basis });
  }

  return { score: Math.round(score * 10) / 10, breakdown };
}

function conversionProbability(score) {
  return clamp((score - 50) / 70, PARAMS.conversionFloor, PARAMS.conversionCeiling);
}

export function buildScenario4() {
  const company = getCompany(COMPANY_ID);
  const customers = buildCustomers();

  const scored = customers.map((c) => {
    const { score, breakdown } = scoreAccount(c);
    const ownsTarget = c.productsOwned.includes(PRODUCTS.B);
    const pConvert = conversionProbability(score);
    const grossOpportunity = c.arr * PARAMS.attachUplift;
    return {
      ...c,
      score,
      breakdown,
      ownsTarget,
      qualified: !ownsTarget && score >= PARAMS.qualifyingScore,
      conversionProbability: Math.round(pConvert * 1000) / 1000,
      grossOpportunity: Math.round(grossOpportunity * 1000) / 1000,
      expectedValue: Math.round(grossOpportunity * pConvert * 1000) / 1000,
    };
  });

  const qualified = scored
    .filter((c) => c.qualified)
    .sort((a, b) => b.expectedValue - a.expectedValue);

  const expected = qualified.reduce((t, c) => t + c.expectedValue, 0);
  const gross = qualified.reduce((t, c) => t + c.grossOpportunity, 0);
  const low = expected * (1 - PARAMS.rangeSensitivity);
  const high = expected * (1 + PARAMS.rangeSensitivity);

  const currentPenetration =
    scored.filter((c) => c.ownsTarget).length / scored.length;

  const insight = makeInsight({
    id: 'payflo-crosssell-2026q4',
    type: 'opportunity',
    companyId: company.id,
    companyName: company.name,
    raisedOn: AS_OF,
    headline: `Cross-sell cohort worth ${formatMoney(low, company.currency)}–${formatMoney(high, company.currency)} of additional ARR`,
    whatHappened:
      `${qualified.length} existing ${company.name} customers match the profile of the six accounts that ` +
      `previously adopted the ${PRODUCTS.B}. They show rising product usage, healthy account signals and ` +
      `renewal dates inside the next two quarters, and none of them currently own the product.`,
    whyItMatters:
      `${company.name} is performing in line with plan, so nothing in the monthly pack draws attention here. ` +
      `Current ${PRODUCTS.B} penetration is ${formatPct(currentPenetration)} of the customer base. ` +
      `Converting this cohort would add ${formatPct(expected / (company.series[company.series.length - 1].revenue * 12))} to recurring revenue ` +
      `without new customer acquisition cost.`,
    evidence: [
      {
        label: 'Qualified accounts',
        value: `${qualified.length} of ${scored.length} customers score ${PARAMS.qualifyingScore} or above and do not own the ${PRODUCTS.B}`,
        source: SOURCES.billing.system,
        refreshedAt: SOURCES.billing.refreshedAt,
        detail: { qualifyingScore: PARAMS.qualifyingScore, weights: SCORE_WEIGHTS },
      },
      {
        label: 'Gross opportunity before conversion',
        value: formatMoney(gross, company.currency),
        source: 'Alba calculation',
        refreshedAt: AS_OF,
        detail: { attachUplift: PARAMS.attachUplift, basis: 'attach rate applied to each account\'s current ARR' },
      },
      {
        label: 'Comparison set',
        value: `${PRIOR_WINS.length} prior adoptions, average usage trend ${formatPct(CENTROID.usageTrend90d)} at the point of purchase`,
        source: SOURCES.pipeline.system,
        refreshedAt: SOURCES.pipeline.refreshedAt,
        detail: { priorWins: PRIOR_WINS, centroid: CENTROID },
      },
      {
        label: 'Renewal timing',
        value: `${qualified.filter((c) => c.renewalInDays <= 200).length} of ${qualified.length} qualified accounts renew within 200 days`,
        source: SOURCES.billing.system,
        refreshedAt: SOURCES.billing.refreshedAt,
      },
    ],
    impact: {
      measure: 'Incremental annual recurring revenue',
      value: expected,
      currency: company.currency,
      horizon: 'Next four quarters',
      direction: 'upside',
    },
    confidence: CONFIDENCE.MEDIUM,
    methodology:
      'Every customer is scored on six weighted, inspectable factors. Accounts scoring at or above ' +
      `${PARAMS.qualifyingScore} that do not already own the ${PRODUCTS.B} are qualified. Expected value is the ` +
      `account's current ARR × attach rate × a conversion probability derived linearly from its score. ` +
      `The reported range applies a ±${Math.round(PARAMS.rangeSensitivity * 100)}% sensitivity to conversion.`,
    actions: qualified.slice(0, 5).map((c, i) => ({
      action: `Cross-sell approach to ${c.account} (${c.segment})`,
      owner: i % 2 === 0 ? 'VP Sales, Southeast Asia' : 'VP Sales, Middle East',
      due: addDays(AS_OF, 14 + i * 7),
      rationale:
        `Score ${c.score}, renewal in ${c.renewalInDays} days, expected ${formatMoney(c.expectedValue, company.currency)}.`,
    })),
    drillDown: { scored, qualified },
  });

  return {
    company,
    customers: scored,
    qualified,
    totals: { expected, gross, low, high, currentPenetration },
    insight,
  };
}
