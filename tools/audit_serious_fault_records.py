"""Offline regression of saved purchase/gauge evidence. Never a corrected estimate or approval."""
import argparse
import contextlib
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import socket
import sys
from unittest.mock import patch

os.environ['SDI_OFFLINE']='1'
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))


def audit(led_path, board_path, charging_path, decisions_path):
    import route_compiler as rc
    import purchase_evidence as pe
    import batch_job_changes as bj
    from customer_changes import build_changes_file, apply_customer_changes
    paths=[Path(p) for p in (led_path,board_path,charging_path,decisions_path)]
    led,board,charging=[json.loads(p.read_text(encoding='utf-8-sig')) for p in paths[:3]]
    report={'inputs':[{'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in paths],
            'not_an_approved_estimate':True, 'network_calls':0, 'jobs_submitted':0}
    graph=rc.compile_route_without_pricing(copy.deepcopy(led))
    nodes={n['part_number']:n for n in graph['nodes']}
    targets={'12133-02-01X':6,'12133-02-01X-HANDED':6,
             '12133-05-GA':6,'12133-05-101':6,'12133-06-GA':3,'12133-06-101':3}
    actual={pn:{'quantity':nodes.get(pn,{}).get('qty_per_unit'),
                'kind':nodes.get(pn,{}).get('kind')} for pn in targets}
    parts=copy.deepcopy(led['parts'])
    pe.stamp_bom_purchase_references(parts,led['document_analysis']['bom_rows'])
    references={p['part_number']:p.get('purchase_reference') for p in parts if p['part_number'] in
                ('12133-02-01X','12133-02-01X-HANDED')}
    report['led']={'after':actual,'purchase_references':references,
                   'prices':'No supplier prices obtained by this audit; both hands need evidenced purchase rates.'}
    changes=bj.load_changes(paths[3],'TTI')['12757-00-GA']
    data,errors=build_changes_file(changes,'12757-00-GA')
    if errors:raise ValueError(errors)
    parts=copy.deepcopy(board['parts'])
    applied=apply_customer_changes(parts,data)
    gauges={p['part_number']:{'mm':p['normalized_thickness_mm'],'source':p.get('thickness_source')}
            for p in parts if p['part_number'] in ('12757-01-11G','12757-02-11G','12757-02-14G')}
    report['board']={'after':gauges,'decision':applied,
                     'basis':'Issued drawing says 1 mm. User instructs 2 mm; not a misread drawing.'}
    buys=[{'part_number':p['part_number'],'qty_per_unit':p.get('qty_per_unit'),'kind':p.get('kind')}
          for p in charging['costed_job']['lines'] if any(t in p['part_number'] for t in ('CHARGING MODULE','DOCK PSU'))]
    report['charging']={'purchases':buys,'prices':'No prices invented. PSU specification explicitly says GUESS.'}
    report['passed']=(all(actual[p]['quantity']==q for p,q in targets.items())
        and all(actual[p]['kind']=='bought_in' for p in references)
        and len(references)==2 and all((v or {}).get('code')=='ADVALU-006' for v in references.values())
        and len(gauges)==3 and all(v=={'mm':2.0,'source':'customer_change'} for v in gauges.values())
        and not applied['not_applied'] and len(buys)==2
        and all(b['qty_per_unit']==30 and b['kind']=='bought_in' for b in buys))
    return report


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for flag in ('led-record','board-record','charging-record','decisions','output'):
        ap.add_argument('--'+flag,required=True,type=Path)
    a=ap.parse_args()
    inputs=(a.led_record,a.board_record,a.charging_record,a.decisions)
    if a.output.resolve() in {p.resolve() for p in inputs} or a.output.exists():
        ap.error('Output must be a new report, not an existing file or an input')
    def no_network(*args,**kwargs):raise AssertionError('Offline audit attempted network access')
    with patch.object(socket.socket,'connect',no_network),contextlib.redirect_stdout(io.StringIO()):
        report=audit(*inputs)
    a.output.write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
    print('PASS' if report['passed'] else 'FAIL', str(a.output))
    print('No CAD reads, supplier research, queue, deployment, source or tracker writes. Not a corrected price.')
    return 0 if report['passed'] else 1


if __name__=='__main__':sys.exit(main())
