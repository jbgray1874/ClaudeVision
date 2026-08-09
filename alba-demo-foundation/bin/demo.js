#!/usr/bin/env node
/**
 * Walk the eight-minute demo on the command line.
 *
 * Purpose: rehearse the numbers before they are wired to screens, and prove
 * they reconcile. If the bridge does not add up here, it will not add up in
 * front of an investment committee.
 *
 *   node bin/demo.js            full walkthrough
 *   node bin/demo.js reports    also print both generated reports
 */

import { buildCommandCentre, buildScenario1, buildScenario4 } from '../src/index.js';
import { buildExceptionReport, buildGrowthOpportunityBrief, toMarkdown } from '../src/report.js';
import { trackerFor } from '../src/actions.js';
import { formatMoney, formatPct } from '../src/insight.js';

const showReports = process.argv.includes('reports');

function rule(title) {
  console.log(`\n${'─'.repeat(78)}\n${title}\n${'─'.repeat(78)}`);
}

function money(v, c) {
  return formatMoney(v, c);
}

// ── 0:00–1:00 · Portfolio Health Command Centre ─────────────────────────────
const cc = buildCommandCentre();
rule(`0:00  PORTFOLIO HEALTH COMMAND CENTRE — as of ${cc.asOf}`);
console.log(
  `${cc.rollup.companies} companies · average health ${cc.rollup.averageHealthScore} · ` +
  `RED ${cc.rollup.ragCounts.RED} / AMBER ${cc.rollup.ragCounts.AMBER} / GREEN ${cc.rollup.ragCounts.GREEN} · ` +
  `average runway ${cc.rollup.averageRunwayMonths.toFixed(1)} months across ${cc.rollup.cashConsumingCompanies} cash-consuming companies`,
);
console.log(`Quarter revenue ${cc.rollup.quarterRevenue.toFixed(2)}m against plan ${cc.rollup.quarterPlanRevenue.toFixed(2)}m (${formatPct(cc.rollup.quarterVariancePct)})\n`);

const COLS = [26, 18, 7, 13, 11, 9];
console.log(['Company', 'RAG', 'Score', 'QTD vs plan', 'Runway', 'Cash'].map((h, i) => h.padEnd(COLS[i])).join(''));
for (const r of cc.companies) {
  console.log(
    r.name.padEnd(COLS[0]) +
    (r.ragMoved ?? r.rag).padEnd(COLS[1]) +
    String(r.healthScore).padEnd(COLS[2]) +
    formatPct(r.variancePct).padEnd(COLS[3]) +
    (!r.cashGenerative ? `${r.runwayMonths.toFixed(1)}mo` : 'cash gen').padEnd(COLS[4]) +
    money(r.cash, r.currency),
  );
}

console.log('\nRisk alerts');
cc.riskAlerts.forEach((a) => console.log(`  ! ${a.line}`));
console.log('Opportunity alerts');
cc.opportunityAlerts.forEach((a) => console.log(`  + ${a.line}`));

// ── 1:00–3:00 · Scenario 1 ──────────────────────────────────────────────────
const s1 = buildScenario1();
const c1 = s1.company.currency;
rule(`1:00  ${s1.company.name.toUpperCase()} — REVENUE MISS BEFORE THE BOARD PACK`);
console.log(
  `Quarter to date ${money(s1.currentQuarter.revenue, c1)} against plan ` +
  `${money(s1.currentQuarter.planRevenue, c1)} — ${formatPct(s1.currentQuarter.variancePct)}` +
  (s1.currentQuarter.estimated ? `  (${s1.currentQuarter.estimationNote})` : ''),
);
console.log(
  `\n${s1.forecastQuarter.quarter} plan ${money(s1.forecastQuarter.planRevenue, c1)} · ` +
  `forecast ${money(s1.forecastQuarter.forecastRevenue, c1)} · ` +
  `gap ${money(s1.forecastQuarter.forecastGap, c1)} (${formatPct(s1.forecastQuarter.forecastGap / s1.forecastQuarter.planRevenue)} of plan)`,
);
console.log(
  `Plan requires ${money(s1.forecastQuarter.newRevenueRequired, c1)} of new revenue → ` +
  `bookings quota ${money(s1.forecastQuarter.bookingsQuota, c1)} · ` +
  `open pipeline ${money(s1.forecastQuarter.openPipelineAcv, c1)} (coverage 1.90x, was 3.20x)`,
);

