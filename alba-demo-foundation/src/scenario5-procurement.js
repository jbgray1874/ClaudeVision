/**
 * Scenario 5 — Cross-portfolio cost and procurement opportunity.
 *
 * The specification ranks this phase 2, after the company-level model is
 * credible. That model now exists, so this is buildable — and it is the only
 * scenario that is impossible without the whole portfolio, which makes it the
 * strongest argument for a platform over a spreadsheet.
 *
 * The work is four steps: normalise vendor names that differ across companies,
 * classify spend into procurement categories, aggregate across the portfolio,
 * then apply transparent negotiation assumptions. Each step is inspectable,
 * because "we found £1m of savings" is a claim a CFO will want to take apart.
 */

import { getPortfolio, getCompany, SOURCES, AS_OF } from './portfolio.js';
import { last } from './kpis.js';
import { makeInsight, CONFIDENCE, formatMoney, formatPct } from './insight.js';
import { rngFor, between } from './rng.js';

/**
 * Consolidation assumptions by category.
 *
 * These are the numbers a buyer will challenge first, so they live here as
 * named, quotable parameters rather than being buried in a calculation.
 * `rate` is the discount assumed available on addressable spend when the
 * portfolio negotiates as one buyer.
 */
export const CATEGORIES = {
  'Cloud & hosting':      { rate: 0.10, basis: 'committed-use discount at portfolio volume' },
  'Cybersecurity':        { rate: 0.12, basis: 'single-tenancy consolidation and licence rationalisation' },
  'HR systems':           { rate: 0.15, basis: 'migration to one platform at portfolio headcount' },
  'Recruitment':          { rate: 0.08, basis: 'preferred-supplier agreement replacing per-hire agency fees' },
  'Professional services': { rate: 0.07, basis: 'panel appointment with agreed rate card' },
  'Insurance':            { rate: 0.09, basis: 'portfolio-level placement rather than individual renewal' },
  'Software & SaaS':      { rate: 0.12, basis: 'enterprise agreement replacing per-company subscriptions' },
  'Telecoms':             { rate: 0.08, basis: 'aggregated connectivity and mobile estate' },
};

export const PARAMS = {
  minCompaniesForAction: 3, // below this, portfolio negotiation is not worth the coordination
  rangeSensitivity: 0.15,
  unitBasis: { 'HR systems': 'per employee', 'Software & SaaS': 'per employee', 'Cybersecurity': 'per employee' },
};

/**
 * Vendors used across the portfolio, with the name each company's ledger
 * actually carries. The variants are the point: the same supplier appears
 * three different ways, which is why cross-company spend is invisible without
 * normalisation.
 */
