"""Private-input replay. Never reads CAD, queues work, researches prices or deploys."""
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
import document_builder as db
import route_compiler as rc
from source_connectors import solidworks as sw
from source_connectors.llm_full_job import apply_full_job_to_pre_estimate
from bom_tree import drawn_counts_by_code
import wb_populate as wb

TARGETS={'12133-02-01X':6,'12133-02-01X-HANDED':6,'12133-02-05G':6,
         '12133-05-GA':6,'12133-05-101':6,'12133-06-GA':3,'12133-06-101':3}
TARGETS.update({f'12133-05-{i:02}M':6 for i in range(1,5)})
TARGETS.update({f'12133-06-{i:02}M':3 for i in range(1,6)})

def load(path):
    data=path.read_bytes()
    return json.loads(data.decode('utf-8-sig')),hashlib.sha256(data).hexdigest()

def rebuild(r):
    s=copy.deepcopy(r)
    parts=db.build_part_index(s)
    apply_full_job_to_pre_estimate(parts,dict(r['llm_full_extract'],found=True))
    n=r['solidworks_native']
    job=sw.NativeJob(found=True,bom=[sw.NativeBomRow(**x) for x in n['bom']],
        hierarchy=copy.deepcopy(n['hierarchy']),
        assembly_pns=sorted(set(n['hierarchy'])|{x['part_number'] for x in n['bom'] if x['is_assembly']}),
        meta={'top_assembly':n['top_assembly']})
    sw.apply_native_to_pre_estimate(parts,job,drawn_counts=drawn_counts_by_code(s['document_analysis']['bom_rows']))
    sw.apply_native_hierarchy_to_parts(parts,job)
    s['manufacturing_writeup']['parts']=parts
    s['parts']=parts
    s['document_analysis']['bay_bom_rows']=[]
    rc.apply_canonical_evidence_to_parts(parts,s['llm_full_extract'],
        s['document_analysis']['bom_rows'],rc.job_drawing_numbers(s),
        rc._assembly_page_owners(s),summary=s)
    route=rc.compile_route_without_pricing(s)
    return s,route

def pdf_evidence(folder,prefix,pages,required):
    import pymupdf
    matches=[p for p in folder.iterdir() if p.suffix.lower()=='.pdf' and p.name.upper().startswith(prefix.upper())]
    if len(matches)!=1:raise AssertionError(f'Expected one {prefix} PDF, found {len(matches)}')
    p=matches[0]
    with pymupdf.open(p) as doc:text='\n'.join(doc[n-1].get_text() for n in pages)
    flat=' '.join(text.upper().split())
    for token in required:
        assert token.upper() in flat, (p.name,token)
    return {'file':str(p),'pages':pages,'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),
            'required_text':required,'text_check':'passed; visual review is documented separately'}

