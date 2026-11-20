"""Offline proof of TTI quantity fixes from provenance-labelled saved evidence.

Run in a review checkout, not a production runner. Does not read CAD, price,
submit, file an estimate, update a tracker, or connect to a service.
"""
import argparse
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import sys

os.environ['SDI_OFFLINE'] = '1'
sys.dont_write_bytecode = True


def refuse_network(*args, **kwargs):
    raise RuntimeError('Network connections forbidden during offline quantity replay')


socket.create_connection = refuse_network
socket.socket.connect = refuse_network
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('actual_tti_replay', ROOT / 'tests' / 'test_actual_tti_quantity_and_pack_regressions.py')
test = importlib.util.module_from_spec(spec)
spec.loader.exec_module(test)

ap = argparse.ArgumentParser(description=__doc__)
ap.add_argument('--output', type=Path, required=True)
args = ap.parse_args()
results = {'scope': 'offline quantity graph only; not a priced workbook or a fresh SolidWorks read', 'jobs': {}}
for name, selected in [
    ('12110-01-GA1', ['12110-02-GA', '12110-02-201', '12110-02-02M', '12110-02-03M', '12110-02-05M', '12110-03-01A']),
    ('12133-00-GA', ['12133-05-GA', '12133-05-101', '12133-05-01M', '12133-05-02M', '12133-05-03M', '12133-05-04M']),
]:
    log = io.StringIO()
    with contextlib.redirect_stdout(log):
        job, graph = test.replay(name)
    nodes = {n.part_number: n for n in graph['nodes']}
    results['jobs'][name] = {
        'provenance': test.fixture(name)['provenance'],
        'quantities': {code: graph['quantities'].get(code) for code in selected},
        'configuration_totals': job.meta.get('bom_configuration_totals', {}),
        'quantity_trails': {code: {'trail': nodes[code].qty_trail, 'note': nodes[code].qty_note}
                            for code in selected if code in nodes},
        'remaining_graph_issues': graph.get('issues', []),
        'log': log.getvalue(),
    }
    print(name, json.dumps(results['jobs'][name]['quantities']))
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
print('Saved offline evidence:', args.output)
