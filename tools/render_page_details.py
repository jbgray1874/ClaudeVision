"""Render selected PDF pages into a NEW evidence directory; no model calls or PDF edits."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from page_detail import plan
from pypdf import PdfReader

p=argparse.ArgumentParser()
p.add_argument('pdf',type=Path)
p.add_argument('--pages',required=True,help='1-based comma-separated page numbers')
p.add_argument('--out',type=Path,required=True)
p.add_argument('--dpi',type=int,default=200)
p.add_argument('--max-tiles',type=int,default=64)
args=p.parse_args()
exe=shutil.which('pdftoppm')
if not exe: raise SystemExit('pdftoppm not available; install Poppler or use supported runtime')
source=args.pdf.resolve(strict=True)
reader=PdfReader(source)
pages=sorted(set(int(x) for x in args.pages.split(',')))
tiles=[]
for n in pages:
    if not 1<=n<=len(reader.pages): raise SystemExit(f'Invalid page {n}')
    page=reader.pages[n-1]
    w,h=float(page.mediabox.width),float(page.mediabox.height)
    if int(page.get('/Rotate',0))%180: w,h=h,w
    for tile in plan(w,h,args.dpi,max_tiles=args.max_tiles):
        tiles.append(dict(page=n,**tile))
if len(tiles)>args.max_tiles: raise SystemExit('Total tile budget exceeded; select fewer pages')
args.out.mkdir(parents=True,exist_ok=False)
manifest=dict(document=str(source),sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
              page_count=len(reader.pages),selected_pages=pages,
              coordinates='rendered MediaBox, top-left, rotation applied',tiles=tiles,
              reading_status='not_sent',complete=False)
try:
    for index,tile in enumerate(tiles):
        prefix=args.out/f"page-{tile['page']}-tile-{index+1}"
        subprocess.run([exe,'-f',str(tile['page']),'-l',str(tile['page']),'-singlefile',
            '-r',str(tile['dpi']),'-x',str(tile['x']),'-y',str(tile['y']),
            '-W',str(tile['width']),'-H',str(tile['height']),'-png',str(source),str(prefix)],
            check=True,capture_output=True,timeout=60)
        output=prefix.with_suffix('.png')
        tile.update(file=output.name,sha256=hashlib.sha256(output.read_bytes()).hexdigest(),status='rendered_not_read')
    manifest['complete']=True
finally:
    (args.out/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
print(f"Rendered {len(tiles)} detail tiles; not sent to a model. Manifest: {args.out/'manifest.json'}")
