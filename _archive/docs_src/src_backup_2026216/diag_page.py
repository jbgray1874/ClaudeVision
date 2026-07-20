import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from document_builder import _get_page_text

json_path = sys.argv[1] if len(sys.argv) > 1 else r'output\json\11367-09-GA - Shelf Lightbox_revD.json'
data = json.load(open(json_path, encoding='utf-8'))

pages = (data.get('pages')
      or data.get('estimate_summary', {}).get('pages')
      or data.get('scan_result', {}).get('pages')
      or [])

print('Pages found:', len(pages))
if pages:
    print('Page keys:', list(pages[0].keys()))

page8 = next((p for p in pages if p.get('page_number') == 8), None)
if page8:
    print()
    print('--- Page 8 fields containing PETG ---')
    def search(obj, path=''):
        if isinstance(obj, str) and 'PETG' in obj.upper():
            print('  FOUND at [' + path + ']:', obj[:80])
        elif isinstance(obj, dict):
            for k, v in obj.items():
                search(v, path + '.' + str(k))
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                search(v, path + '[' + str(i) + ']')
    search(page8)
    rt = page8.get('region_text') or {}
    print()
    print('--- Page 8 field lengths (saved JSON) ---')
    for key in ('text_preview', 'pdfplumber_text', 'normalized_text', 'pypdf_text'):
        v = page8.get(key)
        print(f'  {key}:', len(str(v or '')), 'chars')
    print('  region_text.bom:', len(str(rt.get('bom') or '')), 'chars')
    merged = _get_page_text(page8)
    print('--- _get_page_text(page 8) contains PETG? ---', 'PETG' in merged.upper())
    if 'PETG' in merged.upper():
        idx = merged.upper().index('PETG')
        print('  context:', merged[max(0, idx - 40): idx + 40])
else:
    print('Page 8 not found')
    print('Page numbers:', [p.get('page_number') for p in pages[:5]])
