"""Synthetic OOXML and fake portal: no service calls, CAD, pricing or production writes."""
import copy
import io
import json
import os
from pathlib import Path
import sys
import zipfile
from xml.sax.saxutils import escape

import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import tti_concept_inputs as inp
import tti_concept_batch as batch
import tti_concept_writeback as writer

S=inp.S; R=inp.R; RD=inp.RD
REL='http://schemas.openxmlformats.org/package/2006/relationships'


def fixture(path,rows=None,rich=True):
    rows=rows or [(3,'Fixture',2,''),(4,'Description-only',3,''),(5,'Held',None,''),(6,'Drawing',4,'50009-01-GA')]
    def textcell(c,v): return f'<c r="{c}" t="inlineStr"><is><t>{escape(str(v))}</t></is></c>'
    headers={'E':'Description','F':'Products','G':'Previous Feedback','H':'Latest Feedback','I':'Images','J':'Visual','L':'Drawing Number','N':'Quantity','O':'Cost Each','P':'Column1','Q':'Sell','AN':'Previous Notes'}
    contents='<row r="1">'+textcell('P1','AiCost')+'</row><row r="2">'+''.join(textcell(k+'2',v) for k,v in headers.items())+'</row>'
    for n,desc,qty,ref in rows:
        contents+=f'<row r="{n}">'+''.join(textcell(k+str(n),v) for k,v in {'E':desc,'F':'Drill and battery','G':'Older note','H':'Red finish','L':ref,'AN':'Keep charging accessible'}.items())
        if qty is not None: contents+=f'<c r="N{n}"><v>{qty}</v></c>'
        contents+=f'<c r="O{n}"><v>99999</v></c><c r="P{n}" s="0"/><c r="Q{n}"><f>N{n}*O{n}</f><v>199998</v></c>'
        if n==3 and rich: contents+='<c r="I3" t="e" vm="2"><v>#VALUE!</v></c><c r="J3" t="e" vm="1"><v>#VALUE!</v></c>'
        contents+='</row>'
    files={
        '[Content_Types].xml':'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="xml" ContentType="application/xml"/><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>',
        'xl/workbook.xml':f'<workbook xmlns="{S}" xmlns:r="{R}"><sheets><sheet name="Milwaukee" sheetId="1" r:id="ws"/></sheets></workbook>',
        'xl/_rels/workbook.xml.rels':f'<Relationships xmlns="{REL}"><Relationship Id="ws" Type="{R}/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="other" Type="{R}/custom" Target="../docProps/core.xml"/></Relationships>',
        'xl/worksheets/sheet1.xml':f'<worksheet xmlns="{S}" xmlns:r="{R}"><dimension ref="A1:AN{max(r[0] for r in rows)}"/><sheetData>{contents}</sheetData></worksheet>',
        'docProps/core.xml':'<unchanged/>',
        'xl/metadata.xml':f'<metadata xmlns="{S}" xmlns:rv="{RD}"><metadataTypes><metadataType name="XLRICHVALUE"/></metadataTypes><futureMetadata name="XLRICHVALUE"><bk><extLst><ext><rv:rvb i="1"/></ext></extLst></bk><bk><extLst><ext><rv:rvb i="0"/></ext></extLst></bk></futureMetadata><valueMetadata><bk><rc t="1" v="0"/></bk><bk><rc t="1" v="1"/></bk></valueMetadata></metadata>',
        'xl/richData/rdrichvalue.xml':f'<rvData xmlns="{RD}"><rv s="0"><v>99</v><v>1</v></rv><rv s="0"><v>99</v><v>0</v></rv></rvData>',
        'xl/richData/rdrichvaluestructure.xml':f'<rvStructures xmlns="{RD}"><s t="_localImage"><k n="CalcOrigin"/><k n="_rvRel:LocalImageIdentifier"/></s></rvStructures>',
        'xl/richData/richValueRel.xml':f'<richValueRels xmlns="{RD}" xmlns:r="{R}"><rel r:id="second"/><rel r:id="first"/></richValueRels>',
        'xl/richData/_rels/richValueRel.xml.rels':f'<Relationships xmlns="{REL}"><Relationship Id="first" Target="../media/one.png"/><Relationship Id="second" Target="../media/two.png"/></Relationships>',
        'xl/media/one.png':b'picture ONE', 'xl/media/two.png':b'picture TWO',
    }
    with zipfile.ZipFile(path,'w') as z:
        for k,v in files.items(): z.writestr(k,v)
    return path


