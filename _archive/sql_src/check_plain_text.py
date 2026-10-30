import json
from pathlib import Path

files = sorted(Path('C:/ClaudeVision/input/history').rglob('*.formula_parse.json'))
print(f"Files found: {len(files)}")

if not files:
    print("No files found")
    exit()

# Check first 3 files
for p in files[:3]:
    print(f"\n=== {p.name} ===")
    data = json.load(open(p, encoding='utf-8'))

    print(f"Sheet names: {data.get('sheet_names')}")

    pe = data.get('parsed_entries') or []
    print(f"Total parsed_entries: {len(pe)}")

    # Check sheet names present
    sheets_in_entries = set(str(e.get('sheet','')) for e in pe)
    print(f"Sheets in parsed_entries: {sheets_in_entries}")

    # Check plain text entries
    plain = [e for e in pe if e.get('is_plain_text')]
    print(f"Plain text entries (is_plain_text=True): {len(plain)}")
    for e in plain[:10]:
        print(f"  {str(e.get('address',''))[:8]:10s} sheet={str(e.get('sheet',''))[:12]:14s} val={str(e.get('value',''))[:40]}")

    # Check Estimate sheet specifically
    est = [e for e in pe if str(e.get('sheet','')).upper() == 'ESTIMATE']
    print(f"Entries on 'Estimate' sheet: {len(est)}")

    # Check key_cells col C
    kc = data.get('key_cells') or {}
    ops = kc.get('operation_rows') or []
    mats = kc.get('material_unit_prices') or []
    c_ops  = [e for e in ops  if str(e.get('address','')).upper().startswith('C')]
    c_mats = [e for e in mats if str(e.get('address','')).upper().startswith('C')]
    print(f"key_cells operation_rows col C: {len(c_ops)}")
    print(f"key_cells material col C: {len(c_mats)}")