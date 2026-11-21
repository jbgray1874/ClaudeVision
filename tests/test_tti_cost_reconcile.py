import copy
import hashlib
import json
from pathlib import Path
import sys
import zipfile
from xml.sax.saxutils import escape

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from tti_cost_reconcile import Tracker, make_plan, write_copy, run_price, money, main, patch_xml

NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'


def book(path, row=3, cost=None, qty=2, description='Fixture', formula=False, merge=False):
    cells = {'A':'REF1','D':'Zone','E':description,'G':'Approved','H':'Red finish','L':'99901-01-GA','N':str(qty)}
    header = {'E':'Description','G':'Previous Feedback','H':'Latest Feedback','L':'Drawing Number','N':'Quantity','P':'AiCost'}
    def xmlrow(n, vals):
        return f'<row r="{n}">' + ''.join(f'<c r="{c}{n}" t="inlineStr"><is><t>{escape(str(v))}</t></is></c>' for c,v in vals.items()) + '</row>'
    if cost is not None: cells['P'] = str(cost)
    sheet = f'<worksheet xmlns="{NS}"><sheetData>' + xmlrow(2, header) + xmlrow(row,cells) + '</sheetData>'
    if merge: sheet += f'<mergeCells count="1"><mergeCell ref="P{row}:Q{row}"/></mergeCells>'
    sheet += '</worksheet>'
    if formula: sheet = sheet.replace(f'<c r="P{row}" t="inlineStr"><is><t>{cost}</t></is></c>',f'<c r="P{row}"><f>1+1</f><v>2</v></c>')
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('xl/workbook.xml', f'<workbook xmlns="{NS}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Milwaukee" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>')
        z.writestr('xl/worksheets/sheet1.xml',sheet)
        z.writestr('xl/media/image1.png', b'picture bytes must never change')
        z.writestr('xl/richData/rdrichvalue.xml',b'<richData>preserve</richData>')
        z.writestr('xl/tables/table1.xml',b'<table>preserve</table>')
        z.writestr('xl/worksheets/sheet2.xml',b'<worksheet>untouched</worksheet>')
    return Tracker(path)


@pytest.fixture
def setup(tmp_path):
    source=book(tmp_path/'source.xlsx',cost=12.5)
    target=book(tmp_path/'target.xlsx',row=7)
    entry=dict(row=3,tab='Milwaukee',drawing='99901-01-GA',quantity=2,inputs={'brief':source.brief_hash(3),'client':'TTI'},run_id='abcdef123456',state='done',unit_cost=12.5,approval='provisional')
    run=dict(run_id=entry['run_id'],source='TTI batch',drawing_number=entry['drawing'],units=2,client='TTI',status='done',finished_at=100,engine_price_gbp=12.5)
    ledger=tmp_path/'ledger.json'
    runs=tmp_path/'runs'; runs.mkdir()
    def plan(e=None,r=None):
        ledger.write_text(json.dumps({'entry':e or entry}),encoding='utf-8')
        (runs/(run['run_id']+'.json')).write_text(json.dumps(r or run),encoding='utf-8')
        return make_plan(target,source,[ledger],runs)
    return source,target,entry,run,plan,ledger,runs


def test_shifted_rows_match_brief_not_old_row(setup):
    p=setup[4]()
    assert p['rows'][0]['cell']=='P7'
    assert p['rows'][0]['source_row']==3
    assert p['rows'][0]['unit_cost']==12.5
    assert p['rows'][0]['action']=='fill'


@pytest.mark.parametrize('field,value',[('quantity',3),('drawing','99901-01-GA2'),('tab','Other')])
def test_ledger_identity_mismatch_held(setup,field,value):
    e=copy.deepcopy(setup[2]);e[field]=value
    assert setup[4](e)['rows'][0]['action']=='held'


def test_brief_hash_mismatch_held(setup):
    e=copy.deepcopy(setup[2]);e['inputs']['brief']='wrong'
    assert setup[4](e)['rows'][0]['action']=='held'


@pytest.mark.parametrize('status',['running','queued','error','cancelled','abandoned'])
def test_non_finished_run_held(setup,status):
    r=dict(setup[3],status=status)
    assert setup[4](r=r)['rows'][0]['action']=='held'


def test_done_service_recovers_running_ledger(setup):
    e=dict(setup[2],state='running',unit_cost=None)
    assert setup[4](e)['rows'][0]['action']=='fill'


def test_stale_ledger_is_not_written(setup):
    r=dict(setup[3],engine_price_gbp=15)
    assert setup[4](r=r)['rows'][0]['action']=='held'


def test_exact_quantity_no_fallback():
    with pytest.raises(ValueError):run_price({'units':1,'engine_price_gbp':100},2)
    assert run_price({'units':1,'engine_price_gbp':100,'quantity_prices':[{'quantity':2,'unit_gbp':90}]},2)==90


