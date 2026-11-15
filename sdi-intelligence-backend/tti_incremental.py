"""Incremental tracker decisions and durable dispatch reservations.

Brought in from the reviewed tti_incremental_changes_v1 package (15 Nov 2026), with three
additions for the page: unidentified(), Store.has_baseline() and Store.active_plan(). It lives in the service's own
folder because the service imports it and never imports the engine.

Standard library only: safe for the service to import, no estimator import.
Workbook IO, live pack resolution and the existing batch writer are injected.
This module never sends a job or edits a workbook by itself.
"""
from __future__ import annotations
import copy
import contextlib
import hashlib
import json
from pathlib import Path
import sqlite3
import time
import uuid

ELIGIBLE = {'new_row', 'drawing_added', 'pack_added'}
# CHANGED WORK RUNS ONLY WHEN A PERSON APPROVES IT (JG's standard, 15 Nov 2026: "Runs only
# approved new and changed rows"). A changed row is never eligible by itself; it is approvable,
# and dispatch takes it only when its Row ID is in the approved list.
APPROVABLE = {'changed_existing', 'changed_completed'}
COST_KEPT = 'Existing AI cost retained; replacement needs explicit review'
ACTIVE = {'reserved', 'submitted', 'unknown'}
INPUTS = ('drawing', 'quantity', 'description', 'previous_feedback', 'latest_feedback',
          'revision', 'pack_key', 'method', 'client')


class ReviewRequired(ValueError):
    pass


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def validate_rows(rows):
    found = {}
    for row in rows:
        key = str(row.get('row_id') or '').strip()
        try:
            if str(uuid.UUID(key)) != key.lower():
                raise ValueError()
        except (ValueError, AttributeError):
            raise ReviewRequired('Missing/invalid permanent AI Row ID; assign IDs before scanning')
        key = key.lower()
        if key in found:
            raise ReviewRequired('Duplicate AI Row ID: ' + key)
        found[key] = dict(row, row_id=key)
    return found


def plan_row_ids(rows, factory=lambda: str(uuid.uuid4())):
    """Metadata-only edit plan. Caller persists it with native Excel, then rereads.

    No positional fallback for estimating. Existing IDs are never replaced.
    Copied duplicate IDs need a person to identify the new physical row.
    """
    nonblank = [r for r in rows if str(r.get('row_id') or '').strip()]
    used = set(validate_rows(nonblank))
    edits = []
    seen_rows = set()
    for r in rows:
        n = r.get('row')
        if not isinstance(n, int) or isinstance(n, bool) or n < 1 or n in seen_rows:
            raise ReviewRequired('Invalid or duplicate physical row in ID migration')
        seen_rows.add(n)
        if str(r.get('row_id') or '').strip():
            continue
        new = str(factory()).lower()
        validate_rows([{'row_id': new}])
        if new in used:
            raise ReviewRequired('ID generator collision')
        used.add(new)
        edits.append({'row': n, 'row_id': new})
    return edits


def signature(row):
    return digest({k: row.get(k) for k in INPUTS})


def snapshot_digest(rows):
    # Sorting, insertion and formatting do not change identity. Current costs DO
    # participate, so an intervening human price edit invalidates a preview.
    mapped = validate_rows(rows)
    return digest({key: {k: value.get(k) for k in INPUTS +
                        ('cost', 'pack_state', 'pack_safe', 'holds', 'history')}
                   for key, value in sorted(mapped.items())})


def blockers(row):
    reasons = list(row.get('holds') or [])
    q = row.get('quantity')
    if isinstance(q, bool) or not isinstance(q, int) or q < 1:
        reasons.append('Positive whole quantity required')
    if not str(row.get('drawing') or '').strip():
        reasons.append('No drawing number')
    if row.get('pack_state') != 'ready' or row.get('pack_safe') is not True or not row.get('pack_key'):
        reasons.append('A current reviewed/resolved drawing pack is required')
    if row.get('cost') is not None and row.get('cost') != '':
        reasons.append(COST_KEPT)
    return reasons


