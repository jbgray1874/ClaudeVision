"""Fail-closed proof gate: two completed, archived and explicitly reviewed runs.

No API calls, pricing, queueing, workbook changes, or service changes here.
An ordinary exit code or an arbitrary PASS text file is NOT an approval.
"""
from __future__ import annotations
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import re

from tti_concept_inputs import canonical,read_plan,sha,units
from tti_concept_writeback import money


APPROVAL='proof-approval.json'


def same_build(a,b):
    return (bool(re.fullmatch(r'[0-9a-fA-F]{7,40}',str(a))) and bool(re.fullmatch(r'[0-9a-fA-F]{7,40}',str(b)))
            and (str(a).lower().startswith(str(b).lower()) or str(b).lower().startswith(str(a).lower())))


def same_bytes(archive,relative):
    p=Path(relative)
    if p.is_absolute() or '..' in p.parts: raise ValueError('unsafe proof file name')
    values=[(root/p).read_bytes() for root in archive.roots]
    if values[0]!=values[1]: raise ValueError('C/K proof evidence disagrees: '+str(relative))
    return values[0]


def same_json(archive,relative): return json.loads(same_bytes(archive,relative))


def context(archive,current_plan):
    saved=same_json(archive,'plan.json'); state=same_json(archive,'state.json')
    if saved['workbook']!=current_plan['workbook'] or saved['sheet']!=current_plan['sheet'] or state['workbook']!=saved['workbook']:
        raise ValueError('proof belongs to another workbook')
    if bool(saved.get('assume_missing_quantity_one'))!=bool(current_plan.get('assume_missing_quantity_one')):
        raise ValueError('proof quantity policy differs from requested batch')
    return saved,state


def proof_evidence(plan,archive,state,proof_rows):
    proof_rows=tuple(sorted(proof_rows))
    if len(proof_rows)!=2 or len(set(proof_rows))!=2: raise ValueError('exactly two distinct proof rows required')
    # Validate the files that the running batch actually owns, not an arbitrary marker.
    saved,stored=context(archive,plan)
    if stored!=state: raise ValueError('proof ledger changed during checking')
    chosen=[next((r for r in saved['rows'] if r['row']==n),None) for n in proof_rows]
    if any(r is None or r['state']!='eligible' for r in chosen): raise ValueError('proof row is not eligible in the archived plan')
    if sum(bool(r['images']) for r in chosen)!=1: raise ValueError('proof needs one image row AND one description-only row')
    current,_=read_plan(saved['workbook'],saved['sheet'],assume_missing_quantity_one=bool(saved.get('assume_missing_quantity_one')))
    evidence=[]
    for item in chosen:
        entry=state['entries'].get(item['reference'],{})
        rid=entry.get('run_id','')
        if entry.get('phase') not in ('done','archived') or not re.fullmatch(r'[0-9a-fA-F]{8,64}',rid):
            raise ValueError(f"proof row {item['row']} is not complete and archived")
        if not same_build(entry.get('expected_build'),entry.get('expected_build')):
            raise ValueError('proof has no recorded execution build; reconcile before approval')
        row=next((r for r in current['rows'] if r['row']==item['row']),None)
        if row is None or row['fingerprint']!=item['fingerprint']: raise ValueError('proof source row changed')
        price=money(entry['unit_gbp'])
        if row['cost_before'] in (None,''):
            if entry['phase']=='done': raise ValueError('previously written proof AiCost is now missing')
        elif money(row['cost_before'])!=price:
            raise ValueError('proof AiCost does not match its unit price')
        base=item['reference']+'/'
        hashes={}
        def data(relative):
            value=same_bytes(archive,base+relative); hashes[relative]=sha(value); return value
        def js(relative): return json.loads(data(relative))
        if js('inputs/source-row.json')!=item: raise ValueError('archived proof row differs from frozen source')
        request=js('inputs/request.json')
        if (request.get('client')!='TTI' or request.get('drawing_number')!=item['reference']
                or units(request.get('units'))!=item['quantity'] or request.get('method')!='llm'
                or request.get('enquiry_brief')!=item['brief']
                or request.get('quantity_breaks')!=[item['quantity']]):
            raise ValueError('proof request does not match row/brief/quantity')
        if data('inputs/ENQUIRY_BRIEF.txt').decode('utf-8')!=item['brief']: raise ValueError('proof brief changed')
        files=request.get('files',[])
        if len(files)!=len(item['images']): raise ValueError('proof request omitted/added pictures')
        for number,image in enumerate(item['images']):
            relative=f"inputs/{number+1:02d}-{image['cell']}-{image['sha256'][:12]}"+Path(image['member']).suffix.lower()
            expected=archive.roots[1]/base/relative
            if Path(files[number])!=expected: raise ValueError('proof image request points elsewhere')
            if sha(data(relative))!=image['sha256']: raise ValueError('proof picture bytes differ from source')
        audit=js('results/price-for-writeback.json')
        if (audit.get('run_id')!=rid or audit.get('source_fingerprint')!=item['fingerprint']
                or audit.get('source_row')!=item['row'] or units(audit.get('quantity'))!=item['quantity']
                or money(audit.get('unit_gbp'))!=price): raise ValueError('proof price audit mismatch')
        records=[]; workbooks=0
        for file in js('results/inventory.json'):
            if file.get('not_copied'): continue  # Customer quotation release gate stays intact.
            name=file.get('name','')
            if not name or Path(name).name!=name or '/' in name or '\\' in name or ':' in name:
                raise ValueError('unsafe proof deliverable')
            raw=data('results/'+name)
            if sha(raw)!=file.get('sha256') or len(raw)!=file.get('bytes'): raise ValueError('proof output changed after filing')
            if name.lower().endswith('_record.json'): records.append(json.loads(raw))
            if name.lower().endswith('.xlsx'): workbooks+=1
        if len(records)!=1 or not workbooks: raise ValueError('proof workbook/engine record not archived on both roots')
        q=records[0].get('requested_order_quantity',records[0].get('quantity'))
        if units(q)!=item['quantity']: raise ValueError('proof engine record has wrong quantity')
        snapshots=sorted((archive.roots[0]/base/'results').glob('status-*.json'))
        if not snapshots: raise ValueError('proof finished status missing')
        for path in snapshots:
            s=js('results/'+path.name)
            if (s.get('run_id')!=rid or s.get('client')!='TTI' or s.get('drawing_number')!=item['reference']
                    or s.get('status')!='done' or s.get('error') or s.get('price_validated') is not True
                    or units(s.get('units'))!=item['quantity']): raise ValueError('proof run identity or finished status mismatch')
            quoted=[money(p.get('unit_gbp')) for p in s.get('quantity_prices',[]) if units(p.get('quantity'))==item['quantity']]
            if s.get('quantity_prices') and not quoted: raise ValueError('proof requested quantity missing from prices')
            if any(p!=price for p in quoted) or (not quoted and money(s.get('engine_price_gbp'))!=price):
                raise ValueError('proof finished unit price differs from write-back')
        evidence.append({'row':item['row'],'reference':item['reference'],'run_id':rid,'quantity':item['quantity'],
                         'expected_build':entry['expected_build'],
                         'unit_gbp':str(price),'cost_cell':item['cost_cell'],'source_fingerprint':item['fingerprint'],
                         'picture_count':len(item['images']),'file_hashes':hashes})
    return {'workbook':saved['workbook'],'sheet':saved['sheet'],'server':state['server'],
            'proof_rows':list(proof_rows),'proofs':evidence}


