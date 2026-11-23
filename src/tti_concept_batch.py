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

from tti_concept_inputs import canonical, no_pack_rulings, read_plan, reread_options, sha, units
from tti_concept_writeback import money, write_cost, WorkbookBusy

ROOT = Path(__file__).resolve().parents[1]
TERMINAL_FAILURE = {'error','failed','cancelled','abandoned','held','stopped'}


def now(): return datetime.now(timezone.utc).isoformat()


def winsafe(path, windows=None, reserve=0):
    r"""The path, in Windows' extended-length form when it needs it, else as given.

    Windows refuses a path over about 260 characters unless it is written \\?\C:\... or
    \\?\UNC\server\share\.... Row 29's second attempt filed its unpriced covering e-mail
    264 characters deep on K and the whole queue stopped on FileNotFoundError (23 Nov 2026).
    `reserve` is how many characters will be created INSIDE this path: the first fix
    converted only a path that was itself long, and the queue stopped again at 10:32 on the
    same file, because the folder was 184 characters and it was the temporary file's name
    added inside it that passed the limit. Short paths with room to spare, relative paths
    and every path off Windows are untouched."""
    windows = (os.name == 'nt') if windows is None else windows
    s = str(path)
    if not windows or len(s) + reserve < 248 or s.startswith('\\\\?\\'):
        return s
    if s.startswith('\\\\'):
        return '\\\\?\\UNC' + s[1:]
    if len(s) > 2 and s[1] == ':' and s[2] == '\\':
        return '\\\\?\\' + s
    return s


def atomic(path, data):
    path = Path(path)
    # The temporary name beside the target is "<name>.<8 random>.tmp": the folder must be
    # safe for that full length, not merely for itself.
    dirp = winsafe(path.parent, reserve=len(path.name) + 14)
    Path(dirp).mkdir(parents=True,exist_ok=True)
    fd,tmp = tempfile.mkstemp(prefix=path.name+'.',suffix='.tmp',dir=dirp)
    try:
        with os.fdopen(fd,'wb') as out: out.write(data); out.flush(); os.fsync(out.fileno())
        os.replace(tmp,winsafe(path))
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
    def __init__(self, local, shared, stop_file=None):
        self.roots = (Path(local),Path(shared))
        if self.roots[0].resolve() == self.roots[1].resolve(): raise ValueError('C and K archives must be distinct')
        self.mirror = None
        if os.getenv('SDI_ESTIMATE_LOCAL_FIRST','').strip().lower() in {'1','true','yes','on'}:
            from durable_archive_mirror import Mirror
            self.mirror = Mirror(*self.roots,stop_file=stop_file)

    def sync_pending(self):
        if self.mirror:
            self.mirror.sync()
            self.mirror.wait_online()

    def put(self, relative, data, immutable=True):
        if self.mirror:
            return self.mirror.put(relative,data,immutable)
        if Path(relative).is_absolute() or '..' in Path(relative).parts: raise ValueError('unsafe archive name')
        for root in self.roots:
            path = root/relative
            target = Path(winsafe(path))                 # the same file, long-path safe
            if immutable and target.exists():
                if target.read_bytes() != data: raise ValueError(f'archive conflict: {path}')
            else: atomic(path,data)
            if sha(target.read_bytes()) != sha(data): raise OSError('archive verification failed')

    def event(self, kind, **details):
        event = {'at':now(),'event':kind,**details}
        self.put('events/'+uuid.uuid4().hex+'.json',json_bytes(event))
        print(f"{event['at']} {kind}: {canonical(details)}",flush=True)

    def state(self, value):
        # A journal entry is durable before the replaceable convenience ledger.
        self.put('journal/'+uuid.uuid4().hex+'.json',json_bytes(value))
        self.put('state.json',json_bytes(value),immutable=False)


class Client:
    def __init__(self, server, key='', shared_root=None, stop_file=None):
        self.server = server.rstrip('/'); self.key = key
        self.shared_root=Path(shared_root) if shared_root else None
        self.stop_file=Path(stop_file) if stop_file else None
        parsed = urllib.parse.urlsplit(self.server)
        if parsed.scheme not in ('http','https') or not parsed.netloc or parsed.username or parsed.query or parsed.fragment:
            raise ValueError('invalid service URL')

    def request(self, method, path, body=None, binary=False):
        headers = {'Content-Type':'application/json'}
        if self.key: headers['X-SDI-Key'] = self.key
        req = urllib.request.Request(self.server+path,data=None if body is None else json_bytes(body),headers=headers,method=method)
        attempts=0
        while True:
            try:
                with urllib.request.urlopen(req,timeout=60) as response: data = response.read()
                break
            except (urllib.error.URLError, OSError) as exc:
                local_first=os.getenv('SDI_ESTIMATE_LOCAL_FIRST','').strip().lower() in {'1','true','yes','on'}
                if method!='GET' or not local_first: raise  # never retry an uncertain job submission
                attempts+=1
                if isinstance(exc,urllib.error.HTTPError):
                    share_down=(self.shared_root is not None and not self.shared_root.parent.is_dir())
                    temporary_file=(exc.code==404 and '/deliverables/' in path and share_down)
                    if not temporary_file and not (exc.code in {500,502,503,504} and attempts<=3): raise
                if self.stop_file and self.stop_file.exists():
                    raise InterruptedError('stopped while collecting an existing run; no job resubmitted') from exc
                print('GET RETRY: collecting an existing run only; no job submitted again.',flush=True)
                time.sleep(15)
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


