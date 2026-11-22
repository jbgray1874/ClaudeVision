import json
import tti_pricer as tp
from test_tti_pricer_prices_each_row_and_fills_ai_cost import _sheet, _areas, _args, _quiet, _Portal


def decision_file(tmp_path):
    p=tmp_path/'decisions.json'
    p.write_text(json.dumps({'client':'TTI','drawings':{'TTI-10234':{
        'accepted_by':'Estimator', 'changes':[{'part':'TTI-10234-11G','field':'thickness_mm',
            'value':2,'drawing_value':1,'accepted':True,'origin':'manual',
            'reason':'Customer instruction to cost at 2 mm instead of the drawn 1 mm'}]}}}))
    return p


def test_changes_reach_service_and_ledger_signature(tmp_path,monkeypatch):
    sheet=_sheet(tmp_path);_areas(tmp_path,monkeypatch);_quiet(monkeypatch)
    portal=_Portal()
    result=tp.run_batch(_args(sheet,rows='3',replace_costs=True,job_changes=str(decision_file(tmp_path))),
                        portal=portal,status_path=tmp_path/'status.json',sleep=lambda s:None)
    assert len(portal.started)==1
    assert portal.started[0]['customer_changes']['changes'][0]['value']==2
    assert result['rows'][0]['inputs']['customer_changes']
    assert result['rows'][0]['result_origin']=='new submission'


def test_old_result_writeback_is_explicitly_not_a_new_estimate(tmp_path,monkeypatch):
    sheet=_sheet(tmp_path);_areas(tmp_path,monkeypatch);_quiet(monkeypatch)
    status=tmp_path/'status.json'
    tp.run_batch(_args(sheet,rows='3',replace_costs=True),portal=_Portal(),status_path=status,sleep=lambda s:None)
    portal=_Portal()
    report=tp.run_batch(_args(sheet,rows='3',replace_costs=True),portal=portal,status_path=status,sleep=lambda s:None)
    assert not portal.started
    assert report['rows'][0]['result_origin']=='existing run collected; not proof of a new estimate'


def test_changed_instruction_never_duplicates_running_prior_job(tmp_path,monkeypatch):
    sheet=_sheet(tmp_path);_areas(tmp_path,monkeypatch);_quiet(monkeypatch)
    status=tmp_path/'status.json'
    tp.run_batch(_args(sheet,rows='3',replace_costs=True),portal=_Portal(),status_path=status,sleep=lambda s:None)
    portal=_Portal(status='running')
    report=tp.run_batch(_args(sheet,rows='3',replace_costs=True,job_changes=str(decision_file(tmp_path))),
                        portal=portal,status_path=status,sleep=lambda s:None)
    assert not portal.started
    assert report['rows'][0]['state']=='held: changed instructions while prior outcome unresolved'


def test_unknown_prior_status_is_not_permission_to_submit_changes(tmp_path,monkeypatch):
    sheet=_sheet(tmp_path);_areas(tmp_path,monkeypatch);_quiet(monkeypatch)
    status=tmp_path/'status.json'
    tp.run_batch(_args(sheet,rows='3',replace_costs=True),portal=_Portal(),status_path=status,sleep=lambda s:None)
    portal=_Portal()
    monkeypatch.setattr(portal,'status',lambda rid: {})
    report=tp.run_batch(_args(sheet,rows='3',replace_costs=True,job_changes=str(decision_file(tmp_path))),
                        portal=portal,status_path=status,sleep=lambda s:None)
    assert not portal.started
    assert report['rows'][0]['state'].startswith('held: changed instructions')
