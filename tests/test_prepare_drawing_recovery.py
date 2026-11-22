import copy
import importlib.util
import json
from pathlib import Path
import pytest
import zipfile

spec = importlib.util.spec_from_file_location('drawing_recovery', Path(__file__).parents[1]/'tools'/'prepare_drawing_recovery.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def example():
    scope = {'client': 'Example', 'drawing_number': '50000-GA', 'units': 2,
             'method': 'both', 'brief_sha256': 'abc123', 'brief_status': 'filed', 'reference_documents': []}
    run = {'run_id': 'new', 'client': 'Example', 'drawing_number': '50000-GA', 'units': 2,
           'submitted_scope': scope, 'status': 'done', 'price_validated': True,
           'engine_price_gbp': 12.5, 'finished_at': 100, 'deliverables': [{'name': 'estimate.xlsx'}]}
    entry = {'drawing': '50000-GA', 'quantity': 2, 'inputs': {'client': 'Example'}}
    return entry, copy.deepcopy(run), run


@pytest.mark.parametrize('field,value', [('status', 'running'), ('status', 'error'),
    ('price_validated', False), ('engine_price_gbp', None), ('engine_price_gbp', 0),
    ('engine_price_gbp', float('nan')), ('engine_price_gbp', float('inf')),
    ('engine_price_gbp', True), ('units', 3), ('drawing_number', '50000-GA2'),
    ('client', 'Other'), ('stopped_by_hand', True), ('cancel_requested', True),
    ('instruction_refused', True), ('finished_at', None)])
def test_refuses_invalid_or_unfinished_results(field, value):
    entry, old, run = example()
    run[field] = value
    assert not module.candidate_runs(entry, [run], old)


@pytest.mark.parametrize('key,value', [('brief_sha256', 'changed'), ('brief_sha256', ''),
    ('reference_documents', ['changed.pdf']), ('brief_status', 'not_filed'), ('method', 'llm')])
def test_scope_evidence_must_match(key, value):
    entry, old, run = example()
    run['submitted_scope'][key] = value
    assert not module.candidate_runs(entry, [run], old)


def test_missing_scope_is_not_a_match():
    assert not module.scope_matches({}, {})


def test_persisted_history_computed_flag_is_not_required_but_workbook_is():
    entry, old, run = example()
    del run['price_validated']
    assert module.candidate_runs(entry, [run], old)
    run['deliverables'] = []
    assert not module.candidate_runs(entry, [run], old)


def test_done_with_error_cannot_be_recovered():
    entry, old, run = example()
    run['error'] = 'workbook validation failed'
    assert not module.candidate_runs(entry, [run], old)


def test_latest_finished_candidate_not_old_ledger_run():
    entry, old, run = example()
    second = copy.deepcopy(run)
    second.update(run_id='newer', finished_at=200)
    assert [r['run_id'] for r in module.candidate_runs(entry, [run, second], old)] == ['newer', 'new']


def test_does_not_adopt_generic_latest_file_or_undeclared_workbook(tmp_path):
    entry, old, run = example()
    (tmp_path/'50000-GA_20261122_100000_record.json').write_text('{}')
    (tmp_path/'50000-GA_20261122_100000.xlsx').write_bytes(b'not a validated workbook')
    run['deliverables'] = [{'name': '50000-GA_20261122_100000_record.json'}]
    assert module.result_files(run, [tmp_path]) == []


def saved_pair(tmp_path, run, price='12.5', quantity='2'):
    record = tmp_path/'50000-GA_20261122_100000_record.json'
    record.write_text(json.dumps({'declared_product': run['drawing_number'],
        'run_provenance': {'service_run_id':run['run_id'], 'submitted_scope':run['submitted_scope']},
        'assumed_job_quantity':2, 'final_estimate':{'totals':{'unit_gbp':12.5,'unit_cell':'Estimate!M225'}}}))
    book = tmp_path/'50000-GA_20261122_100000.xlsx'
    with zipfile.ZipFile(book,'w') as z:
        z.writestr('xl/workbook.xml','<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Estimate" r:id="r1"/></sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels','<Relationships><Relationship Id="r1" Target="worksheets/sheet1.xml"/></Relationships>')
        z.writestr('xl/worksheets/sheet1.xml',f'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row><c r="D6"><v>{quantity}</v></c><c r="M225"><f>SUM(M1:M10)</f><v>{price}</v></c></row></sheetData></worksheet>')
    return record, book


def test_saved_workbook_uses_actual_readback_cell_not_fixed_m105(tmp_path):
    _, _, run = example()
    record, book = saved_pair(tmp_path,run)
    result = module.verify_saved_pair(run, record, book)
    assert result['workbook_price_independently_checked']
    assert result['price_cell']=='Estimate!M225'
    assert not result['calculation_reexecuted']


@pytest.mark.parametrize('price,quantity',[('0','2'),('13','2'),('12.5','3'),('NaN','2')])
def test_cached_price_or_quantity_mismatch_refused(tmp_path,price,quantity):
    _, _, run = example()
    record,book = saved_pair(tmp_path,run,price,quantity)
    with pytest.raises(ValueError):
        module.verify_saved_pair(run,record,book)


def test_another_runs_record_cannot_be_collected(tmp_path):
    _, _, run = example()
    record,book = saved_pair(tmp_path,run)
    run['run_id']='another'
    with pytest.raises(ValueError):
        module.verify_saved_pair(run,record,book)