def mutate(path,member,fn):
    with zipfile.ZipFile(path) as z: files={n:z.read(n) for n in z.namelist()}
    files[member]=fn(files[member])
    with zipfile.ZipFile(path,'w') as z:
        for k,v in files.items(): z.writestr(k,v)


def test_rich_chain_uses_all_indices_not_media_order(tmp_path):
    path=fixture(tmp_path/'book.xlsx'); plan,pics=inp.read_plan(path)
    assert [(p.cell,p.data) for p in pics[3]]==[('I3',b'picture ONE'),('J3',b'picture TWO')]
    assert [r['row'] for r in plan['rows'] if r['state']=='eligible']==[3,4]
    assert plan['rows'][2]['state']=='held: quantity'
    assert plan['rows'][3]['state']=='drawing row excluded'


@pytest.mark.parametrize('value',[None,0,-1,1.5,True,'n/a','NaN','inf'])
def test_missing_quantity_never_becomes_one(value): assert inp.units(value) is None


@pytest.mark.parametrize('value',[1,'2',3.0])
def test_valid_quantity(value): assert inp.units(value)==int(value)


def test_all_row_facts_and_no_price_anchoring(tmp_path):
    plan,_=inp.read_plan(fixture(tmp_path/'b.xlsx'))
    row=plan['rows'][0]
    for text in ('Drill and battery','Older note','Red finish','Keep charging accessible'):
        assert text in row['brief']
    assert '99999' not in row['brief'] and '#VALUE!' not in row['brief']
    assert any(d['value']==99999 for d in row['details'])
    assert 'description-only' in plan['rows'][1]['brief']


@pytest.mark.parametrize('member,old,new',[
    ('xl/worksheets/sheet1.xml',b'vm="2"',b'vm="99"'),
    ('xl/metadata.xml',b'i="0"',b'i="-1"'),
    ('xl/richData/rdrichvalue.xml',b'<v>1</v>',b'<v>999</v>'),
    ('xl/richData/_rels/richValueRel.xml.rels',b'Id="first" Target=',b'Id="first" TargetMode="External" Target='),
])
def test_broken_images_fail_closed(tmp_path,member,old,new):
    path=fixture(tmp_path/'b.xlsx'); mutate(path,member,lambda b:b.replace(old,new))
    with pytest.raises(ValueError,match='image'): inp.read_plan(path)


def test_picture_outside_ij_is_still_used(tmp_path):
    path=fixture(tmp_path/'b.xlsx'); mutate(path,'xl/worksheets/sheet1.xml',lambda b:b.replace(b'r="J3"',b'r="K3"'))
    _,pics=inp.read_plan(path); assert [p.cell for p in pics[3]]==['I3','K3']


def test_writer_changes_only_target_cell_and_preserves_all_other_members(tmp_path):
    path=fixture(tmp_path/'b.xlsx'); original=path.read_bytes(); plan,_=inp.read_plan(path)
    result=writer.write_cost(path,plan['rows'][0],'12.34')
    assert not result['already_written']
    with zipfile.ZipFile(io.BytesIO(original)) as old,zipfile.ZipFile(path) as new:
        assert old.namelist()==new.namelist()
        for name in old.namelist():
            if name!='xl/worksheets/sheet1.xml': assert old.read(name)==new.read(name)
        text=new.read('xl/worksheets/sheet1.xml')
        assert b'<c r="P3" s="0"><v>12.34</v></c>' in text
        assert b'<c r="Q3"><f>N3*O3</f><v>199998</v></c>' in text
    after,_=inp.read_plan(path); assert after['rows'][0]['cost_before']==12.34
    assert after['rows'][0]['fingerprint']==plan['rows'][0]['fingerprint']
    assert writer.write_cost(path,plan['rows'][0],'12.34')['already_written']
    with pytest.raises(ValueError,match='different'): writer.write_cost(path,plan['rows'][0],'13.00')


