/**
 * Scenario 2 — cash runway, as an interactive engine.
 *
 * The demo specification lists "scenario calculations" on the must-work side of
 * the line: changing an assumption has to change the forecast immediately, and
 * the user has to see why. A screen with sliders that move a pre-baked chart
 * fails that test the first time someone drags one.
 *
 * The design decision that matters here is where the model is anchored. A
 * bottom-up build — headcount times salary, plus suppliers, plus debt service —
 * produces a weekly forecast whose implied burn does not match the burn the
 * company actually reports, and the portfolio table and the cash screen then
 * disagree in front of the customer.
 *
 * So the model is anchored to reported net burn and the *composition* is
 * derived from it: payroll is calculated from headcount, and supplier spend is
 * whatever is left once the model ties. Every lever then moves a baseline that
 * is true by construction.
 */

import { getCompany, SOURCES, AS_OF } from './portfolio.js';
import { runway, last } from './kpis.js';
import { formatMoney } from './insight.js';

export const ASSUMPTIONS = {
  companyId: 'meridian',
  weeks: 13,
  dsoDays: 62,
  averageSalary: 0.086,       // millions per employee per year, fully loaded
  payrollWeeksOfMonth: 4,     // payroll clears every fourth week
  debtServicePerQuarter: 0.09,
  minimumCash: 2.40,          // board-agreed floor that triggers a funding process
  plannedHires: 6,            // over the next quarter, at plan
  collectionsReleaseWeeks: 8, // a DSO improvement releases working capital over this period
};

/** The baseline, derived so that it reproduces the reported position exactly. */
export function cashBaseline() {
  const company = getCompany(ASSUMPTIONS.companyId);
  const latest = last(company.series);
  const reported = runway(company.series);

  const annualRevenue = latest.revenue * 12;
  const monthlyReceipts = annualRevenue / 12;

  // Total outflow is fixed by the identity: receipts less outflow is the burn
  // the company reports. Nothing here is free to drift away from that.
  const monthlyOutflow = monthlyReceipts + reported.avgMonthlyBurn;
  const monthlyPayroll = (latest.headcount * ASSUMPTIONS.averageSalary) / 12;
  const monthlyDebtService = ASSUMPTIONS.debtServicePerQuarter / 3;
  const monthlySuppliers = monthlyOutflow - monthlyPayroll - monthlyDebtService;

  return {
    company,
    latest,
    reported,
    annualRevenue,
    monthlyReceipts,
    monthlyOutflow,
    monthlyPayroll,
    monthlySuppliers,
    monthlyDebtService,
    monthlyBurn: reported.avgMonthlyBurn,
    openingCash: latest.cashClose,
    composition: {
      payrollShare: monthlyPayroll / monthlyOutflow,
      supplierShare: monthlySuppliers / monthlyOutflow,
      debtShare: monthlyDebtService / monthlyOutflow,
      note: 'Supplier spend is derived so that receipts less outflow equals reported net burn.',
    },
  };
}

/**
 * Recompute under a set of management levers.
 *
 * @param {object} levers
 * @param {number}  levers.collectionsDaysImprovement  days taken out of DSO
 * @param {boolean} levers.hiringPause                 freeze the planned hires
 * @param {number}  levers.discretionaryCutPct         proportion cut from supplier spend
 */
