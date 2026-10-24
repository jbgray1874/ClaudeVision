"""Read-only saved-record replay. No pricing, model calls, Excel or input writes."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys

p = argparse.ArgumentParser()
p.add_argument('record', type=Path)
p.add_argument('--engine-src', type=Path, default=Path(__file__).resolve().parents[1] / 'src')
p.add_argument('--dependencies', type=Path)
p.add_argument('--out', type=Path, required=True)
a = p.parse_args()
sys.path.insert(0, str(a.engine_src))
if a.dependencies:
    sys.path.append(str(a.dependencies))
from owned_specification import audit_owned_specifications, retain_own_material, review_cautions
from source_precedence import apply_field
from route_compiler import compile_route_without_pricing

data = a.record.read_bytes()
saved = json.loads(data)
s = copy.deepcopy(saved)
before = audit_owned_specifications(s)
changed = []
for part in (s.get('manufacturing_writeup') or {}).get('parts') or []:
    old = part.get('normalized_material')
    retain_own_material(part, s.get('pages'), apply_field)
    if part.get('normalized_material') != old:
        changed.append({'part': part['part_number'], 'before': old,
                        'after': part.get('normalized_material'),
                        'evidence': part.get('owned_material_evidence')})
compiled = compile_route_without_pricing(s)
decisions = [{'part': d.get('target_id'), 'operation': d.get('operation'),
              'status': d.get('status'), 'reason': d.get('reason')}
             for d in compiled.get('decisions') or []
             if d.get('operation') in ('cnc_routing', 'glue', 'laser_cutting')]
result = {'record_sha256': hashlib.sha256(data).hexdigest(),
          'before_findings': before, 'material_changes_in_memory': changed,
          'after_findings': audit_owned_specifications(s),
          'route_recompiled_without_pricing': decisions,
          'report_cautions': review_cautions(saved),
          'limits': 'No workbook recalculation, no sheet-price mapping, no automatic role count or step interpretation; saved counts unchanged.'}
assert a.record.read_bytes() == data
a.out.parent.mkdir(parents=True, exist_ok=True)
a.out.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')
print(json.dumps(result, indent=2, ensure_ascii=False))