def settled_check_build(api, expected, required=2, wait_s=300, sleep=time.sleep):
    """check_build, giving a runner mid-restart time to check back in.

    The main runner's process was replaced at 12:13:49 (23 Nov 2026) while a job ran; the
    next submission's check saw the new process before its first check-in and the whole
    queue stopped on "Runner build/health mismatch", with the runner healthy on the right
    build half a minute later. A runner that legitimately restarts gets up to wait_s to
    come back; a real mismatch, a wrong build or local edits is still refused, with the
    same words, when the wait runs out. Nothing is submitted while waiting."""
    deadline = time.monotonic() + wait_s
    while True:
        try:
            return check_build(api.runners(), expected, required)
        except RuntimeError as exc:
            if time.monotonic() >= deadline: raise
            print(f'{now()} RUNNER NOT SETTLED: {exc}; waiting for it to check back in',flush=True)
            sleep(20)


class UnpricedResult(ValueError):
    """Identified completed run, but no usable price. Never means zero."""


def checked_price(snapshot,item):
    if not matches(snapshot,item): raise ValueError('run identity/quantity does not match source row')
    if snapshot.get('status') != 'done' or snapshot.get('error') or snapshot.get('price_validated') is not True:
        raise UnpricedResult('no validated finished workbook price')
    quotes = snapshot.get('quantity_prices') or []
    try:
        exact = [money(q.get('unit_gbp')) for q in quotes if units(q.get('quantity')) == item['quantity']]
    except ValueError as exc:
        raise UnpricedResult('invalid exact-quantity unit price') from exc
    if quotes and not exact: raise UnpricedResult('requested quantity missing from price breaks')
    if len(set(exact)) > 1: raise ValueError('conflicting unit prices for requested quantity')
    try:
        return exact[0] if exact else money(snapshot.get('engine_price_gbp'))
    except ValueError as exc:
        raise UnpricedResult('completed run has no positive finite unit price; retained for review') from exc


def archive_unpriced(api,archive,item,entry,snapshot,why):
    if not matches(snapshot,item): raise ValueError('unpriced run identity differs')
    base=item['reference']+'/unpriced/'+safe_id(entry['run_id'])+'/'
    evidence=status_evidence(snapshot)
    # As in archive_result: a snapshot acquires log lines (a service restart adds its restored
    # note), so refiling the same run's evidence after a crash is a new version, not a
    # conflict. Row 29, 23 Nov 2026: the 08:40 crash left status.json half filed, and the
    # resume was refused with "archive conflict" on its own evidence.
    archive.put(base+'status-'+sha(json_bytes(evidence))[:16]+'.json',json_bytes(evidence))
    inventory=[]
    for d in snapshot.get('deliverables') or []:
        name=str(d.get('name') or '')
        if not name or Path(name).name!=name or any(c in name for c in '/\\:'):
            raise ValueError('unsafe unpriced output name')
        try: raw=api.download(entry['run_id'],name)
        except urllib.error.HTTPError as exc:
            if exc.code==403:
                inventory.append({'name':name,'not_copied':'403: release gate retained'}); continue
            raise
        archive.put(base+name,raw)
        inventory.append({'name':name,'sha256':sha(raw),'bytes':len(raw)})
    archive.put(base+'inventory.json',json_bytes(inventory))
    archive.put(base+'HOLD.json',json_bytes({'row':item['row'],'reference':item['reference'],
        'run_id':entry['run_id'],'why':str(why),'AiCost_written':False,'automatic_resubmission':False}))


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
    audit={'source_row':item['row'],'quantity':item['quantity'],
                'unit_gbp':str(price),'run_id':state['run_id'],'classification':'PROVISIONAL CONCEPT - not a quote',
                'source_quantity':item.get('source_quantity'),'quantity_assumed':bool(item.get('quantity_assumed')),
                'quantity_assumption_reason':item.get('quantity_assumption_reason'),
                'order_total_gbp':str(price*item['quantity']),'AiCost_basis':'GBP per unit, NOT order total',
                'source_fingerprint':item['fingerprint']}
    if item.get('no_pack'):
        # Said in the filed price audit as well as in the brief the estimate was made from.
        audit.update(classification='PROVISIONAL CONCEPT - NO DRAWING PACK FOUND, priced from the description and pictures - not a quote',
                     no_drawing_pack=True,drawing_number_on_sheet=item['no_pack']['drawing'],
                     no_drawing_pack_evidence=item['no_pack'].get('evidence'),
                     reprice='from the drawings when they are supplied')
    archive.put(base+'price-for-writeback.json',json_bytes(audit))
    return price