const VENDORS = [
  {
    canonical: 'Northwind Cloud',
    category: 'Cloud & hosting',
    portfolioSpend: 3.80,
    contracts: [
      { company: 'kestrel',    ledgerName: 'Northwind Cloud Services Ltd',        renewal: '2027-01-31' },
      { company: 'payflo',     ledgerName: 'NORTHWIND CLOUD SVCS (SG) PTE LTD',   renewal: '2026-11-30' },
      { company: 'meridian',   ledgerName: 'Northwind Cloud Services',            renewal: '2027-03-31' },
      { company: 'swiftlogix', ledgerName: 'Northwind Cloud Svcs Pte',            renewal: '2026-12-31' },
      { company: 'lumen',      ledgerName: 'Northwind Cloud Services FZ-LLC',     renewal: '2027-02-28' },
      { company: 'halcyon',    ledgerName: 'northwind cloud services pte ltd',    renewal: '2026-10-31' },
      { company: 'solstice',   ledgerName: 'Northwind Cloud Services (DMCC)',     renewal: '2027-04-30' },
    ],
  },
  {
    canonical: 'Sentinel Cyber',
    category: 'Cybersecurity',
    portfolioSpend: 0.95,
    contracts: [
      { company: 'kestrel',   ledgerName: 'Sentinel Cyber Defence Ltd',      renewal: '2026-12-31' },
      { company: 'payflo',    ledgerName: 'Sentinel Cyber Defense Inc',      renewal: '2027-01-31' },
      { company: 'forgetech', ledgerName: 'Sentinel Cyber Defence',          renewal: '2026-11-30' },
      { company: 'northgate', ledgerName: 'SENTINEL CYBER DEFENCE LIMITED',  renewal: '2027-02-28' },
      { company: 'solstice',  ledgerName: 'Sentinel Cyber Defence FZE',      renewal: '2026-12-31' },
    ],
  },
  {
    canonical: 'PeopleFirst HR',
    category: 'HR systems',
    portfolioSpend: 0.50,
    contracts: [
      { company: 'kestrel',    ledgerName: 'PeopleFirst HR Platform',       renewal: '2027-03-31' },
      { company: 'swiftlogix', ledgerName: 'Peoplefirst HR Pte Ltd',        renewal: '2026-11-30' },
      { company: 'lumen',      ledgerName: 'PeopleFirst HR Software FZ',    renewal: '2027-01-31' },
      { company: 'halcyon',    ledgerName: 'PEOPLEFIRST HR',                renewal: '2026-12-31' },
    ],
  },
  {
    canonical: 'Talentbridge Recruitment',
    category: 'Recruitment',
    portfolioSpend: 1.60,
    contracts: [
      { company: 'kestrel',    ledgerName: 'Talentbridge Recruitment Ltd',       renewal: '2026-12-31' },
      { company: 'payflo',     ledgerName: 'Talentbridge Search & Selection',    renewal: '2027-02-28' },
      { company: 'forgetech',  ledgerName: 'Talentbridge Recruitment',           renewal: '2026-11-30' },
      { company: 'northgate',  ledgerName: 'TALENTBRIDGE RECRUITMENT LTD',       renewal: '2027-01-31' },
      { company: 'solstice',   ledgerName: 'Talentbridge Recruitment ME FZ-LLC', renewal: '2026-12-31' },
      { company: 'halcyon',    ledgerName: 'Talentbridge Recruitment Pte',       renewal: '2027-03-31' },
    ],
  },
  {
    canonical: 'Grantly & Co',
    category: 'Professional services',
    portfolioSpend: 1.50,
    contracts: [
      { company: 'kestrel',   ledgerName: 'Grantly & Co LLP',            renewal: '2027-06-30' },
      { company: 'payflo',    ledgerName: 'Grantly and Co (Singapore)',  renewal: '2027-06-30' },
      { company: 'forgetech', ledgerName: 'Grantly & Co',                renewal: '2026-12-31' },
      { company: 'northgate', ledgerName: 'GRANTLY & CO LLP',            renewal: '2027-06-30' },
      { company: 'lumen',     ledgerName: 'Grantly & Co Middle East',    renewal: '2027-01-31' },
    ],
  },
  {
    canonical: 'Meridian Assurance',
    category: 'Insurance',
    portfolioSpend: 0.70,
    contracts: [
      { company: 'forgetech', ledgerName: 'Meridian Assurance Brokers Ltd', renewal: '2026-10-31' },
      { company: 'northgate', ledgerName: 'Meridian Assurance Brokers',     renewal: '2026-10-31' },
      { company: 'swiftlogix', ledgerName: 'MERIDIAN ASSURANCE (ASIA)',     renewal: '2026-11-30' },
      { company: 'solstice',  ledgerName: 'Meridian Assurance Brokers FZE', renewal: '2026-10-31' },
    ],
  },
  {
    canonical: 'Atlas Collaboration Suite',
    category: 'Software & SaaS',
    portfolioSpend: 1.00,
    contracts: [
      { company: 'kestrel',    ledgerName: 'Atlas Collaboration Suite',        renewal: '2027-02-28' },
      { company: 'payflo',     ledgerName: 'Atlas Collab Suite (APAC)',        renewal: '2026-12-31' },
      { company: 'meridian',   ledgerName: 'Atlas Collaboration',              renewal: '2027-01-31' },
      { company: 'forgetech',  ledgerName: 'ATLAS COLLABORATION SUITE LTD',    renewal: '2026-11-30' },
      { company: 'northgate',  ledgerName: 'Atlas Collaboration Suite Ltd',    renewal: '2027-03-31' },
      { company: 'swiftlogix', ledgerName: 'Atlas Collaboration Suite Pte',    renewal: '2026-12-31' },
      { company: 'lumen',      ledgerName: 'Atlas Collab Suite FZ-LLC',        renewal: '2027-02-28' },
      { company: 'halcyon',    ledgerName: 'atlas collaboration suite',        renewal: '2027-01-31' },
    ],
  },
  {
    canonical: 'Orbit Telecom',
    category: 'Telecoms',
    portfolioSpend: 0.25,
    contracts: [
      { company: 'swiftlogix', ledgerName: 'Orbit Telecom Pte Ltd',   renewal: '2026-12-31' },
      { company: 'halcyon',    ledgerName: 'Orbit Telecom',           renewal: '2027-01-31' },
      { company: 'solstice',   ledgerName: 'Orbit Telecom FZ-LLC',    renewal: '2026-11-30' },
    ],
  },
  // Single-company suppliers. Present so the addressable filter has something
  // to exclude — a savings figure that quietly counts unshared spend is wrong.
  {
    canonical: 'Halden Specialist Tooling',
    category: 'Professional services',
    portfolioSpend: 0.42,
    contracts: [{ company: 'forgetech', ledgerName: 'Halden Specialist Tooling Ltd', renewal: '2027-05-31' }],
  },
  {
    canonical: 'Coastal Clinical Supplies',
    category: 'Professional services',
    portfolioSpend: 0.31,
    contracts: [{ company: 'lumen', ledgerName: 'Coastal Clinical Supplies FZ', renewal: '2027-04-30' }],
  },
];