export function buildCashScenario(levers = {}) {
  const {
    collectionsDaysImprovement = 0,
    hiringPause = false,
    discretionaryCutPct = 0,
  } = levers;

  const base = cashBaseline();

  // A DSO improvement is a one-off release of working capital, not a permanent
  // uplift in receipts. Modelling it as recurring is the most common way a cash
  // plan overstates itself.
  const workingCapitalRelease = base.annualRevenue * (collectionsDaysImprovement / 365);

  const payrollSaving = hiringPause
    ? 0
    : -(ASSUMPTIONS.plannedHires * ASSUMPTIONS.averageSalary) / 12; // planned hires add cost
  const supplierSaving = base.monthlySuppliers * discretionaryCutPct;

  const monthlyPayroll = base.monthlyPayroll - payrollSaving;
  const monthlySuppliers = base.monthlySuppliers - supplierSaving;
  const monthlyBurn =
    monthlyPayroll + monthlySuppliers + base.monthlyDebtService - base.monthlyReceipts;

  // Weekly profile, for the thirteen-week view and the minimum-cash breach.
  const weeklyReceipts = base.monthlyReceipts * (12 / 52);
  const weeklySuppliers = monthlySuppliers * (12 / 52);
  const weeklyDebtService = base.monthlyDebtService * (12 / 52);
  const weeklyRelease =
    collectionsDaysImprovement > 0 ? workingCapitalRelease / ASSUMPTIONS.collectionsReleaseWeeks : 0;

  const weeks = [];
  let cash = base.openingCash;
  let breachWeek = null;

  // Round each line to the precision it is displayed at, then derive the
  // closing balance from those rounded lines. A cash statement whose columns
  // do not add up on screen is the fastest way to lose a finance director.
  for (let w = 1; w <= ASSUMPTIONS.weeks; w++) {
    const opening = round(cash);
    const receipts = round(
      weeklyReceipts + (w <= ASSUMPTIONS.collectionsReleaseWeeks ? weeklyRelease : 0),
    );
    const payroll = round(w % ASSUMPTIONS.payrollWeeksOfMonth === 0 ? monthlyPayroll : 0);
    const suppliers = round(weeklySuppliers);
    const debtService = round(weeklyDebtService);

    cash = round(opening + receipts - payroll - suppliers - debtService);
    if (breachWeek === null && cash < ASSUMPTIONS.minimumCash) breachWeek = w;

    weeks.push({
      week: w,
      opening,
      receipts,
      payroll,
      suppliers,
      debtService,
      closing: cash,
      belowMinimum: cash < ASSUMPTIONS.minimumCash,
    });
  }

  const effectiveCash = base.openingCash + workingCapitalRelease;
  const runwayMonths = monthlyBurn <= 0 ? Infinity : effectiveCash / monthlyBurn;

  return {
    levers: { collectionsDaysImprovement, hiringPause, discretionaryCutPct },
    openingCash: base.openingCash,
    workingCapitalRelease: round(workingCapitalRelease),
    monthlyBurn: round(monthlyBurn),
    runwayMonths: round(runwayMonths, 1),
    weeks,
    closingCash: round(cash),
    minimumCash: ASSUMPTIONS.minimumCash,
    breachWeek,
    breachNote:
      breachWeek === null
        ? `Holds above the ${formatMoney(ASSUMPTIONS.minimumCash, base.company.currency)} minimum through week ${ASSUMPTIONS.weeks}`
        : `Falls below the ${formatMoney(ASSUMPTIONS.minimumCash, base.company.currency)} minimum in week ${breachWeek}`,
    headcount: base.latest.headcount + (hiringPause ? 0 : ASSUMPTIONS.plannedHires),
    source: SOURCES.bank.system,
    refreshedAt: AS_OF,
  };
}

/** The management cases the specification asks to be shown side by side. */
export function buildManagementCases() {
  const base = cashBaseline();

  const cases = [
    { name: 'Current trajectory, including the 6 planned hires', levers: {} },
    { name: 'Collections plan (15 days of DSO)', levers: { collectionsDaysImprovement: 15 } },
    {
      name: 'Collections plus hiring pause',
      levers: { collectionsDaysImprovement: 15, hiringPause: true },
    },
    {
      name: 'Collections, hiring pause and 20% supplier cut',
      levers: { collectionsDaysImprovement: 15, hiringPause: true, discretionaryCutPct: 0.20 },
    },
  ].map((c) => ({ ...c, result: buildCashScenario(c.levers) }));

  const baseline = cases[0].result;

  return {
    company: base.company,
    baseline: base,
    reportedRunway: base.reported,
    cases,
    // The forward baseline is shorter than the reported trailing runway because
    // the hiring plan has not happened yet. Stating that explicitly is the
    // difference between a signal and an apparent contradiction between screens.
    forwardVsReported: {
      reportedMonths: round(base.reported.months, 1),
      forwardMonths: baseline.runwayMonths,
      differenceMonths: round(baseline.runwayMonths - base.reported.months, 1),
      note:
        `Reported runway of ${round(base.reported.months, 1)} months is calculated on trailing burn. ` +
        `Funding the ${ASSUMPTIONS.plannedHires} hires already in plan takes it to ${baseline.runwayMonths} months.`,
    },
    comparison: cases.map((c) => ({
      name: c.name,
      monthlyBurn: c.result.monthlyBurn,
      runwayMonths: c.result.runwayMonths,
      closingCash: c.result.closingCash,
      headroomAtHorizon: round(c.result.closingCash - ASSUMPTIONS.minimumCash, 3),
      breachWeek: c.result.breachWeek,
      improvementMonths: round(c.result.runwayMonths - baseline.runwayMonths, 1),
    })),
  };
}

function round(n, dp = 3) {
  const f = 10 ** dp;
  return Math.round(n * f) / f;
}