def current_item(plan,item):
    current,_ = read_plan(plan['workbook'],plan['sheet'],**reread_options(item))
    row = next((r for r in current['rows'] if r['row'] == item['row']),None)
    if not row or row['fingerprint'] != item['fingerprint']: raise ValueError(f"Row {item['row']} changed since planning")
    return row


AMENDMENTS='plan-amendments'


def filed_amendments(archive):
    """No-pack rows added to a filed plan. C and K must hold the same files, byte for byte."""
    names=[sorted(p.name for p in (root/AMENDMENTS).glob('*.json')) if (root/AMENDMENTS).is_dir() else [] for root in archive.roots]
    if names[0]!=names[1]: raise RuntimeError('C/K plan amendments disagree; reconcile them. No submission')
    out=[]
    for name in names[0]:
        raw=[(root/AMENDMENTS/name).read_bytes() for root in archive.roots]
        if raw[0]!=raw[1]: raise RuntimeError('C/K plan amendments disagree; reconcile them. No submission')
        out.append(json.loads(raw[0]))
    return out


def with_amendments(archive, saved, offered=None):
    """The filed plan plus its no-pack rows. plan.json itself is never rewritten.

    The ONLY amendment there is: a row the filed plan excluded as a drawing row, now
    eligible under an explicit no-pack ruling. A new one is filed on both roots before
    it can be submitted, and is then kept on every later resume, option given or not.
    """
    rows={r['row']:r for r in saved['rows']}; added={}
    def admissible(item):
        return (rows.get(item.get('row'),{}).get('state')=='drawing row excluded' and bool(item.get('no_pack'))
                and item.get('state')=='eligible')
    for item in filed_amendments(archive):
        if not admissible(item) or item['row'] in added:
            raise RuntimeError('A filed plan amendment is not one no-pack ruling on an excluded drawing row. No submission')
        added[item['row']]=item
    for item in (offered or {}).get('rows',[]):
        if item['row'] in added or not admissible(item): continue
        archive.put(f"{AMENDMENTS}/no-pack-row-{item['row']:05d}.json",json_bytes(item))
        archive.event('NO-PACK ROW ADDED TO PLAN',row=item['row'],drawing=item['no_pack']['drawing'],reference=item['reference'])
        added[item['row']]=item
    if not added: return saved
    plan=dict(saved); plan['rows']=[added.get(r['row'],r) for r in saved['rows']]
    return plan


def with_attempts(state, plan):
    """The plan's rows under their current attempt. A row retried after a hold is a NEW
    attempt: its reference carries -R2, -R3 ..., so the service makes a new run instead of
    handing back the failed one, and its records sit beside the old attempt's, never over them.
    The base reference and the attempt number ride on the row for the audit."""
    attempts=state.get('attempts') or {}
    if not attempts: return plan
    rows=[dict(r,base_reference=r['reference'],attempt=attempts[r['reference']],reference=f"{r['reference']}-R{attempts[r['reference']]}")
          if r['reference'] in attempts else r for r in plan['rows']]
    return dict(plan,rows=rows)


def retire_for_retry(archive, plan, rows, proof_rows=None, basis=''):
    """Queue named HELD rows for another attempt (JG, 22 Nov 2026: "we'll need to pick these
    up at the end. Can we queue these up?"). Only a held row; never a proof row; the held
    attempt and its run are kept in retired_attempts and in retries/, on both roots, and the
    row's next attempt gets a new reference. Nothing is sent here."""
    from tti_concept_proof import context
    saved,state=context(archive,plan)
    effective=with_attempts(state,with_amendments(archive,saved))
    by_row={r['row']:r for r in effective['rows'] if r['state']=='eligible'}
    queued=[]
    for row in rows:
        item=by_row.get(row)
        if item is None: raise ValueError(f'Row {row} is not an eligible row of this plan')
        if proof_rows and row in proof_rows: raise ValueError(f'Row {row} is a proof row; a proof is never retried in place')
        entry=state['entries'].get(item['reference'])
        if not entry or entry.get('phase')!='held': raise ValueError(f"Row {row} is not held (phase {entry.get('phase') if entry else 'not started'}); only a held row is retried")
        n=(item.get('attempt') or 1)+1
        base=item.get('base_reference') or item['reference']
        record={'row':row,'base_reference':base,'retired_reference':item['reference'],'retired_run_id':entry.get('run_id'),
                'retired_why':entry.get('why'),'attempt_retired':item.get('attempt') or 1,'next_attempt':n,
                'next_reference':f'{base}-R{n}','at':now(),'basis':' '.join(str(basis).split()) or 'operator retry of a held row',
                'reviewed_by':os.getenv('USERNAME') or os.getenv('USER') or 'explicit operator'}
        archive.put(f'retries/row-{row:05d}-attempt-{n:02d}.json',json_bytes(record))
        state.setdefault('retired_attempts',[]).append(dict(entry,reference=item['reference'],retired_at=now()))
        del state['entries'][item['reference']]
        state.setdefault('attempts',{})[base]=n
        archive.state(state)
        archive.event('HELD ROW QUEUED FOR RETRY',row=row,retired_run_id=entry.get('run_id'),next_reference=record['next_reference'],attempt=n)
        queued.append(row)
    return queued