const LEGAL_SUFFIXES = new Set([
  'ltd', 'limited', 'llp', 'plc', 'inc', 'llc', 'pte', 'pty', 'gmbh', 'bv', 'sa',
  'fz', 'fze', 'fzllc', 'fzco', 'dmcc', 'co', 'corp', 'holdings', 'group',
]);

const REGION_TOKENS = new Set([
  'singapore', 'sg', 'apac', 'asia', 'me', 'uk', 'emea', 'middle', 'east', 'uae',
]);

/**
 * Reduce a ledger name to an anchor and a qualifier.
 *
 * Deliberately boring: lowercase, strip punctuation, drop legal suffixes and
 * region tokens. The first meaningful word is the anchor (the brand); the
 * second is the qualifier (what they sell).
 */
export function normaliseVendorName(name) {
  const tokens = name
    .toLowerCase()
    .replace(/[^a-z0-9&\s]/g, ' ')
    .replace(/\band\b/g, '&')
    .split(/\s+/)
    .filter(Boolean)
    .filter((t) => !LEGAL_SUFFIXES.has(t) && !REGION_TOKENS.has(t));

  return { anchor: tokens[0] ?? '', qualifier: tokens[1] ?? '', key: tokens.slice(0, 2).join(' ') };
}

/**
 * How confidently two ledger names are the same supplier.
 *
 * Real ledgers defeat pure string matching. `Atlas Collab Suite` and
 * `Atlas Collaboration Suite` are the same vendor abbreviated; `Talentbridge
 * Search & Selection` and `Talentbridge Recruitment Ltd` are the same vendor
 * trading under two names, and no string operation can know that.
 *
 * So the resolver grades rather than guesses. Exact and prefix matches merge
 * automatically; anything weaker goes to a review queue with the evidence
 * attached. Silently merging the third case would inflate a savings number,
 * and silently splitting it would hide one — a visible queue is the only
 * honest option, and it is also the one a finance director trusts.
 */
export function matchQuality(a, b) {
  const x = normaliseVendorName(a);
  const y = normaliseVendorName(b);
  if (x.anchor !== y.anchor) return 'different';
  if (x.qualifier === y.qualifier) return 'exact';
  const short = x.qualifier.length <= y.qualifier.length ? x.qualifier : y.qualifier;
  const long = short === x.qualifier ? y.qualifier : x.qualifier;
  if (short.length >= 4 && long.startsWith(short)) return 'prefix';
  return 'review';
}

