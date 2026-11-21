"""One-off, resumable TTI concept pricing. Default: plan ONLY; --execute is explicit.

Never changes deployment, indexes drawing folders, clears a stale batch lock, or
emails a quote. Source workbook, row facts, images, request, responses, engine
record and deliverables are retained on both archive roots before AiCost changes.
"""
from __future__ import annotations
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile

from tti_concept_inputs import canonical, read_plan, sha, units
from tti_concept_writeback import money, write_cost, require_closed

ROOT = Path(__file__).resolve().parents[1]
TERMINAL_FAILURE = {'error','failed','cancelled','abandoned','held','stopped'}


def now(): return datetime.now(timezone.utc).isoformat()


def atomic(path, data):
    path = Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp = tempfile.mkstemp(prefix=path.name+'.',suffix='.tmp',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as out: out.write(data); out.flush(); os.fsync(out.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)


def json_bytes(value): return (canonical(value)+'\n').encode('utf-8')


def read_json(path): return json.loads(Path(path).read_text(encoding='utf-8'))


@contextmanager
def exclusive_claim(path):
    """O_EXCL; an existing claim (alive, stale or unreadable) is NEVER removed."""
    path = Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    token = uuid.uuid4().hex
    data = {'task_id':'TTI concept pricing','pid':os.getpid(),'started':time.time(),'token':token}
    try: fd = os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    except FileExistsError as exc: raise RuntimeError(f'Batch claim exists: {path}. Nothing submitted; check its owner.') from exc
    try:
        with os.fdopen(fd,'wb') as f: f.write(json_bytes(data)); f.flush(); os.fsync(f.fileno())
        yield token
    finally:
        try:
            if read_json(path).get('token') == token: path.unlink()
        except (OSError,ValueError): pass


class Archive:
    def __init__(self, local, shared):
        self.roots = (Path(local),Path(shared))
        if self.roots[0].resolve() == self.roots[1].resolve(): raise ValueError('C and K archives must be distinct')

    def put(self, relative, data, immutable=True):
        if Path(relative).is_absolute() or '..' in Path(relative).parts: raise ValueError('unsafe archive name')
        for root in self.roots:
            path = root/relative
            if immutable and path.exists():
                if path.read_bytes() != data: raise ValueError(f'archive conflict: {path}')
            else: atomic(path,data)
            if sha(path.read_bytes()) != sha(data): raise OSError('archive verification failed')

    def event(self, kind, **details):
        event = {'at':now(),'event':kind,**details}
        self.put('events/'+uuid.uuid4().hex+'.json',json_bytes(event))
        print(f"{event['at']} {kind}: {canonical(details)}",flush=True)

    def state(self, value):
        # A journal entry is durable before the replaceable convenience ledger.
        self.put('journal/'+uuid.uuid4().hex+'.json',json_bytes(value))
        self.put('state.json',json_bytes(value),immutable=False)


class Client:
    def __init__(self, server, key=''):
        self.server = server.rstrip('/'); self.key = key
        parsed = urllib.parse.urlsplit(self.server)
        if parsed.scheme not in ('http','https') or not parsed.netloc or parsed.username or parsed.query or parsed.fragment:
            raise ValueError('invalid service URL')

    def request(self, method, path, body=None, binary=False):
        headers = {'Content-Type':'application/json'}
        if self.key: headers['X-SDI-Key'] = self.key
        req = urllib.request.Request(self.server+path,data=None if body is None else json_bytes(body),headers=headers,method=method)
        with urllib.request.urlopen(req,timeout=60) as response: data = response.read()
        return data if binary else json.loads(data)

    def recent(self): return self.request('GET','/api/estimate?limit=1000').get('runs',[])
    def runners(self): return self.request('GET','/api/estimate/runners').get('runners',[])
    def start(self, body): return self.request('POST','/api/estimate',body)
    def status(self, run): return self.request('GET','/api/estimate/'+safe_id(run))
    def download(self, run, name):
        return self.request('GET','/api/estimate/'+safe_id(run)+'/deliverables/'+urllib.parse.quote(name,safe=''),binary=True)


def safe_id(run):
    if not re.fullmatch(r'[a-fA-F0-9]{8,64}',str(run)): raise ValueError('invalid run id')
    return str(run)


def matches(snapshot, item):
    return (snapshot.get('client') == 'TTI' and snapshot.get('drawing_number') == item['reference']
            and units(snapshot.get('units')) == item['quantity'])


def check_build(runners, expected, required=2):
    if not re.fullmatch(r'[a-fA-F0-9]{7,40}',expected): raise ValueError('expected build must be a bare commit hash')
    online = [r for r in runners if r.get('online')]
    if len(online) < required: raise RuntimeError(f'Only {len(online)} online runners; expected {required}')
    # Any online runner may take this job; all must be compatible, not just the first two.
    for r in online:
        build = str(r.get('build','')); token = build.split(' ',1)[0]
        if (not re.fullmatch(r'[a-fA-F0-9]{7,40}',token) or not (expected.startswith(token) or token.startswith(expected))
                or '+local edits' in build or r.get('conflict') or r.get('process_count') != 1):
            raise RuntimeError('Runner build/health mismatch: '+str(r.get('runner_id')))


def checked_price(snapshot,item):
    if not matches(snapshot,item): raise ValueError('run identity/quantity does not match source row')
    if snapshot.get('status') != 'done' or snapshot.get('error') or snapshot.get('price_validated') is not True:
        raise ValueError('no validated finished workbook price')
    quotes = snapshot.get('quantity_prices') or []
    exact = [money(q.get('unit_gbp')) for q in quotes if units(q.get('quantity')) == item['quantity']]
    if quotes and not exact: raise ValueError('requested quantity missing from price breaks')
    if len(set(exact)) > 1: raise ValueError('conflicting unit prices for requested quantity')
    return exact[0] if exact else money(snapshot.get('engine_price_gbp'))


def status_evidence(snapshot):
    # Exclude API access/bundle/pack tokens and email addresses. Keep engine log and evidence.
    allowed = ('run_id','status','client','drawing_number','units','quantity_prices','engine_price_gbp',
               'price_validated','error','review','log','deliverables','output_path','runner','source',
               'queued_at','started_at','finished_at','submitted_scope','job_type','llm_only')
    return {k:snapshot[k] for k in allowed if k in snapshot}


def archive_result(api, archive, item, state, snapshot):
    price = checked_price(snapshot,item); base = item['reference']+'/results/'
    evidence = status_evidence(snapshot)
    # Snapshots can acquire additional log lines: preserve every distinct version.
    archive.put(base+'status-'+sha(json_bytes(evidence))[:16]+'.json',json_bytes(evidence))
    inventory=[]; records=[]; workbooks=0
    for d in snapshot.get('deliverables') or []:
        name = str(d.get('name') or '')
        if not name or Path(name).name != name or '/' in name or '\\' in name or ':' in name:
            raise ValueError('unsafe/unnamed deliverable')
        try: data = api.download(state['run_id'],name)
        except urllib.error.HTTPError as exc:
            if exc.code == 403:
                inventory.append({'name':name,'not_copied':'403: service did not permit download; release gate retained'})
                continue
            raise
        archive.put(base+name,data)
        inventory.append({'name':name,'sha256':sha(data),'bytes':len(data)})
        if name.lower().endswith('_record.json'): records.append(json.loads(data))
        if name.lower().endswith('.xlsx'):
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                if 'xl/workbook.xml' not in z.namelist(): raise ValueError('invalid result workbook')
            workbooks += 1
    if not workbooks or len(records) != 1: raise ValueError('need a readable workbook and exactly one engine record on C and K')
    record = records[0]
    q = record.get('requested_order_quantity',record.get('quantity'))
    if units(q) != item['quantity']: raise ValueError('engine record quantity differs from source')
    archive.put(base+'inventory.json',json_bytes(inventory))
    archive.put(base+'price-for-writeback.json',json_bytes({'source_row':item['row'],'quantity':item['quantity'],
                'unit_gbp':str(price),'run_id':state['run_id'],'classification':'PROVISIONAL CONCEPT - not a quote',
                'source_quantity':item.get('source_quantity'),'quantity_assumed':bool(item.get('quantity_assumed')),
                'quantity_assumption_reason':item.get('quantity_assumption_reason'),
                'order_total_gbp':str(price*item['quantity']),'AiCost_basis':'GBP per unit, NOT order total',
                'source_fingerprint':item['fingerprint']}))
    return price


def current_item(plan,item):
    current,_ = read_plan(plan['workbook'],plan['sheet'],assume_missing_quantity_one=bool(item.get('quantity_assumed')))
    row = next((r for r in current['rows'] if r['row'] == item['row']),None)
    if not row or row['fingerprint'] != item['fingerprint']: raise ValueError(f"Row {item['row']} changed since planning")
    return row


def prepare(archive, plan, pictures, item):
    base = item['reference']+'/inputs/'
    archive.put(base+'source-row.json',json_bytes(item))
    archive.put(base+'ENQUIRY_BRIEF.txt',item['brief'].encode('utf-8'))
    files=[]
    for i,pic in enumerate(pictures.get(item['row'],[])):
        relative = base+f'{i+1:02d}-{pic.cell}-{pic.sha256[:12]}'+Path(pic.member).suffix.lower()
        archive.put(relative,pic.data)
        files.append(str(archive.roots[1]/relative))
    body = {'client':'TTI','drawing_number':item['reference'],'job_title':item['description'][:180],
            'units':item['quantity'],'quantity_breaks':[item['quantity']], 'files':files,
            'method':'llm','source':'tti','deliverables':True,'email_to':'','enquiry_brief':item['brief']}
    archive.put(base+'request.json',json_bytes(body))
    return body


def run_batch(plan,pictures,archive,api,expected,at_once=2,poll_seconds=20,stop_file=None,
              sleep=time.sleep,writer=write_cost,selected_rows=None,proof_rows=None):
    """Resume known IDs. An uncertain POST is NEVER blindly retried.

    On an error, stop new submissions and retain already-started jobs; do not kill
    runners. A subsequent invocation can collect their results. Initial execution
    requires no other live service runs and ownership of the common batch claim.
    """
    require_closed(plan['workbook'])
    state_paths=[r/'state.json' for r in archive.roots]
    states=[read_json(p) for p in state_paths if p.exists()]
    if len(states)==1 or (len(states)==2 and states[0] != states[1]):
        raise RuntimeError('C/K ledgers disagree: reconcile journal before resuming; no submission')
    state = states[0] if states else {'schema':'tti_concept_batch.v1','workbook':plan['workbook'],
              'server':getattr(api,'server','test'),'entries':{},'created':now()}
    if state['workbook'] != plan['workbook'] or state['server'] != getattr(api,'server','test'):
        raise ValueError('ledger belongs to another workbook or service')
    original=archive.roots[0]/'plan.json'
    if original.exists():
        saved=read_json(original)
        if bool(saved.get('assume_missing_quantity_one')) != bool(plan.get('assume_missing_quantity_one')):
            raise RuntimeError('Quantity policy differs from the archived plan. Do not delete its history or start another full batch: reconcile the plan with the integrator first.')
        for item in saved['rows']:
            if item['state']=='eligible':
                row=current_item(plan,item)
                entry=state['entries'].get(item['reference'],{})
                if entry.get('phase')=='done' and (row['cost_before'] in (None,'') or money(row['cost_before'])!=money(entry['unit_gbp'])):
                    raise ValueError('A previously written AiCost changed; reconcile it, do not silently mark complete')
        plan=saved
    else:
        raw=Path(plan['workbook']).read_bytes()
        if sha(raw)!=plan['workbook_sha256']: raise ValueError('workbook changed before backup')
        archive.put('source-workbook.xlsx',raw)
        archive.put('plan.json',json_bytes(plan))
    items=[r for r in plan['rows'] if r['state']=='eligible']
    if selected_rows is not None:
        selected_rows=set(selected_rows)
        if not selected_rows or selected_rows-{r['row'] for r in items}:
            raise ValueError('--rows must name eligible rows from this plan, never held/drawing rows')
        items=[r for r in items if r['row'] in selected_rows]
        if any(e.get('phase') not in ('done','held') and e.get('row') not in selected_rows for e in state['entries'].values()):
            raise RuntimeError('Uncollected runs outside selected rows: resume the full batch first')
    # CLI always supplies its two proof rows. Existing library callers/tests may
    # omit this optional contract; they are not the unattended command interface.
    needs_proof=proof_rows is not None and any(i['row'] not in proof_rows for i in items)
    if needs_proof:
        from tti_concept_proof import require_approved_proof
        require_approved_proof(plan,archive,state,proof_rows,expected_build=expected)
    archive.state(state)
    check_build(api.runners(),expected,at_once)
    recent=api.recent()
    owned={s.get('run_id') for s in state['entries'].values() if s.get('run_id')}
    uncertain = [i for i in items if state['entries'].get(i['reference'],{}).get('phase') == 'submitting']
    if any(r.get('status') in ('running','queued') and r.get('run_id') not in owned
           and not any(matches(r,i) for i in uncertain) for r in recent):
        raise RuntimeError('Other jobs are live; finish them first. Nothing submitted by this invocation.')
    # Include previously completed rows in the immutable plan, even though they now have AiCost.
    archive.event('READY',eligible=len(items),remaining=sum(state['entries'].get(i['reference'],{}).get('phase')!='done' for i in items),held=sum(r['state'].startswith('held:') for r in plan['rows']),parallel=at_once)
    try:
        while True:
            pending=False; active=0
            for item in items:
                entry=state['entries'].get(item['reference'],{})
                if entry.get('phase')=='done': continue
                pending=True
                if entry.get('phase')=='held': raise RuntimeError(f"Row {item['row']} held: {entry.get('why')}")
                if entry.get('phase')=='submitting':
                    # A crashed/timeout POST may have been accepted. Recover only a unique match.
                    found=[r for r in api.recent() if matches(r,item)]
                    if len(found)!=1: raise RuntimeError(f"Row {item['row']}: uncertain submission; reconcile manually, DO NOT resend")
                    entry.update(run_id=safe_id(found[0]['run_id']),phase='running'); archive.state(state)
                if entry.get('phase') in ('running','archived'):
                    snapshot=api.status(entry['run_id'])
                    if not matches(snapshot,item): raise ValueError('service run identity changed')
                    archive.put(item['reference']+'/polls/'+uuid.uuid4().hex+'.json',json_bytes(status_evidence(snapshot)))
                    if snapshot.get('status') in TERMINAL_FAILURE:
                        entry.update(phase='held',why=str(snapshot.get('error') or snapshot.get('status')))
                        archive.state(state); raise RuntimeError(f"Row {item['row']} failed/held; no new jobs")
                    if snapshot.get('status')=='done':
                        price=archive_result(api,archive,item,entry,snapshot)
                        entry.update(phase='archived',unit_gbp=str(price)); archive.state(state)
                        audit=writer(plan['workbook'],item,price,plan['sheet'])
                        archive.put(item['reference']+'/writeback-'+uuid.uuid4().hex+'.json',json_bytes(audit))
                        entry.update(phase='done',finished=now()); archive.state(state)
                        archive.event('AiCost WRITTEN',row=item['row'],run_id=entry['run_id'],unit_gbp=str(price),classification='provisional concept')
                    elif snapshot.get('status') in ('queued','running'): active+=1
                    else: raise RuntimeError('Unrecognised run status; no new submissions')
            if not pending: break
            if stop_file and Path(stop_file).exists():
                archive.event('STOP REQUESTED',note='No new submissions. Existing runs are not cancelled; resume to collect.')
                return 2
            if active < at_once:
                check_build(api.runners(),expected,at_once)
                for item in items:
                    if item['reference'] in state['entries']: continue
                    if needs_proof and item['row'] not in proof_rows:
                        require_approved_proof(plan,archive,state,proof_rows,expected_build=expected)
                    require_closed(plan['workbook'])
                    row=current_item(plan,item)
                    if row['cost_before'] not in (None,''): raise RuntimeError('AiCost was filled outside this batch; no overwrite or reprice')
                    found=[r for r in api.recent() if matches(r,item)]
                    if len(found)>1: raise RuntimeError('Multiple existing runs for concept reference; manual reconciliation needed')
                    body=prepare(archive,plan,pictures,item)
                    entry={'row':item['row'],'phase':'submitting','at':now(),'expected_build':expected}
                    state['entries'][item['reference']]=entry; archive.state(state)
                    if found:
                        entry.update(run_id=safe_id(found[0]['run_id']),phase='running')
                    else:
                        # Exactly one POST. Do not retry on timeout, 409, or connection errors.
                        response=api.start(body)
                        entry.update(run_id=safe_id(response['run_id']),phase='running')
                    archive.state(state); active+=1
                    archive.event('RUN ATTACHED',row=item['row'],run_id=entry['run_id'],images=len(item['images']))
                    if active>=at_once: break
            if all(state['entries'].get(i['reference'],{}).get('phase')=='done' for i in items): break
            print(f'{now()} WAITING: {active} active; '+str(sum(e.get('phase')=='done' for e in state['entries'].values()))+f'/{len(items)} written. State saved on C and K.',flush=True)
            sleep(poll_seconds)
    except BaseException as exc:
        # Do not try to mutate/restart any engine. Durable state owns all accepted IDs.
        try: archive.event('STOPPED',reason=type(exc).__name__,note='No automatic resubmission; see state and journals. Already-started jobs remain on runners.')
        except OSError: pass
        raise
    archive.event('COMPLETE',written=len(items),note='Provisional concept prices; held rows remain blank. No estimate approved.')
    return 0


def argument_parser():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--sheet',required=True,help='Tracker workbook path')
    p.add_argument('--sheet-name',default='Milwaukee')
    p.add_argument('--plan-output',required=True,help='Local JSON plan; --execute is separately required')
    p.add_argument('--execute',action='store_true')
    p.add_argument('--local-root',default=str(ROOT/'output'/'tti_concepts'))
    p.add_argument('--shared-root',help='Explicit UNC folder on the K share, inside service allowed roots')
    p.add_argument('--server',default='http://localhost:8071')
    p.add_argument('--expected-build',help='Bare reviewed production commit; required for execution')
    p.add_argument('--at-once',type=int,choices=(1,2),default=2)
    p.add_argument('--rows',help='Optional comma-separated eligible rows for an initial proof; omit for the full plan')
    p.add_argument('--assume-missing-quantity-one','--blank-quantity-as-one',dest='assume_missing_quantity_one',action='store_true',help='Explicit user ruling: blank/zero/unreadable concept quantities are one; original values and assumptions retained')
    p.add_argument('--proof-rows',default='6,12',help='Exactly two distinct pilot rows: one image and one description-only. Default: 6,12')
    p.add_argument('--approve-proof',action='store_true',help='After human review, validate and approve the two archived proofs ONLY; never submits or writes AiCost')
    p.add_argument('--stop-file',help='Stops further submissions, never cancels accepted jobs')
    return p


def main(argv=None):
    p=argument_parser(); a=p.parse_args(argv)
    if a.execute and a.approve_proof: p.error('--approve-proof cannot be combined with --execute')
    try: proof_rows=tuple(int(v.strip()) for v in a.proof_rows.split(','))
    except ValueError: p.error('--proof-rows must name two row numbers')
    if len(proof_rows)!=2 or len(set(proof_rows))!=2: p.error('--proof-rows must name two DISTINCT row numbers')
    plan,pictures=read_plan(a.sheet,a.sheet_name,assume_missing_quantity_one=a.assume_missing_quantity_one)
    if Path(a.plan_output).resolve()==Path(a.sheet).resolve(): raise ValueError('plan output cannot replace workbook')
    atomic(a.plan_output,json_bytes(plan))
    ready=[r for r in plan['rows'] if r['state']=='eligible']; held=[r['row'] for r in plan['rows'] if r['state'].startswith('held:')]
    print(f'PLAN ONLY until --execute: {len(ready)} eligible ({sum(bool(r["images"]) for r in ready)} with pictures; {sum(not r["images"] for r in ready)} description-only); held {held}',flush=True)
    print('Quantity ONE assumed for rows: '+str([r['row'] for r in ready if r.get('quantity_assumed')]),flush=True)
    if not a.execute and not a.approve_proof: return 0
    if not a.shared_root or not a.expected_build: p.error('execution/approval requires --shared-root and --expected-build')
    if not a.shared_root.startswith('\\\\'): p.error('use the K share UNC path, not a mapped drive invisible to runners')
    if not Path(a.shared_root).parent.is_dir(): raise OSError('shared parent is unavailable; connect VPN first')
    # Load settings without logging any values. No service processes or .env files are changed.
    from dotenv import load_dotenv
    load_dotenv(ROOT/'.env',override=False)
    expected=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    if not expected.startswith(a.expected_build): raise RuntimeError('checkout is not the requested build')
    if subprocess.check_output(['git','status','--porcelain','--untracked-files=no'],cwd=ROOT,text=True).strip():
        raise RuntimeError('tracked local edits: integrate and test before running')
    base=Path(os.getenv('SDI_STATE_DIR') or str(Path(os.getenv('PROGRAMDATA',str(Path.home())))/'SDI Intelligence'))
    key=sha(str(Path(a.sheet).resolve()).casefold().encode())[:20]
    archive=Archive(Path(a.local_root)/key,Path(a.shared_root)/key)
    if a.approve_proof:
        from tti_concept_proof import approve_proof
        # Review/approval writes only audit files, so it can happen while the
        # separately authorised nine drawing jobs hold the global batch claim.
        approve_proof(archive,plan,proof_rows,expected_build=a.expected_build)
        return 0
    with exclusive_claim(base/'tti'/'batch.lock'):
        return run_batch(plan,pictures,archive,Client(a.server,os.getenv('SDI_API_KEY','')),a.expected_build,a.at_once,
                         stop_file=a.stop_file,selected_rows=None if not a.rows else [int(v.strip()) for v in a.rows.split(',')],proof_rows=proof_rows)


if __name__=='__main__':
    try: sys.exit(main())
    except Exception as exc:
        print('STOP: '+str(exc),file=sys.stderr,flush=True); sys.exit(1)
