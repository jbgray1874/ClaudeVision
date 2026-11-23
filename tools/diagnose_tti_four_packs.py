"""Read-only discovery evidence for four brief substitutes. No service/estimator imports."""
import argparse
import json
import os
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))

ROWS=[(20,'12806-00-GA'),(43,'12802-00-GA1'),(44,'12802-00-GA2'),(68,'12803-00-GA')]

def discover(reference, areas, resolver):
    try:
        rows,said,design=resolver.rows_for_job_now(reference,areas)
    except Exception as exc:
        return {'drawing':reference,'state':'lookup_error','error':str(exc),
                'meaning':'The lookup failed; no conclusion that the drawings are missing.'}
    exact=[];nearby=[]
    for folder,files,archived in rows:
        for path,size,mtime in files:
            entry={'path':str(path),'area':'Design' if str(folder) in design else 'Prototype',
                   'archive':bool(archived),'bytes':size,'mtime':mtime}
            if resolver._same(resolver.drawing_id(Path(path).name),reference):exact.append(entry)
            elif reference.split('-')[0] in Path(path).name and Path(path).suffix.lower()=='.pdf':
                nearby.append(entry)
    return {'drawing':reference,'state':'exact_filename_found' if exact else 'no_exact_filename',
            'lookup':said,'exact_files':exact,'other_job_pdfs':nearby,
            'meaning':'Discovery only: filenames do not establish title-block identity, revision or pack completeness.'}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',required=True)
    a=p.parse_args()
    import pack_resolver
    from drive_map import to_unc
    areas=[('Design',Path(to_unc(os.getenv('SDI_TTI_DESIGN_ROOT') or r'\\sdi-dc01\CAD\Design\Customers April 08 Onwards\TTI'))),
           ('Prototype',Path(to_unc(os.getenv('SDI_TTI_PROTOTYPE_ROOT') or r'\\sdi-dc01\CAD\Prototype\TTi')))]
    results=[dict(discover(ref,areas,pack_resolver),row=row) for row,ref in ROWS]
    target=Path(a.output)
    if target.suffix.lower()!='.json' or target.exists():
        raise SystemExit('Use a new .json report path; no existing file is overwritten.')
    with target.open('x',encoding='utf-8') as f:json.dump(results,f,indent=2)
    for r in results:print(f"row {r['row']} {r['drawing']}: {r['state']}")
    return 1 if any(r['state']=='lookup_error' for r in results) else 0

if __name__=='__main__':raise SystemExit(main())
