import copy
import pytest
from assembly_identity_inference import apply
from owned_component_manufacturing import prepare


def sheet():
    return {'source_pdf_name':'nc1-c45678.pdf','page_number':1,
        'pypdf_text':'383.3 CUT\n125.5 CUT\nBRACKET\nPART NO.:20129991\nMATERIAL:2.5mm CR4 SHEET STEEL 2500X1250'}


def test_stock_envelope_is_replaced_in_all_active_geometry_and_vectors_stay_audited():
    part={'part_number':'C.45678','quantity':2,'blank_length_mm':2500,'blank_width_mm':1250,
        'blank_length_mm_source':'pdf_overall_dims','blank_width_mm_source':'pdf_overall_dims',
        'geometry_rollup':{'estimated_cut_length_mm':750000,'_raw':{'estimated_cut_length_mm':750000}},
        'normalized_geometry':{'cut_length_mm':750000,'bounding_box_flat_mm':{'length':2500,'width':1250}}}
    s={'pages':[sheet()],'manufacturing_writeup':{'parts':[part]}}
    prepare(s)
    assert (part['blank_length_mm'],part['blank_width_mm'])==(383.3,125.5)
    assert part['normalized_geometry']['bounding_box_flat_mm']['length']==383.3
    assert 0 < part['geometry_rollup']['estimated_cut_length_mm'] < 10000
    assert part['geometry_rollup']['_raw']['estimated_cut_length_mm'] < 10000
    assert part['drawing_cut_displaced_mm']==750000
    assert part['drawing_vector_original']['estimated_cut_length_mm']==750000
    assert part['quantity']==2
    first=copy.deepcopy(part)
    prepare(s)
    assert part==first


@pytest.mark.parametrize('source',['solidworks_api','dxf_flat_pattern'])
def test_complex_measured_contour_is_not_capped_by_a_bbox_heuristic(source):
    part={'part_number':'C.45678','quantity':2,'blank_length_mm':500,'blank_width_mm':400,
          'normalized_geometry':{'geometry_source':source,'cut_length_mm':750000},
          'rejected_dxf_files':[{'file':'alternate-drawing-export.dxf','reason':'not a flat'}]}
    s={'pages':[sheet()],'manufacturing_writeup':{'parts':[part]}}
    prepare(s)
    assert (part['blank_length_mm'],part['blank_width_mm'])==(500,400)
    assert part['normalized_geometry']['cut_length_mm']==750000


def test_stated_hole_work_is_retained_in_provisional_cut_budget():
    page=sheet();page['pypdf_text']+='\n8mm HOLES (X4)'
    part={'part_number':'C.45678','quantity':4,
          'geometry_rollup':{'estimated_cut_length_mm':750000,'estimated_hole_count':10000},
          'normalized_geometry':{'cut_length_mm':750000}}
    prepare({'pages':[page],'manufacturing_writeup':{'parts':[part]}})
    assert part['owned_stated_holes']['count']==4
    assert part['normalized_geometry']['hole_count']==4
    assert part['_cut_allowance']['cut_mm']>2*(383.3+125.5)
    assert part['_cut_allowance']['internal_detail_factor']==1.25


def assembly():
    return {'declared_product':'B.45670','pages':[{'source_pdf_name':'nc1-a45671.pdf','page_number':1}],
        'parts':[{'part_number':'10129991','description':'CABINET ASSEMBLY','quantity':1}],
        'document_analysis':{'bom_rows':[
            {'part_number':'10129991','description':'CABINET ASSEMBLY','bom_parent':'B.45670','quantity':1},
            {'part_number':'PANEL','bom_parent':'A.45671','quantity':4}]}}


def test_missing_identity_link_is_a_visible_provisional_decision_not_an_exclusion():
    s=assembly()
    assert len(apply(s))==1
    assert s['document_analysis']['bom_rows'][0]['sheet_identity_aliases']=={'10129991':'A.45671'}
    assert s['assembly_identity_inferences'][0]['provisional'] is True
    assert apply(s)==[]
    assert s['parts'][0]['quantity']==1


@pytest.mark.parametrize('flag',['is_bought_in','supplied_by_third_party','reference_only','is_alternative'])
def test_explicit_purchase_scope_and_variant_decisions_are_not_overridden(flag):
    s=assembly();s['parts'][0][flag]=True
    assert apply(s)==[]


