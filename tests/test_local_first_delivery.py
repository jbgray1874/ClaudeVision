"""Fault injection only: no live servers, Excel, VPN, shares or AI calls."""
import errno
from io import BytesIO
import json
from pathlib import Path
import re
import sys
from types import SimpleNamespace
import zipfile

import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools/runner'))
import runner_delivery as D
import sdi_estimate_runner as R


def template_bytes():
    out=BytesIO()
    with zipfile.ZipFile(out,'w') as z:
        z.writestr('xl/workbook.xml','''<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Estimate" r:id="r1"/><sheet name="Labour" r:id="r2"/><sheet name="Material Price Break" r:id="r3"/></sheets></workbook>''')
        z.writestr('xl/_rels/workbook.xml.rels','''<Relationships><Relationship Id="r1" Target="worksheets/sheet1.xml"/><Relationship Id="r2" Target="worksheets/sheet2.xml"/><Relationship Id="r3" Target="worksheets/sheet3.xml"/></Relationships>''')
        z.writestr('xl/worksheets/sheet1.xml','''<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row><c r="D3"/><c r="D5"/><c r="D6"/><c r="M105"><f>SUM(A1)/$D$6</f></c></row></sheetData></worksheet>''')
        for i in [2,3]: z.writestr(f'xl/worksheets/sheet{i}.xml','<worksheet/>')
    return out.getvalue()


def test_template_copy_pins_hash_and_structure(tmp_path):
    source=tmp_path/'template.xlsx';source.write_bytes(template_bytes())
    path,record=D.template_copy(source,tmp_path/'cache',clock=lambda:100)
    assert path.read_bytes()==source.read_bytes() and record['sha256']==D.digest(source.read_bytes())
    assert not record['offline_cache'] and record['structure']['formula_count']==1


def test_template_survives_source_disappearing_without_changing_bytes(tmp_path):
    source=tmp_path/'template.xlsx';source.write_bytes(template_bytes())
    first,_=D.template_copy(source,tmp_path/'cache',clock=lambda:100)
    source.unlink()
    path,record=D.template_copy(source,tmp_path/'cache',clock=lambda:101)
    assert path==first and record['offline_cache']


def test_readable_invalid_source_never_silently_uses_old_rates(tmp_path):
    source=tmp_path/'template.xlsx';source.write_bytes(template_bytes())
    D.template_copy(source,tmp_path/'cache')
    source.write_bytes(b'corrupt download')
    with pytest.raises(ValueError):D.template_copy(source,tmp_path/'cache')


@pytest.mark.parametrize('action',['expired','tampered','no cache'])
def test_unsafe_or_stale_cache_is_refused(tmp_path,action):
    source=tmp_path/'template.xlsx';source.write_bytes(template_bytes())
    if action!='no cache':
        local,_=D.template_copy(source,tmp_path/'cache',clock=lambda:1)
        if action=='tampered':local.write_bytes(b'changed locally')
    source.unlink()
    with pytest.raises((ValueError,OSError)):
        D.template_copy(source,tmp_path/'cache',clock=lambda:100000 if action=='expired' else 2)


def test_new_template_does_not_modify_a_running_jobs_pinned_copy(tmp_path):
    source=tmp_path/'template.xlsx';source.write_bytes(template_bytes())
    first,record=D.template_copy(source,tmp_path/'cache')
    # Different valid ZIP container, same workbook formulas: a separate immutable version.
    raw=BytesIO(template_bytes())
    with zipfile.ZipFile(raw,'a') as z:z.writestr('revision.txt','revision two')
    source.write_bytes(raw.getvalue())
    second,_=D.template_copy(source,tmp_path/'cache')
    assert first!=second and D.digest(first.read_bytes())==record['sha256']


def test_local_inputs_preserve_files_and_selected_pdf(tmp_path):
    source=tmp_path/'staged';source.mkdir();(source/'D-1.pdf').write_bytes(b'pdf evidence')
    dest,pdf,files=D.pin_inputs(source,source/'D-1.pdf',tmp_path/'local')
    assert pdf==dest/'D-1.pdf' and pdf.read_bytes()==b'pdf evidence'
    assert files[0]['sha256']==D.digest(b'pdf evidence')
    with pytest.raises(ValueError):D.pin_inputs(source,tmp_path/'outside.pdf',tmp_path/'other')


@pytest.fixture
def delivery(tmp_path,monkeypatch):
    monkeypatch.setattr(R,'_unit_cost_from_deliverables',lambda *a,**kw:12.34)
    monkeypatch.setattr(R,'_quantity_prices_from_deliverables',lambda *a,**kw:[{'quantity':2,'unit_gbp':12.34}])
    monkeypatch.setattr(R,'file_parity',lambda *a,**kw:None)
    monkeypatch.setattr(R.time,'sleep',lambda *a:None)
    root=D.local_root(tmp_path,'runner-1')
    source=tmp_path/'collected';source.mkdir();(source/'D-1_20261122_100000.xlsx').write_bytes(b'finished book')
    files=[dict(name=p.name,path=str(p)) for p in source.iterdir()]
    job=dict(run_id='abcdef123456',drawing_number='D-1',client='TTI',units=2,output_path=str(tmp_path/'share'/'run'),api_key='MUST NOT BE SAVED')
    manifest=D.stage(root,job,'runner-1','http://service/api/estimate',files,['engine finished'],1,{})
    return SimpleNamespace(root=root,manifest=manifest,job=job,engine=tmp_path)


