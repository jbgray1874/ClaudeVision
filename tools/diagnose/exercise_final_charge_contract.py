"""Break a saved run on purpose, nine ways per traced section line, and prove the engine's
own final-charge contract catches each (D-579):

    python tools/diagnose/exercise_final_charge_contract.py record.json book.xlsx --engine-root . [--out proof.json]

The baseline must be applicable, passing and traced, or no proof is claimed. Every
mutation is made on a copy in memory; nothing on disk changes and nothing is re-costed.
It imports the engine's contract, never a copy of its rules. Detection proof only: it
executes no download or e-mail route and approves no price. --out is exclusive-create.
"""
import argparse
import copy
import hashlib
import importlib
import json
from pathlib import Path
import sys


def exercise(contract, doc, snapshot):
    baseline=contract.audit(doc,snapshot)
    result={'schema':'contract_mutation_proof.v1','baseline':baseline,'cases':[],'passed':False}
    if not baseline.get('applicable') or not baseline.get('passed') or not baseline.get('trace'):
        result['error']='Baseline must be applicable, passing and traced. No mutation proof claimed.'
        return result
    mutations={
        'remove_material':'section_material_row_missing_or_duplicate',
        'zero_material':'section_material_not_charged',
        'wrong_quantity':'section_charged_quantity_mismatch',
        'duplicate_material':'section_material_row_missing_or_duplicate',
        'wrong_identity':'section_material_row_missing_or_duplicate',
        'missing_cached_value':'saved_cell_differs_from_readback',
        'text_cached_value':'saved_cell_differs_from_readback',
        'remove_cut':'section_cut_not_charged',
        'zero_cut_hours':'section_cut_not_charged',
    }
    for trace in baseline['trace']:
        for mutation, expected in mutations.items():
            d,s=copy.deepcopy(doc),copy.deepcopy(snapshot)
            final=d['final_estimate']; cell=trace['material_cells'][0]
            row=next(r for r in final['material_rows'] if r.get('charged_cell')==cell)
            if mutation=='remove_material': final['material_rows'].remove(row)
            elif mutation=='zero_material': row['total_value_gbp']=0
            elif mutation=='wrong_quantity': row['qty_per_unit']+=0.5
            elif mutation=='duplicate_material': final['material_rows'].append(copy.deepcopy(row))
            elif mutation=='wrong_identity': row['part_code']='__UNRELATED__'; row['description']='__UNRELATED__'
            elif mutation=='missing_cached_value': s['cells'][cell]=None
            elif mutation=='text_cached_value': s['cells'][cell]=str(s['cells'][cell])
            elif mutation=='remove_cut': final['labour_rows']=[r for r in final['labour_rows'] if r.get('charged_cell') not in trace['cut_cells']]
            elif mutation=='zero_cut_hours':
                for r in final['labour_rows']:
                    if r.get('charged_cell') in trace['cut_cells']: r['batch_hours']=0
            out=contract.audit(d,s); codes=sorted({i['code'] for i in out['issues']})
            result['cases'].append({'part':trace['part'],'mutation':mutation,'expected':expected,
                                    'observed':codes,'detected':not out['passed'] and expected in codes})
    result['passed']=all(c['detected'] for c in result['cases'])
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('record'); p.add_argument('workbook'); p.add_argument('--engine-root',required=True)
    p.add_argument('--out')
    a=p.parse_args(); sys.path.insert(0,str(Path(a.engine_root)/'src'))
    c=importlib.import_module('final_charge_contract')
    raw=Path(a.record).read_bytes(); doc=json.loads(raw.decode('utf-8-sig'))
    result=exercise(c,doc,c.snapshot_xlsx(a.workbook))
    result['record_sha256']=hashlib.sha256(raw).hexdigest()
    result['checker_sha256']=hashlib.sha256(Path(c.__file__).read_bytes()).hexdigest()
    result['note']='Technical detection proof only. No rates approved; no send/download routes executed.'
    text=json.dumps(result,indent=2,ensure_ascii=False,allow_nan=False)
    if a.out:
        with Path(a.out).open('x',encoding='utf-8') as f: f.write(text+'\n')
    print(text); return 0 if result['passed'] else 2

if __name__=='__main__': sys.exit(main())