def test_ambiguous_candidates_are_not_falsely_claimed_to_be_exact_aliases():
    s=assembly();s['document_analysis']['bom_rows'].append(
        {'part_number':'10129992','description':'OTHER ASSEMBLY','bom_parent':'B.45670','quantity':1})
    assert apply(s)==[]
    assert not s.get('assembly_identity_inferences')


def test_faced_board_is_not_generically_demoted_to_raw_mdf():
    from estimator import _faced_board_promotion
    assert _faced_board_promotion({'textual_operations':['laminating']},'MDF')[0]=='MFMDF'
    assert _faced_board_promotion({'owned_board_construction':{'mode':'raw_board_with_wet_finish'},
                                  'textual_operations':['laminating']},'MDF')==(None,'')


def test_synthetic_repaired_component_reaches_positive_material_and_manufacturing_money():
    from estimator import estimate_material,estimate_process_times,estimate_labour_costs
    p={'part_number':'C.45678','quantity':2,'blank_length_mm':2500,'blank_width_mm':1250,
       'geometry_rollup':{'estimated_cut_length_mm':750000},
       'normalized_geometry':{'cut_length_mm':750000}}
    prepare({'pages':[sheet()],'manufacturing_writeup':{'parts':[p]}})
    material=estimate_material(p)
    process=estimate_process_times(p,quantity=2)
    labour=estimate_labour_costs(process,job_quantity=2,material=p['normalized_material'])
    assert material['extended_material_cost_gbp']>0
    assert labour['costs_gbp']['laser_cutting']>0 and labour['costs_gbp']['deburring']>0
    assert process['run_times_min_per_unit']['laser_cutting']<15


def test_dimension_capture_is_source_bound_and_not_repeated(monkeypatch):
    import drawing_dimension_evidence as dims
    calls=[]
    monkeypatch.setattr(dims,'read_axes',lambda path,page: calls.append((path,page)) or
        {'axes_mm':[500,300],'basis':'synthetic printed dimensions'})
    s={'pages':[dict(sheet(),source_pdf_path='fixture/nc1-c45678.pdf',source_page_number=1)]}
    assert dims.capture(s)==[1] and dims.capture(s)==[]
    assert len(calls)==1
    s['pages'].append(dict(sheet(),source_pdf_path='fixture/not-this-drawing.pdf',page_number=2))
    assert dims.capture(s)==[] and len(calls)==1


def test_pdf_dimensions_keep_axes_separate_and_ignore_stock_in_border(tmp_path):
    import fitz
    from drawing_dimension_evidence import read_axes
    doc=fitz.open();page=doc.new_page(width=1000,height=700)
    page.insert_text((100,100),'1866')
    page.insert_text((100,150),'1518')  # another horizontal dimension, not the height
    page.insert_text((50,500),'770',rotate=90)
    page.insert_text((900,200),'2500')  # title/material border
    page.insert_text((100,650),'2026')  # date in bottom border
    path=tmp_path/'component.pdf';doc.save(path);doc.close()
    got=read_axes(path)
    assert got['axes_mm']==[1866,770]
    assert len(got['pdf_sha256'])==64 and got['source_page_index']==0


def test_synthetic_raw_board_spray_has_positive_material_cnc_and_finish_money(monkeypatch):
    from estimator import estimate_material,estimate_process_times,estimate_labour_costs
    page=sheet();page['pypdf_text']='500 CUT\n300 CUT\n18MM MR MDF 3050X1220\nSPRAY BROWN'
    p={'part_number':'C.45678','quantity':1}
    summary={'pages':[page],'manufacturing_writeup':{'parts':[p]}}
    prepare(summary)
    assert p['normalized_material']=='MDF' and p['normalized_thickness_mm']==18
    material=estimate_material(p)
    process=estimate_process_times(p,quantity=1)
    labour=estimate_labour_costs(process,job_quantity=1,material=p['normalized_material'])
    assert material['extended_material_cost_gbp']>0
    assert labour['costs_gbp']['cnc_routing']>0
    assert labour['costs_gbp']['wet_spray']>0
    consumables=[part for part in summary['manufacturing_writeup']['parts'] if part.get('named_finish_consumable')]
    assert len(consumables)==2
    import estimator
    monkeypatch.setattr(estimator,'_resolve_part_system_cost',
        lambda p:pytest.fail('A disclosed house budget must not request a catalogue price'))
    for part in consumables:
        priced=estimator.estimate_part(copy.deepcopy(part))
        assert priced['material_estimate']['extended_material_cost_gbp']>0