/** Split a vendor's portfolio spend across its contracts by company size. */
function allocateSpend(vendor) {
  const rng = rngFor(`vendor:${vendor.canonical}`);
  const weights = vendor.contracts.map((c) => {
    const company = getCompany(c.company);
    const revenue = last(company.series).revenue;
    return revenue * between(rng, 0.7, 1.4);
  });
  const total = weights.reduce((t, w) => t + w, 0);

  return vendor.contracts.map((c, i) => {
    const company = getCompany(c.company);
    const spend = (weights[i] / total) * vendor.portfolioSpend;
    const headcount = last(company.series).headcount;
    return {
      ...c,
      companyName: company.name,
      annualSpend: Math.round(spend * 1000) / 1000,
      headcount,
      unitCost: Math.round((spend * 1_000_000) / headcount),
      normalisedTo: normaliseVendorName(c.ledgerName).key,
      source: SOURCES.financials.system,
      refreshedAt: SOURCES.financials.refreshedAt,
    };
  });
}

export function buildVendorMatrix() {
  return VENDORS.map((v) => {
    const contracts = allocateSpend(v);
    const spends = contracts.map((c) => c.annualSpend);
    const units = contracts.map((c) => c.unitCost);

    // Grade every variant against the most common spelling.
    const counts = new Map();
    for (const c of contracts) counts.set(c.normalisedTo, (counts.get(c.normalisedTo) ?? 0) + 1);
    const reference = [...counts.entries()].sort((a, b) => b[1] - a[1])[0][0];
    const referenceName = contracts.find((c) => c.normalisedTo === reference).ledgerName;

    const grades = contracts.map((c) => ({
      company: c.company,
      companyName: c.companyName,
      ledgerName: c.ledgerName,
      annualSpend: c.annualSpend,
      quality: matchQuality(referenceName, c.ledgerName),
    }));
    const needsReview = grades.filter((g) => g.quality === 'review' || g.quality === 'different');

    return {
      canonical: v.canonical,
      category: v.category,
      companies: contracts.length,
      totalSpend: Math.round(contracts.reduce((t, c) => t + c.annualSpend, 0) * 1000) / 1000,
      confirmedSpend: grades.filter((g) => g.quality !== 'review' && g.quality !== 'different')
        .reduce((t, g) => t + g.annualSpend, 0),
      pendingSpend: needsReview.reduce((t, g) => t + g.annualSpend, 0),
      contracts,
      ledgerVariants: [...new Set(contracts.map((c) => c.ledgerName))],
      matchedOnKey: reference,
      matchGrades: grades,
      autoMatched: contracts.length - needsReview.length,
      needsReview,
      spendRange: { min: Math.min(...spends), max: Math.max(...spends) },
      unitCostRange: { min: Math.min(...units), max: Math.max(...units) },
      unitBasis: PARAMS.unitBasis[v.category] ?? null,
      priceDispersion: Math.min(...units) === 0 ? 0 : Math.max(...units) / Math.min(...units) - 1,
      earliestRenewal: contracts.map((c) => c.renewal).sort()[0],
      addressable: contracts.length >= PARAMS.minCompaniesForAction,
    };
  });
}