class Reply:
    def __init__(self,body):self.body=body
    def json(self):return self.body
    def raise_for_status(self):pass


class Service:
    def __init__(self,d):
        self.live=dict(d.job,status='running',runner='runner-1',deliverables=[],engine_price_gbp=None)
        self.posts=[];self.lose_ack=False;self.cancel=False
    def get(self,*a,**kw):return Reply(self.live)
    def post(self,url,json,**kw):
        self.posts.append((url,json))
        assert '/runner/abcdef123456/' in url,'must never submit a new estimate'
        if url.endswith('/progress'):return Reply({'cancel':self.cancel})
        assert url.endswith('/complete')
        self.live.update(status='done',deliverables=json['deliverables'],engine_price_gbp=json['unit_cost_gbp'],quantity_prices=json['quantity_prices'])
        if self.lose_ack:raise OSError('completion response lost')
        return Reply({'ok':True})


def resume(d,service):
    return R.resume_deliveries(service,['http://service'],{'X-SDI-Key':'never persist'},'runner-1',d.engine,Path('python'))


def test_local_result_contains_no_auth_and_can_publish_repeatably(delivery):
    d=delivery;state=D.load(d.manifest)
    assert 'MUST NOT BE SAVED' not in d.manifest.read_text()
    assert D.publish(d.manifest,state)==D.publish(d.manifest,state)
    assert (Path(d.job['output_path'])/state['inventory'][0]['name']).read_bytes()==b'finished book'


def test_vpn_loss_then_reconnect_retries_files_not_engine(delivery,monkeypatch):
    d=delivery; service=Service(d);real=D.publish
    def offline(*a,**kw):raise OSError(errno.ENETUNREACH,'share down')
    monkeypatch.setattr(D,'publish',offline)
    monkeypatch.setattr(R.subprocess,'Popen',lambda *a,**kw:pytest.fail('must not run engine or Excel during filing'))
    assert not resume(d,service)
    assert D.load(d.manifest)['phase']=='pending'
    assert D.verify_local(d.manifest,D.load(d.manifest))
    assert not any(url.endswith('/complete') for url,_ in service.posts)
    monkeypatch.setattr(D,'publish',real)
    assert resume(d,service)
    assert D.load(d.manifest)['phase']=='reported' and service.live['engine_price_gbp']==12.34
    before=len(service.posts)
    assert resume(d,service) and len(service.posts)==before


def test_lost_completion_ack_reconciles_same_existing_run(delivery):
    d=delivery;service=Service(d);service.lose_ack=True
    assert not resume(d,service)
    assert D.load(d.manifest)['phase']=='pending' and service.live['status']=='done'
    before=len(service.posts)
    assert resume(d,service)
    assert D.load(d.manifest)['phase']=='reported' and len(service.posts)==before


def test_service_authorised_lease_expiry_recovery_does_not_rerun(delivery):
    d=delivery;service=Service(d)
    service.live.update(status='error',filing_recovery_allowed=True)
    assert resume(d,service)
    assert D.load(d.manifest)['phase']=='reported'
    complete=[body for url,body in service.posts if url.endswith('/complete')]
    assert len(complete)==1 and complete[0]['recover_expired_run'] is True
    assert complete[0]['local_first_delivery'] is True
    assert not any(url.endswith('/progress') for url,_ in service.posts)


def test_finished_service_quantity_prices_must_match_saved_completion(delivery):
    d=delivery;service=Service(d);service.lose_ack=True
    assert not resume(d,service)
    service.live['quantity_prices']=[{'quantity':2,'unit_gbp':999.0}]
    before=len(service.posts)
    assert resume(d,service)
    assert D.load(d.manifest)['phase']=='held' and len(service.posts)==before


@pytest.mark.parametrize('change',['owner','quantity','destination','cancel','stopped','different bytes'])
def test_unsafe_recovery_is_held_not_overwritten_or_repriced(delivery,change):
    d=delivery;service=Service(d)
    if change=='owner':service.live['runner']='another runner'
    if change=='quantity':service.live['units']=55
    if change=='destination':service.live['output_path']=str(d.engine/'wrong target')
    if change=='cancel':service.cancel=True
    if change=='stopped':service.live['status']='error'
    if change=='different bytes':
        dest=Path(d.job['output_path']);dest.mkdir(parents=True)
        (dest/'D-1_20261122_100000.xlsx').write_bytes(b'previous estimate: never overwrite')
    assert resume(d,service)
    assert D.load(d.manifest)['phase']=='held'
    assert not any(url.endswith('/complete') for url,_ in service.posts)
    assert D.verify_local(d.manifest,D.load(d.manifest))