def prepare(archive, plan, pictures, item):
    base = item['reference']+'/inputs/'
    archive.put(base+'source-row.json',json_bytes(item))
    archive.put(base+'ENQUIRY_BRIEF.txt',item['brief'].encode('utf-8'))
    files=[]
    for i,pic in enumerate(pictures.get(item['row'],[])):
        relative = base+f'{i+1:02d}-{pic.cell}-{pic.sha256[:12]}'+Path(pic.member).suffix.lower()
        archive.put(relative,pic.data)
        files.append(str(archive.roots[1]/relative))
    body = {'client':'TTI','drawing_number':item['reference'],'job_title':item['description'][:180],'source_row':item['row'],
            'units':item['quantity'],'quantity_breaks':[item['quantity']], 'files':files,
            'method':'llm','source':'tti','deliverables':True,'email_to':'','enquiry_brief':item['brief']}
    archive.put(base+'request.json',json_bytes(body))
    return body


def archived_price(archive,item,entry):
    """Validate durable, mirrored outputs without contacting the estimator."""
    from tti_concept_proof import same_json, same_bytes
    base=item['reference']+'/results/'
    audit=same_json(archive,base+'price-for-writeback.json')
    price=money(entry['unit_gbp'])
    if (audit.get('run_id')!=entry['run_id'] or audit.get('source_row')!=item['row']
            or audit.get('source_fingerprint')!=item['fingerprint']
            or units(audit.get('quantity'))!=item['quantity'] or money(audit.get('unit_gbp'))!=price):
        raise ValueError('archived write-back price/identity mismatch')
    records=0; books=0
    for file in same_json(archive,base+'inventory.json'):
        if file.get('not_copied'): continue
        name=file.get('name','')
        if not name or Path(name).name!=name or any(c in name for c in '/\\:'):
            raise ValueError('unsafe archived output name')
        raw=same_bytes(archive,base+name)
        if sha(raw)!=file['sha256'] or len(raw)!=file['bytes']:
            raise ValueError('archived output changed before write-back')
        if name.lower().endswith('_record.json'):
            record=json.loads(raw)
            if units(record.get('requested_order_quantity',record.get('quantity')))!=item['quantity']:
                raise ValueError('archived record quantity mismatch')
            records+=1
        if name.lower().endswith('.xlsx'): books+=1
    if records!=1 or not books: raise ValueError('archived record/workbook missing')
    return price


def attempt_writeback(plan,archive,state,item,writer=write_cost):
    entry=state['entries'][item['reference']]
    price=archived_price(archive,item,entry)
    try:
        audit=writer(plan['workbook'],item,price,plan['sheet'])
    except (WorkbookBusy,PermissionError) as exc:
        # Only an unavailable tracker is deferrable. Archive failures and changed
        # source rows/prices remain fatal; never label them Excel locks.
        entry.update(phase='archived',writeback_pending=True,writeback_reason=str(exc))
        archive.state(state)
        archive.event('ESTIMATE SAVED - AiCost PENDING',row=item['row'],run_id=entry['run_id'],
                      unit_gbp=str(price),reason=str(exc),note='Retained on C and K; retry write-back only, never reprice.')
        return False
    archive.put(item['reference']+'/writeback-'+uuid.uuid4().hex+'.json',json_bytes(audit))
    entry.update(phase='done',finished=now(),writeback_pending=False)
    entry.pop('writeback_reason',None)
    archive.state(state)
    archive.event('AiCost WRITTEN',row=item['row'],run_id=entry['run_id'],unit_gbp=str(price),classification='provisional concept')
    return True


def retry_writebacks(plan,archive,selected_rows=None,writer=write_cost):
    """Local/shared files only. Cannot submit, poll, release or restart anything."""
    archive.sync_pending()
    from tti_concept_proof import context
    saved,state=context(archive,plan)
    saved=with_attempts(state,with_amendments(archive,saved))
    items=[r for r in saved['rows'] if state['entries'].get(r['reference'],{}).get('phase')=='archived']
    if selected_rows is not None:
        if set(selected_rows)-{r['row'] for r in items}: raise ValueError('Select pending write-back rows only')
        items=[r for r in items if r['row'] in selected_rows]
    for item in items: attempt_writeback(saved,archive,state,item,writer)
    pending=[i['row'] for i in items if state['entries'][i['reference']]['phase']=='archived']
    archive.event('WRITE-BACK RETRY ENDED',pending_rows=pending,submissions=0)
    return 3 if pending else 0


