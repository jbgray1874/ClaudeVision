"""Prepare one selected saved job offline; never price, submit, deploy or overwrite it."""
import argparse
import json
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from saved_scope_recovery import prepare

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('record',type=Path)
    ap.add_argument('--out',required=True,type=Path)
    ap.add_argument('--scope')
    ap.add_argument('--scope-basis')
    ap.add_argument('--identity-aliases',type=Path,
        help='Reviewed JSON object mapping numeric supplier stock codes to exact drawing references; requires --scope-basis')
    ap.add_argument('--allowances',type=Path,
        help='Explicit job-scoped estimating_allowances.v1 input; adds provisional material and operation inputs, not prices')
    ap.add_argument('--owned-text',type=Path,
        help='Explicit owned_manufacturing_text.v1 reviewed transcription, bound to an existing filename/page; never auto-discovered')
    ap.add_argument('--read-printed-dimensions',action='store_true',
        help="Read each page's printed dimension axes from its own PDF (saved path, or --drawings) into the copy")
    ap.add_argument('--drawings',type=Path,
        help='With --read-printed-dimensions: folder holding the job\'s PDFs, matched by exact file name')
    args=ap.parse_args()
    os.environ['SDI_OFFLINE']='1'
    if args.out.resolve() == args.record.resolve() or args.out.exists():
        ap.error('Output must be a new file, never the source or an existing result')
    raw=args.record.read_bytes()
    source=json.loads(raw.decode('utf-8-sig'))
    printed=None
    if args.read_printed_dimensions:
        from drawing_dimension_evidence import read_saved_pages
        printed=read_saved_pages(source,args.drawings)   # the in-memory copy; the file is only read
    elif args.drawings:
        ap.error('--drawings needs --read-printed-dimensions')
    aliases=json.loads(args.identity_aliases.read_text(encoding='utf-8-sig')) if args.identity_aliases else None
    if aliases is not None and not isinstance(aliases,dict):
        ap.error('--identity-aliases must contain a JSON object')
    allowances=json.loads(args.allowances.read_text(encoding='utf-8-sig')) if args.allowances else None
    owned_text=json.loads(args.owned_text.read_text(encoding='utf-8-sig')) if args.owned_text else None
    result,audit=prepare(source,scope=args.scope,scope_basis=args.scope_basis,identity_aliases=aliases,
        allowances=allowances,owned_text=owned_text)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    with args.out.open('x',encoding='utf-8') as f:
        json.dump(result,f,indent=2,default=str)
    import hashlib
    audit['source_record_sha256']=hashlib.sha256(raw).hexdigest()
    if printed is not None:
        audit['printed_dimensions']=printed
    print(json.dumps(audit,indent=2,default=str))
    print('No estimate was run or repriced. Prepared input:',args.out)

if __name__ == '__main__':
    main()
