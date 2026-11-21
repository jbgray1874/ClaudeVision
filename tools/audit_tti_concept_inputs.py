"""Offline concept input audit. No API/queue/CAD; write-back exercised on a marked COPY only."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys
import zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from tti_concept_inputs import read_plan,sha,canonical
from tti_concept_writeback import write_cost


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--workbook',required=True)
    p.add_argument('--output',required=True,help='New private verification folder, outside git')
    p.add_argument('--exercise-writeback',action='store_true')
    p.add_argument('--assume-missing-quantity-one','--blank-quantity-as-one',dest='assume_missing_quantity_one',action='store_true')
    a=p.parse_args(); source=Path(a.workbook).resolve(); out=Path(a.output).resolve()
    if out.exists(): raise SystemExit('Use a NEW verification folder; nothing overwritten')
    raw=source.read_bytes(); plan,pictures=read_plan(source,assume_missing_quantity_one=a.assume_missing_quantity_one)
    if sha(raw)!=plan['workbook_sha256']: raise RuntimeError('source changed during read')
    out.mkdir(parents=True)
    (out/'plan.PRIVATE.json').write_text(canonical(plan)+'\n',encoding='utf-8')
    eligible=[r for r in plan['rows'] if r['state']=='eligible']
    report={'source_sha256':sha(raw),'counts':dict(Counter(r['state'] for r in plan['rows'])),
            'picture_cells':sum(map(len,pictures.values())),
            'eligible_with_pictures':sum(bool(r['images']) for r in eligible),
            'eligible_description_only':sum(not r['images'] for r in eligible),
            'quantity_holds':[r['row'] for r in plan['rows'] if r['state']=='held: quantity'],
            'quantity_one_assumptions':[r['row'] for r in plan['rows'] if r.get('quantity_assumed')],
            'live_service_called':False,'production_workbook_written':False}
    previews=[]
    for item in [r for r in eligible if r['images']][:2]:
        for pic in pictures[item['row']]:
            name='source-'+pic.cell+Path(pic.member).suffix
            (out/name).write_bytes(pic.data)
            previews.append({'row':item['row'],'cell':pic.cell,'file':name,'sha256':pic.sha256,'description':item['description']})
    report['preview_sources']=previews
    if a.exercise_writeback:
        copy=out/'VALIDATION-ONLY-NOT-AN-ESTIMATE.xlsx'; copy.write_bytes(raw)
        item=eligible[0]; result=write_cost(copy,item,'12.34',plan['sheet'])
        with zipfile.ZipFile(source) as before,zipfile.ZipFile(copy) as after:
            changed=[n for n in before.namelist() if before.read(n)!=after.read(n)]
            assert changed==[plan['sheet_member']]
            b=before.read(plan['sheet_member']); c=after.read(plan['sheet_member'])
            from tti_concept_writeback import patch_cell
            assert c==patch_cell(b,item['cost_cell'],'12.34')
        new, pics=read_plan(copy,assume_missing_quantity_one=a.assume_missing_quantity_one)
        assert [p.record() for row in pictures.values() for p in row]==[p.record() for row in pics.values() for p in row]
        report['copy_only_writeback']={'cell':item['cost_cell'],'synthetic_test_value':'12.34 - NOT A PRICE',
                                      'only_changed_zip_member':changed,'pictures_preserved':True,'audit':result}
    if source.read_bytes()!=raw: raise RuntimeError('source workbook was changed by another process')
    report['source_unchanged']=True
    (out/'verification.json').write_text(canonical(report)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2,ensure_ascii=True))


if __name__=='__main__': main()
