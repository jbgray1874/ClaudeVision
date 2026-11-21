"""The drawing pricer's status report is the proof that a row has no pack, for the workbook
it was made on and no other (21 Nov 2026). The pricer keeps "needs drawing" only in that
report, and rows move between copies of a tracker: rows named from another copy's numbers
were all refused. Made-up rows."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
sys.path.insert(0, str(ROOT/'tests'))
import tti_concept_batch as batch
import tti_concept_inputs as inp
from test_tti_concept_batch import fixture

ROWS = [(3, 'Image pilot', 2, ''), (6, 'Counter unit, no pack', 4, '50009-01-GA'), (7, 'Has its drawings', 1, '50010-01-GA')]


def report(tmp_path, sheet, rows):
    path = tmp_path/'pack check.json'
    path.write_text(json.dumps({'sheet': str(sheet), 'updated': '2026-11-21T19:40:00', 'dry_run': True, 'rows': rows}))
    return path


def test_a_report_made_on_this_workbook_is_accepted_row_by_row(tmp_path):
    sheet = fixture(tmp_path/'t.xlsx', ROWS)
    rep = report(tmp_path, sheet, [
        {'row': 6, 'drawing': '50009-01-GA', 'drawing_cell': '50009-01-GA', 'state': 'needs drawing', 'why': 'no drawings found for this number'},
        {'row': 7, 'drawing': '50010-01-GA', 'state': 'planned'}])
    rulings, refused = inp.no_pack_rulings(rep, [6, 7], sheet=sheet)
    assert list(rulings) == [6] and 'recorded 2026-11-21T19:40:00' in rulings[6]['evidence']
    assert [n for n, _ in refused] == [7]
    plan, _ = inp.read_plan(sheet, no_pack=rulings)
    assert {r['row']: r['state'] for r in plan['rows']}[6] == 'eligible'


def test_a_report_made_on_another_copy_is_refused_whole(tmp_path):
    sheet = fixture(tmp_path/'t.xlsx', ROWS)
    other = fixture(tmp_path/'t (2).xlsx', ROWS)
    rep = report(tmp_path, other, [{'row': 6, 'drawing': '50009-01-GA', 'state': 'needs drawing'}])
    rulings, refused = inp.no_pack_rulings(rep, [6], sheet=sheet)
    assert rulings == {} and 'another workbook' in refused[0][1]


def test_a_row_the_report_puts_under_another_drawing_is_held(tmp_path):
    sheet = fixture(tmp_path/'t.xlsx', ROWS)
    rep = report(tmp_path, sheet, [{'row': 6, 'drawing': '59999-01-GA', 'state': 'needs drawing'}])
    rulings, _ = inp.no_pack_rulings(rep, [6], sheet=sheet)
    plan, _ = inp.read_plan(sheet, no_pack=rulings)
    assert {r['row']: r['state'] for r in plan['rows']}[6] == 'held: no-pack ruling names another drawing'


def test_the_command_line_checks_the_report_against_the_sheet_it_was_given(tmp_path, capsys):
    sheet = fixture(tmp_path/'t.xlsx', ROWS)
    other = fixture(tmp_path/'t (2).xlsx', ROWS)
    rep = report(tmp_path, other, [{'row': 6, 'drawing': '50009-01-GA', 'state': 'needs drawing'}])
    assert batch.main(['--sheet', str(sheet), '--plan-output', str(tmp_path/'plan.json'),
                       '--no-pack-rows', '6', '--no-pack-ledger', str(rep)]) == 0
    out = capsys.readouterr().out
    assert 'NO-PACK row 6 NOT accepted' in out and 'another workbook' in out and 'rows []' in out


def test_a_ledger_is_still_read_as_before(tmp_path):
    led = tmp_path/'l.json'
    led.write_text(json.dumps({'6|X|4': {'row': 6, 'drawing': '50009-01-GA', 'state': 'needs drawing', 'updated': '2026-11-20T10:00:00'}}))
    rulings, refused = inp.no_pack_rulings(led, [6], sheet=tmp_path/'anything.xlsx')
    assert list(rulings) == [6] and not refused
