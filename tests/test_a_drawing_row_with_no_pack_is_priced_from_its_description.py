"""A drawing row whose number found no pack is priced from its description and pictures,
only on an explicit ruling backed by the drawing pricer's own ledger. Made-up rows only;
a fake service; nothing here searches for drawings or prices anything."""
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
import tti_concept_reconcile as rec
from test_tti_concept_batch import FakeAPI, fixture, run

ROWS = [(3, 'Image pilot', 2, ''), (4, 'Description pilot', 3, ''), (6, 'Counter unit, no pack', 4, '50009-01-GA'),
        (7, 'Has its drawings', 1, '50010-01-GA')]
RULING = {6: {'drawing': '50009-01-GA', 'evidence': 'made-up ledger: needs drawing'}}


def ledger(tmp_path, entries):
    path = tmp_path/'drawing.ledger.json'
    path.write_text(json.dumps({f"{e['row']}|{e.get('drawing')}|{i}": e for i, e in enumerate(entries)}))
    return path


def by_row(plan):
    return {r['row']: r for r in plan['rows']}


def test_without_a_ruling_a_drawing_row_is_never_a_concept(tmp_path):
    plan, _ = inp.read_plan(fixture(tmp_path/'t.xlsx', ROWS))
    assert by_row(plan)[6]['state'] == 'drawing row excluded' and 'no_pack' not in by_row(plan)[6]


def test_a_ruling_makes_only_that_row_eligible_and_says_so_in_the_brief(tmp_path):
    path = fixture(tmp_path/'t.xlsx', ROWS)
    plain, _ = inp.read_plan(path); ruled, _ = inp.read_plan(path, no_pack=RULING)
    row = by_row(ruled)[6]
    assert row['state'] == 'eligible' and row['no_pack']['drawing'] == '50009-01-GA'
    assert 'NO DRAWING PACK' in row['brief'] and '50009-01-GA' in row['brief'] and 'repriced from the drawings' in row['brief']
    assert row['reference'] != by_row(plain)[6]['reference']
    # The other rows are untouched: same identity, same brief, and row 7 keeps its drawings route.
    for n in (3, 4, 7):
        assert by_row(ruled)[n] == by_row(plain)[n]
    assert by_row(ruled)[7]['state'] == 'drawing row excluded'


def test_a_ruling_for_another_drawing_number_holds_the_row(tmp_path):
    plan, _ = inp.read_plan(fixture(tmp_path/'t.xlsx', ROWS), no_pack={6: {'drawing': '59999-01-GA'}})
    assert by_row(plan)[6]['state'] == 'held: no-pack ruling names another drawing'


def test_a_blank_quantity_on_a_no_pack_row_is_one_only_with_the_quantity_ruling(tmp_path):
    path = fixture(tmp_path/'t.xlsx', [(3, 'Image pilot', 2, ''), (6, 'No pack, no quantity', None, '50009-01-GA')])
    assert by_row(inp.read_plan(path, no_pack=RULING)[0])[6]['state'] == 'held: quantity'
    row = by_row(inp.read_plan(path, assume_missing_quantity_one=True, no_pack=RULING)[0])[6]
    assert row['state'] == 'eligible' and row['quantity'] == 1 and row['quantity_assumed']


def test_the_ruling_comes_from_the_drawing_pricers_latest_record(tmp_path):
    path = ledger(tmp_path, [
        {'row': 6, 'drawing': '50009-01-GA', 'state': 'needs drawing', 'why': 'no drawings found for this number', 'updated': '2026-11-20T10:00:00'},
        {'row': 7, 'drawing': '50010-01-GA', 'state': 'done', 'updated': '2026-11-20T10:00:00'},
        {'row': 8, 'drawing': '50011-01-GA', 'state': 'needs drawing', 'updated': '2026-11-19T10:00:00'},
        {'row': 8, 'drawing': '50011-01-GA', 'state': 'done', 'updated': '2026-11-20T10:00:00'},
        {'row': 9, 'drawing': '50012-01-GA', 'state': 'needs decision', 'updated': '2026-11-20T10:00:00'}])
    rulings, refused = inp.no_pack_rulings(path, [6, 7, 8, 9, 10])
    assert list(rulings) == [6] and rulings[6]['drawing'] == '50009-01-GA' and 'needs drawing' in rulings[6]['evidence']
    assert [n for n, _ in refused] == [7, 8, 9, 10]


def fresh(tmp_path, no_pack=None):
    path = fixture(tmp_path/'t.xlsx', ROWS)
    plan, pics = inp.read_plan(path, no_pack=no_pack)
    return path, plan, pics, batch.Archive(tmp_path/'C', tmp_path/'K'), FakeAPI()


def test_a_no_pack_row_is_sent_with_the_ruling_and_filed_with_it(tmp_path):
    path, plan, pics, archive, api = fresh(tmp_path, RULING)
    assert run(plan, pics, archive, api) == 0
    sent = next(b for b in api.posts if 'NO DRAWING PACK' in b['enquiry_brief'])
    assert sent['drawing_number'] == by_row(plan)[6]['reference'] and sent['units'] == 4
    for root in archive.roots:
        audit = json.loads((root/by_row(plan)[6]['reference']/'results'/'price-for-writeback.json').read_text())
        assert audit['no_drawing_pack'] is True and audit['drawing_number_on_sheet'] == '50009-01-GA'
        assert 'NO DRAWING PACK FOUND' in audit['classification']
        plain = json.loads((root/by_row(plan)[3]['reference']/'results'/'price-for-writeback.json').read_text())
        assert plain['classification'] == 'PROVISIONAL CONCEPT - not a quote' and 'no_drawing_pack' not in plain
    after, _ = inp.read_plan(path, no_pack=RULING)
    assert by_row(after)[6]['state'] == 'has cost' and by_row(after)[7]['cost_before'] in (None, '')


