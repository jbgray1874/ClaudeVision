"""Replay external 20 Nov evidence; no CAD, prices, services or source writes."""
from pathlib import Path
import argparse
import contextlib
import copy
import hashlib
import io
import json
import os
import socket
import sys
from unittest.mock import patch
os.environ['SDI_OFFLINE']='1'
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import document_builder as db
import route_compiler as rc
from source_connectors import solidworks as sw
from source_connectors.llm_full_job import apply_full_job_to_pre_estimate
from bom_tree import drawn_counts_by_code

TARGETS={'12133-05-GA':6,'12133-05-101':6,
         '12133-06-GA':3,'12133-06-101':3}
TARGETS.update({f'12133-05-{i:02}M':6 for i in range(1,5)})
TARGETS.update({f'12133-06-{i:02}M':3 for i in range(1,6)})


def drawing_evidence(folder):
    import pymupdf
    evidence=[]
    for code,pages in [('12133-02-GA',(0,1,2)),('12133-05-GA',(0,1)),
                       ('12133-06-GA',(0,1))]:
        candidates=[p for p in folder.iterdir() if p.suffix.lower()=='.pdf'
                    and p.name.upper().startswith(code+'_')]
        if len(candidates)!=1: raise AssertionError(f'{code}: expected one PDF, found {len(candidates)}')
        path=candidates[0]
        with pymupdf.open(path) as doc:
            text=[doc[i].get_text() for i in pages]
        if code=='12133-02-GA':
            assert "GLASS' & CAP" in text[0] and "GLASS' & WOOL HAT" in text[0]
            assert '12133-05-GA' in text[1]
        else:
            assert code in text[0] and code.replace('-GA','-101') in text[1]
        evidence.append({'file':path.name,'pages':[i+1 for i in pages],
                         'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
    return evidence


def replay(record_path,drawings):
    raw=record_path.read_bytes()
    r=json.loads(raw.decode('utf-8-sig'))
    assert r['declared_product']=='12133-00-GA'
    evidence=drawing_evidence(drawings)
    summary=copy.deepcopy(r)
    # Rebuild identities from SAVED original page readings and printed BOM rows.
    # Do not reuse the already-merged priced parts or patch their quantities.
    parts=db.build_part_index(summary)
    apply_full_job_to_pre_estimate(parts,dict(r['llm_full_extract'],found=True))
    n=r['solidworks_native']
    job=sw.NativeJob(found=True,bom=[sw.NativeBomRow(**x) for x in n['bom']],
        hierarchy=copy.deepcopy(n['hierarchy']),
        assembly_pns=sorted(set(n['hierarchy']) | {x['part_number'] for x in n['bom'] if x['is_assembly']}),
        meta={'top_assembly':n['top_assembly']})
    sw.apply_native_to_pre_estimate(parts,job,
        drawn_counts=drawn_counts_by_code(summary['document_analysis']['bom_rows']))
    sw.apply_native_hierarchy_to_parts(parts,job)
    summary['manufacturing_writeup']['parts']=parts
    summary['parts']=parts
    # Old projection is a derivative, not an independent second BOM source.
    summary['document_analysis']['bay_bom_rows']=[]
    route=rc.compile_route_without_pricing(summary)
    nodes={x['part_number']:x for x in route['nodes']}
    recs={x['part_number']:x for x in parts}
    actual={pn:nodes.get(pn,{}).get('qty_per_unit') for pn in TARGETS}
    wrong=[pn for pn,q in TARGETS.items() if actual[pn]!=q]
    merges=[str(f) for p in parts for f in p.get('review_flags',[])
            if 'taken as ONE part' in str(f) and '12133-05-' in str(f) and '12133-06-' in str(f)]
    children={pn:[x['part_number'] for x in nodes.get(pn,{}).get('children',[])]
              for pn in ('12133-05-GA','12133-05-101','12133-06-GA','12133-06-101')}
    missing_links=[]
    for p,c in [('12133-05-GA','12133-05-101'),('12133-06-GA','12133-06-101')]:
        if c not in children[p]: missing_links.append([p,c])
    cross_links=[(p,c) for p,cs in children.items() for c in cs
                 if (p.startswith('12133-05-') and c.startswith('12133-06-'))
                 or (p.startswith('12133-06-') and c.startswith('12133-05-'))]
    before={x['part_number']:x.get('qty_per_unit') for x in r['costed_job']['lines']
            if x.get('part_number') in TARGETS}
    return {'record_sha256':hashlib.sha256(raw).hexdigest(),
            'source_engine_build':r.get('estimate_summary',{}).get('engine_build'),'drawing_evidence':evidence,
            'saved_costed_quantities':before,'replayed_quantities':actual,
            'expected':TARGETS,'wrong_quantities':wrong,'wrong_identity_merges':merges,
            'assembly_children':children,'missing_links':missing_links,'cross_links':cross_links,
            'new_parent_quantity_evidence':{pn:{k:recs.get(pn,{}).get(k) for k in
                ('quantity','quantity_source','quantity_total_per_unit','quantity_total_per_unit_product')}
                for pn in ('12133-05-GA','12133-06-GA')},
            'passed':not (wrong or merges or missing_links or cross_links),
            'drawing_review_warning':(
                'Product-display PDF page 3 shows the wool-hat variant but its table repeats '
                'the 05-GA cap-holder reference. Preserve this discrepancy for drawing-office '
                'review. The separate 06 drawings and saved native totals support 3 wool holders; '
                'do not merge the 05 and 06 identities because of that repeated reference.'),
            'limitations':['Saved original PDF readings and normalized model BOM/hierarchy replayed; no fresh CAD read.',
                           'The drawing pages were visually checked separately; text assertions alone do not prove geometry.',
                           '02-101 covers multiple configurations: normalized edge factors reconcile product totals, not an instruction that every physical module has the same holder mix.',
                           'No costing, Excel recalculation, print or mirrored LED fix is performed by this audit.']}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--record',type=Path,required=True)
    ap.add_argument('--drawings',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args()
    if args.record.resolve()==args.output.resolve(): ap.error('output must not overwrite record')
    def forbidden(*a,**k): raise AssertionError('Offline audit attempted network access')
    with patch.object(socket.socket,'connect',forbidden),contextlib.redirect_stdout(io.StringIO()):
        report=replay(args.record,args.drawings)
    args.output.write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
    print('PASS' if report['passed'] else 'FAIL',report['replayed_quantities'])
    print('Report:',args.output)
    print('No pricing, CAD, queue, publish or source writes.')
    return 0 if report['passed'] else 1

if __name__=='__main__': sys.exit(main())