def test_changed_row_cannot_receive_old_price(tmp_path):
    path=fixture(tmp_path/'b.xlsx'); plan,_=inp.read_plan(path)
    mutate(path,'xl/worksheets/sheet1.xml',lambda b:b.replace(b'Red finish',b'Blue finish'))
    with pytest.raises(ValueError,match='changed'): writer.write_cost(path,plan['rows'][0],10)


@pytest.mark.parametrize('cell',[b'<c r="P3"><f>1+1</f><v>2</v></c>',b'<c r="P3" vm="1"/>'])
def test_writer_refuses_formula_or_picture_cell(tmp_path,cell):
    path=fixture(tmp_path/'b.xlsx')
    with zipfile.ZipFile(path) as z: xml=z.read('xl/worksheets/sheet1.xml')
    xml=xml.replace(b'<c r="P3" s="0"/>',cell)
    with pytest.raises(ValueError): writer.patch_cell(xml,'P3',10)


def test_exclusive_claim_refuses_stale_and_duplicate(tmp_path):
    path=tmp_path/'batch.lock'
    with batch.exclusive_claim(path):
        with pytest.raises(RuntimeError):
            with batch.exclusive_claim(path): pass
    assert not path.exists()
    path.write_text('{"pid":99999999}')
    with pytest.raises(RuntimeError):
        with batch.exclusive_claim(path): pass
    assert path.exists()


class FakeAPI:
    server='fake'
    def __init__(self): self.runs={}; self.posts=[]; self.fail_post=False; self.failure=False
    def runners(self): return [{'online':True,'runner_id':str(i),'build':'abcdef12 · src test','process_count':1,'conflict':False} for i in (1,2)]
    def recent(self): return list(self.runs.values())
    def start(self,body):
        self.posts.append(body); rid=f'{len(self.posts):012x}'
        self.runs[rid]={'run_id':rid,'status':'running','client':body['client'],'drawing_number':body['drawing_number'],'units':body['units'],
                        'price_validated':True,'engine_price_gbp':12.34,'deliverables':[{'name':'result.xlsx'},{'name':'result_record.json'},{'name':'report.html'}]}
        if self.fail_post: raise TimeoutError('accepted then connection lost')
        return {'run_id':rid}
    def status(self,rid):
        s=self.runs[rid]; s['status']='error' if self.failure else 'done'
        if self.failure: s['error']='test error'
        return s
    def download(self,rid,name):
        if name=='result_record.json': return batch.json_bytes({'quantity':self.runs[rid]['units'],'llm_only':True,'parts':[{'description':'recorded'}]})
        if name=='report.html': return b'<html>DRAFT report</html>'
        out=io.BytesIO()
        with zipfile.ZipFile(out,'w') as z: z.writestr('xl/workbook.xml','<workbook/>')
        return out.getvalue()


def setup(tmp_path,rows=None):
    path=fixture(tmp_path/'tracker.xlsx',rows=rows)
    plan,pics=inp.read_plan(path); archive=batch.Archive(tmp_path/'C',tmp_path/'K'); api=FakeAPI()
    return path,plan,pics,archive,api


def run(plan,pics,archive,api,**kw):
    return batch.run_batch(plan,pics,archive,api,'abcdef12',sleep=lambda _:None,**kw)


def test_two_concepts_archive_both_roots_then_writeback_and_resume_without_post(tmp_path):
    path,plan,pics,a,api=setup(tmp_path)
    original=path.read_bytes()
    assert run(plan,pics,a,api)==0
    assert len(api.posts)==2
    assert len(api.posts[0]['files'])==2 and api.posts[1]['files']==[]
    assert all(b['method']=='llm' and b['email_to']=='' for b in api.posts)
    current,_=inp.read_plan(path)
    assert [r['cost_before'] for r in current['rows']]==[12.34,12.34,None,None]
    for root in a.roots:
        assert (root/'source-workbook.xlsx').read_bytes()==original
        for row in plan['rows'][:2]:
            assert (root/row['reference']/'inputs'/'source-row.json').exists()
            assert (root/row['reference']/'results'/'result_record.json').exists()
            assert (root/row['reference']/'results'/'report.html').exists()
    assert run(current,pics,a,api)==0 and len(api.posts)==2


