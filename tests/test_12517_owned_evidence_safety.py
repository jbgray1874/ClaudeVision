"""Actual 12517 extraction regressions. Offline: never invoke CAD, Excel or an LLM."""
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
FIXTURE_PATH = Path(os.environ.get('SDI_12517_AUDIT_FIXTURE') or ROOT/'tests/fixtures/12517_evidence.json')
FIXTURE = json.loads(FIXTURE_PATH.read_text(encoding='utf-8')) if FIXTURE_PATH.is_file() else None

def actual_fixture():
    if FIXTURE is None:
        pytest.skip('Private 12517 evidence not installed; set SDI_12517_AUDIT_FIXTURE. Not proof of a pack pass.')
    return FIXTURE

def pack():
    f = copy.deepcopy(actual_fixture())
    f['manufacturing_writeup'] = {'parts':f.pop('parts')}
    return f

def part(s, number):
    return next(p for p in s['manufacturing_writeup']['parts'] if p['part_number']==number)

def test_the_pack_bom_screw_length_is_not_a_document_gauge():
    from part_index import document_gauge_to_hand_down
    assert document_gauge_to_hand_down(actual_fixture()) is None

def test_explicit_single_sheet_gauge_still_available():
    from part_index import document_gauge_to_hand_down
    s={'document_analysis':{'title_block':{'thicknesses_mm':['1.5']},'primary_fields':{'thickness_mm':1.5}}}
    assert document_gauge_to_hand_down(s)==1.5

@pytest.mark.parametrize('page_no',[12,30,31,47,48])
def test_flat_candidates_do_not_include_the_year_or_grit(page_no):
    from extractor_patterns import classify_dimensions
    pg=next(p for p in actual_fixture()['pages'] if p['page_number']==page_no)
    dims=classify_dimensions(pg['pdfplumber_text'])
    assert 2026 not in dims['flat_pattern_dimensions_mm']
    assert 400 not in dims['flat_pattern_dimensions_mm']

def test_real_explicit_2026mm_dimension_is_not_a_date():
    from extractor_patterns import classify_dimensions
    d=classify_dimensions('FLAT PATTERN 2026 x 400 mm DATE 2026/11/4')
    assert d['overall_length_mm']==2026 and d['overall_width_mm']==400

def test_own_mag_annotation_beats_tig_default():
    from extractor_patterns import weld_process_stated
    got=weld_process_stated('3 MAG\nWELD SPECIFICATION: ALL WELDS TO BE TIG UNLESS STATED')
    assert got['word']=='MAG' and got['process']=='MIG' and not got['default']

def test_default_tig_does_not_create_a_weld():
    from weld_symbols import apply_pack_weld_default
    p={'part_number':'P','textual_operations':[]}
    assert apply_pack_weld_default([p],[{'pdfplumber_text':'ALL WELDS TO BE TIG UNLESS STATED'}])==[]
    assert 'weld_process_stated' not in p

def test_mag_survives_to_the_workbook_wording():
    from wb_populate import weld_process_note
    text=weld_process_note('Weld (CO2)',['A'],{'A':{'weld_process_stated':{'process':'MIG','word':'MAG','default':False}}})
    assert 'MAG' in text and 'TIG' not in text

def test_actual_shelf_assembly_keeps_its_specific_mag_instruction():
    from part_evidence_safety import prepare
    s=pack(); prepare(s)
    stated=part(s,'12517-15-GA')['weld_process_stated']
    assert stated['word']=='MAG' and not stated['default']

def test_flat_pattern_word_is_not_a_measurement():
    from document_builder import _build_normalized_geometry
    p={'flat_pattern_detected':True,'overall_length_mm':384,'overall_width_mm':100.2,
       'normalized_thickness_mm':3,'manufacturing_features':{'bend_count':1}}
    assert _build_normalized_geometry(p)['blank_basis']=='pdf_flat_pattern_candidates'
    p['dxf_augmented']=True
    assert _build_normalized_geometry(p)['blank_basis']=='measured_flat_pattern'

