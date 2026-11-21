"""A run that FAILED holds its own row, exactly as one that finished unpriced does (JG, 21 Nov
2026: "one unpriced row mustn't stop the whole queue"). The reviewer's package covered the
unpriced case; a failed run still stopped every row behind it. Made-up rows; a fake service."""
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
sys.path.insert(0, str(ROOT/'tests'))
import tti_concept_batch as batch
import tti_concept_inputs as inp
from test_tti_concept_batch import FakeAPI, fixture, run

ROWS = [(3, 'One', 1, ''), (4, 'Two', 2, ''), (5, 'Three', 3, ''), (6, 'Four', 4, '')]


class SecondRunFails(FakeAPI):
    def status(self, rid):
        s = super().status(rid)
        if rid == '000000000002': s['status'] = 'error'; s['error'] = 'engine stopped: made-up reason'
        return s


def phases(archive):
    return {e['row']: e['phase'] for e in json.loads((archive.roots[0]/'state.json').read_text())['entries'].values()}


def test_the_failed_row_is_held_and_every_other_row_is_priced(tmp_path):
    path = fixture(tmp_path/'t.xlsx', ROWS); plan, pics = inp.read_plan(path)
    archive, api = batch.Archive(tmp_path/'C', tmp_path/'K'), SecondRunFails()
    assert run(plan, pics, archive, api) == 4
    assert len(api.posts) == 4, 'every row was sent, once'
    assert phases(archive) == {3: 'done', 4: 'held', 5: 'done', 6: 'done'}
    assert {r['row']: r['cost_before'] for r in inp.read_plan(path)[0]['rows']} == {3: 12.34, 4: None, 5: 12.34, 6: 12.34}
    for root in archive.roots:
        held = next(e for e in json.loads((root/'state.json').read_text())['entries'].values() if e['row'] == 4)
        assert 'engine stopped' in held['why'] and held['automatic_resubmission'] is False
    events = [json.loads(p.read_text()) for p in (archive.roots[0]/'events').glob('*.json')]
    assert [e['row'] for e in events if e['event'] == 'ROW FAILED - CONTINUING'] == [4]
    assert any(e['event'] == 'FINISHED WITH HOLDS' and [h['row'] for h in e['held_rows']] == [4] for e in events)
    # And a resume sends nothing again.
    assert run(inp.read_plan(path)[0], pics, archive, api) == 4 and len(api.posts) == 4


# ── a reviewed carry-forward names every other changed path ──────────────────────────────
def git(changed, ancestor=True):
    def run_git(*args):
        if args[0] == 'rev-parse': return 'a' * 40 if args[1].startswith('a') else 'b' * 40
        if args[0] == 'merge-base': return 'a' * 40 if ancestor else 'c' * 40
        return changed
    return run_git


REPORTING = 'src/tti_concept_batch.py\nsdi-intelligence-backend/estimate_routes.py'
WIDER = REPORTING + '\nsrc/vision_fallback.py\ntests/test_something_new.py'
WHY = 'The vision fallback change only reports a credential failure more clearly; it sends the same images and brief and prices nothing differently.'


def test_a_reporting_only_release_needs_no_statement():
    out = batch.validate_health_only_proof_build(ROOT, 'a' * 7, 'b' * 7, git(REPORTING))
    assert 'reviewed_paths' not in out


def test_a_wider_release_is_refused_unless_every_other_path_is_named():
    with pytest.raises(ValueError, match='refused'):
        batch.validate_health_only_proof_build(ROOT, 'a' * 7, 'b' * 7, git(WIDER))
    out = batch.validate_health_only_proof_build(ROOT, 'a' * 7, 'b' * 7, git(WIDER), reviewed_paths=['src/vision_fallback.py'], statement=WHY)
    assert out['reviewed_paths'] == ['src/vision_fallback.py'] and out['statement'] == WHY and out['resume_build'] == 'b' * 40


def test_test_files_are_not_counted_but_a_source_file_always_is():
    out = batch.validate_health_only_proof_build(ROOT, 'a' * 7, 'b' * 7, git(REPORTING + '\ntests/test_new.py'))
    assert 'reviewed_paths' not in out
    with pytest.raises(ValueError, match='not named'):
        batch.validate_health_only_proof_build(ROOT, 'a' * 7, 'b' * 7, git(WIDER + '\nsrc/pack_resolver.py'), reviewed_paths=['src/vision_fallback.py'], statement=WHY)


def test_a_statement_about_another_release_is_refused():
    with pytest.raises(ValueError, match='did not change'):
        batch.validate_health_only_proof_build(ROOT, 'a' * 7, 'b' * 7, git(WIDER), reviewed_paths=['src/vision_fallback.py', 'src/estimator.py'], statement=WHY)
    with pytest.raises(ValueError, match='full sentence'):
        batch.validate_health_only_proof_build(ROOT, 'a' * 7, 'b' * 7, git(WIDER), reviewed_paths=['src/vision_fallback.py'], statement='ok')


def test_the_options_go_together(tmp_path, capsys):
    path = fixture(tmp_path/'t.xlsx', ROWS)
    with pytest.raises(SystemExit):
        batch.main(['--sheet', str(path), '--plan-output', str(tmp_path/'p.json'), '--carry-forward-statement', WHY])
    assert 'go with --proof-execution-build' in capsys.readouterr().err
