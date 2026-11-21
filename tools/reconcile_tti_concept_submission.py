"""Audit or explicitly retire ONE proven unaccepted POST; never deploys or queues."""
import argparse
import json
import os
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from tti_concept_batch import Archive, Client, atomic, json_bytes, read_json
from tti_concept_reconcile import audit, retire_unaccepted

ROOT = Path(__file__).resolve().parents[1]


def service_key(root=None):
    """The key the batch itself sends: the process setting, else this checkout's .env.
    Read the same way tti_concept_batch.main does. Never printed, never written."""
    from dotenv import load_dotenv
    load_dotenv(Path(root or ROOT)/'.env', override=False)
    return os.getenv('SDI_API_KEY', '')


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--local-archive',required=True)
    p.add_argument('--shared-archive',required=True)
    p.add_argument('--history-directory',required=True,help='Complete authoritative service runs folder')
    p.add_argument('--server',action='append',required=True,help='Repeat for EVERY service peer')
    p.add_argument('--row',type=int,required=True)
    p.add_argument('--report',required=True,help='Local audit report outside source/archives/history')
    p.add_argument('--apply',action='store_true',help='State reconciliation ONLY, no job submission; requires all jobs idle')
    p.add_argument('--reviewed-evidence')
    p.add_argument('--confirm-prequeue-failure',help='Human-reviewed server failure BEFORE run creation/queueing')
    p.add_argument('--claim',help='Common batch.lock; required with --apply')
    a=p.parse_args(argv)
    archive=Archive(a.local_archive,a.shared_archive)
    report=Path(a.report).resolve()
    source=Path(read_json(Path(a.local_archive)/'plan.json')['workbook']).resolve()
    protected=[Path(x).resolve() for x in (a.local_archive,a.shared_archive,a.history_directory)]
    if report==source or any(report==x or x in report.parents for x in protected):
        p.error('Report must be outside workbook, archives and history')
    if a.reviewed_evidence and report==Path(a.reviewed_evidence).resolve():
        p.error('Do not overwrite reviewed evidence')
    # Existing settings only; never prints secrets or changes service configuration.
    key=service_key()
    clients=[Client(url,key) for url in a.server]
    if a.apply:
        if not all((a.reviewed_evidence,a.confirm_prequeue_failure,a.claim)):
            p.error('--apply requires reviewed evidence, pre-queue ruling and common claim')
        expected=Path(os.getenv('SDI_STATE_DIR') or str(Path(os.getenv('PROGRAMDATA',str(Path.home())))/'SDI Intelligence'))/'tti'/'batch.lock'
        if Path(a.claim).resolve()!=expected.resolve():
            p.error('--claim must be the common service batch.lock')
        result=retire_unaccepted(archive,a.row,a.history_directory,clients,
            read_json(a.reviewed_evidence),a.confirm_prequeue_failure,a.claim)
    else:
        result=audit(archive,a.row,a.history_directory,clients)
    atomic(report,json_bytes(result))
    print(json.dumps(result,indent=2))
    return 0


if __name__=='__main__':
    try: sys.exit(main())
    except Exception as exc:
        print('STOP: '+str(exc),file=sys.stderr); sys.exit(1)