def run_batch(plan,pictures,archive,api,expected,at_once=2,poll_seconds=20,stop_file=None,
              sleep=time.sleep,writer=write_cost,selected_rows=None,proof_rows=None,proof_execution_build=None):
    """Resume known IDs. An uncertain POST is NEVER blindly retried.

    On an error, stop new submissions and retain already-started jobs; do not kill
    runners. A subsequent invocation can collect their results. Initial execution
    requires no other live service runs and ownership of the common batch claim.
    """
    archive.sync_pending()
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
        saved=with_amendments(archive,saved,plan)
        for item in saved['rows']:
            if item['state']=='eligible':
                row=current_item(plan,item)
                entry=state['entries'].get(item['reference'],{})
                if entry.get('phase')=='done' and (row['cost_before'] in (None,'') or money(row['cost_before'])!=money(entry['unit_gbp'])):
                    raise ValueError('A previously written AiCost changed; reconcile it, do not silently mark complete')
        plan=with_attempts(state,saved)
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
        if any(e.get('phase') not in ('done','archived','held') and e.get('row') not in selected_rows for e in state['entries'].values()):
            raise RuntimeError('Uncollected runs outside selected rows: resume the full batch first')
    # CLI always supplies its two proof rows. Existing library callers/tests may
    # omit this optional contract; they are not the unattended command interface.
    needs_proof=proof_rows is not None and any(i['row'] not in proof_rows for i in items)
    if needs_proof:
        from tti_concept_proof import require_approved_proof
        require_approved_proof(plan,archive,state,proof_rows,expected_build=proof_execution_build or expected)
    archive.state(state)
    settled_check_build(api,expected,at_once,sleep=sleep)
    recent=api.recent()
    owned={s.get('run_id') for s in state['entries'].values() if s.get('run_id')}
    uncertain = [i for i in items if state['entries'].get(i['reference'],{}).get('phase') == 'submitting']
    if any(r.get('status') in ('running','queued') and r.get('run_id') not in owned
           and not any(matches(r,i) for i in uncertain) for r in recent):
        raise RuntimeError('Other jobs are live; finish them first. Nothing submitted by this invocation.')
    # Include previously completed rows in the immutable plan, even though they now have AiCost.
    archive.event('READY',eligible=len(items),remaining=sum(state['entries'].get(i['reference'],{}).get('phase')!='done' for i in items),held=sum(r['state'].startswith('held:') for r in plan['rows']),parallel=at_once)
    attempted_writebacks=set()
    try:
        while True:
            pending=False; active=0
            for item in items:
                entry=state['entries'].get(item['reference'],{})
                if entry.get('phase') in ('done','held'): continue
                pending=True
                if entry.get('phase')=='archived':
                    if item['reference'] not in attempted_writebacks:
                        attempt_writeback(plan,archive,state,item,writer)
                        attempted_writebacks.add(item['reference'])
                    continue
                if entry.get('phase')=='submitting':
                    # A crashed/timeout POST may have been accepted. Recover only a unique match.
                    found=[r for r in api.recent() if matches(r,item)]
                    if len(found)!=1: raise RuntimeError(f"Row {item['row']}: uncertain submission; reconcile manually, DO NOT resend")
                    entry.update(run_id=safe_id(found[0]['run_id']),phase='running'); archive.state(state)
                if entry.get('phase')=='running':
                    snapshot=api.status(entry['run_id'])
                    if not matches(snapshot,item): raise ValueError('service run identity changed')
                    archive.put(item['reference']+'/polls/'+uuid.uuid4().hex+'.json',json_bytes(status_evidence(snapshot)))
                    if snapshot.get('status') in TERMINAL_FAILURE:
                        # A RUN THAT FAILED HOLDS ITS OWN ROW, LIKE ONE THAT FINISHED UNPRICED (JG,
                        # 21 Nov 2026: "one unpriced row mustn't stop the whole queue"). The reason
                        # is filed on both archives; nothing is resent; the other rows carry on.
                        why='run '+str(snapshot.get('status'))+': '+str(snapshot.get('error') or 'no reason given')
                        entry.update(phase='held',why=why,held_at=now(),automatic_resubmission=False)
                        archive.state(state)
                        archive.event('ROW FAILED - CONTINUING',row=item['row'],run_id=entry['run_id'],why=why,AiCost_written=False)
                        continue
                    if snapshot.get('status')=='done':
                        try:
                            checked_price(snapshot,item)
                        except UnpricedResult as exc:
                            archive_unpriced(api,archive,item,entry,snapshot,str(exc))
                            entry.update(phase='held',why=str(exc),held_at=now(),automatic_resubmission=False)
                            archive.state(state)
                            archive.event('ROW UNPRICED - CONTINUING',row=item['row'],run_id=entry['run_id'],why=str(exc),AiCost_written=False)
                            continue
                        price=archive_result(api,archive,item,entry,snapshot)
                        entry.update(phase='archived',unit_gbp=str(price)); archive.state(state)
                        attempt_writeback(plan,archive,state,item,writer)
                        attempted_writebacks.add(item['reference'])
                    elif snapshot.get('status') in ('queued','running'): active+=1
                    else: raise RuntimeError('Unrecognised run status; no new submissions')
            if not pending: break
            if stop_file and Path(stop_file).exists():
                archive.event('STOP REQUESTED',note='No new submissions. Existing runs are not cancelled; resume to collect.')
                return 2
            if active < at_once:
                settled_check_build(api,expected,at_once,sleep=sleep)
                for item in items:
                    if item['reference'] in state['entries']: continue
                    if needs_proof and item['row'] not in proof_rows:
                        require_approved_proof(plan,archive,state,proof_rows,expected_build=proof_execution_build or expected)
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
            if all(state['entries'].get(i['reference'],{}).get('phase') in ('done','archived','held') for i in items): break
            print(f'{now()} WAITING: {active} active; '+str(sum(e.get('phase')=='done' for e in state['entries'].values()))+f'/{len(items)} written. State saved on C and K.',flush=True)
            sleep(poll_seconds)
    except BaseException as exc:
        # Do not try to mutate/restart any engine. Durable state owns all accepted IDs.
        try: archive.event('STOPPED',reason=type(exc).__name__,note='No automatic resubmission; see state and journals. Already-started jobs remain on runners.')
        except OSError: pass
        raise
    waiting=[i['row'] for i in items if state['entries'][i['reference']]['phase']=='archived']
    held=[{'row':i['row'],'run_id':state['entries'][i['reference']].get('run_id'),
           'why':state['entries'][i['reference']].get('why')} for i in items if state['entries'][i['reference']]['phase']=='held']
    archive.put('hold-reports/'+uuid.uuid4().hex+'.json',json_bytes(held))
    archive.event('FINISHED WITH HOLDS' if held else ('ESTIMATES SAVED' if waiting else 'COMPLETE'),written=len(items)-len(waiting)-len(held),
                  estimates_saved=len(items)-len(held),pending_writeback_rows=waiting,held_rows=held,
                  note='Provisional estimates on C and K. Pending AiCost is not a pricing failure; retry --writeback-only. No estimate approved.')
    return 4 if held else (3 if waiting else 0)


