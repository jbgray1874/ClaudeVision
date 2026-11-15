"""Bounded TTI batches and deliberate reruns; no workbook or CAD writes here.

Uses the SAME tti_incremental.Store as changes dispatch. The injected submit
adapter must enforce the capabilities below. The old row-number-only adapter
does not satisfy this contract. Pricing is disabled unless explicitly enabled.
"""
from __future__ import annotations
import copy
import json
import uuid
from tti_incremental import ReviewRequired, blockers, COST_KEPT, digest, snapshot_digest, signature, validate_rows

CAPABILITIES = frozenset({'stable_id_writeback', 'locked_writer', 'pack_input_pinning',
                          'durable_idempotent_submit', 'row_isolation', 'versioned_outputs',
                          'per_row_persistence'})
UNSETTLED = {'queued', 'running', 'reserved', 'submitted', 'unknown', 'failed',
             'completed_pending_write', 'outcome not known', 'not queued'}


def whole(value, name, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ReviewRequired(f'{name} must be a whole number from {minimum} to {maximum}')
    return value


def control_digest(rows):
    # The shared snapshot deliberately omits run IDs; the batch must notice a
    # newly reconciled run even if its costs and estimating inputs are unchanged.
    return digest({'snapshot': snapshot_digest(rows),
                   'runs': {k: r.get('run_id') for k, r in validate_rows(rows).items()}})


class BatchControls:
    def __init__(self, store, *, snapshot, submit, enabled=lambda: False,
                 capabilities=(), busy=lambda: None, reconcile=lambda tracker: None,
                 held_drawings=('12748-01-GA', '12754-01-GA')):
        self.store, self.snapshot, self.submit = store, snapshot, submit
        self.enabled, self.busy, self.reconcile = enabled, busy, reconcile
        self.capabilities = frozenset(capabilities)
        self.held_drawings = {x.upper() for x in held_drawings}
        with store.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS tti_batch_review('
                       'tracker TEXT PRIMARY KEY, plan_id TEXT NOT NULL, notes TEXT, reviewed_at REAL)')

    def _base(self, tracker):
        with self.store.connect() as db:
            r = db.execute('SELECT rows_json FROM baseline WHERE tracker=?', (tracker,)).fetchone()
        if not r:
            raise ReviewRequired('No reconciled baseline. Do not infer that all rows are new.')
        return validate_rows(json.loads(r[0]))

    def _snapshot(self, tracker):
        snap = self.snapshot(tracker)
        if not snap.get('row_id_column') or snap.get('rows_without_id'):
            raise ReviewRequired('Permanent AI Row IDs are required. Do not use row numbers as identity.')
        rows = list(validate_rows(snap['rows']).values())
        seen = set()
        for r in rows:
            n = whole(r.get('row'), 'Sheet row', 1, 1048576)
            if n in seen:
                raise ReviewRequired('Duplicate physical sheet row')
            seen.add(n)
        return sorted(rows, key=lambda r: r['row'])

    def _catalogue(self, tracker, rows, base=None):
        base = self._base(tracker) if base is None else base
        out = []
        for row in rows:
            old = base.get(row['row_id'], {})
            histories = {row.get('history'), old.get('history')} - {None, ''}
            hard = [r for r in blockers(row) if r != COST_KEPT]
            if str(row.get('drawing') or '').upper() in self.held_drawings:
                hard.append('Explicit drawing hold: requires estimating clearance')
            run_id = row.get('run_id') or old.get('run_id')
            if row.get('run_id') and old.get('run_id') and row['run_id'] != old['run_id']:
                hard.append('Current and baseline run IDs differ; reconcile history')
            if histories & UNSETTLED:
                hard.append('Previous attempt needs completion/reconciliation; do not resubmit')
            unknown = histories - UNSETTLED - {'completed', 'not_submitted'}
            if unknown:
                hard.append('Unrecognised history state; reconcile before pricing')
            completed = 'completed' in histories
            has_cost = row.get('cost') not in (None, '')
            if completed and not run_id:
                hard.append('Completed history has no run ID')
            if run_id and not completed:
                hard.append('Run ID exists without reconciled completion')
            # An existing manual cost is never implicitly overwritten by Next N.
            reason = hard or (['Completed: select explicitly under Rerun'] if completed else
                              ['Existing AI cost: review its provenance'] if has_cost else [])
            out.append(dict(row_id=row['row_id'], row=row['row'], drawing=row.get('drawing'),
                            quantity=row.get('quantity'), cost=row.get('cost'), run_id=run_id,
                            state='held' if hard else 'completed' if completed else 'has_cost' if has_cost else 'ready',
                            reasons=reason, next_eligible=not hard and not completed and not has_cost,
                            rerun_allowed=not hard and completed and bool(run_id),
                            inputs_changed=bool(old and signature(old) != signature(row))))
        return out

    def _gate(self, tracker, db=None):
        if db is None:
            with self.store.connect() as conn:
                return self._gate(tracker, conn)
        r = db.execute('SELECT * FROM tti_batch_review WHERE tracker=? AND reviewed_at IS NULL',
                       (tracker,)).fetchone()
        return dict(r) if r else None

    def browse(self, tracker):
        last = self.reconcile(tracker)
        rows = self._snapshot(tracker)
        base = self._base(tracker)
        items = self._catalogue(tracker, rows, base)
        missing = sorted(CAPABILITIES - self.capabilities)
        gate = self._gate(tracker)
        return dict(rows=items, at_once=2, suggested_start=next((x['row'] for x in items if x['next_eligible']), None),
                    review_gate=gate, active=self.store.active_plan(tracker), last_batch=last,
                    enabled=bool(self.enabled()) and not missing, missing_capabilities=missing)

    def preview(self, tracker, *, mode='next', count=5, start_row=1, row_ids=(), reason=''):
        if mode not in {'next', 'rerun'}:
            raise ReviewRequired('Choose next or rerun')
        whole(count, 'Jobs in batch', 1, 50)
        whole(start_row, 'Start row', 1, 1048576)
        self.reconcile(tracker)
        if self.store.active_plan(tracker) or self.busy():
            raise ReviewRequired('A batch is active or uncertain. Reconcile it before another preview.')
        if self._gate(tracker):
            raise ReviewRequired('Review the previous batch before selecting another batch.')
        rows = self._snapshot(tracker)
        base = self._base(tracker)
        items = self._catalogue(tracker, rows, base)
        missing = sorted(CAPABILITIES - self.capabilities)
        reason = str(reason or '').strip()
        if mode == 'next':
            if row_ids:
                raise ReviewRequired('Next batch does not accept explicit rerun IDs')
            chosen = [x for x in items if x['row'] >= start_row and x['next_eligible']][:count]
        else:
            if not isinstance(row_ids, (list, tuple)) or not row_ids:
                raise ReviewRequired('Select completed rows to rerun')
            wanted = [str(x).lower() for x in row_ids]
            if len(wanted) > 50 or len(set(wanted)) != len(wanted):
                raise ReviewRequired('Select at most 50 distinct rows')
            if not reason:
                raise ReviewRequired('A reason is required for a deliberate rerun')
            available = {x['row_id']: x for x in items if x['rerun_allowed']}
            if set(wanted) - set(available):
                raise ReviewRequired('A selected row is held, unfinished, unknown or not previously completed')
            chosen = [x for x in items if x['row_id'] in wanted]
        if not chosen:
            raise ReviewRequired('No eligible rows in this selection. No fallback to the whole sheet.')
        selected = [x['row_id'] for x in chosen]
        plan = dict(plan_id=str(uuid.uuid4()), tracker=tracker, created=self.store.clock(),
                    snapshot=control_digest(rows), baseline=digest(base), rows=copy.deepcopy(rows), at_once=2,
                    selected=selected, mode=mode, reason=reason, count=count, start_row=start_row,
                    control='tti_batch_controls.v1',
                    decisions=[dict(x, eligible=x['row_id'] in selected) for x in items])
        with self.store.connect() as db:
            db.execute('INSERT INTO plans VALUES(?,?,?,?,?,?)',
                       (plan['plan_id'], tracker, plan['created'], json.dumps(plan), 'preview', None))
        # Expose no file paths, raw pack contents, or credentials to the browser.
        return dict(plan_id=plan['plan_id'], mode=mode, reason=reason, selected=chosen,
                    skipped=[x for x in items if x['row'] >= start_row and x['row_id'] not in selected],
                    at_once=2, runnable=bool(self.enabled()) and not missing, missing_capabilities=missing,
                    message='This exact selection only. Each result is saved as it completes; review before the next batch.')

    def run(self, tracker, plan_id, *, confirm_replace=False):
        if not self.enabled() or CAPABILITIES - self.capabilities:
            raise ReviewRequired('Pricing disabled until stable-ID writeback, pinned packs and submission safeguards are wired and proved')
        if self.busy():
            raise ReviewRequired('A command-line or portal batch is already active')
        current = self._snapshot(tracker)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            rec = db.execute('SELECT * FROM plans WHERE id=?', (plan_id,)).fetchone()
            if not rec or rec['tracker'] != tracker or rec['status'] != 'preview':
                raise ReviewRequired('Unknown, cross-tracker or consumed preview; reconcile instead of retrying')
            plan = json.loads(rec['payload'])
            if plan.get('control') != 'tti_batch_controls.v1':
                raise ReviewRequired('Not a batch-controls preview')
            age = self.store.clock() - plan['created']
            if not 0 <= age <= 900:
                raise ReviewRequired('Preview expired; preview again')
            if control_digest(current) != plan['snapshot']:
                raise ReviewRequired('Tracker, cost or drawing pack changed; preview again')
            baseline = db.execute('SELECT rows_json FROM baseline WHERE tracker=?', (tracker,)).fetchone()
            if not baseline or digest(validate_rows(json.loads(baseline[0]))) != plan['baseline']:
                raise ReviewRequired('Run history changed; preview again')
            if plan['mode'] == 'rerun' and confirm_replace is not True:
                raise ReviewRequired('Explicit consent to replace the selected rows\' previous AI costs is required')
            if self._gate(tracker, db):
                raise ReviewRequired('Previous batch still needs review')
            if db.execute('SELECT 1 FROM active WHERE tracker=?', (tracker,)).fetchone():
                raise ReviewRequired('Another batch owns this tracker')
            by_id = validate_rows(current)
            # Stable IDs pin the selected set. Sorting after preview cannot substitute a row.
            selected = sorted((by_id[k] for k in plan['selected']), key=lambda r: r['row'])
            plan['rows'] = copy.deepcopy(current)
            positions = {r['row_id']: r['row'] for r in current}
            for d in plan['decisions']:
                d['row'] = positions[d['row_id']]
            db.execute('INSERT INTO active VALUES(?,?)', (tracker, plan_id))
            db.execute("UPDATE plans SET status='reserved',payload=? WHERE id=?", (json.dumps(plan), plan_id))
            db.execute('INSERT OR REPLACE INTO tti_batch_review VALUES(?,?,NULL,NULL)', (tracker, plan_id))
        try:
            receipt = self.submit(tracker, selected, request_id=plan_id, at_once=2,
                                  replace_costs=plan['mode'] == 'rerun', rerun_reason=plan['reason'],
                                  expected_inputs={r['row_id']: dict(signature=signature(r), pack_key=r['pack_key'],
                                                                   cost_before=r.get('cost')) for r in selected})
            if not isinstance(receipt, dict) or not receipt.get('task_id'):
                raise ReviewRequired('No durable task receipt')
        except Exception:
            with self.store.connect() as db:
                db.execute("UPDATE plans SET status='unknown' WHERE id=?", (plan_id,))
            raise ReviewRequired('Submission outcome unknown. Reservation retained; reconcile, never automatically resend.') from None
        with self.store.connect() as db:
            db.execute("UPDATE plans SET status='submitted',receipt=? WHERE id=?", (json.dumps(receipt), plan_id))
        return receipt

    def review(self, tracker, plan_id, *, outputs_checked=False, costs_reviewed=False, notes=''):
        if outputs_checked is not True or costs_reviewed is not True or not str(notes).strip():
            raise ReviewRequired('Confirm filing and cost review, and record unresolved items or corrections')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            gate = self._gate(tracker, db)
            rec = db.execute('SELECT * FROM plans WHERE id=? AND tracker=?', (plan_id, tracker)).fetchone()
            if not gate or gate['plan_id'] != plan_id or not rec or rec['status'] != 'finished':
                raise ReviewRequired('Batch must be terminal and reconciled before review acknowledgement')
            outcomes = json.loads(rec['receipt'])
            if any(x.get('state') == 'completed_pending_write' for x in outcomes.values()):
                raise ReviewRequired('Write-back pending; recover before acknowledging completion')
            plan = json.loads(rec['payload'])
            plan['batch_review'] = dict(notes=str(notes).strip(), reviewed_at=self.store.clock(),
                                        outputs_checked=True, costs_reviewed=True)
            db.execute('UPDATE plans SET payload=? WHERE id=?', (json.dumps(plan), plan_id))
            db.execute('UPDATE tti_batch_review SET notes=?,reviewed_at=? WHERE tracker=? AND plan_id=?',
                       (str(notes).strip(), self.store.clock(), tracker, plan_id))
        return dict(reviewed=True, plan_id=plan_id, note='Review recorded. This does not send estimates or approve client quotations.')
