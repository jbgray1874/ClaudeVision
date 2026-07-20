import json
from pathlib import Path

files = sorted(Path('C:/ClaudeVision/input/history').rglob('*.formula_parse.json'))
print(f"Total formula_parse.json files found: {len(files)}")

if not files:
    print("No files found - reparse may still be running")
else:
    # Check last 3 files
    for p in files[-3:]:
        print(f"\n=== {p.name} ===")
        data = json.load(open(p, encoding='utf-8'))
        kc = data.get('key_cells') or {}

        tots = kc.get('totals') or []
        print(f"Totals ({len(tots)}):")
        for t in tots:
            addr = t.get('address', '')
            val  = str(t.get('value', ''))[:35]
            form = str(t.get('formula', ''))[:65]
            print(f"  {addr:8s}  val={val:37s}  formula={form}")

        ops = kc.get('operation_rows') or []
        c_ops = [e for e in ops if str(e.get('address','')).upper().startswith('C')]
        print(f"Operation name cells (col C): {len(c_ops)}")
        for e in c_ops[:5]:
            print(f"  {e['address']:8s}  val={str(e.get('value',''))[:40]}  plain={e.get('is_plain_text')}")

        mats = kc.get('material_unit_prices') or []
        c_mats = [e for e in mats if str(e.get('address','')).upper().startswith('C')]
        print(f"Material description cells (col C): {len(c_mats)}")
        for e in c_mats[:5]:
            print(f"  {e['address']:8s}  val={str(e.get('value',''))[:40]}  plain={e.get('is_plain_text')}")