export function buildScenario5() {
  const portfolio = getPortfolio();
  const vendors = buildVendorMatrix();

  const totalSpend = vendors.reduce((t, v) => t + v.totalSpend, 0);
  const addressable = vendors.filter((v) => v.addressable);
  const addressableSpend = addressable.reduce((t, v) => t + v.totalSpend, 0);

  // Spend whose supplier identity is only a candidate match is held out of the
  // headline number until a human confirms it. Counting it would be the easy
  // way to a bigger figure and the fast way to lose the room.
  const confirmedSpend = addressable.reduce((t, v) => t + v.confirmedSpend, 0);
  const pendingSpend = addressable.reduce((t, v) => t + v.pendingSpend, 0);
  const reviewQueue = addressable.flatMap((v) =>
    v.needsReview.map((g) => ({
      supplier: v.canonical,
      category: v.category,
      company: g.companyName,
      ledgerName: g.ledgerName,
      annualSpend: g.annualSpend,
      matchedAgainst: v.matchedOnKey,
      reason: 'Same brand token, different trading name — confirm this is one supplier',
    })),
  );

  const byCategory = Object.keys(CATEGORIES)
    .map((category) => {
      const inCategory = addressable.filter((v) => v.category === category);
      if (inCategory.length === 0) return null;
      const spend = inCategory.reduce((t, v) => t + v.confirmedSpend, 0);
      const pending = inCategory.reduce((t, v) => t + v.pendingSpend, 0);
      const companies = new Set(inCategory.flatMap((v) => v.contracts.map((c) => c.company)));
      const { rate, basis } = CATEGORIES[category];
      return {
        category,
        spend,
        pendingSpend: pending,
        companies: companies.size,
        vendors: inCategory.length,
        rate,
        basis,
        saving: spend * rate,
        savingIfConfirmed: pending * rate,
        earliestRenewal: inCategory.map((v) => v.earliestRenewal).sort()[0],
        maxPriceDispersion: Math.max(...inCategory.map((v) => v.priceDispersion)),
      };
    })
    .filter(Boolean)
    .sort((a, b) => b.saving - a.saving);

  const expected = byCategory.reduce((t, c) => t + c.saving, 0);
  const additionalIfConfirmed = byCategory.reduce((t, c) => t + c.savingIfConfirmed, 0);
  const low = expected * (1 - PARAMS.rangeSensitivity);
  const high = expected * (1 + PARAMS.rangeSensitivity);

  // Contracts renewing inside twelve months are the practical window — a
  // consolidation recommendation that ignores contract timing is not actionable.
  const renewalWindow = addressable
    .flatMap((v) => v.contracts.map((c) => ({ vendor: v.canonical, category: v.category, ...c })))
    .filter((c) => c.renewal <= '2027-08-31')
    .sort((a, b) => a.renewal.localeCompare(b.renewal));

  const top = byCategory[0];

  const insight = makeInsight({
    id: 'portfolio-procurement-2026q3',
    type: 'opportunity',
    companyId: 'portfolio',
    companyName: 'Portfolio-wide',
    raisedOn: AS_OF,
    headline: `Vendor consolidation worth ${formatMoney(low, 'USD')}–${formatMoney(high, 'USD')} a year`,
    whatHappened:
      `${addressable.length} suppliers are engaged independently by three or more portfolio companies, ` +
      `under ${addressable.reduce((t, v) => t + v.companies, 0)} separate contracts carrying ` +
      `${addressable.reduce((t, v) => t + v.ledgerVariants.length, 0)} different ledger names. ` +
      `Combined addressable spend is ${formatMoney(addressableSpend, 'USD')} of ${formatMoney(totalSpend, 'USD')} total.`,
    whyItMatters:
      `No individual company can see this. Each is negotiating alone at its own volume, and unit prices ` +
      `for the same service differ by up to ${formatPct(Math.max(...addressable.map((v) => v.priceDispersion)))} across the portfolio. ` +
      `${renewalWindow.length} of those contracts renew within twelve months, which is the window in which ` +
      `consolidation is practical rather than theoretical.`,
    evidence: [
      {
        label: 'Addressable spend',
        value: `${formatMoney(addressableSpend, 'USD')} across ${addressable.length} shared suppliers`,
        source: SOURCES.financials.system,
        refreshedAt: SOURCES.financials.refreshedAt,
        detail: {
          threshold: `${PARAMS.minCompaniesForAction}+ companies`,
          excluded: vendors.filter((v) => !v.addressable).map((v) => ({ vendor: v.canonical, spend: v.totalSpend })),
        },
      },
      {
        label: 'Vendor name normalisation',
        value:
          `${addressable.reduce((t, v) => t + v.autoMatched, 0)} ledger names resolved automatically to ` +
          `${addressable.length} suppliers; ${reviewQueue.length} held for confirmation`,
        source: 'Alba calculation',
        refreshedAt: AS_OF,
        detail: addressable.map((v) => ({
          supplier: v.canonical, key: v.matchedOnKey, grades: v.matchGrades,
        })),
      },
      {
        label: 'Spend held pending review',
        value:
          reviewQueue.length === 0
            ? 'None'
            : `${formatMoney(pendingSpend, 'USD')} across ${reviewQueue.length} contract${reviewQueue.length === 1 ? '' : 's'} — excluded from the figure above, ` +
              `worth a further ${formatMoney(additionalIfConfirmed, 'USD')} if confirmed`,
        source: 'Alba calculation',
        refreshedAt: AS_OF,
        detail: reviewQueue,
      },
      {
        label: 'Largest single category',
        value: `${top.category} — ${formatMoney(top.spend, 'USD')} across ${top.companies} companies`,
        source: SOURCES.financials.system,
        refreshedAt: SOURCES.financials.refreshedAt,
        detail: top,
      },
      {
        label: 'Price dispersion on identical services',
        value: addressable
          .filter((v) => v.unitBasis)
          .map((v) => `${v.canonical} ${formatPct(v.priceDispersion, 0)} (${v.unitBasis})`)
          .join('; '),
        source: 'Alba calculation',
        refreshedAt: AS_OF,
        detail: addressable.filter((v) => v.unitBasis).map((v) => ({ vendor: v.canonical, unitCostRange: v.unitCostRange })),
      },
      {
        label: 'Contracts renewing within twelve months',
        value: `${renewalWindow.length} contracts, earliest ${renewalWindow[0].renewal}`,
        source: SOURCES.financials.system,
        refreshedAt: SOURCES.financials.refreshedAt,
        detail: renewalWindow.slice(0, 12),
      },
    ],
    impact: {
      measure: 'Annual cost saving across the portfolio',
      value: expected,
      currency: 'USD',
      horizon: 'Annualised, from first consolidated renewal',
      direction: 'upside',
    },
    confidence: CONFIDENCE.MEDIUM,
    methodology:
      'Ledger names are reduced to a comparison key by lowercasing, stripping punctuation, legal suffixes ' +
      'and region tokens. Names sharing a brand token merge automatically when the remaining word matches ' +
      'exactly or as a prefix; anything weaker is held in a review queue and excluded from the figure until ' +
      `confirmed. Spend is aggregated by resolved supplier and category. Only categories with ` +
      `${PARAMS.minCompaniesForAction} or more participating companies are treated as addressable. A stated ` +
      'consolidation rate is applied per category — each rate is a named assumption, not a model output, and ' +
      'should be replaced with negotiated terms as they become known.',
    actions: byCategory.slice(0, 3).map((c, i) => ({
      action: `Run a portfolio sourcing process for ${c.category} across ${c.companies} companies`,
      owner: i === 0 ? 'Operating Partner' : 'Portfolio Finance Director',
      due: c.earliestRenewal,
      rationale:
        `${formatMoney(c.saving, 'USD')} at a ${formatPct(c.rate, 0)} consolidation rate; ` +
        `first contract renews ${c.earliestRenewal}.`,
    })),
    drillDown: { vendors, byCategory, renewalWindow, portfolioCompanies: portfolio.length },
  });

  return {
    vendors,
    addressable,
    byCategory,
    renewalWindow,
    reviewQueue,
    totals: {
      totalSpend, addressableSpend, confirmedSpend, pendingSpend,
      expected, additionalIfConfirmed, low, high,
    },
    insight,
  };
}