def decisions(before, current):
    old, now = validate_rows(before), validate_rows(current)
    result = []
    for key, row in now.items():
        prev = old.get(key)
        history = row.get('history') or (prev or {}).get('history')
        reasons = blockers(row)
        changed = [k for k in INPUTS if prev and prev.get(k) != row.get(k)]
        if history in ('queued', 'running', 'reserved', 'unknown', 'failed'):
            kind = 'held_previous_attempt'
            reasons.append('Reconcile the existing attempt; never resubmit automatically')
        elif history in ('completed', 'completed_pending_write'):
            kind = 'changed_completed' if changed else 'unchanged_completed'
            reasons.append('Reuse/reconcile the saved result; changed completed work needs separate approval')
        elif reasons:
            kind = 'held'
        elif prev is None:
            kind = 'new_row'
        elif not prev.get('drawing') and row.get('drawing'):
            kind = 'drawing_added'
        elif prev.get('pack_state') == 'missing' and row.get('pack_state') == 'ready':
            kind = 'pack_added'
        elif changed:
            kind = 'changed_existing'
            reasons.append('Existing inputs changed; not part of new-work-only mode')
        else:
            kind = 'existing_unpriced'
            reasons.append('Existing baseline row; select through the reviewed initial batch, not as new work')
        # Approvable: a changed row with nothing else against it. The cost on a row this
        # process priced before is its own earlier answer, so it does not block the re-price a
        # person approves; a cost on a row with no completed run is somebody's, and does.
        hard = [b for b in blockers(row)
                if not (b == COST_KEPT and kind == 'changed_completed')]
        result.append({'row_id': key, 'row': row.get('row'), 'drawing': row.get('drawing'),
                       'quantity': row.get('quantity'), 'kind': kind,
                       'eligible': kind in ELIGIBLE, 'approvable': kind in APPROVABLE and not hard,
                       'changed': changed, 'reasons': reasons})
    for key, row in old.items():
        if key not in now:
            result.append({'row_id': key, 'row': row.get('row'), 'drawing': row.get('drawing'),
                           'quantity': row.get('quantity'), 'kind': 'removed', 'eligible': False,
                           'approvable': False, 'changed': [], 'reasons': ['History retained; no cancellation or deletion']})
    # Different physical rows may legitimately share a drawing, but the current
    # batch groups by drawing. Hold them until that grouping preserves both briefs.
    groups = {}
    for item in result:
        if item.get('drawing') and item['kind'] != 'removed':
            groups.setdefault(str(item['drawing']).upper(), []).append(item)
    for group in groups.values():
        if len(group) > 1:
            for item in group:
                if item['eligible'] or item.get('approvable'):
                    item.update(eligible=False, approvable=False, kind='held_duplicate_drawing')
                    item['reasons'].append('Drawing appears on multiple rows; resolve per-row scope before batch grouping')
    return result


def baseline_rows(rows, ledgers):
    """The first baseline, from work already done (JG, 15 Nov 2026: "the first Check does not
    call finished rows new"). `ledgers` are the batch's own ledger files' contents: one line per
    row it handled, with drawing, quantity, run_id, state, unit_cost and written.

    A current row is matched to a ledger line by its drawing number AND quantity, never by row
    number (rows move). What the ledger proves is what the row carries:
        a finished run with a cost, written       -> completed
        a finished run with a cost, not written   -> completed_pending_write
        a run started that did not finish         -> unknown (held; never resubmitted unasked)
        no line                                   -> no history: an existing row, not new work
    Returns (rows with history, counts)."""
    rank = {'completed': 3, 'completed_pending_write': 2, 'unknown': 1}
    best = {}
    for ledger in ledgers:
        for line in (ledger or {}).values():
            if not isinstance(line, dict) or not line.get('drawing'):
                continue
            done = str(line.get('state')) == 'done' and line.get('unit_cost') is not None
            history = ('completed' if done and line.get('written') else
                       'completed_pending_write' if done else
                       'unknown' if line.get('run_id') else None)
            if history is None:
                continue
            key = (str(line['drawing']).upper(), line.get('quantity'))
            if rank[history] > rank.get((best.get(key) or {}).get('history'), 0):
                best[key] = {'history': history, 'run_id': line.get('run_id')}
    out, counts = [], {}
    for row in validate_rows(rows).values():
        found = (best.get((str(row.get('drawing') or '').upper(), row.get('quantity')))
                 if row.get('drawing') else None)
        row = dict(row, history=(found or {}).get('history'), run_id=(found or {}).get('run_id'))
        name = row['history'] or 'no_earlier_run'
        counts[name] = counts.get(name, 0) + 1
        out.append(row)
    return out, counts


def unidentified(rows, why):
    """The check's answer when the tracker cannot yet be compared row for row (no permanent
    AI Row ID on every row, or no reconciled baseline). Every row is listed with its own holds;
    NOTHING is eligible, so nothing can be run from it. A row with no blocker is named as
    waiting on `why`, not as new work: without identity or a baseline, "new" is a guess."""
    result = []
    for row in rows:
        reasons = blockers(row)
        kind = 'held' if reasons else 'waiting_on_setup'
        result.append({'row_id': row.get('row_id'), 'row': row.get('row'), 'drawing': row.get('drawing'),
                       'quantity': row.get('quantity'), 'kind': kind, 'eligible': False,
                       'approvable': False, 'changed': [],
                       'reasons': reasons + ([] if reasons else [why])})
    return result