def test_prepare_keeps_every_quantity_and_identity():
    from part_evidence_safety import prepare
    s=pack()
    before=[(p['part_number'],p.get('quantity'),p.get('quantity_source')) for p in s['manufacturing_writeup']['parts']]
    prepare(s)
    assert [(p['part_number'],p.get('quantity'),p.get('quantity_source')) for p in s['manufacturing_writeup']['parts']]==before
    assert s['provenance']['service_run_id']=='fc173150e3c7'

def test_legacy_document_ten_is_withdrawn_not_relabelled_as_measured():
    from part_evidence_safety import prepare
    s=pack(); prepare(s)
    p=part(s,'12517-04-01M')
    assert p['normalized_thickness_mm'] is None
    assert p['thicknesses_mm']==[]
    assert p['evidence_safety_issues']['unowned_gauge']

def test_actual_measured_gauge_is_untouched():
    from part_evidence_safety import prepare
    s=pack(); p=part(s,'12517-04-01M')
    p.update(normalized_thickness_mm=2,thicknesses_mm=['2'],thickness_source='dxf_flat_pattern')
    prepare(s)
    assert p['normalized_thickness_mm']==2
    assert 'unowned_gauge' not in p.get('evidence_safety_issues',{})

def test_numeric_string_gauges_do_not_crash_the_safety_pass():
    from part_evidence_safety import prepare
    s=pack(); p=part(s,'12517-04-01M'); p['normalized_thickness_mm']='10.0'
    s['document_analysis']['primary_fields']['thickness_mm']='10.0'
    prepare(s)
    assert p['normalized_thickness_mm'] is None

def test_title_block_year_cannot_remain_a_measured_blank():
    from part_evidence_safety import prepare
    s=pack(); prepare(s); p=part(s,'12517-06-07M')
    assert p['normalized_geometry']['bounding_box_flat_mm']['length'] is None
    assert p['overall_length_mm'] is None
    assert p['evidence_safety_issues']['metadata_blank']

def test_real_measured_2026mm_blank_is_untouched():
    from part_evidence_safety import prepare
    s=pack(); p=part(s,'12517-06-07M')
    p['geometry_source']='dxf_flat_pattern'; p['dxf_augmented']=True
    before=copy.deepcopy(p['normalized_geometry'])
    prepare(s)
    assert p['normalized_geometry']['bounding_box_flat_mm']['length']==before['bounding_box_flat_mm']['length']
    assert p['normalized_geometry']['bounding_box_flat_mm']['width']==before['bounding_box_flat_mm']['width']

def test_duplicate_acrylic_sheet_is_not_automatically_renamed():
    from part_evidence_safety import prepare
    s=pack(); prepare(s)
    a=part(s,'12517-05-05A'); b=part(s,'12517-07-05A')
    assert a['evidence_safety_issues']['duplicate_detail_identity']['pages']==[25,38]
    assert b['part_number']=='12517-07-05A' and b['quantity']==5

def test_context_column_is_asked_not_silently_zeroed_or_removed():
    from part_evidence_safety import prepare, unresolved
    s=pack(); prepare(s); p=part(s,'Store Column')
    assert p['quantity']==1
    assert p['evidence_safety_issues']['context_supply_scope']
    assert any(x['part']=='Store Column' and x['issue']=='context_supply_scope' for x in unresolved(s))

def test_unresolved_evidence_blocks_firm_release():
    from part_evidence_safety import prepare
    from invariants import check_part_evidence_safety
    s=pack(); prepare(s)
    findings=check_part_evidence_safety(s)
    assert findings and all(x['severity']=='blocking' for x in findings)

def test_no_questions_on_unrelated_pack():
    from part_evidence_safety import prepare, unresolved
    s={'pages':[],'manufacturing_writeup':{'parts':[{'part_number':'A','quantity':3}]}}
    prepare(s)
    assert unresolved(s)==[]