/** Portfolio Procurement Opportunity Report payload. */
export function buildProcurementReport(scenario) {
  const { byCategory, addressable, renewalWindow, totals, insight } = scenario;
  return {
    kind: 'Portfolio Procurement Opportunity Report',
    company: 'Portfolio-wide',
    fund: 'Alba Growth I',
    preparedAt: insight.raisedOn,
    opportunity:
      `${addressable.length} suppliers are engaged independently across three or more portfolio companies. ` +
      `Consolidating them is estimated to save ${formatMoney(totals.low, 'USD')} to ${formatMoney(totals.high, 'USD')} a year ` +
      `on ${formatMoney(totals.addressableSpend, 'USD')} of addressable spend.`,
    estimatedValue: {
      expected: totals.expected,
      low: totals.low,
      high: totals.high,
      gross: totals.addressableSpend,
      currency: 'USD',
    },
    spendByCategory: byCategory,
    sharedVendors: addressable.map((v) => ({
      supplier: v.canonical,
      category: v.category,
      companies: v.companies,
      totalSpend: v.totalSpend,
      ledgerVariants: v.ledgerVariants.length,
      priceDispersion: v.priceDispersion,
      earliestRenewal: v.earliestRenewal,
    })),
    renewalTimetable: renewalWindow,
    supportingEvidence: insight.evidence,
    recommendedActions: insight.actions,
    sourceData: insight.evidence.map((e) => ({
      metric: e.label, value: e.value, source: e.source, asOf: e.refreshedAt,
    })),
    methodology: insight.methodology,
  };
}