def test_uncertain_post_never_repeated_and_unique_recovery_works(tmp_path):
    path,plan,pics,a,api=setup(tmp_path,[(3,'One',2,'')]); api.fail_post=True
    with pytest.raises(TimeoutError): run(plan,pics,a,api)
    assert batch.read_json(a.roots[0]/'state.json')['entries'][plan['rows'][0]['reference']]['phase']=='submitting'
    api.fail_post=False
    assert run(plan,pics,a,api)==0
    assert len(api.posts)==1


def test_uncertain_post_not_found_stops_no_resend(tmp_path):
    _,plan,pics,a,api=setup(tmp_path); api.fail_post=True
    with pytest.raises(TimeoutError): run(plan,pics,a,api)
    api.runs.clear(); api.fail_post=False
    with pytest.raises(RuntimeError,match='uncertain'): run(plan,pics,a,api)
    assert len(api.posts)==1


def test_engine_failure_stops_further_submissions(tmp_path):
    _,plan,pics,a,api=setup(tmp_path,[(3,'One',1,''),(4,'Two',2,''),(5,'Three',3,'')]); api.failure=True
    with pytest.raises(RuntimeError,match='failed/held'): run(plan,pics,a,api)
    assert len(api.posts)==2


def test_archive_failure_prevents_cost_write(tmp_path):
    path,plan,pics,a,api=setup(tmp_path); original=path.read_bytes()
    def broken(*args): raise OSError('K unavailable')
    api.download=broken
    with pytest.raises(OSError): run(plan,pics,a,api)
    assert path.read_bytes()==original


def test_stop_file_starts_nothing(tmp_path):
    _,plan,pics,a,api=setup(tmp_path); stop=tmp_path/'STOP'; stop.touch()
    assert run(plan,pics,a,api,stop_file=stop)==2
    assert not api.posts


def test_other_live_job_blocks_batch(tmp_path):
    _,plan,pics,a,api=setup(tmp_path)
    api.runs['a'*12]={'run_id':'a'*12,'status':'running','client':'Other'}
    with pytest.raises(RuntimeError,match='Other jobs'): run(plan,pics,a,api)
    assert not api.posts


@pytest.mark.parametrize('change',[{'online':False},{'build':'1234567'},{'build':'abcdef12 +local edits'},{'process_count':2},{'conflict':True}])
def test_runner_gate(change):
    runners=FakeAPI().runners(); runners[0].update(change)
    with pytest.raises(RuntimeError): batch.check_build(runners,'abcdef12')


@pytest.mark.parametrize('changes',[{'units':20},{'price_validated':False},{'engine_price_gbp':0},{'quantity_prices':[{'quantity':1,'unit_gbp':10}]},
                                   {'quantity_prices':[{'quantity':2,'unit_gbp':10},{'quantity':2,'unit_gbp':20}]}])
def test_no_wrong_quantity_or_unvalidated_write(changes):
    item={'reference':'TTI-C-test','quantity':2}
    s={'client':'TTI','drawing_number':item['reference'],'units':2,'status':'done','price_validated':True,'engine_price_gbp':12}
    s.update(changes)
    with pytest.raises(ValueError): batch.checked_price(s,item)


def test_plan_cli_never_calls_service(tmp_path,monkeypatch):
    path=fixture(tmp_path/'b.xlsx'); out=tmp_path/'plan.json'
    monkeypatch.setattr(batch.Client,'start',lambda *a:pytest.fail('POST in plan'))
    assert batch.main(['--sheet',str(path),'--plan-output',str(out)])==0
    assert out.exists()


def test_actual_tracker_read_only_when_explicitly_provided():
    path=os.getenv('SDI_TTI_CONCEPT_TRACKER')
    if not path: pytest.skip('private workbook not supplied; set SDI_TTI_CONCEPT_TRACKER')
    original=Path(path).read_bytes(); plan,pics=inp.read_plan(path)
    eligible=[r for r in plan['rows'] if r['state']=='eligible']
    assert len(eligible)==144
    assert sum(bool(r['images']) for r in eligible)==116
    assert sum(not r['images'] for r in eligible)==28
    assert [r['row'] for r in plan['rows'] if r['state']=='held: quantity']==[65,93,94,105,106,107,208,209,210,211]
    assert sum(map(len,pics.values()))==316
    assert Path(path).read_bytes()==original