class Store:
    """One shared database for both portals. BEGIN IMMEDIATE serialises claims.

    A reservation is durable BEFORE the external submit call. An exception or
    crash leaves it blocked for reconciliation, never silently runnable again.
    """
    def __init__(self, path, clock=time.time):
        self.path = Path(path)
        self.clock = clock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS baseline(tracker TEXT PRIMARY KEY, rows_json TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS plans(id TEXT PRIMARY KEY, tracker TEXT, created REAL,
                    payload TEXT, status TEXT, receipt TEXT);
                CREATE TABLE IF NOT EXISTS active(tracker TEXT PRIMARY KEY, plan_id TEXT NOT NULL);
            ''')

    @contextlib.contextmanager
    def connect(self):
        db = sqlite3.connect(str(self.path), timeout=10)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def initialise(self, tracker, rows, *, history_reconciled=False):
        validate_rows(rows)
        if not tracker or history_reconciled is not True:
            raise ReviewRequired('Reconcile existing runs/costs before initialising this tracker')
        with self.connect() as db:
            db.execute('INSERT INTO baseline VALUES(?,?)', (tracker, json.dumps(rows)))

    def has_baseline(self, tracker):
        with self.connect() as db:
            return db.execute('SELECT 1 FROM baseline WHERE tracker=?', (tracker,)).fetchone() is not None

    def active_plan(self, tracker):
        """The reservation that owns this tracker, or None: {plan_id, status, receipt, rows}
        where rows are the selected rows as submitted ({row_id, row, drawing})."""
        with self.connect() as db:
            rec = db.execute('SELECT plans.* FROM active JOIN plans ON plans.id=active.plan_id '
                             'WHERE active.tracker=?', (tracker,)).fetchone()
            if not rec:
                return None
            plan = json.loads(rec['payload'])
            chosen = set(plan.get('selected') or [d['row_id'] for d in plan['decisions'] if d['eligible']])
            try:
                receipt = json.loads(rec['receipt']) if rec['receipt'] else None
            except ValueError:
                receipt = None
            return {'plan_id': rec['id'], 'status': rec['status'], 'receipt': receipt,
                    'rows': [{'row_id': d['row_id'], 'row': d['row'], 'drawing': d['drawing']}
                             for d in plan['decisions'] if d['row_id'] in chosen]}

    def preview(self, tracker, rows):
        with self.connect() as db:
            base = db.execute('SELECT rows_json FROM baseline WHERE tracker=?', (tracker,)).fetchone()
            if base is None:
                raise ReviewRequired('No baseline: initialise after legacy-run reconciliation; do not treat all rows as new')
            active = db.execute('SELECT plan_id FROM active WHERE tracker=?', (tracker,)).fetchone()
            items = decisions(json.loads(base[0]), rows)
            if active:
                for item in items:
                    if item['eligible'] or item.get('approvable'):
                        item.update(eligible=False, approvable=False, kind='held_active_batch')
                        item['reasons'].append('Existing batch/reservation needs completion or reconciliation')
            plan = {'plan_id': str(uuid.uuid4()), 'tracker': tracker, 'created': self.clock(),
                    'snapshot': snapshot_digest(rows), 'rows': copy.deepcopy(rows), 'decisions': items,
                    'at_once': 2}
            db.execute('INSERT INTO plans VALUES(?,?,?,?,?,?)',
                       (plan['plan_id'], tracker, plan['created'], json.dumps(plan), 'preview', None))
        return plan

    def dispatch(self, plan_id, current_rows, submit, *, max_age=900, approved=()):
        """submit(rows, request_id=..., at_once=2) must start ONE existing batch.

        The injected adapter must filter exact stable IDs, verify before each
        submission/write, stage packs through the normal store, and return a
        durable task receipt. No caller may implement this as a sheet row range.
        """
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            record = db.execute('SELECT * FROM plans WHERE id=?', (plan_id,)).fetchone()
            if not record:
                raise ReviewRequired('Unknown preview')
            if record['status'] != 'preview':
                raise ReviewRequired('Preview already consumed; reconcile its task instead of submitting again')
            plan = json.loads(record['payload'])
            if self.clock() - plan['created'] > max_age or self.clock() < plan['created']:
                raise ReviewRequired('Preview expired; scan again')
            if snapshot_digest(current_rows) != plan['snapshot']:
                raise ReviewRequired('Tracker or pack inputs changed since preview; scan again')
            keys = {d['row_id'] for d in plan['decisions'] if d['eligible']}
            approvable = {d['row_id'] for d in plan['decisions'] if d.get('approvable')}
            wanted = {str(a).lower() for a in (approved or ())}
            if wanted - approvable:
                raise ReviewRequired('An approved row is not a changed row this preview offered; scan again')
            keys |= wanted
            if not keys:
                raise ReviewRequired('No eligible new work and no approved changed work')
            by_id = validate_rows(current_rows)
            selected = [by_id[k] for k in sorted(keys)]
            if db.execute('SELECT 1 FROM active WHERE tracker=?', (plan['tracker'],)).fetchone():
                raise ReviewRequired('A batch/reservation already owns this tracker')
            db.execute('INSERT INTO active VALUES(?,?)', (plan['tracker'], plan_id))
            # THE INTENT IS ON DISK BEFORE ANYTHING IS SENT: which rows, under which plan.
            plan['selected'] = sorted(keys)
            db.execute("UPDATE plans SET status='reserved', payload=? WHERE id=?",
                       (json.dumps(plan), plan_id))
        try:
            receipt = submit(selected, request_id=plan_id, at_once=2)
            if not isinstance(receipt, dict) or not receipt.get('task_id'):
                raise ReviewRequired('Submission returned no durable task ID')
        except Exception:
            with self.connect() as db:
                db.execute("UPDATE plans SET status='unknown' WHERE id=?", (plan_id,))
            raise ReviewRequired('Submission outcome unknown; reservation kept. Reconcile, do not retry.') from None
        with self.connect() as db:
            db.execute("UPDATE plans SET status='submitted',receipt=? WHERE id=?", (json.dumps(receipt), plan_id))
        return receipt

    def finish(self, plan_id, outcomes):
        """Only terminal, reconciled outcomes release ownership. Never auto-retry.

        outcomes keyed by Row ID: {state: completed/completed_pending_write/failed,
        run_id: ...}. Completion does not imply estimating approval.
        """
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            rec = db.execute('SELECT * FROM plans WHERE id=?', (plan_id,)).fetchone()
            if not rec or rec['status'] not in ACTIVE:
                raise ReviewRequired('Not an active reservation')
            plan = json.loads(rec['payload'])
            selected = set(plan.get('selected') or
                           [d['row_id'] for d in plan['decisions'] if d['eligible']])
            if set(outcomes) != selected:
                raise ReviewRequired('Reconcile every selected row before releasing the batch')
            for value in outcomes.values():
                if value.get('state') == 'not_submitted':
                    if not value.get('evidence') or value.get('run_id'):
                        raise ReviewRequired('Explicit non-submission evidence required; absence of a run alone is not proof')
                elif value.get('state') not in ('completed', 'completed_pending_write', 'failed') or not value.get('run_id'):
                    raise ReviewRequired('Terminal run evidence required for each row')
            old = validate_rows(json.loads(db.execute('SELECT rows_json FROM baseline WHERE tracker=?', (plan['tracker'],)).fetchone()[0]))
            submitted = validate_rows(plan['rows'])
            for key in selected:
                state = outcomes[key]['state']
                # PREVIOUS RESULTS ARE KEPT: a re-priced row carries every earlier run it had.
                before = old.get(key) or {}
                earlier = list(before.get('previous_results') or [])
                if before.get('run_id') or before.get('history'):
                    earlier.append({'run_id': before.get('run_id'), 'history': before.get('history'),
                                    'cost': before.get('cost'),
                                    'reconciliation': before.get('reconciliation')})
                old[key] = dict(submitted[key], history='failed' if state == 'not_submitted' else state,
                                run_id=outcomes[key].get('run_id'), reconciliation=outcomes[key],
                                previous_results=earlier)
            db.execute('UPDATE baseline SET rows_json=? WHERE tracker=?', (json.dumps(list(old.values())), plan['tracker']))
            db.execute("UPDATE plans SET status='finished',receipt=? WHERE id=?", (json.dumps(outcomes), plan_id))
            db.execute('DELETE FROM active WHERE tracker=? AND plan_id=?', (plan['tracker'], plan_id))


def locate_writeback(rows, submitted):
    """Find current row by permanent ID and reject changed inputs/manual cost.
    Caller must perform this check and native Excel write in one locked operation.
    """
    now = validate_rows(rows).get(submitted['row_id'])
    if now is None:
        raise ReviewRequired('Row removed; keep result, do not write to its old row number')
    if signature(now) != signature(submitted):
        raise ReviewRequired('Row inputs changed while estimating; keep result without overwriting cost')
    if now.get('cost') != submitted.get('cost'):
        raise ReviewRequired('Cost changed while estimating; preserve the intervening edit')
    return now['row']
