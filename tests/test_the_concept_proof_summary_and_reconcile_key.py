"""Two helpers around the concept proof: the reconcile tool reads the service key the way
the batch does, and the proof summary a person reviews only reads."""
import hashlib
import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
sys.path.insert(0, str(ROOT/'tests'))
from test_tti_concept_batch import setup, run


def tool(name):
    spec = importlib.util.spec_from_file_location(name, ROOT/'tools'/(name + '.py'))
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod


def test_the_reconcile_tool_reads_the_key_from_the_checkouts_settings(tmp_path, monkeypatch):
    monkeypatch.delenv('SDI_API_KEY', raising=False)
    (tmp_path/'.env').write_text('SDI_API_KEY=made-up-key-for-a-test\n')
    assert tool('reconcile_tti_concept_submission').service_key(tmp_path) == 'made-up-key-for-a-test'


def test_a_key_already_set_for_the_process_is_not_replaced(tmp_path, monkeypatch):
    monkeypatch.setenv('SDI_API_KEY', 'already-set')
    (tmp_path/'.env').write_text('SDI_API_KEY=made-up-key-for-a-test\n')
    assert tool('reconcile_tti_concept_submission').service_key(tmp_path) == 'already-set'


def test_no_settings_file_means_no_key_rather_than_a_failure(tmp_path, monkeypatch):
    monkeypatch.delenv('SDI_API_KEY', raising=False)
    assert tool('reconcile_tti_concept_submission').service_key(tmp_path) == ''


def tree(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(Path(root).rglob('*')) if p.is_file()}


def test_the_summary_shows_both_finished_rows_and_changes_nothing(tmp_path, capsys):
    _, plan, pics, archive, api = setup(tmp_path, [(3, 'Image pilot', 2, ''), (4, 'Description pilot', 3, '')])
    assert run(plan, pics, archive, api, selected_rows=[3, 4], proof_rows=(3, 4)) == 0
    before = tree(tmp_path)
    show = tool('show_tti_concept_proof')
    rows = show.summary(archive.roots[0], [3, 4])
    assert [r['phase'] for r in rows] == ['done', 'done']
    assert all(r['run_id'] and r['unit_gbp'] is not None and r['workbooks'] for r in rows)
    assert sorted(bool(r['pictures']) for r in rows) == [False, True]
    assert show.main(['--local-archive', str(archive.roots[0]), '--rows', '3,4']) == 0
    assert 'approves nothing' in capsys.readouterr().out
    assert tree(tmp_path) == before
    assert not any((root/'proof-approval.json').exists() for root in archive.roots)


def test_a_row_that_has_not_run_is_said_plainly(tmp_path):
    _, plan, pics, archive, api = setup(tmp_path, [(3, 'Image pilot', 2, ''), (4, 'Description pilot', 3, '')])
    assert run(plan, pics, archive, api, selected_rows=[3], proof_rows=(3, 4)) == 0
    rows = tool('show_tti_concept_proof').summary(archive.roots[0], [3, 4, 99])
    assert [r['phase'] for r in rows] == ['done', 'not started', 'not in the plan']