def test_float_image_is_attached_by_actual_row(tmp_path):
    path=fixture(tmp_path/'b.xlsx',rich=False)
    with zipfile.ZipFile(path,'a') as z:
        z.writestr('xl/worksheets/_rels/sheet1.xml.rels',f'<Relationships xmlns="{REL}"><Relationship Id="draw" Type="{R}/drawing" Target="../drawings/drawing1.xml"/></Relationships>')
        z.writestr('xl/drawings/drawing1.xml',f'<wsDr xmlns="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing" xmlns:r="{R}" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><twoCellAnchor><from><col>8</col><row>3</row></from><pic><blipFill><a:blip r:embed="pic"/></blipFill></pic></twoCellAnchor></wsDr>')
        z.writestr('xl/drawings/_rels/drawing1.xml.rels',f'<Relationships xmlns="{REL}"><Relationship Id="pic" Target="../media/one.png"/></Relationships>')
    mutate(path,'xl/worksheets/sheet1.xml',lambda b:b.replace(b'</worksheet>',b'<drawing r:id="draw"/></worksheet>'))
    _,pics=inp.read_plan(path)
    assert list(pics)==[4] and pics[4][0].cell=='I4'


def test_write_requires_both_archives_first(tmp_path):
    _,plan,pics,a,api=setup(tmp_path)
    def assert_archived(path,item,price,sheet):
        for root in a.roots:
            assert (root/item['reference']/'results'/'result_record.json').exists()
            assert (root/item['reference']/'results'/'result.xlsx').exists()
            assert (root/item['reference']/'results'/'price-for-writeback.json').exists()
        return writer.write_cost(path,item,price,sheet)
    assert run(plan,pics,a,api,writer=assert_archived)==0


def test_mismatched_archive_ledgers_never_submit(tmp_path):
    _,plan,pics,a,api=setup(tmp_path)
    a.roots[0].mkdir(); (a.roots[0]/'state.json').write_text('{}')
    with pytest.raises(RuntimeError,match='ledgers disagree'): run(plan,pics,a,api)
    assert not api.posts


def test_open_excel_defers_writeback_not_submission(tmp_path):
    path,plan,pics,a,api=setup(tmp_path); (path.parent/('~$'+path.name)).touch()
    assert run(plan,pics,a,api)==3
    assert len(api.posts)==2
    assert all(e['phase']=='archived' for e in batch.read_json(a.roots[0]/'state.json')['entries'].values())


def test_completed_but_manually_changed_cost_is_not_silently_done(tmp_path):
    path,plan,pics,a,api=setup(tmp_path); assert run(plan,pics,a,api)==0
    mutate(path,'xl/worksheets/sheet1.xml',lambda b:b.replace(b'<v>12.34</v>',b'<v>99.00</v>'))
    with pytest.raises(ValueError,match='previously written'): run(plan,pics,a,api)
    assert len(api.posts)==2


def test_crash_after_cost_write_resumes_without_reprice(tmp_path):
    path,plan,pics,a,api=setup(tmp_path,[(3,'One',1,'')])
    def crash_after_write(*args):
        writer.write_cost(*args); raise RuntimeError('simulated crash after write')
    with pytest.raises(RuntimeError,match='simulated crash'): run(plan,pics,a,api,writer=crash_after_write)
    current,_=inp.read_plan(path)
    assert run(current,pics,a,api)==0 and len(api.posts)==1


def test_pilot_then_full_plan_does_not_duplicate(tmp_path):
    path,plan,pics,a,api=setup(tmp_path)
    assert run(plan,pics,a,api,selected_rows=[3])==0 and len(api.posts)==1
    current,_=inp.read_plan(path)
    assert run(current,pics,a,api)==0 and len(api.posts)==2


@pytest.mark.parametrize('rows',[[5],[6],[999],[]])
def test_rows_cannot_force_held_or_drawing_or_unknown(tmp_path,rows):
    _,plan,pics,a,api=setup(tmp_path)
    with pytest.raises(ValueError,match='eligible'): run(plan,pics,a,api,selected_rows=rows)
    assert not api.posts