def validate_health_only_proof_build(repo, old, expected, git=None, reviewed_paths=(), statement=''):
    """Explicit proof carry-forward ONLY for a reporting-only release, or one whose every
    other changed path a person has named and vouched for.

    No ledger build is rewritten. A path outside the reporting-only set that is NOT named
    in reviewed_paths refuses; a named path that did not change refuses too (the statement
    must be about this release and no other). Test files cannot change a price and are not
    counted. The decision, the paths and the exact commit are returned to be archived.
    """
    git = git or (lambda *args: subprocess.check_output(['git',*args],cwd=repo,text=True).strip())
    if not re.fullmatch(r'[a-fA-F0-9]{7,40}',old): raise ValueError('proof execution build must be bare hash')
    before=git('rev-parse',old+'^{commit}'); after=git('rev-parse',expected+'^{commit}')
    if git('merge-base',before,after)!=before: raise ValueError('proof build is not an ancestor')
    allowed={'tools/runner/sdi_estimate_runner.py','sdi-intelligence-backend/estimate_routes.py',
             'src/tti_concept_batch.py','tests/test_busy_runner_process_health.py',
             'tests/test_health_only_proof_carry_forward.py'}
    changed=set(git('diff','--name-only',before,after).splitlines())
    if not changed: raise ValueError('Not a reporting-only release: proof carry-forward refused')
    extra={p for p in changed-allowed if not p.startswith('tests/')}
    reviewed=set(reviewed_paths or ())
    if extra and not reviewed: raise ValueError('Not a reporting-only release: proof carry-forward refused')
    if extra-reviewed: raise ValueError('changed paths not named in the reviewed carry-forward: '+', '.join(sorted(extra-reviewed)))
    if reviewed-changed: raise ValueError('reviewed carry-forward names paths this release did not change: '+', '.join(sorted(reviewed-changed)))
    if reviewed and len(' '.join(str(statement).split()))<40:
        raise ValueError('a reviewed carry-forward must say, in a full sentence, why the named changes leave the proofs valid')
    out={'proof_execution_build':before,'resume_build':after,'changed_paths':sorted(changed),
         'basis':'Explicit operator carry-forward of unchanged pricing proofs after reporting-only integration'}
    if reviewed:
        out.update(reviewed_paths=sorted(reviewed),statement=' '.join(str(statement).split()),
                   reviewed_by=os.getenv('USERNAME') or os.getenv('USER') or 'explicit operator',
                   basis='Explicit reviewed operator carry-forward: the named changes do not alter the proofs\' source, inputs or prices')
    return out


