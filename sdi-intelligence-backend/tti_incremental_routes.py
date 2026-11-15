"""The two buttons: Check for changes, Price the changes. Import-safe: no engine imports.

From the reviewed tti_incremental_changes_v1 package (15 Nov 2026), changed where the page
needed it:

  * Check ANSWERS even when the tracker cannot yet be compared row for row (no AI Row ID on
    every row, or no reconciled baseline): every row is listed with its holds, nothing is
    eligible, and the reason is said in one sentence. The package refused with a 409 instead.
  * Run is OFF unless the host says otherwise (run_enabled), is refused while a batch that
    writes is alive (busy), and hands the caller's own address and key to the submit adapter.
  * A finished batch is reconciled from its own status before the next comparison, so the
    button is not single-use.

There is deliberately no fallback to the whole-sheet /tti/run endpoint.
"""
from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool
from tti_incremental import ReviewRequired, baseline_rows, unidentified

NO_IDS = ('The tracker has no permanent AI Row ID on every row yet, so new and changed rows '
          'cannot be told apart safely. Nothing can be priced from this button until the IDs '
          'are assigned.')
NO_BASELINE = ('No reconciled baseline of earlier runs exists for this tracker yet, so which rows '
               'are new is not known. Nothing can be priced from this button until it is set.')
RUN_OFF = 'Pricing from this button is switched off on this service (SDI_TTI_CHANGES_RUN).'


class CheckRequest(BaseModel):
    tracker_id: str


class RunRequest(CheckRequest):
    plan_id: str
    approved: list = []          # AI Row IDs of CHANGED rows a person ticked; new rows need none


class BaselineRequest(CheckRequest):
    apply: bool = False


GROUPS = {'new_row': 'new', 'drawing_added': 'new', 'pack_added': 'new',
          'changed_existing': 'changed', 'changed_completed': 'changed',
          'unchanged_completed': 'unchanged', 'removed': 'removed'}


def grouped(items):
    """new / changed / unchanged / held, each row with its reasons. A changed row that cannot
    be approved (something else is against it) is shown as held, with why."""
    for d in items:
        g = GROUPS.get(d['kind'], 'held')
        if g == 'new' and not d['eligible']:
            g = 'held'
        if g == 'changed' and not d.get('approvable'):
            g = 'held'
        d['group'] = g
    return items


def _counts(items):
    out = {}
    for d in items:
        out[d.get('group') or d['kind']] = out.get(d.get('group') or d['kind'], 0) + 1
    return out


def make_router(store, *, allowed_trackers, snapshot, submit, check_key,
                run_enabled=lambda: False, busy=lambda: None, reconcile=None, ledgers=None,
                prefix='/api/estimate/tti/changes'):
    """snapshot(tracker_id) -> {rows, row_id_column, rows_without_id, ...};
    submit(tracker_id, rows, server=..., key=..., request_id=..., at_once=2) -> {task_id, ...};
    busy() -> a sentence while a writing batch is alive, else None;
    reconcile(tracker_id) -> a sentence about the last batch, or None.

    Submit must return promptly with a persistent task ID. One task runs the exact selected
    rows, at most two estimates concurrently, one writer. It must never reinterpret the
    selection as a min/max row interval.
    """
    router = APIRouter(prefix=prefix)

    def guard(tracker_id, key):
        check_key(key)
        if tracker_id not in allowed_trackers:
            raise HTTPException(400, 'Unknown tracker; choose a configured master')

    @router.post('/check')
    async def check(req: CheckRequest, x_sdi_key: str = Header(default='')):
        guard(req.tracker_id, x_sdi_key)
        try:
            last = await run_in_threadpool(reconcile, req.tracker_id) if reconcile else None
            snap = await run_in_threadpool(snapshot, req.tracker_id)
            rows = snap['rows']
            base = {'tracker': req.tracker_id, 'at_once': 2, 'plan_id': None, 'runnable': False,
                    'rows': len(rows), 'last_batch': last, 'run_enabled': bool(run_enabled())}
            why = (NO_IDS if not snap.get('row_id_column') or snap.get('rows_without_id')
                   else NO_BASELINE if not await run_in_threadpool(store.has_baseline, req.tracker_id)
                   else '')
            if why:
                items = grouped(unidentified(rows, why))
                return dict(base, message=why, decisions=items, counts=_counts(items))
            plan = await run_in_threadpool(store.preview, req.tracker_id, rows)
            grouped(plan['decisions'])
            eligible = sum(1 for d in plan['decisions'] if d['eligible'])
            changed = sum(1 for d in plan['decisions'] if d.get('approvable'))
            # Do not expose internal raw row data/pack paths in the button receipt.
            return dict(base, plan_id=plan['plan_id'], created=plan['created'],
                        decisions=plan['decisions'], counts=_counts(plan['decisions']),
                        eligible=eligible, approvable=changed,
                        runnable=bool((eligible or changed) and run_enabled()),
                        message=(f'{eligible} new row(s) with a current drawing pack; {changed} '
                                 f'changed row(s) that run only if ticked.'
                                 + ('' if run_enabled() else ' ' + RUN_OFF)))
        except ReviewRequired as exc:
            raise HTTPException(409, str(exc)) from None

    @router.post('/run')
    async def run(req: RunRequest, request: Request, x_sdi_key: str = Header(default='')):
        guard(req.tracker_id, x_sdi_key)
        if not run_enabled():
            raise HTTPException(409, RUN_OFF)
        said = busy()
        if said:                       # before the preview is consumed: nothing was started
            raise HTTPException(409, said)
        try:
            # A plan ID may only be used against the tracker it belongs to.
            with store.connect() as db:
                rec = db.execute('SELECT tracker FROM plans WHERE id=?', (req.plan_id,)).fetchone()
            if not rec or rec[0] != req.tracker_id:
                raise ReviewRequired('Preview belongs to another tracker or does not exist')
            snap = await run_in_threadpool(snapshot, req.tracker_id)
            server = str(request.base_url).rstrip('/')
            callback = lambda selected, **kw: submit(req.tracker_id, selected, server=server,
                                                     key=x_sdi_key, **kw)
            return await run_in_threadpool(
                lambda: store.dispatch(req.plan_id, snap['rows'], callback, approved=req.approved))
        except ReviewRequired as exc:
            raise HTTPException(409, str(exc)) from None

    @router.post('/baseline')
    async def baseline(req: BaselineRequest, x_sdi_key: str = Header(default='')):
        """The first baseline, from the ledgers earlier batches left. apply=false only counts."""
        guard(req.tracker_id, x_sdi_key)
        if ledgers is None:
            raise HTTPException(409, 'No ledger folder is configured on this service')
        try:
            if await run_in_threadpool(store.has_baseline, req.tracker_id):
                raise ReviewRequired('This tracker already has a baseline; it is never reset from here')
            snap = await run_in_threadpool(snapshot, req.tracker_id)
            if not snap.get('row_id_column') or snap.get('rows_without_id'):
                raise ReviewRequired(NO_IDS)
            found = await run_in_threadpool(ledgers)
            rows, counts = baseline_rows(snap['rows'], found)
            if req.apply:
                await run_in_threadpool(
                    lambda: store.initialise(req.tracker_id, rows, history_reconciled=True))
            return {'tracker': req.tracker_id, 'applied': bool(req.apply), 'rows': len(rows),
                    'ledgers': len(found), 'counts': counts}
        except ReviewRequired as exc:
            raise HTTPException(409, str(exc)) from None
    return router
