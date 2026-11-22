"""Prepare a validated per-runner C template cache. No service/VPN/job changes."""
import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent/'runner'))
import runner_delivery as delivery
from sdi_estimate_runner import workbook_template


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--engine-root',required=True)
    p.add_argument('--runner-id',required=True)
    p.add_argument('--source',default=None)
    p.add_argument('--prepare',action='store_true',help='Explicitly read the source and write only the local C cache')
    a=p.parse_args()
    root=delivery.local_root(a.engine_root,a.runner_id)/'templates'
    if not a.prepare:
        print(json.dumps({'mode':'plan only','cache':str(root),'source':a.source or workbook_template(),
                          'meaning':'No file copied, no setting changed, no service or job contacted.'}))
        return 0
    path,record=delivery.template_copy(a.source or workbook_template(),root,
        max_age_hours=float(os.getenv('SDI_TEMPLATE_CACHE_MAX_HOURS','24')))
    print(json.dumps({'mode':'local cache prepared','path':str(path),'sha256':record['sha256'],
                      'offline_cache':record['offline_cache'],'verified_at':record['verified_at'],
                      'structure':record['structure'],'jobs_submitted':0}))
    return 0


if __name__=='__main__':raise SystemExit(main())
