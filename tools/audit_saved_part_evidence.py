"""Offline evidence-only audit. Never price a job or call CAD, Excel or services."""
import argparse
import copy
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from part_evidence_safety import prepare, unresolved


def audit(record):
    summary=copy.deepcopy(record)
    if not isinstance(summary.get('manufacturing_writeup'),dict):
        summary['manufacturing_writeup']={'parts':summary.get('parts') or []}
    parts=summary['manufacturing_writeup'].get('parts') or []
    quantities=[(p.get('part_number'),p.get('quantity'),p.get('quantity_source')) for p in parts]
    final_before=copy.deepcopy(summary.get('final_estimate'))
    prepare(summary)
    after=[(p.get('part_number'),p.get('quantity'),p.get('quantity_source')) for p in parts]
    if quantities!=after or summary.get('final_estimate')!=final_before:
        raise AssertionError('Evidence audit changed quantities or a saved price contract')
    return {'schema':'part_evidence_audit.v1','source_run_id':(record.get('run_provenance') or {}).get('service_run_id'),
            'quantities_unchanged':True,'saved_price_unchanged':True,'estimates_submitted':0,
            'issues':unresolved(summary),
            'withdrawn_evidence':[{ 'part':p.get('part_number'),'fields':p['withdrawn_evidence']}
                                   for p in parts if p.get('withdrawn_evidence')],
            'note':'Evidence audit only. No corrected estimate price has been produced.'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--record',type=Path,required=True)
    parser.add_argument('--report',type=Path)
    args=parser.parse_args()
    if args.report and args.report.resolve()==args.record.resolve():
        parser.error('The report must not overwrite the saved record')
    result=audit(json.loads(args.record.read_text(encoding='utf-8-sig')))
    if args.report:
        args.report.write_text(json.dumps(result,indent=2,ensure_ascii=True),encoding='utf-8')
    print(json.dumps({'source_run_id':result['source_run_id'],'quantities_unchanged':True,
        'saved_price_unchanged':True,'issues':len(result['issues']),'estimates_submitted':0}))


if __name__=='__main__':
    main()
