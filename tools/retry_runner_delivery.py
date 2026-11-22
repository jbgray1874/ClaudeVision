"""List saved C results; --retry files the SAME run IDs. Never queues/re-executes."""
import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent/'runner'))
import runner_delivery as delivery
import sdi_estimate_runner as runner


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--engine-root',required=True)
    p.add_argument('--runner-id',required=True)
    p.add_argument('--server',default=os.getenv('SDI_SERVER','http://localhost:8071,http://localhost:8072'))
    p.add_argument('--retry',action='store_true',help='Explicit filing/reporting only; same IDs, no engine or Excel')
    a=p.parse_args()
    root=delivery.local_root(a.engine_root,a.runner_id)
    reports=[]
    for path in sorted(root.glob('*/delivery.json')):
        state=delivery.load(path)
        reports.append({'run_id':state['run_id'],'phase':state['phase'],
                        'drawing':state['job']['drawing_number'],'files':len(state['inventory']),
                        'local_manifest':str(path),'reason':state.get('reason',state.get('last_filing_error',''))})
    uncertain=[{'run_id':p.parent.name,'local_marker':str(p),
                'meaning':'Execution began but no delivery inventory was sealed. Inspect saved C files; never resubmit automatically.'}
               for p in sorted(root.glob('*/execution-started.json')) if not (p.parent/'delivery.json').exists()]
    print(json.dumps({'mode':'filing retry' if a.retry else 'read-only report','entries':reports,
                      'execution_markers_without_delivery':uncertain,'new_jobs':0}))
    if not a.retry:return 0
    import requests
    headers={'X-SDI-Key':os.getenv('SDI_API_KEY','')} if os.getenv('SDI_API_KEY') else {}
    good=runner.resume_deliveries(requests,[s.strip().rstrip('/') for s in a.server.split(',') if s.strip()],
        headers,a.runner_id,Path(a.engine_root),Path(sys.executable))
    return 0 if good else 3


if __name__=='__main__':raise SystemExit(main())
