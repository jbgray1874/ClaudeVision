import copy
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from supplier_sheet_identity import reconcile_sheet_identities
from route_compiler import build_part_graph
from product_identity import names_the_product


def test_stock_named_parent_is_the_declared_drawing_not_an_unrelated_product():
    rows=[dict(part_number='B.12346',quantity=1,bom_parent='B.12345',bom_sheet='nc1-b12345.pdf#0'),
          dict(part_number='D.12347',quantity=2,bom_parent='B.12346',bom_sheet='nc1-b12346.pdf#0')]
    sheets=[('nc1-b12345.pdf#0','FINISHED PART NO.10100585 DRG No. B.12345'),
            ('nc1-b12346.pdf#0','FINISHED PART NO.10100573 DRG No. B.12346')]
    reconcile_sheet_identities(rows,sheets)
    ext={'assemblies':[{'part_number':'10100585','children':[{'part_number':'10100573','qty':1}]}]}
    parts=[dict(part_number=p,quantity=1) for p in ('B.12345','B.12346','D.12347')]
    g=build_part_graph(parts,ext,bom_rows=rows,declared_product='B.12345')
    q={n.part_number:n.qty_per_unit for n in g['nodes']}
    assert q['D.12347']==2
    assert not any(i['code']=='outside_the_product' and 'B.12346' in i.get('identities',[]) for i in g['issues'])
    assert '10100585' not in q


def test_raster_root_and_its_thirty_boxes_are_not_confused_with_the_box_sheet():
    rows=[dict(part_number='A-33488',finished_part_no='00026207',drawing_reference='A-33488',
               quantity=30,bom_parent='A-33486',bom_sheet='nc1-a33446.pdf#0'),
          dict(part_number='D-33498',quantity=4,bom_parent='A-33493',bom_sheet='nc1-a33493.pdf#0'),
          dict(part_number='A-33493',quantity=1,bom_parent='A-33488',bom_sheet='nc1-a33486.pdf#0')]
    sheets=[('nc1-a33446.pdf#0',''),
            ('nc1-a33486.pdf#0','FINISHED PART NO.00026207 DRG No. A-33486'),
            ('nc1-a33493.pdf#0','FINISHED PART NO.10100275 DRG No. A-33493')]
    reconcile_sheet_identities(rows,sheets)
    assert rows[0]['bom_parent']=='A-33446' and rows[0]['part_number']=='A-33486'
    parts=[dict(part_number=p,quantity=1) for p in ('A-33486','A-33493','D-33498')]
    g=build_part_graph(parts,{},bom_rows=rows,declared_product='A.33446')
    q={n.part_number:n.qty_per_unit for n in g['nodes']}
    assert q['D-33498']==120
    assert not any(i['code']=='declared_product_not_resolved' for i in g['issues'])


def test_conflicting_sheet_and_filename_are_not_silently_substituted():
    rows=[dict(part_number='D-11112',quantity=1,bom_parent='A-11111',bom_sheet='nc1-a11111.pdf#0')]
    before=copy.deepcopy(rows)
    found=reconcile_sheet_identities(rows,[('nc1-a11111.pdf#0','FINISHED PART NO.10123456 DRG No. A-22222')])
    assert found[0]['code']=='sheet_filename_identity_conflict'
    assert rows==before
    from engine_discoveries import classify
    assert classify(found[0]['code'])=='drawing'


def test_two_drawings_claiming_a_stock_code_do_not_create_an_alias():
    rows=[dict(part_number='10123456',quantity=1,bom_parent='A-11111',bom_sheet='main.pdf#0')]
    reconcile_sheet_identities(rows,[('nc1-b12345.pdf#0','FINISHED PART NO.10123456 DRG No. B-12345'),
                                      ('nc1-b12346.pdf#0','FINISHED PART NO.10123456 DRG No. B-12346')])
    assert '10123456' not in rows[0].get('sheet_identity_aliases',{})


def test_product_separator_spelling_does_not_change_product_scope():
    assert names_the_product('A.33446','A-33446')
    assert not names_the_product('A.33446','A-33486')


def test_a_filename_hyphen_and_a_printed_dot_are_not_conflicting_stock_claims():
    from route_compiler import _stock_code_aliases
    rows=[{'sheet_identity_aliases':{'10100585':'B-33792'}},
          {'part_number':'B.33792','drawing_reference':'B.33792','finished_part_no':'10100585'}]
    assert _stock_code_aliases(rows,['10100585','B.33792'])['10100585']=='B.33792'