rule('1:30  DRIVER BRIDGE');
for (const b of s1.bridge) {
  console.log(`  ${b.driver.padEnd(34)} ${money(b.value, c1).padStart(9)}   ${formatPct(b.value / s1.forecastQuarter.forecastGap).padStart(6)}`);
  console.log(`  ${' '.repeat(34)} ${b.workings}`);
}
console.log(`  ${'TOTAL FORECAST GAP'.padEnd(34)} ${money(s1.forecastQuarter.forecastGap, c1).padStart(9)}`);

const reconciles =
  Math.abs(
    s1.forecastQuarter.planRevenue -
      s1.bridge.reduce((t, b) => t + b.value, 0) -
      s1.forecastQuarter.forecastRevenue,
  ) < 1e-9;
console.log(`\n  Plan − drivers = forecast: ${reconciles ? 'reconciles' : 'DOES NOT RECONCILE'}`);

rule('1:45  EVIDENCE (every row opens to its source)');
for (const e of s1.insight.evidence) {
  console.log(`  ${e.label.padEnd(44)} ${e.value}`);
  console.log(`  ${' '.repeat(44)} ${e.source} · refreshed ${e.refreshedAt}`);
}

rule('3:00  RECOMMENDED ACTIONS');
const tracker1 = trackerFor(s1.insight, 'Pipeline coverage');
for (const a of tracker1) {
  console.log(`  [${a.id}] ${a.action}`);
  console.log(`         ${a.owner} · due ${a.due} · ${a.status}`);
}

// ── 4:30–7:15 · Scenario 4 ──────────────────────────────────────────────────
const s4 = buildScenario4();
const c4 = s4.company.currency;
rule(`4:30  ${s4.company.name.toUpperCase()} — CROSS-SELL EXPANSION OPPORTUNITY`);
console.log(
  `${s4.qualified.length} of ${s4.customers.length} customers qualify · ` +
  `gross ${money(s4.totals.gross, c4)} · expected ${money(s4.totals.expected, c4)} · ` +
  `range ${money(s4.totals.low, c4)}–${money(s4.totals.high, c4)}`,
);
console.log(`Current second-product penetration ${formatPct(s4.totals.currentPenetration)}\n`);

console.log(['Account', 'Segment', 'ARR', 'Score', 'p(conv)', 'Expected'].map((h, i) =>
  h.padEnd([26, 13, 10, 8, 9, 10][i])).join(''));
for (const c of s4.qualified.slice(0, 10)) {
  console.log(
    c.account.padEnd(26) +
    c.segment.padEnd(13) +
    money(c.arr, c4).padEnd(10) +
    String(c.score).padEnd(8) +
    formatPct(c.conversionProbability, 0).padEnd(9) +
    money(c.expectedValue, c4),
  );
}

rule('5:00  WHY THIS ACCOUNT? (top-scoring account, factor by factor)');
const top = s4.qualified[0];
console.log(`  ${top.account} — score ${top.score}/100`);
for (const f of top.breakdown) {
  console.log(`    ${f.factor.padEnd(16)} ${String(f.points).padStart(5)} of ${String(f.of).padStart(2)}   ${f.basis}`);
}

rule('6:30  COMMERCIAL ACTION LIST');
for (const a of trackerFor(s4.insight, 'Qualified cohort ARR')) {
  console.log(`  [${a.id}] ${a.action}`);
  console.log(`         ${a.owner} · due ${a.due} · ${a.rationale}`);
}

// ── Reports ─────────────────────────────────────────────────────────────────
const exception = buildExceptionReport(s1);
const brief = buildGrowthOpportunityBrief(s4);

rule('3:45 / 7:15  GENERATED REPORTS');
console.log(`  ${exception.kind} — ${exception.rootCauses.length} root causes, ${exception.sourceData.length} sourced metrics`);
console.log(`  ${brief.kind} — ${brief.prioritisedCustomers.length} prioritised accounts, ${brief.sourceData.length} sourced metrics`);

if (showReports) {
  console.log(`\n\n${toMarkdown(exception)}`);
  console.log(`\n\n${toMarkdown(brief)}`);
}

rule('CLOSING MESSAGE');
console.log(
  `Alba identified one potential miss (${money(s1.forecastQuarter.forecastGap, c1)}, ${s1.forecastQuarter.quarter}) before it\n` +
  `reached the board pack, and one value-creation opportunity (${money(s4.totals.low, c4)}–${money(s4.totals.high, c4)} ARR)\n` +
  `that conventional reporting did not surface. Both are explained, quantified and assigned.\n`,
);