def test_existing_reviewed_coat_schedule_is_not_replaced_by_default_count():
    page=sheet();page['pypdf_text']='500 CUT\n300 CUT\n18MM MR MDF 3050X1220\nSPRAY BROWN'
    reviewed={'operation':'wet_spray','stages':[{'passes':4,'description':'Reviewed specialist system'}],
              'basis':'Estimator reviewed','passes':4}
    p={'part_number':'C.45678','quantity':1,'finish_schedule':copy.deepcopy(reviewed)}
    prepare({'pages':[page],'manufacturing_writeup':{'parts':[p]}})
    assert p['finish_schedule']==reviewed


def test_coating_consumables_do_not_turn_a_made_panel_into_an_assembly():
    from route_compiler import apply_canonical_evidence_to_parts
    from named_finish_schedule import mint_consumables
    part={'part_number':'C.45678','quantity':1,'normalized_material':'MDF',
        'normalized_thickness_mm':18,'blank_length_mm':500,'blank_width_mm':300,
        'owned_blank_basis':{'provisional':True},
        'owned_board_construction':{'mode':'raw_board_with_wet_finish'},
        'inferred_operations':['cnc_routing','wet_spray'],
        'finish_schedule':{'operation':'wet_spray','stages':[{'passes':2,'description':'Provisional colour coat'}]}}
    parts=[part]
    mint_consumables(parts)
    apply_canonical_evidence_to_parts(parts,{},[],['C.45678'])
    assert part['canonical_kind']=='leaf'
    assert 'cnc_routing' in part['inferred_operations']


def test_final_synthetic_workbook_row_keeps_correct_quantity_and_positive_sensible_labour(tmp_path,monkeypatch):
    import openpyxl
    import estimator as E
    import wb_populate as W
    from test_a_material_keeps_its_own_block import _template
    root={'part_number':'A.45670','quantity':1,'is_sub_assembly':True,
          'assembly_children':['C.45678']}
    part={'part_number':'C.45678','description':'FABRICATED BRACKET','quantity':150,'quantity_source':'bom_tree',
        'blank_length_mm':2500,'blank_width_mm':1250,
        'bom_parent':'A.45670','bom_parents':[{'parent':'A.45670','qty':150}],
        'geometry_rollup':{'estimated_cut_length_mm':750000},
        'normalized_geometry':{'cut_length_mm':750000}}
    summary={'declared_product':'A.45670','drawing_number':'A.45670','pages':[sheet(),
        {'page_number':2,'source_pdf_name':'nc1-a45670.pdf','page_analysis':{
            'title_block':{'drawing_numbers':['A.45670']}}}],
        'manufacturing_writeup':{'parts':[root,part]},'job_folder':str(tmp_path),
        'document_analysis':{'bom_rows':[{'part_number':'C.45678','bom_parent':'A.45670','quantity':150,
            'bom_parent_known':True,'bom_sheet':'nc1-a45670.pdf#0','source_pdf':'A.45670','bom_source':'BOTH'}]}}
    prepare(summary)
    monkeypatch.setattr(E,'_resolve_part_system_cost',lambda p:{})
    template=_template(tmp_path/'template.xlsx')
    fixture_book=openpyxl.load_workbook(template)
    fixture_sheet=fixture_book['Estimate']
    fixture_sheet['D6']=1
    for r in range(96,168):
        fixture_sheet.cell(r,11,40.0)  # synthetic test department rate, not a live quote
        fixture_sheet.cell(r,12,10.0)
        fixture_sheet.cell(r,13,f'=H{r}/I{r}*K{r}+L{r}/60*K{r}/MAX(D6,1)')
    fixture_book.save(template)
    fixture_book.close()
    monkeypatch.setenv('SDI_WB_TEMPLATE',str(template))
    monkeypatch.setitem(W.CELL_MAP,'output_dir',str(tmp_path/'books'))
    summary['estimate_summary']=E.estimate_document([root,part],summary=summary)
    summary['part_estimates']=summary['estimate_summary']['part_estimates']
    path=W.populate_workbook(summary,'SYNTHETIC-CONTOUR-CHECK')
    assert path
    book=openpyxl.load_workbook(path,data_only=False)
    ws=book['Estimate']
    lab=W.CELL_MAP['labour']
    rows=[r for r in range(lab['first_row'],lab['last_row']+1)
          if ws.cell(r,3).value=='Laser (Metal)']
    assert rows
    for row in rows:
        assert ws.cell(row,8).value==150
        throughput=ws.cell(row,9).value
        if isinstance(throughput,str):
            # Inspect the actual emitted formula's live calculator inputs.
            # No Excel/COM session is opened and no native recalc is claimed.
            import re
            match=re.search(r'MAX\(V(\d+),4\)',throughput)
            assert match,throughput
            calculator_row=int(match[1])
            seconds=ws.cell(calculator_row,22).value
            if isinstance(seconds,(int,float)) and seconds>0:
                throughput=3600/max(seconds,4)
            else:
                # This deliberately minimal fixture has no calculator body;
                # its actual IFERROR branch must retain the engine-derived,
                # corrected positive rate, not the old page-vector rate.
                fallback=re.search(r',([\d.]+)\)$',throughput)
                assert fallback,throughput
                throughput=float(fallback[1])
        assert isinstance(throughput,(int,float)) and throughput>10
        assert ws.cell(row,11).value>0
        assert ws.cell(row,13).value is not None
        assert 0 < 150/throughput*ws.cell(row,11).value < 1000
    assert part['blank_length_mm']*part['blank_width_mm']<100000
    book.close()


