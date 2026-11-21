"""An approval records what happened (JG, 21 Nov 2026: "no more one or two jobs ... all in
one queue"). Run on the owner's instruction without a look at the two proofs, it says so,
in place of the statement that they were reviewed. The mechanical checks do not change."""
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
from test_tti_concept_batch import setup, run

ROWS = [(3, 'Image pilot', 2, ''), (4, 'Description pilot', 3, ''), (5, 'Remaining', 4, '')]
BASIS = "Owner's instruction, 21 Nov 2026: run every row in one queue; the two proofs were not looked at first."


def pilot(tmp_path):
    path, plan, pics, archive, api = setup(tmp_path, ROWS)
    assert run(plan, pics, archive, api, selected_rows=[3, 4], proof_rows=(3, 4)) == 0
    return path, pics, archive, api


def filed(archive):
    return [json.loads((root/proof.APPROVAL).read_text()) for root in archive.roots]


def test_a_reviewed_approval_reads_as_it_always_did(tmp_path):
    path, pics, archive, api = pilot(tmp_path)
    proof.approve_proof(archive, inp.read_plan(path)[0], (3, 4))
    for report in filed(archive):
        assert 'Operator confirms reviewing' in report['meaning'] and 'proofs_reviewed_by_a_person' not in report


def test_an_instructed_approval_says_the_proofs_were_not_looked_at(tmp_path):
    path, pics, archive, api = pilot(tmp_path)
    proof.approve_proof(archive, inp.read_plan(path)[0], (3, 4), basis=BASIS)
    for report in filed(archive):
        assert report['meaning'] == BASIS and report['proofs_reviewed_by_a_person'] is False
        assert 'confirms reviewing' not in report['meaning']
    assert run(inp.read_plan(path)[0], pics, archive, api, proof_rows=(3, 4)) == 0 and len(api.posts) == 3


def test_it_must_say_whose_instruction_it_rests_on(tmp_path):
    path, pics, archive, api = pilot(tmp_path)
    with pytest.raises(ValueError, match='whose instruction'):
        proof.approve_proof(archive, inp.read_plan(path)[0], (3, 4), basis='ok')
    assert not any((root/proof.APPROVAL).exists() for root in archive.roots)


def test_the_mechanical_checks_are_not_waived_with_it(tmp_path):
    path, plan, pics, archive, api = setup(tmp_path, ROWS)
    assert run(plan, pics, archive, api, selected_rows=[3], proof_rows=(3, 4)) == 0      # one proof only
    with pytest.raises(ValueError):
        proof.approve_proof(archive, inp.read_plan(path)[0], (3, 4), basis=BASIS)
    with pytest.raises(RuntimeError, match='PROOF NOT APPROVED'):
        run(inp.read_plan(path)[0], pics, archive, api, proof_rows=(3, 4))


def test_the_basis_belongs_with_an_approval_only(tmp_path, capsys):
    path, plan, pics, archive, api = setup(tmp_path, ROWS)
    with pytest.raises(SystemExit):
        batch.main(['--sheet', str(path), '--plan-output', str(tmp_path/'plan.json'), '--approval-basis', BASIS])
    assert 'belongs with --approve-proof' in capsys.readouterr().err