def test_prepare_is_idempotent():
    from part_evidence_safety import prepare
    s=pack(); prepare(s); before=copy.deepcopy(s); prepare(s)
    assert s==before

@pytest.mark.parametrize('code,expected',[
    ('12517-05-05A',36),('12517-07-05A',60),('12517-12-01M',164),
    ('12517-12-02M',44),('12517-04-05M',12),('12517-06-03M',20)])
def test_actual_native_quantity_tree_survives(code,expected):
    from part_evidence_safety import prepare
    s=pack(); before=copy.deepcopy(s['solidworks_native']['hierarchy']); prepare(s)
    tree=s['solidworks_native']['hierarchy']
    assert tree==before
    def count(parent,multiplier=1):
        if parent==code:
            return multiplier
        return sum(count(child,multiplier*qty) for child,qty in tree.get(parent,[]))
    assert count('12517-GA')==expected

def test_ordinary_multiple_detail_sheets_are_not_an_identity_fault():
    from part_evidence_safety import prepare, unresolved
    s={'pages':[{'page_number':n,'pdfplumber_text':f'view {n}',
        'page_analysis':{'title_block':{'drawing_numbers':['A']}}} for n in (1,2)],
       'manufacturing_writeup':{'parts':[{'part_number':'A','description':'Panel','quantity':1}]}}
    prepare(s)
    assert unresolved(s)==[]

def test_cp1252_console_does_not_fail_on_chinese_material():
    spec=importlib.util.spec_from_file_location('sw_12517_encoding_test',ROOT/'tools/solidworks/sw_native_analyse.py')
    m=importlib.util.module_from_spec(spec); sys.modules[spec.name]=m; spec.loader.exec_module(m)
    stream=io.TextIOWrapper(io.BytesIO(),encoding='cp1252',errors='strict')
    m.configure_console_stream(stream)
    print('material=普通碳钢',file=stream,flush=True)
    assert b'material=' in stream.buffer.getvalue()

def test_console_output_never_adds_a_fake_failed_model_record(monkeypatch,tmp_path):
    spec=importlib.util.spec_from_file_location('sw_12517_full_console_test',ROOT/'tools/solidworks/sw_native_analyse.py')
    m=importlib.util.module_from_spec(spec); sys.modules[spec.name]=m; spec.loader.exec_module(m)
    model=tmp_path/'part.SLDPRT'; model.write_bytes(b'offline test model, never opened')
    output=tmp_path/'extract.json'
    class Session:
        sw=None
        def close_all(self): pass
        def shutdown(self): pass
    calls=[]
    def fake_read(session,path):
        calls.append(path)
        return {'title':'普通碳钢','path':str(path),'doctype':1,
                'route_signals':{'material':'普通碳钢','feature_types':[]}}
    buffer=io.BytesIO(); stream=io.TextIOWrapper(buffer,encoding='cp1252',errors='strict')
    with monkeypatch.context() as patch:
        patch.setattr(m,'SolidWorksSession',lambda **kw:Session())
        patch.setattr(m,'analyse_file',fake_read)
        patch.setattr(m.sys,'argv',['analyser',str(model),'--out',str(output)])
        patch.setattr(m.sys,'stdout',stream)
        m.main()
    saved=json.loads(output.read_text(encoding='utf-8'))
    assert len(calls)==1 and len(saved['records'])==1
    assert saved['_manifest']['files_failed']==0
    assert saved['records'][0]['route_signals']['material']=='普通碳钢'

def test_live_pre_costing_path_calls_safety_pass():
    import ast
    tree=ast.parse((ROOT/'src/file_scan.py').read_text(encoding='utf-8'))
    func=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='pre_costing_passes')
    assert any(isinstance(n,ast.ImportFrom) and n.module=='part_evidence_safety' for n in ast.walk(func))
