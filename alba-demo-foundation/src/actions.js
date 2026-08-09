/**
 * Alert and action tracker.
 *
 * The demo specification is explicit that insight must connect to execution
 * and then show whether the intervention worked. An insight with no owner and
 * no subsequent metric movement is a dashboard, which is the thing Alba is
 * meant to replace.
 */

export const STATUS = ['Open', 'In progress', 'Blocked', 'Complete', 'Closed — no action'];

let counter = 0;

export function trackAction({ insight, action, owner, due, rationale, status = 'Open', watchMetric = null }) {
  counter += 1;
  return {
    id: `act-${String(counter).padStart(3, '0')}`,
    insightId: insight.id,
    companyId: insight.companyId,
    companyName: insight.companyName,
    severity: insight.type === 'risk' ? 'Risk' : 'Opportunity',
    raisedOn: insight.raisedOn,
    action,
    owner,
    due,
    rationale,
    status,
    watchMetric,
    history: [{ on: insight.raisedOn, status, note: 'Raised by Alba' }],
  };
}

/** Build the tracker rows implied by an insight's recommended actions. */
export function trackerFor(insight, watchMetric = null) {
  return insight.actions.map((a) =>
    trackAction({ insight, watchMetric, ...a }),
  );
}

export function advance(row, { on, status, note, metricValue = null }) {
  if (!STATUS.includes(status)) throw new Error(`Unknown status: ${status}`);
  return {
    ...row,
    status,
    history: [...row.history, { on, status, note, metricValue }],
  };
}

/** Closed-loop view: did the watched metric move after the action was taken? */
export function outcome(row) {
  const readings = row.history.filter((h) => h.metricValue != null);
  if (readings.length < 2) {
    return { measurable: false, note: 'Not enough readings to judge the intervention yet.' };
  }
  const first = readings[0];
  const latest = readings[readings.length - 1];
  const change = latest.metricValue - first.metricValue;
  return {
    measurable: true,
    metric: row.watchMetric,
    from: first,
    to: latest,
    change,
    note:
      change === 0
        ? 'No movement in the watched metric since the action was agreed.'
        : `${row.watchMetric} moved by ${change > 0 ? '+' : ''}${change.toFixed(2)} since the action was agreed.`,
  };
}

export function resetIds() {
  counter = 0;
}