def _board_panel(text):
    page=sheet();page['pypdf_text']=text
    p={'part_number':'C.45678','quantity':1}
    prepare({'pages':[page],'manufacturing_writeup':{'parts':[p]}})
    return p


def test_a_section_printed_thinner_than_the_material_note_is_kept_as_a_review_item():
    # The material note says 18 mm; a section on the same sheet prints a bare 6. The note
    # stays the provisional choice, and the disagreement is put in front of the estimator.
    p=_board_panel('6\n500 CUT\n300 CUT\nFRONT PANEL\n18MM MR MDF 3050X1220\nSPRAY BROWN\n6\n')
    assert p['normalized_thickness_mm']==18
    conflict=p['owned_thickness_conflict']
    assert conflict['stated_mm']==18 and conflict['printed_mm']==[6]
    assert any('18 mm' in f and '6 mm' in f for f in p['review_flags'])
    first=copy.deepcopy(p['review_flags'])
    _board_panel('6\n500 CUT\n300 CUT\nFRONT PANEL\n18MM MR MDF 3050X1220\nSPRAY BROWN\n6\n')
    assert p['review_flags']==first


def test_a_board_whose_section_agrees_with_its_note_raises_nothing():
    p=_board_panel('18\n500 CUT\n300 CUT\nFRONT PANEL\n18MM MR MDF 3050X1220\nSPRAY BROWN\n')
    assert 'owned_thickness_conflict' not in p


def test_a_groove_depth_or_a_sheet_whose_sections_print_the_note_is_not_a_conflict():
    groove=_board_panel('4\n11\n500 CUT\n300 CUT\nTOP PANEL\n18MM MR MDF 3050X1220\nSPRAY BROWN\n4\n')
    assert 'owned_thickness_conflict' not in groove
    agreed=_board_panel('18\n6\n500 CUT\n300 CUT\nFRONT PANEL\n18MM MR MDF 3050X1220\nSPRAY BROWN\n18\n')
    assert 'owned_thickness_conflict' not in agreed


def test_dashed_lines_ruled_out_as_folds_are_not_charged_as_folds_at_costing():
    # The owned pass says dashed lines on this raw-board panel are not press-brake folds;
    # the costing's fold resolver must not read the same dashed lines back as six folds.
    import estimator
    page=sheet();page['pypdf_text']='500 CUT\n300 CUT\nFRONT PANEL\n18MM MR MDF 3050X1220\nSPRAY BROWN'
    p={'part_number':'C.45678','quantity':1,
       'manufacturing_features':{'bend_count':6,'bend_count_source':'inferred_dashed_lines','fold_required':True},
       'geometry_rollup':{'dashed_long_axis_lines':6,'estimated_bend_line_count':6},
       'normalized_geometry':{'bend_count':6}}
    prepare({'pages':[page],'manufacturing_writeup':{'parts':[p]}})
    assert p['owned_board_displaced_bends']==6
    times=estimator.estimate_process_times(copy.deepcopy(p),1)
    assert 'folding' not in (times.get('setup_times_min') or {})
    assert 'folding' not in estimator.estimate_process_times(p,1).get('run_times_min',{})
    assert p['geometry_rollup']['dashed_long_axis_lines']==0
    assert p['owned_board_dashed_lines_displaced']=={'dashed_long_axis_lines':6,'estimated_bend_line_count':6,
                                                     'normalized_geometry.bend_count':6}
