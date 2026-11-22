"""The grid statistics tool reads the service's run history by kind of job, keeps hung runs
out of the baselines, and changes nothing. Made-up runs."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
import grid_run_stats as g


def run(i, kind, minutes, status='done', runner='r1', t0=1_700_000_000):
    base = {'run_id': f'{i:012x}', 'client': 'Made Up', 'status': status, 'runner': runner,
            'queued_at': t0 + i * 100, 'started_at': t0 + i * 100 + 30, 'finished_at': t0 + i * 100 + 30 + minutes * 60}
    if kind == 'thumb': base.update(drawing_number='TTI-C-abc', llm_only=True)
    if kind == 'models': base.update(drawing_number='50001-01-GA', sw_turn_at=1.0)
    if kind == 'nomodels': base.update(drawing_number='50002-01-GA')
    if kind == 'pre': base.update(drawing_number='50003-01-GA', job_type='bom_routes')
    return base


def write(tmp_path, runs):
    d = tmp_path/'runs'; d.mkdir()
    for r in runs: (d/(r['run_id'] + '.json')).write_text(json.dumps(r))
    (d/'bad.json').write_text('not json')
    return d


def test_kinds_are_told_apart_and_a_hung_run_is_not_the_usual(tmp_path, capsys):
    runs = [run(i, 'thumb', m) for i, m in enumerate([8, 9, 10, 12, 14])]
    runs += [run(10 + i, 'models', m, runner='r2') for i, m in enumerate([40, 50, 60, 55, 300])]   # 300 is a hang
    runs += [run(20, 'nomodels', 25), run(21, 'pre', 5), run(22, 'thumb', 3, status='error')]
    d = write(tmp_path, runs)
    before = sorted((p.name, p.stat().st_size) for p in d.iterdir())
    assert g.main(['--history', str(d), '--days', '0', '--csv', str(tmp_path/'out.csv')]) == 0
    out = capsys.readouterr().out
    kinds, by_runner, waits = g.analyse(g.load(d, 0))
    assert set(kinds) == {'thumbnail / brief only', 'drawing pack with models', 'drawing pack, no models', 'pre-run (bom_routes)'}
    t = kinds['thumbnail / brief only']
    assert t['runs'] == 6 and t['done'] == 5 and t['failed'] == 1 and t['median'] == 10 * 60
    m = kinds['drawing pack with models']
    assert m['hung'] == 1 and m['slowest_typical'] == 60 * 60 and m['hung_examples'][0][1] == 300
    assert by_runner['r1']['runs'] == 8 and by_runner['r2']['runs'] == 5
    assert 'hung: 50001-01-GA took 300 min' in out and 'one runner does about' in out
    assert sorted((p.name, p.stat().st_size) for p in d.iterdir()) == before, 'read only'
    assert (tmp_path/'out.csv').read_text().count('\n') == 14


def test_an_empty_folder_is_said_not_crashed(tmp_path, capsys):
    (tmp_path/'runs').mkdir()
    assert g.main(['--history', str(tmp_path/'runs')]) == 1
    assert 'no runs found' in capsys.readouterr().out