def require_approved_proof(plan,archive,state,proof_rows,expected_build=None):
    try:
        approved=same_json(archive,APPROVAL)
        if approved.get('schema')!='tti_concept_proof.v1' or approved.get('decision')!='PASS' or not approved.get('reviewed_by'):
            raise ValueError('no explicit reviewed PASS approval')
        evidence=proof_evidence(plan,archive,state,proof_rows)
        if expected_build and any(not same_build(p['expected_build'],expected_build) for p in evidence['proofs']):
            raise ValueError('proofs were not run on the requested build')
        if approved.get('evidence')!=evidence or approved.get('evidence_sha256')!=sha(canonical(evidence).encode('utf-8')):
            raise ValueError('approval is stale or belongs to different proof runs/evidence')
        return approved
    except (OSError,ValueError,KeyError,TypeError) as exc:
        raise RuntimeError('PROOF NOT APPROVED: remaining concept rows will NOT start. '+str(exc)) from exc


def approve_proof(archive,current_plan,proof_rows,expected_build=None,basis=None):
    """Explicit operator confirmation AFTER reviewing both actual estimates.

    Mechanical checks cannot judge a concept's dimensions, omissions or price
    plausibility. Never call --approve-proof automatically from the queue chain.

    THE RECORD SAYS WHAT HAPPENED (JG, 21 Nov 2026: "no more one or two jobs ... all in one
    queue"). When the owner instructs the rows to run on without looking at the two proofs
    first, that is given as `basis` and filed in place of the statement that they were
    reviewed. The mechanical checks are the same either way; only the claim differs, and a
    review that did not happen is never recorded as one.
    """
    plan,state=context(archive,current_plan)
    evidence=proof_evidence(plan,archive,state,proof_rows)
    if not same_build(evidence['proofs'][0]['expected_build'],evidence['proofs'][1]['expected_build']):
        raise ValueError('the two proofs were run on different builds')
    if expected_build and any(not same_build(p['expected_build'],expected_build) for p in evidence['proofs']):
        raise ValueError('proofs were not run on the requested build')
    report={'schema':'tti_concept_proof.v1','decision':'PASS','evidence':evidence,
            'evidence_sha256':sha(canonical(evidence).encode('utf-8')),
            'reviewed_by':os.getenv('USERNAME') or os.getenv('USER') or 'explicit operator',
            'reviewed_at':datetime.now(timezone.utc).isoformat(),
            'meaning':'Operator confirms reviewing image inclusion, assumptions, quantities, unit prices and outputs for BOTH proofs.'}
    if basis is not None:
        basis=' '.join(str(basis).split())
        if len(basis)<40: raise ValueError('an approval that is not a review must say, in a full sentence, whose instruction it rests on')
        report.update(meaning=basis,proofs_reviewed_by_a_person=False)
    if any((root/APPROVAL).exists() for root in archive.roots):
        return require_approved_proof(plan,archive,state,proof_rows,expected_build=expected_build)
    archive.put(APPROVAL,(canonical(report)+'\n').encode('utf-8'))
    archive.event('PROOF APPROVED',rows=list(sorted(proof_rows)),run_ids=[p['run_id'] for p in evidence['proofs']],
                  note='No jobs submitted. Later full batch must revalidate this evidence.')
    return report