@pytest.mark.parametrize('cost',[None,True,float('nan'),float('inf'),-1])
def test_invalid_costs_rejected(cost):
    with pytest.raises((ValueError,ArithmeticError)):money(cost)


def test_preserve_all_members_and_other_cells(setup,tmp_path):
    target=setup[1]; out=tmp_path/'out.xlsx'
    before=target.raw
    write_copy(target,{'P7':12.5},out)
    got=Tracker(out)
    assert money(got.rows[7]['P'])==12.5
    with zipfile.ZipFile(target.path) as a,zipfile.ZipFile(out) as b:
        assert a.namelist()==b.namelist()
        for name in a.namelist():
            if name!=target.member:assert a.read(name)==b.read(name)
    for row,values in target.rows.items():
        for col,value in values.items(): assert got.rows[row][col]==value
    assert target.path.read_bytes()==before
    with pytest.raises(ValueError):write_copy(target,{'P7':20},out)
    with pytest.raises(ValueError):write_copy(target,{'P7':20},target.path)


@pytest.mark.parametrize('kwargs',[{'cost':2,'formula':True},{'merge':True}])
def test_formula_or_merge_never_overwritten(tmp_path,kwargs):
    b=book(tmp_path/'in.xlsx',**kwargs)
    with pytest.raises(ValueError):write_copy(b,{'P3':50},tmp_path/'out.xlsx')


def test_source_change_rejected_before_publish(setup,tmp_path):
    target=setup[1]
    target.path.write_bytes(target.raw+b'changed')
    with pytest.raises(ValueError,match='target changed'):write_copy(target,{'P7':10},tmp_path/'out.xlsx')
    assert not (tmp_path/'out.xlsx').exists()


def test_cli_dryrun_and_apply_audited(setup,tmp_path):
    source,target,e,r,plan,ledger,runs=setup
    plan()
    args=['--target',str(target.path),'--source',str(source.path),'--ledger',str(ledger),'--runs-dir',str(runs),'--audit-dir',str(tmp_path/'audit')]
    before=target.path.read_bytes()
    assert main(args)==0
    assert target.path.read_bytes()==before
    out=tmp_path/'result.xlsx'
    assert main(args+['--apply','--output',str(out)])==0
    assert money(Tracker(out).rows[7]['P'])==12.5
    assert len(list((tmp_path/'audit').glob('*/events.jsonl')))==2
    assert target.path.read_bytes()==before


def test_conflicting_quantity_breaks():
    with pytest.raises(ValueError):run_price({'quantity_prices':[{'quantity':2,'unit_gbp':3},{'quantity':2,'unit_gbp':4}]},2)


def test_newer_unlinked_run_blocks_stale_write(setup):
    setup[4]()
    newer=dict(setup[3],run_id='abcdef999999',finished_at=200,engine_price_gbp=9)
    (setup[6]/'abcdef999999.json').write_text(json.dumps(newer))
    r=setup[4]() ['rows'][0]
    assert r['action']=='held'
    assert 'newer completed' in r['reason']


def test_numeric_existing_needs_explicit_replacement(setup,tmp_path):
    source,target,e,r,plan,ledger,runs=setup
    plan()
    target=book(tmp_path/'other.xlsx',row=7,cost=999)
    assert make_plan(target,source,[ledger],runs)['rows'][0]['action']=='replace'


def test_changed_scope_not_matched_by_drawing_alone(setup,tmp_path):
    source,target,e,r,plan,ledger,runs=setup
    plan()
    target=book(tmp_path/'changed.xlsx',row=7,description='Changed size')
    assert make_plan(target,source,[ledger],runs)['rows'][0]['action']=='held'


def test_latest_linked_run_uses_finish_time_not_file_time(setup,tmp_path):
    source,target,e,r,plan,ledger,runs=setup
    plan()
    older=dict(e,run_id='abcdef000000')
    oldrun=dict(r,run_id='abcdef000000',finished_at=50)
    (runs/'abcdef000000.json').write_text(json.dumps(oldrun))
    other=tmp_path/'other-ledger.json';other.write_text(json.dumps({'old':older}))
    result=make_plan(target,source,[other,ledger],runs)['rows'][0]
    assert result['run_id']==r['run_id']
    assert result['action']=='fill'


def test_empty_styled_cell_does_not_swallow_next_formula():
    xml='<worksheet><sheetData><row r="3"><c r="P3" s="10"/><c r="Q3"><f>A3*N3</f><v>12</v></c></row></sheetData></worksheet>'
    result=patch_xml(xml,{'P3':1.25})
    assert result==xml.replace('<c r="P3" s="10"/>','<c r="P3" s="10"><v>1.25</v></c>')


def test_missing_quantity_is_reported_not_silently_dropped(setup,tmp_path):
    source,target,e,r,plan,ledger,runs=setup
    plan()
    target=book(tmp_path/'missing-qty.xlsx',row=7,qty='')
    result=make_plan(target,source,[ledger],runs)['rows'][0]
    assert result['action']=='held'
    assert 'quantity missing' in result['reason']