@pytest.mark.parametrize('source_qty',[None,0])
def test_explicit_quantity_one_ruling_preserves_source_and_archives_assumption(tmp_path,source_qty):
    path=fixture(tmp_path/'b.xlsx',rows=[(3,'Assumed one',source_qty,'')])
    strict,_=inp.read_plan(path)
    assert strict['rows'][0]['state']=='held: quantity'
    plan,pics=inp.read_plan(path,assume_missing_quantity_one=True)
    row=plan['rows'][0]
    assert row['state']=='eligible' and row['quantity']==1 and row['quantity_assumed']
    assert row['source_quantity']==source_qty
    assert row['fingerprint']!=strict['rows'][0]['fingerprint']
    assert 'QUANTITY ASSUMPTION: price ONE unit' in row['brief']
    archive=batch.Archive(tmp_path/'C',tmp_path/'K'); api=FakeAPI()
    assert run(plan,pics,archive,api)==0
    assert api.posts[0]['units']==1 and api.posts[0]['quantity_breaks']==[1]
    new,_=inp.read_plan(path,assume_missing_quantity_one=True)
    assert new['rows'][0]['source_quantity']==source_qty and new['rows'][0]['cost_before']==12.34
    for root in archive.roots:
        audit=batch.read_json(root/row['reference']/'results'/'price-for-writeback.json')
        assert audit['quantity_assumed'] and audit['source_quantity']==source_qty
        assert audit['unit_gbp']=='12.34' and audit['order_total_gbp']=='12.34'
    assert run(new,pics,archive,api)==0 and len(api.posts)==1


@pytest.mark.parametrize('value',[-1,1.5,True,'invalid','nan','inf'])
def test_quantity_one_does_not_hide_other_invalid_values(value):
    assert not inp.missing_or_zero(value)


def test_valid_row_identity_and_unit_writeback_unchanged_under_new_policy(tmp_path):
    path=fixture(tmp_path/'b.xlsx',rows=[(3,'Four units',4,'')])
    old,_=inp.read_plan(path); new,pics=inp.read_plan(path,assume_missing_quantity_one=True)
    assert old['rows'][0]['fingerprint']==new['rows'][0]['fingerprint']
    archive=batch.Archive(tmp_path/'C',tmp_path/'K'); api=FakeAPI()
    assert run(new,pics,archive,api)==0
    current,_=inp.read_plan(path)
    assert current['rows'][0]['cost_before']==12.34  # NOT 49.36
    audit=batch.read_json(archive.roots[0]/new['rows'][0]['reference']/'results'/'price-for-writeback.json')
    assert audit['order_total_gbp']=='49.36' and audit['unit_gbp']=='12.34'


def test_existing_plan_cannot_silently_change_quantity_policy(tmp_path):
    path,plan,pics,archive,api=setup(tmp_path)
    stop=tmp_path/'STOP'; stop.touch()
    assert run(plan,pics,archive,api,stop_file=stop)==2
    changed,pics=inp.read_plan(path,assume_missing_quantity_one=True)
    with pytest.raises(RuntimeError,match='Quantity policy differs'): run(changed,pics,archive,api)
    assert not api.posts


def test_drawing_row_never_becomes_a_concept_with_assumed_quantity(tmp_path):
    path=fixture(tmp_path/'b.xlsx',rows=[(3,'Drawing',None,'50009-01-GA')])
    plan,_=inp.read_plan(path,assume_missing_quantity_one=True)
    assert plan['rows'][0]['state']=='drawing row excluded'
    assert not plan['rows'][0]['quantity_assumed']


def test_actual_tracker_quantity_one_ruling_read_only():
    path=os.getenv('SDI_TTI_CONCEPT_TRACKER')
    if not path: pytest.skip('private actual tracker not supplied')
    raw=Path(path).read_bytes()
    plan,_=inp.read_plan(path,assume_missing_quantity_one=True)
    assert len([r for r in plan['rows'] if r['state']=='eligible'])==154
    assert [r['row'] for r in plan['rows'] if r['quantity_assumed']]==[65,93,94,105,106,107,208,209,210,211]
    assert not any(r['state']=='held: quantity' for r in plan['rows'])
    assert Path(path).read_bytes()==raw
