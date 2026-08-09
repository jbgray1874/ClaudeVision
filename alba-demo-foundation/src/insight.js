/**
 * The standard Alba insight card.
 *
 * The demo specification requires every risk and opportunity to use the same
 * structure so a user learns the shape once. It also requires that an insight
 * never asserts a number without an inspectable source — so `evidence` and
 * `methodology` are mandatory, and `makeInsight` refuses to build a card
 * without them.
 */

export const CONFIDENCE = {
  HIGH: { label: 'High', note: 'Multiple independent indicators agree and source data is current.' },
  MEDIUM: { label: 'Medium', note: 'Indicators agree but one input is estimated or lagging.' },
  LOW: { label: 'Low', note: 'Directionally supported; treat as a prompt to investigate.' },
};

/**
 * @param {object} spec
 * @param {'risk'|'opportunity'} spec.type
 * @param {Array<{label:string,value:string,source:string,refreshedAt:string,detail?:object}>} spec.evidence
 */
export function makeInsight(spec) {
  const required = [
    'id', 'type', 'companyId', 'companyName', 'headline',
    'whatHappened', 'whyItMatters', 'evidence', 'impact', 'confidence', 'methodology',
  ];
  for (const key of required) {
    if (spec[key] == null) throw new Error(`Insight ${spec.id ?? '(unnamed)'} is missing "${key}"`);
  }
  if (!Array.isArray(spec.evidence) || spec.evidence.length === 0) {
    throw new Error(`Insight ${spec.id} must carry at least one evidence row`);
  }
  for (const row of spec.evidence) {
    if (!row.source || !row.refreshedAt) {
      throw new Error(`Insight ${spec.id}: evidence "${row.label}" has no source or refresh date`);
    }
  }

  return {
    id: spec.id,
    type: spec.type,
    companyId: spec.companyId,
    companyName: spec.companyName,
    headline: spec.headline,
    whatHappened: spec.whatHappened,
    whyItMatters: spec.whyItMatters,
    evidence: spec.evidence,
    impact: spec.impact, // { measure, value, currency, horizon, direction }
    confidence: spec.confidence,
    methodology: spec.methodology,
    actions: spec.actions ?? [],
    raisedOn: spec.raisedOn,
    drillDown: spec.drillDown ?? null,
  };
}

/**
 * Compact one-line form for the command centre alert list.
 *
 * `impact.unit` defaults to money. A runway insight is measured in months and
 * a margin insight can be measured in points — rendering either as currency
 * produces a number that is confidently wrong, which is the failure mode this
 * whole package exists to avoid.
 */
export function summarise(insight) {
  const { value, currency, unit = 'money', horizon, direction } = insight.impact;
  const sign = direction === 'downside' ? '−' : '+';
  let rendered;
  switch (unit) {
    case 'months':
      // The headline already carries the figure; repeating it in the impact
      // parenthetical reads as two different numbers at a glance.
      return `${insight.companyName} — ${insight.headline}`;
    case 'points':
      rendered = `${Math.abs(value).toFixed(1)} points`;
      break;
    case 'percent':
      rendered = formatPct(Math.abs(value));
      break;
    default:
      rendered = formatMoney(Math.abs(value), currency);
  }
  return `${insight.companyName} — ${insight.headline} (${sign}${rendered}, ${horizon})`;
}

export function formatMoney(millions, currency = 'USD') {
  const symbol = { USD: '$', GBP: '£', EUR: '€', SGD: 'S$', AED: 'AED ' }[currency] ?? '';
  if (Math.abs(millions) >= 1) return `${symbol}${millions.toFixed(2)}m`;
  return `${symbol}${Math.round(millions * 1000)}k`;
}

export function formatPct(fraction, dp = 1) {
  return `${(fraction * 100).toFixed(dp)}%`;
}
