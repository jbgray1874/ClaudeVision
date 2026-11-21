"""Reconcile an uncertain concept POST. Audit by default; NEVER submits a job.

Absence from a recent list is not proof of rejection. Reset additionally requires
an explicit operator ruling that the server failed BEFORE creating/queuing a run,
complete local history and all service views, unchanged C/K evidence, and an idle
global batch claim. Old attempts are retained, not deleted. No AiCost writes.
"""
from __future__ import annotations
import copy
import json
from pathlib import Path
from tti_concept_batch import read_json, json_bytes, now, sha, exclusive_claim, current_item
from tti_concept_proof import same_bytes, same_json

LIMIT = 100000


def history_snapshot(directory):
    directory = Path(directory)
    if not directory.is_dir():
        raise ValueError('Authoritative service history directory is unavailable')
    files = sorted(directory.glob('*.json'))
    if not files:
        raise ValueError('History is empty; completeness is not established')
    rows = []
    for path in files:
        rec = read_json(path)
        if not isinstance(rec, dict) or not rec.get('run_id'):
            raise ValueError('Unreadable or unrecognised history: ' + path.name)
        rows.append(rec)
    return rows


def audit(archive, row, history_dir, clients):
    state_raw = same_bytes(archive, 'state.json')
    state = json.loads(state_raw)
    plan = same_json(archive, 'plan.json')
    if state['workbook'] != plan['workbook']:
        raise ValueError('Ledger and plan workbook differ')
    items = [x for x in plan['rows'] if x['row'] == row and x['state'] == 'eligible']
    if len(items) != 1:
        raise ValueError('Row is not uniquely eligible')
    item = items[0]; ref = item['reference']
    entry = state['entries'].get(ref)
    if not entry or entry.get('phase') != 'submitting' or entry.get('run_id'):
        raise ValueError('Only an uncertain submitting entry WITHOUT a run ID can be reconciled')
    if entry.get('row') != row:
        raise ValueError('Entry row mismatch')
    current = current_item(plan, item)
    if current['cost_before'] not in (None, ''):
        raise ValueError('AiCost already exists; no reset or reprice')
    if same_json(archive, ref+'/inputs/source-row.json') != item:
        raise ValueError('Archived source row changed')
    raw = same_bytes(archive, ref+'/inputs/request.json'); req = json.loads(raw)
    if (req.get('client') != 'TTI' or req.get('drawing_number') != ref
            or req.get('units') != item['quantity'] or req.get('enquiry_brief') != item['brief']):
        raise ValueError('Archived request identity/quantity/brief mismatch')
    if any((root/ref/'results').exists() for root in archive.roots):
        raise ValueError('Result artifacts exist; reconcile them, never reset the submission')
    urls = [c.server for c in clients]
    if not clients or len(set(urls)) != len(urls) or state['server'] not in urls:
        raise ValueError('Include the submitting service and every peer once')
    views = [('history', history_snapshot(history_dir))]
    for client in clients:
        response = client.request('GET', '/api/estimate?limit='+str(LIMIT))
        runs = response.get('runs')
        if not isinstance(runs, list) or len(runs) >= LIMIT:
            raise ValueError('Service history unavailable or truncated: '+client.server)
        if any(not isinstance(r, dict) or not r.get('run_id') for r in runs):
            raise ValueError('Malformed service history: '+client.server)
        views.append((client.server, runs))
    found = {}; active = {}
    for source, runs in views:
        for run in runs:
            # Any count/status of this reference blocks reset, not merely exact-qty matches.
            if run.get('drawing_number') == ref:
                found[run['run_id']] = {k:run.get(k) for k in ('run_id','client','drawing_number','units','status')}
            if source != 'history' and run.get('status') in ('queued','running'):
                active[run['run_id']] = run.get('status')
    if same_bytes(archive, 'state.json') != state_raw:
        raise ValueError('State changed while auditing')
    return {'schema':'tti_concept_reconciliation.v1','checked_at':now(), 'row':row,
            'reference':ref,'workbook':plan['workbook'],'quantity':item['quantity'],
            'state_sha256':sha(state_raw),'request_sha256':sha(raw),
            'source_fingerprint':item['fingerprint'],'services':urls,
            'history_directory':str(Path(history_dir).resolve()),
            'history_counts':{source:len(runs) for source,runs in views},
            'matching_runs':list(found.values()),'active_service_runs':active,
            'decision':'DO NOT RESET: existing run found' if found else
                       'NO RUN FOUND: explicit pre-queue failure ruling still required',
            'state_changed':False,'jobs_submitted':0}


def retire_unaccepted(archive, row, history_dir, clients, reviewed, reason, claim):
    if not reason or len(reason.strip()) < 20:
        raise ValueError('An explicit reviewed server-side PRE-QUEUE failure reason is required')
    if reviewed.get('schema') != 'tti_concept_reconciliation.v1':
        raise ValueError('Unrecognised reviewed evidence')
    # Never clear/steal an existing lock, including a stale one.
    with exclusive_claim(claim):
        fresh = audit(archive, row, history_dir, clients)
        for key in ('row','reference','workbook','quantity','state_sha256','request_sha256',
                    'source_fingerprint','services','history_directory'):
            if fresh[key] != reviewed.get(key):
                raise ValueError('Reviewed evidence is stale or differs: '+key)
        if fresh['matching_runs'] or reviewed.get('matching_runs'):
            raise ValueError('A matching run exists: attach/collect it, do not reset')
        if fresh['active_service_runs']:
            raise ValueError('Service has active jobs; defer reconciliation until idle')
        state = same_json(archive, 'state.json')
        if sha(same_bytes(archive, 'state.json')) != fresh['state_sha256']:
            raise ValueError('State changed after final check')
        ref = fresh['reference']; old = copy.deepcopy(state)
        evidence = {'audit':fresh, 'operator_prequeue_ruling':reason.strip(),
                    'retired_at':now(), 'old_entry':old['entries'][ref]}
        # Both backups and ruling durable BEFORE state changes. Any partial write
        # leaves C/K unequal and normal execution fails closed.
        base = 'reconciliation/'+fresh['state_sha256']+'/'
        archive.put(base+'state-before.json', json_bytes(old))
        archive.put(base+'reviewed-evidence.json', json_bytes(evidence))
        state.setdefault('retired_submissions', []).append(evidence)
        del state['entries'][ref]
        archive.state(state)
        archive.event('UNACCEPTED ATTEMPT RETIRED',row=row,reference=ref,
                      note='No job submitted. A later explicit proof run is required.')
        return {'row':row,'reference':ref,'state_changed':True,'jobs_submitted':0}