def argument_parser():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--sheet',required=True,help='Tracker workbook path')
    p.add_argument('--sheet-name',default='Milwaukee')
    p.add_argument('--plan-output',required=True,help='Local JSON plan; --execute is separately required')
    p.add_argument('--execute',action='store_true')
    p.add_argument('--writeback-only',action='store_true',help='Retry archived AiCost updates only. No API calls or submissions; exit 3 means tracker updates remain pending.')
    p.add_argument('--local-root',default=str(ROOT/'output'/'tti_concepts'))
    p.add_argument('--shared-root',help='Explicit UNC folder on the K share, inside service allowed roots')
    p.add_argument('--server',default='http://localhost:8071')
    p.add_argument('--expected-build',help='Bare reviewed production commit; required for execution')
    p.add_argument('--proof-execution-build',help='Explicit original proof build for a reviewed health-only release; strict changed-path/ancestor check, no ledger rewrite')
    p.add_argument('--carry-forward-reviewed-paths',help='With --proof-execution-build: every changed path outside the reporting-only set, comma separated, that a person has reviewed and vouches for')
    p.add_argument('--carry-forward-statement',help='With --carry-forward-reviewed-paths: why those changes leave the two proofs valid. Archived with the exact commit')
    p.add_argument('--at-once',type=int,choices=(1,2),default=2)
    p.add_argument('--rows',help='Optional comma-separated eligible rows for an initial proof; omit for the full plan')
    p.add_argument('--assume-missing-quantity-one','--blank-quantity-as-one',dest='assume_missing_quantity_one',action='store_true',help='Explicit user ruling: blank/zero/unreadable concept quantities are one; original values and assumptions retained')
    p.add_argument('--proof-rows',default='6,12',help='Exactly two distinct pilot rows: one image and one description-only. Default: 6,12')
    p.add_argument('--approve-proof',action='store_true',help='After human review, validate and approve the two archived proofs ONLY; never submits or writes AiCost')
    p.add_argument('--approval-basis',help='With --approve-proof only, when the two proofs have NOT been looked at: whose instruction the approval rests on. Filed in place of the statement that they were reviewed')
    p.add_argument('--no-pack-rows',help='Comma-separated DRAWING rows to price from their description and pictures because no drawing pack was found. Requires --no-pack-ledger')
    p.add_argument('--no-pack-ledger',help="The drawing pricer's ledger, or the status report of its pack check on THIS workbook. Each --no-pack-rows row must be recorded there as 'needs drawing' under the drawing number the row carries")
    p.add_argument('--retry-held',help='Comma-separated HELD rows to send again, each as a new numbered attempt; the held attempt and its run are kept. Runs those rows only')
    p.add_argument('--stop-file',help='Stops further submissions, never cancels accepted jobs')
    return p


