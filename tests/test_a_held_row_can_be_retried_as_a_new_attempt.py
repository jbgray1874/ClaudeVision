"""A held row can be sent again, as a new numbered attempt (JG, 22 Nov 2026: "we'll need to
pick these up at the end. Can we queue these up?"). Only a held row; never a proof row; the
held attempt and its run are kept for audit; the new attempt has its own reference, so the
service makes a new run rather than handing back the failed one. Made-up rows; a fake service."""
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
sys.path.insert(0, str(ROOT/'tests'))
import tti_concept_batch as batch
import tti_concept_inputs as inp
import tti_concept_proof as proof
from test_tti_concept_batch import FakeAPI, fixture, run

ROWS = [(3, 'Image pilot', 2, ''), (4, 'Description pilot', 3, ''), (5, 'Third', 4, ''), (6, 'Fourth', 1, '')]


class FailsOnce(FakeAPI):
    """The third run sent fails; every later run is fine."""
    def status(self, rid):
        s = super().status(rid)
        if rid == '000000000003': s['status'] = 'error'; s['error'] = 'reader rejected its credentials'
        return s


def setup(tmp_path):
    path = fixture(tmp_path/'t.xlsx', ROWS)
    plan, pics = inp.read_plan(path)
    archive, api = batch.Archive(tmp_path/'C', tmp_path/'K'), FailsOnce()
    assert run(plan, pics, archive, api, selected_rows=[3, 4], proof_rows=(3, 4)) == 0
    proof.approve_proof(archive, inp.read_plan(path)[0], (3, 4))
    assert run(inp.read_plan(path)[0], pics, archive, api, proof_rows=(3, 4)) == 4
    return path, pics, archive, api


def state(archive):
    return json.loads((archive.roots[0]/'state.json').read_text())


def costs(path):
    return {r['row']: r['cost_before'] for r in inp.read_plan(path)[0]['rows']}


def test_the_held_row_is_sent_again_as_attempt_two_and_the_old_attempt_is_kept(tmp_path):
    path, pics, archive, api = setup(tmp_path)
    assert costs(path) == {3: 12.34, 4: 12.34, 5: None, 6: 12.34}
    held = {e['row']: e for e in state(archive)['entries'].values()}[5]
    assert held['phase'] == 'held' and held['run_id'] == '000000000003'
    plan = inp.read_plan(path)[0]
    assert batch.retire_for_retry(archive, plan, [5], proof_rows=(3, 4)) == [5]
    assert run(plan, pics, archive, api, selected_rows=[5], proof_rows=(3, 4)) == 0
    assert len(api.posts) == 5, 'one more job, for the retried row only'
    sent = api.posts[-1]
    assert sent['drawing_number'].endswith('-R2') and sent['units'] == 4
    assert costs(path) == {3: 12.34, 4: 12.34, 5: 12.34, 6: 12.34}
    st = state(archive)
    new = {e['row']: e for e in st['entries'].values()}[5]
    assert new['phase'] == 'done' and new['run_id'] == '000000000005'
    assert st['retired_attempts'][0]['run_id'] == '000000000003' and st['retired_attempts'][0]['phase'] == 'held'
    assert st['attempts'] == {sent['drawing_number'][:-3]: 2}
    for root in archive.roots:
        rec = json.loads((root/'retries'/'row-00005-attempt-02.json').read_text())
        assert rec['retired_run_id'] == '000000000003' and rec['next_reference'] == sent['drawing_number']
        assert (root/sent['drawing_number']/'results'/'price-for-writeback.json').exists()
        assert (root/sent['drawing_number'][:-3]/'polls').exists(), 'the failed attempt is still on file'
    # A later full resume sends nothing again.
    assert run(inp.read_plan(path)[0], pics, archive, api, proof_rows=(3, 4)) == 0 and len(api.posts) == 5


def test_a_second_retry_is_attempt_three(tmp_path):
    path, pics, archive, api = setup(tmp_path)
    plan = inp.read_plan(path)[0]
    batch.retire_for_retry(archive, plan, [5], proof_rows=(3, 4))
    api.status = lambda rid, _s=api.status: dict(_s(rid), status='error', error='again') if rid == '000000000005' else _s(rid)
    assert run(plan, pics, archive, api, selected_rows=[5], proof_rows=(3, 4)) == 4
    batch.retire_for_retry(archive, inp.read_plan(path)[0], [5], proof_rows=(3, 4))
    assert run(inp.read_plan(path)[0], pics, archive, api, selected_rows=[5], proof_rows=(3, 4)) == 0
    assert api.posts[-1]['drawing_number'].endswith('-R3') and len(state(archive)['retired_attempts']) == 2
    assert costs(path)[5] == 12.34


@pytest.mark.parametrize('row, why', [(6, 'not held'), (3, 'proof row'), (99, 'not an eligible row')])
def test_only_a_held_non_proof_row_is_retried(tmp_path, row, why):
    path, pics, archive, api = setup(tmp_path)
    before = (archive.roots[0]/'state.json').read_bytes()
    with pytest.raises(ValueError, match=why):
        batch.retire_for_retry(archive, inp.read_plan(path)[0], [row], proof_rows=(3, 4))
    assert (archive.roots[0]/'state.json').read_bytes() == before and len(api.posts) == 4


def test_the_option_stands_alone(tmp_path, capsys):
    path = fixture(tmp_path/'t.xlsx', ROWS)
    with pytest.raises(SystemExit):
        batch.main(['--sheet', str(path), '--plan-output', str(tmp_path/'p.json'), '--retry-held', '5', '--execute'])
    assert 'mutually exclusive' in capsys.readouterr().err