def test_local_hash_tampering_is_held(delivery):
    d=delivery;state=D.load(d.manifest);name=state['inventory'][0]['name']
    (d.manifest.parent/'files'/name).write_bytes(b'different book')
    service=Service(d);assert resume(d,service)
    assert D.load(d.manifest)['phase']=='held' and not service.posts


def test_two_collectors_cannot_publish_the_same_intent_concurrently(delivery):
    d=delivery;claim=D.acquire(d.manifest)
    try:
        service=Service(d);assert not resume(d,service);assert not service.posts
        with pytest.raises(FileExistsError):D.acquire(d.manifest)
    finally:D.release(claim)
    assert resume(d,service)


def test_execute_uses_local_template_inputs_and_output_then_never_relaunches(delivery,monkeypatch):
    d=delivery;d.manifest.unlink()  # this test starts a new execution with no saved result
    # Use a separate run ID/destination from the fixture's old copied file.
    job=dict(d.job,run_id='abcdef654321',job_folder=str(d.engine/'staged'),output_path=str(d.engine/'K'/'second'))
    source=Path(job['job_folder']);source.mkdir();(source/'brief.txt').write_text('known source facts')
    tpl=d.engine/'template.xlsx';tpl.write_bytes(template_bytes())
    monkeypatch.setenv('SDI_ESTIMATE_LOCAL_FIRST','1');monkeypatch.setenv('SDI_WB_TEMPLATE',str(tpl))
    calls=[]
    class Proc:
        pid=None;stdout=[]
        def poll(self):return 0
        def wait(self):return 0
    def engine(cmd,**kw):
        calls.append((cmd,kw))
        assert Path(kw['env']['SDI_WB_TEMPLATE']).is_file()
        assert kw['env']['SDI_WB_TEMPLATE']!=str(tpl)
        assert str(d.engine/'output'/'runner_delivery') in kw['env']['SDI_WB_OUTPUT_DIR']
        assert cmd[cmd.index('--job')+1]!=str(source)
        assert cmd[cmd.index('--product')+1]=='D-1'
        return Proc()
    monkeypatch.setattr(R.subprocess,'Popen',engine)
    def collect(root,dest,*a,**kw):
        dest.mkdir(parents=True,exist_ok=True);book=dest/'D-1_20261122_100001.xlsx';book.write_bytes(b'new completed book')
        return [dict(name=book.name,path=str(book))]
    monkeypatch.setattr(R,'collect',collect)
    # All progress is accepted, but the file share is down after calculation.
    class API:
        def get(self,*a,**kw):return Reply(dict(job,status='running',runner='runner-1'))
        def post(self,*a,**kw):return Reply({'cancel':False})
    real=D.publish
    monkeypatch.setattr(D,'publish',lambda *a,**kw:(_ for _ in ()).throw(OSError(errno.ENETUNREACH,'VPN down')))
    R._execute(API(),'http://service/api/estimate',{},job,d.engine,Path('python'),'runner-1')
    manifest=D.local_root(d.engine,'runner-1')/job['run_id']/'delivery.json'
    assert len(calls)==1 and D.load(manifest)['phase']=='pending'
    assert D.verify_local(manifest,D.load(manifest))
    # A repeated dispatch with this ID is allowed to collect/file only, never execute.
    R._execute(API(),'http://service/api/estimate',{},job,d.engine,Path('python'),'runner-1')
    assert len(calls)==1
    monkeypatch.setattr(D,'publish',real)


def test_local_staging_cannot_copy_itself_recursively(tmp_path):
    source=tmp_path/'source';source.mkdir();(source/'brief').write_text('x')
    with pytest.raises(ValueError,match='inside its source'):
        D.pin_inputs(source,None,source/'output'/'copy')


def test_secondary_archive_destination_is_pinned_once(delivery):
    d=delivery;state=D.load(d.manifest);state['job']['archive_root']=str(d.engine/'briefs');D.save(d.manifest,state)
    service=Service(d);assert resume(d,service)
    final=D.load(d.manifest)
    assert Path(final['archive_destination']).is_dir()
    assert any(re.fullmatch(r'\[archive\] \d+ of \d+ file\(s\) also filed to .+',line) for line in final['log'])
    assert len(list((d.engine/'briefs').rglob('*.xlsx')))==1
    assert resume(d,service) and len(list((d.engine/'briefs').rglob('*.xlsx')))==1


@pytest.mark.parametrize('name',['../bad','C:bad','bad/name','bad\\name',''])
def test_unsafe_flat_deliverable_names_are_refused(name):
    with pytest.raises(ValueError):D.safe_name(name)
