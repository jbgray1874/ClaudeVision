"""Compare quantity/source checks on saved records; no model, pricing or Excel writes (D-598i).

    python tools/probe_ownership_release.py <record.json> [...] --out probe.json
        [--baseline-dir <review package>/baseline/src]

Each record is audited as saved, then with one captured leaf deleted IN MEMORY from both the
graph and the price population: the audit must name the lost member. With --baseline-dir the
same is run through an earlier audit for comparison. Nothing is written back to a record.
"""
import argparse
import copy
import hashlib
import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from quantity_flow_contract import audit

parser = argparse.ArgumentParser()
parser.add_argument('records', nargs='+')
parser.add_argument('--out', required=True)
parser.add_argument('--baseline-dir', help='an earlier quantity_flow_contract.py and '
                                           'quantity_path_evidence.py to compare against')
args = parser.parse_args()

# Baseline module must also use its own helper, not the patched helper on sys.path.
def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module

baseline = None
if args.baseline_dir:
    old_helper = load('old_quantity_path', Path(args.baseline_dir) / 'quantity_path_evidence.py')
    baseline = load('old_quantity_flow', Path(args.baseline_dir) / 'quantity_flow_contract.py')
    baseline.local_edges = old_helper.local_edges

def counts(result):
    return dict(Counter(i['code'] for i in result['issues'])) if result else None

results = []
for name in args.records:
    path = Path(name); raw = path.read_bytes(); s = json.loads(raw.decode('utf-8-sig'))
    original = copy.deepcopy(s)
    before, after = (baseline.audit(s) if baseline else None), audit(s)
    assert s == original, 'audit mutated input'
    # Delete a captured leaf from BOTH downstream populations. Retain the source.
    # This is a controlled mutation, never saved back into the customer's record.
    changed = copy.deepcopy(s)
    es = changed.get('estimate_summary') or {}
    graph = es.get('canonical_route_shadow') or changed.get('canonical_route_shadow') or {}
    captured = {str(t['part']).replace(' ', '').upper()
                for t in (after.get('source_population') or {}).get('trace', [])}
    chosen = next((n.get('part_number') for n in graph.get('nodes', [])
                   if not n.get('children') and str(n.get('part_number')).replace(' ', '').upper() in captured), None)
    mutation = {'executed': False, 'reason': 'no captured leaf available'}
    if chosen:
        graph['nodes'] = [n for n in graph['nodes'] if n.get('part_number') != chosen]
        for node in graph['nodes']:
            node['children'] = [e for e in node.get('children', []) if e.get('part_number') != chosen]
        population = 'canonical_part_estimates' if 'canonical_part_estimates' in es else 'part_estimates'
        es[population] = [p for p in es.get(population, []) if p.get('part_number') != chosen]
        old_broken, new_broken = (baseline.audit(changed) if baseline else None), audit(changed)
        mutation = {'executed': True, 'removed_part': chosen,
                    'before': counts(old_broken), 'after': counts(new_broken),
                    'caught': any(i['code'] == 'captured_part_missing_from_graph' for i in new_broken['issues'])}
        assert mutation['caught'], 'source member loss escaped the audit'
    results.append({'record': str(path), 'sha256': hashlib.sha256(raw).hexdigest(),
                    'before': counts(before), 'after': counts(after),
                    'source_population': after.get('source_population'),
                    'deleted_member_mutation': mutation,
                    'new_findings': ([i for i in after['issues'] if i not in before['issues']]
                                     if before else None)})
Path(args.out).write_text(json.dumps({'scope': 'read-only source/quantity audit, not calculated-workbook acceptance',
                                   'records': results}, indent=2), encoding='utf-8')
for r in results:
    print(json.dumps({k: r[k] for k in ('record', 'before', 'after')}))