def replay(record,drawings,charging_record,charging_drawings):
    r,sha=load(record)
    s,route=rebuild(r)
    nodes={x['part_number']:x for x in route['nodes']}
    actual={pn:nodes.get(pn,{}).get('qty_per_unit') for pn in TARGETS}
    led=[x for x in nodes if '12133-02-01X' in x]
    before={x['part_number']:x.get('qty_per_unit') for x in r['costed_job']['lines'] if '12133-02-01X' in x['part_number']}
    purchased={pn:nodes.get(pn,{}).get('kind') for pn in ('12133-02-01X','12133-02-01X-HANDED')}
    estimates=r['estimate_summary']['part_estimates']
    source=next(x for x in estimates if x['part_number']=='12133-02-05G')
    # Exercise the real writer boundary on the saved print cost and rebuilt node.
    # Other unpriced lines are not sent to its price-research fallback in this offline audit.
    population={'nodes':[nodes['12133-02-05G']], 'issues':[], 'mode':'cutover'}
    with patch.object(wb,'canonical_route_payload',return_value=population):
        lines=wb.canonicalise_part_estimates_for_workbook({'assumed_job_quantity':r['assumed_job_quantity']},[copy.deepcopy(source)])
    printed=next(x for x in lines if x['part_number']=='12133-02-05G')
    pc=printed['print_calculator']
    extra_scrap=0 if wb.waste_already_in_price(printed) else .04
    line_charge=printed['unit_cost_gbp']*printed['quantity']*(1+extra_scrap)
    expected=(pc['run_cost_per_sheet_gbp']/pc['parts_per_sheet']*(1+pc['scrap'])*6
              +pc['setup_gbp']/r['assumed_job_quantity'])
    # A second route compilation must not bring back a self-child or phantom hand.
    again={x['part_number']:x for x in rc.compile_route_without_pricing(s)['nodes']}
    stable=all(again.get(pn,{}).get('qty_per_unit')==qty for pn,qty in actual.items())
    stable=stable and all(again[pn]['kind']==kind for pn,kind in purchased.items())
    purchases={p['part_number']:{k:p.get(k) for k in ('canonical_kind','is_assembly_parent','is_sub_assembly','is_bought_in')}
               for p in s['parts'] if p['part_number'] in purchased}
    c,csha=load(charging_record)
    charged=[x for x in c['costed_job']['lines'] if any(w in x['part_number'].upper() for w in ('CHARGING MODULE','DOCK PSU'))]
    cr=c['document_analysis']['bom_rows']
    charging_rows=[x for x in cr if any(w in str(x.get('part_number') or x.get('part_code')).upper() for w in ('CHARGING MODULE','DOCK PSU'))]
    evidence=[pdf_evidence(drawings,'12133-00-GA_', [4], ['12133-02-01X','HANDED','ADVALU-006']),
              pdf_evidence(drawings,'12133-02-GA_', [6,10], ['695','275','202','DISPLAY BOARD']),
              pdf_evidence(charging_drawings,'12713-01-Headset', [2], ['12713-01-103-SA','10']),
              pdf_evidence(charging_drawings,'12713-01-103', [1], ['Charging Module','Dock PSU','GUESS','3'])]
    passed=(actual==TARGETS and set(led)=={'12133-02-01X','12133-02-01X-HANDED'}
            and set(purchased.values())=={'bought_in'} and stable
            and all(not p['is_assembly_parent'] and p['is_bought_in'] for p in purchases.values())
            and abs(line_charge-expected)<.0001
            and pc['quantity_printed']==6*r['assumed_job_quantity'] and not extra_scrap
            and len(charged)==2 and all(x['qty_per_unit']==30 for x in charged))
    return {'passed':passed,'record_sha256':sha,'charging_record_sha256':csha,
            'drawings':evidence,'before_led_quantities':before,'after_quantities':actual,
            'expected_quantities':TARGETS,'led_kinds':purchased,'second_compile_stable':stable,
            'pre_cost_purchase_flags':purchases,
            'after_led_paths':{p:nodes[p]['qty_trail'] for p in purchased},
            'before_print':source['print_calculator'], 'after_print':pc,
            'print_charge_before_workbook_scrap':printed['unit_cost_gbp']*printed['quantity'],
            'extra_workbook_scrap':extra_scrap,'print_line_charge':line_charge,
            'charging_costed_lines':charged,'charging_drawing_rows':charging_rows,
            'limitations':['Offline replay of saved PDF/model readings, not a fresh CAD read or full priced rerun.',
                'LED supplier prices remain unresolved: six of EACH hand must be quoted.',
                'Calculator negative scrap and substrate inclusion remain questions; no rate changed.',
                '12713 requires 10 drawers x 3 modules and 3 PSUs = 30 each per trolley. Capacity x16 is not the purchase count.',
                'No supplier identities/prices invented for charging equipment. Dock PSU is explicitly GUESS.',
                'Neither complete estimate is approved by this replay.']}

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for k in ('record','drawings','charging-record','charging-drawings','output'):ap.add_argument('--'+k,type=Path,required=True)
    a=ap.parse_args()
    if a.output.resolve() in (a.record.resolve(),a.charging_record.resolve()):ap.error('Output must not overwrite an input')
    def forbidden(*args,**kw):raise AssertionError('Offline audit attempted network access')
    with patch.object(socket.socket,'connect',forbidden),contextlib.redirect_stdout(io.StringIO()):
        result=replay(a.record,a.drawings,a.charging_record,a.charging_drawings)
    a.output.write_text(json.dumps(result,indent=2,ensure_ascii=False,default=str),encoding='utf-8')
    print('PASS' if result['passed'] else 'FAIL',result['after_quantities'])
    print('Print line:',round(result['print_line_charge'],2),'Extra workbook scrap:',result['extra_workbook_scrap'])
    print('Report:',a.output)
    print('No CAD, pricing service, queue, publish, source or calculator writes.')
    return 0 if result['passed'] else 1

if __name__=='__main__':sys.exit(main())