def main(argv=None):
    p=argument_parser(); a=p.parse_args(argv)
    if sum((a.execute,a.approve_proof,a.writeback_only,bool(a.retry_held)))>1: p.error('--execute, --approve-proof, --writeback-only and --retry-held are mutually exclusive')
    if a.approval_basis and not a.approve_proof: p.error('--approval-basis belongs with --approve-proof')
    if (a.carry_forward_reviewed_paths or a.carry_forward_statement) and not a.proof_execution_build:
        p.error('--carry-forward-reviewed-paths and --carry-forward-statement go with --proof-execution-build')
    try: proof_rows=tuple(int(v.strip()) for v in a.proof_rows.split(','))
    except ValueError: p.error('--proof-rows must name two row numbers')
    if len(proof_rows)!=2 or len(set(proof_rows))!=2: p.error('--proof-rows must name two DISTINCT row numbers')
    no_pack=None
    if a.no_pack_rows or a.no_pack_ledger:
        if not (a.no_pack_rows and a.no_pack_ledger): p.error('--no-pack-rows and --no-pack-ledger go together')
        try: named=[int(v.strip()) for v in a.no_pack_rows.split(',')]
        except ValueError: p.error('--no-pack-rows must be row numbers')
        no_pack,refused=no_pack_rulings(a.no_pack_ledger,named,sheet=a.sheet)
        for n,why in refused: print(f'NO-PACK row {n} NOT accepted, so not priced: {why}',flush=True)
    plan,pictures=read_plan(a.sheet,a.sheet_name,assume_missing_quantity_one=a.assume_missing_quantity_one,no_pack=no_pack)
    if no_pack is not None:
        print('No drawing pack, priced from description and pictures: rows '+str([r['row'] for r in plan['rows'] if r.get('no_pack')]),flush=True)
    if Path(a.plan_output).resolve()==Path(a.sheet).resolve(): raise ValueError('plan output cannot replace workbook')
    atomic(a.plan_output,json_bytes(plan))
    ready=[r for r in plan['rows'] if r['state']=='eligible']; held=[r['row'] for r in plan['rows'] if r['state'].startswith('held:')]
    print(f'PLAN ONLY until --execute: {len(ready)} eligible ({sum(bool(r["images"]) for r in ready)} with pictures; {sum(not r["images"] for r in ready)} description-only); held {held}',flush=True)
    print('Quantity ONE assumed for rows: '+str([r['row'] for r in ready if r.get('quantity_assumed')]),flush=True)
    if not a.execute and not a.approve_proof and not a.writeback_only and not a.retry_held: return 0
    if not a.shared_root or not a.expected_build: p.error('execution/approval requires --shared-root and --expected-build')
    if not a.shared_root.startswith('\\\\'): p.error('use the K share UNC path, not a mapped drive invisible to runners')
    # Load settings without logging any values. No service processes or .env files are changed.
    from dotenv import load_dotenv
    load_dotenv(ROOT/'.env',override=False)
    local_first=os.getenv('SDI_ESTIMATE_LOCAL_FIRST','').strip().lower() in {'1','true','yes','on'}
    if not local_first and not Path(a.shared_root).parent.is_dir(): raise OSError('shared parent is unavailable; connect VPN first')
    expected=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    if not expected.startswith(a.expected_build): raise RuntimeError('checkout is not the requested build')
    if subprocess.check_output(['git','status','--porcelain','--untracked-files=no'],cwd=ROOT,text=True).strip():
        raise RuntimeError('tracked local edits: integrate and test before running')
    base=Path(os.getenv('SDI_STATE_DIR') or str(Path(os.getenv('PROGRAMDATA',str(Path.home())))/'SDI Intelligence'))
    key=sha(str(Path(a.sheet).resolve()).casefold().encode())[:20]
    archive=Archive(Path(a.local_root)/key,Path(a.shared_root)/key,stop_file=a.stop_file)
    archive.sync_pending()
    if a.proof_execution_build:
        bridge=validate_health_only_proof_build(ROOT,a.proof_execution_build,a.expected_build,
            reviewed_paths=[x.strip() for x in (a.carry_forward_reviewed_paths or '').split(',') if x.strip()],
            statement=a.carry_forward_statement or '')
        # THE SAME DECISION FILES ONCE (reviewer, 21 Nov 2026): the approval call and the
        # execute call both record it, and an immutable archive refuses a second copy that
        # differs by so much as a timestamp. The content carries no clock, and the name
        # carries its own digest, so the same decision is the same file every time and a
        # different decision for the same build sits beside it, never over it.
        archive.put('proof-build-carry-forward/'+bridge['resume_build']+'-'+sha(canonical(bridge).encode('utf-8'))[:12]+'.json',json_bytes(bridge))
    if a.approve_proof:
        from tti_concept_proof import approve_proof
        # Review/approval writes only audit files, so it can happen while the
        # separately authorised nine drawing jobs hold the global batch claim.
        approve_proof(archive,plan,proof_rows,expected_build=a.proof_execution_build or a.expected_build,basis=a.approval_basis)
        return 0
    with exclusive_claim(base/'tti'/'batch.lock'):
        if a.writeback_only:
            return retry_writebacks(plan,archive,None if not a.rows else [int(v.strip()) for v in a.rows.split(',')])
        if a.retry_held:
            if a.rows: p.error('--retry-held names its own rows; do not give --rows as well')
            try: rows=[int(v.strip()) for v in a.retry_held.split(',')]
            except ValueError: p.error('--retry-held must be row numbers')
            retire_for_retry(archive,plan,rows,proof_rows=proof_rows,basis='Operator retry of held rows after the picture-reader settings were corrected')
            return run_batch(plan,pictures,archive,Client(a.server,os.getenv('SDI_API_KEY',''),archive.roots[1],a.stop_file),a.expected_build,a.at_once,
                             stop_file=a.stop_file,selected_rows=rows,proof_rows=proof_rows,proof_execution_build=a.proof_execution_build)
        return run_batch(plan,pictures,archive,Client(a.server,os.getenv('SDI_API_KEY',''),archive.roots[1],a.stop_file),a.expected_build,a.at_once,
                         stop_file=a.stop_file,selected_rows=None if not a.rows else [int(v.strip()) for v in a.rows.split(',')],proof_rows=proof_rows,proof_execution_build=a.proof_execution_build)


if __name__=='__main__':
    try: sys.exit(main())
    except InterruptedError as exc:
        print('PAUSED: '+str(exc),file=sys.stderr,flush=True); sys.exit(2)
    except Exception as exc:
        print('STOP: '+str(exc),file=sys.stderr,flush=True); sys.exit(1)