def test_a_row_ruled_after_the_plan_was_filed_is_added_without_rewriting_the_plan(tmp_path):
    path, plan, pics, archive, api = fresh(tmp_path)
    assert run(plan, pics, archive, api) == 0 and len(api.posts) == 2          # rows 3 and 4 only
    filed = [(root/'plan.json').read_bytes() for root in archive.roots]
    ruled, pics = inp.read_plan(path, no_pack=RULING)
    assert run(ruled, pics, archive, api) == 0 and len(api.posts) == 3
    assert [(root/'plan.json').read_bytes() for root in archive.roots] == filed
    names = [sorted(p.name for p in (root/batch.AMENDMENTS).glob('*.json')) for root in archive.roots]
    assert names == [['no-pack-row-00006.json']] * 2
    # A later resume without the option still knows the row, and sends nothing again.
    again, pics = inp.read_plan(path)
    assert run(again, pics, archive, api) == 0 and len(api.posts) == 3
    assert by_row(inp.read_plan(path, no_pack=RULING)[0])[6]['state'] == 'has cost'


def test_an_added_row_still_waits_for_the_approved_proof(tmp_path):
    path, plan, pics, archive, api = fresh(tmp_path)
    assert run(plan, pics, archive, api, selected_rows=[3, 4], proof_rows=(3, 4)) == 0
    ruled, pics = inp.read_plan(path, no_pack=RULING)
    with pytest.raises(RuntimeError, match='PROOF NOT APPROVED'):
        run(ruled, pics, archive, api, proof_rows=(3, 4))
    assert len(api.posts) == 2
    proof.approve_proof(archive, inp.read_plan(path)[0], (3, 4))
    ruled, pics = inp.read_plan(path, no_pack=RULING)
    assert run(ruled, pics, archive, api, proof_rows=(3, 4)) == 0 and len(api.posts) == 3


@pytest.mark.parametrize('fault', ['one root only', 'not a ruling', 'a row that was eligible'])
def test_a_plan_amendment_that_is_not_a_filed_ruling_stops_the_batch(tmp_path, fault):
    path, plan, pics, archive, api = fresh(tmp_path)
    assert run(plan, pics, archive, api) == 0
    ruled = by_row(inp.read_plan(path, no_pack=RULING)[0])[6]
    item = dict(ruled)
    if fault == 'not a ruling': item.pop('no_pack')
    if fault == 'a row that was eligible': item['row'] = 3
    for root in archive.roots[:1 if fault == 'one root only' else 2]:
        (root/batch.AMENDMENTS).mkdir(parents=True, exist_ok=True)
        (root/batch.AMENDMENTS/'no-pack-row-00006.json').write_bytes(batch.json_bytes(item))
    again, pics = inp.read_plan(path)
    with pytest.raises(RuntimeError, match='amendment'):
        run(again, pics, archive, api)
    assert len(api.posts) == 2


def test_an_uncertain_no_pack_submission_can_be_audited_like_any_other(tmp_path):
    path, plan, pics, archive, api = fresh(tmp_path)
    assert run(plan, pics, archive, api) == 0
    ruled, pics = inp.read_plan(path, no_pack=RULING)
    api.fail_post = True
    with pytest.raises(TimeoutError):
        run(ruled, pics, archive, api)
    effective = batch.with_amendments(archive, json.loads((archive.roots[0]/'plan.json').read_text()))
    assert by_row(effective)[6]['state'] == 'eligible' and by_row(effective)[6]['no_pack']
    assert rec.with_amendments is batch.with_amendments


def test_the_two_options_go_together(tmp_path, capsys):
    path = fixture(tmp_path/'t.xlsx', ROWS)
    with pytest.raises(SystemExit):
        batch.main(['--sheet', str(path), '--plan-output', str(tmp_path/'plan.json'), '--no-pack-rows', '6'])
    assert 'go together' in capsys.readouterr().err


def test_the_plan_only_run_reports_accepted_and_refused_rows(tmp_path, capsys):
    path = fixture(tmp_path/'t.xlsx', ROWS)
    led = ledger(tmp_path, [{'row': 6, 'drawing': '50009-01-GA', 'state': 'needs drawing', 'updated': '2026-11-20T10:00:00'},
                            {'row': 7, 'drawing': '50010-01-GA', 'state': 'done', 'updated': '2026-11-20T10:00:00'}])
    assert batch.main(['--sheet', str(path), '--plan-output', str(tmp_path/'plan.json'),
                       '--no-pack-rows', '6,7', '--no-pack-ledger', str(led)]) == 0
    out = capsys.readouterr().out
    assert 'NO-PACK row 7 NOT accepted' in out and 'rows [6]' in out
    saved = json.loads((tmp_path/'plan.json').read_text())
    assert by_row(saved)[6]['state'] == 'eligible' and by_row(saved)[7]['state'] == 'drawing row excluded'
