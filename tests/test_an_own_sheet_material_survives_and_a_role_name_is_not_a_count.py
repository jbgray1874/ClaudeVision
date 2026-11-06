"""A drawing's own material survives, and a role name is not a count (D-598m).

9287-10-GA, a clear acrylic cube on a solid-surface base, 24 Oct 2026. The base's own sheet
prints "HANEX GAD-001" and the CAD model applied its library steel; the box's SIDE and TOP
flats name what each piece is, not how many one box takes. Owned material, role quantities,
their calculated rows and assembly CNC ownership, each with deliberately broken cases.
"""
import ast
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from owned_specification import (own_material, retain_own_material, apply_role_counts,
                                audit_owned_specifications, review_cautions)
from source_precedence import apply_field
from route_compiler import compile_job_route
from invariants import check_owned_specifications_survive


def page(owner='DRAW-1', material='RESIN-X9'):
    return {'page_number': 2, 'page_analysis': {'title_block': {
        'drawing_numbers': [owner], 'material_stated_unresolved': material}}}


def roles():
    return {'manufacturing_writeup': {'parts': [
        {'part_number': 'UNIT', 'dxf_pieces': [
            {'piece': 'SIDE', 'costed_as': 'UNIT-SIDE-01'},
            {'piece': 'TOP', 'costed_as': 'UNIT-TOP-01'}],
         'manufacturing_questions': [{'subject': 'dxf_piece_count'}, {'subject': 'other'}]},
        {'part_number': 'UNIT-SIDE-01', 'dxf_minted_piece_of': 'UNIT',
         'dxf_piece_role': 'SIDE', 'quantity': 1},
        {'part_number': 'UNIT-TOP-01', 'dxf_minted_piece_of': 'UNIT',
         'dxf_piece_role': 'TOP', 'quantity': 1}]}}


def rulings(s):
    s['estimator_decisions'] = {'dxf_role_quantities': [
        {'parent': 'UNIT', 'role': role, 'quantity': n, 'basis': 'per_parent',
         'evidence': 'drawing page 3, assembly view; checked by estimator',
         'decided_by': 'Test estimator'} for role, n in [('SIDE', 4), ('TOP', 1)]]}
    return s


class OwnedMaterialTests(unittest.TestCase):
    def test_existing_library_default_is_replaced(self):
        p = {'part_number': 'DRAW-1', 'normalized_material': 'MILD_STEEL',
             'material_source': 'solidworks_applied_material'}
        self.assertTrue(retain_own_material(p, [page()], apply_field))
        self.assertEqual(p['normalized_material'], 'RESIN-X9')
        self.assertEqual(p['material_source'], 'drawing_deterministic')

    def test_other_sheet_does_not_supply_material(self):
        self.assertIsNone(own_material({'part_number': 'DRAW-2'}, [page()]))

    def test_conflicting_own_sheets_not_chosen(self):
        self.assertIsNone(own_material({'part_number': 'DRAW-1'}, [page(), page(material='OTHER')]))

    def test_multiowner_title_block_not_part_specific(self):
        pg = page(); pg['page_analysis']['title_block']['drawing_numbers'].append('DRAW-2')
        self.assertIsNone(own_material({'part_number': 'DRAW-1'}, [pg]))

    def test_estimator_material_survives(self):
        p = {'part_number': 'DRAW-1', 'normalized_material': 'PETG',
             'material_source': 'estimator_confirmed'}
        retain_own_material(p, [page()], apply_field)
        self.assertEqual(p['normalized_material'], 'PETG')
        self.assertEqual(p['material_stated'], 'RESIN-X9')

    def test_repeated_agreement_not_ambiguous(self):
        self.assertIsNotNone(own_material({'part_number': 'DRAW-1'}, [page(), page()]))

    def test_saved_default_conflict_blocks(self):
        s = {'pages': [page()], 'manufacturing_writeup': {'parts': [
            {'part_number': 'DRAW-1', 'material_source': 'solidworks_applied_material'}]}}
        self.assertEqual(check_owned_specifications_survive(s)[0]['severity'], 'blocking')


class RoleTests(unittest.TestCase):
    def test_role_names_never_establish_count(self):
        s = roles(); self.assertTrue(audit_owned_specifications(s))
        self.assertEqual(s['manufacturing_writeup']['parts'][1]['quantity'], 1)

    def test_evidenced_counts_reach_local_edges(self):
        s = rulings(roles()); self.assertFalse(apply_role_counts(s))
        p = s['manufacturing_writeup']['parts'][1]
        self.assertEqual(p['quantity'], 4)
        self.assertEqual(p['bom_parents'], [{'parent': 'UNIT', 'qty': 4}])
        self.assertFalse(audit_owned_specifications(s))
        self.assertEqual(s['manufacturing_writeup']['parts'][0]['manufacturing_questions'], [{'subject':'other'}])

    def test_invalid_input_matrix(self):
        for field, value in [('basis','per_order'), ('quantity',True), ('quantity','4'),
                             ('quantity',0), ('quantity',-1), ('quantity',float('nan')),
                             ('quantity',1.5), ('evidence',''), ('decided_by','an estimator'),
                             ('role','BACK'), ('parent','OTHER')]:
            with self.subTest(field=field, value=value):
                s = rulings(roles()); s['estimator_decisions']['dxf_role_quantities'][0][field] = value
                self.assertTrue(apply_role_counts(s))
                self.assertTrue(audit_owned_specifications(s))

    def test_duplicate_ruling_refused(self):
        s = rulings(roles()); e=s['estimator_decisions']['dxf_role_quantities']; e.append(copy.deepcopy(e[0]))
        self.assertTrue(apply_role_counts(s))

    def test_shared_child_not_overwritten(self):
        s = rulings(roles()); p=s['manufacturing_writeup']['parts'][1]
        p['bom_parents']=[{'parent':'OTHER','qty':2}]
        self.assertTrue(apply_role_counts(s)); self.assertEqual(p['bom_parents'][0]['parent'],'OTHER')

    def test_duplicate_role_identity_refused(self):
        s=rulings(roles()); s['manufacturing_writeup']['parts'].append(copy.deepcopy(s['manufacturing_writeup']['parts'][1]))
        self.assertTrue(apply_role_counts(s))

    def test_lost_child_does_not_clear_question(self):
        s=rulings(roles()); s['manufacturing_writeup']['parts'].pop()
        apply_role_counts(s); self.assertTrue(audit_owned_specifications(s))

    def test_downstream_quantity_mutation_caught(self):
        s=rulings(roles()); apply_role_counts(s)
        s['manufacturing_writeup']['parts'][1]['quantity']=1
        self.assertTrue(audit_owned_specifications(s))

    def test_idempotent(self):
        s=rulings(roles()); apply_role_counts(s); before=copy.deepcopy(s)
        apply_role_counts(s); self.assertEqual(s,before)

    def test_no_global_shadow_enforcement(self):
        s={'material_charge_result':{'passed':False,'mode':'shadow','issues':[{'code':'x'}]}}
        self.assertFalse(audit_owned_specifications(s)); self.assertTrue(review_cautions(s))


class WiringTests(unittest.TestCase):
    def test_ruling_reaches_real_compiler_quantity_once(self):
        s=rulings(roles()); apply_role_counts(s)
        parts=s['manufacturing_writeup']['parts']
        parts[0].update(is_assembly_parent=True, quantity=1,
                        assembly_children=['UNIT-SIDE-01','UNIT-TOP-01'])
        result=compile_job_route(parts, declared_product='UNIT')
        nodes={n['part_number']:n for n in result['nodes']}
        self.assertEqual(nodes['UNIT-SIDE-01']['qty_per_unit'],4)
        self.assertEqual(nodes['UNIT-TOP-01']['qty_per_unit'],1)

    def test_release_check_is_registered(self):
        from invariants import CHECKS
        self.assertIn(check_owned_specifications_survive, CHECKS)

    def test_report_withholds_praise_for_shadow_findings(self):
        import html
        text=(Path(__file__).resolve().parents[1]/'src/job_report_html.py').read_text(encoding='utf-8')
        node=next(n for n in ast.parse(text).body if isinstance(n,ast.FunctionDef) and n.name=='_render_whats_right')
        ns={'Dict':dict,'List':list,'Any':object,'_extract_parts':lambda s:[],
            '_structure_qualifiers':lambda s:[], '_structure_is_unverified':lambda s:[],
            '_esc':html.escape,'_h2':lambda s:'<h2>Review</h2>'}
        exec(compile(ast.Module(body=[node],type_ignores=[]),'report','exec'),ns)
        result=ns[node.name]({'material_charge_result':{'passed':False,'mode':'shadow'}},[])
        self.assertIn('shadow',result)
        self.assertNotIn('every consistency check passed',result)
        self.assertNotIn('Material streams correctly separated',result)

    def test_inferred_parent_cnc_not_required_but_leaf_is(self):
        parts=[{'part_number':'A-100','is_assembly_parent':True, 'quantity':1,
                'assembly_children':['A-101'], 'textual_operations':['cnc_routing','glue'],
                'operation_sources':{'cnc_routing':'inference','glue':'inference'}},
               {'part_number':'A-101','quantity':1, 'normalized_material':'ACRYLIC',
                'textual_operations':['cnc_routing'], 'operation_sources':{'cnc_routing':'inference'},
                'bom_parents':[{'parent':'A-100','qty':1}]}]
        result=compile_job_route(parts, declared_product='A-100')
        ds=result['decisions']
        self.assertTrue(any(d['operation']=='cnc_routing' and d['target_id']=='A-101' and d['status']=='required' for d in ds))
        self.assertFalse(any(d['operation']=='cnc_routing' and d['target_id']=='A-100' and d['status']=='required' for d in ds))
        self.assertTrue(any(d['operation']=='glue' and d['status']=='required' for d in ds))

    def test_real_file_scan_adapter_runs_before_default_skip(self):
        text=(Path(__file__).resolve().parents[1]/'src/file_scan.py').read_text(encoding='utf-8')
        tree=ast.parse(text)
        node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_inherit_document_material_to_parts')
        ns={'_apply_field':apply_field,'Dict':dict,'List':list,'Any':object}
        exec(compile(ast.Module(body=[node],type_ignores=[]),'adapter','exec'),ns)
        p={'part_number':'DRAW-1','normalized_material':'MILD_STEEL','material_source':'solidworks_applied_material'}
        ns[node.name]([p],{},[page()])
        self.assertEqual(p['normalized_material'],'RESIN-X9')


class ChargedRoleTests(unittest.TestCase):
    def fixture(self):
        s=rulings(roles()); apply_role_counts(s)
        s['estimate_summary']={'canonical_route_shadow':{'nodes':[
            {'part_number':'UNIT','qty_per_unit':2}]}}
        s['final_estimate']={'material_rows':[
            {'description':'UNIT-SIDE-01 side', 'qty_per_unit':8,
             'total_value_gbp':10, 'charged_cell':'Estimate!M139'},
            {'description':'UNIT-TOP-01 top', 'qty_per_unit':2,
             'total_value_gbp':3, 'charged_cell':'Estimate!M140'}]}
        return s

    def test_nested_parent_multiplied_once(self):
        self.assertFalse(audit_owned_specifications(self.fixture()))

    def test_missing_row(self):
        s=self.fixture(); s['final_estimate']['material_rows'].pop()
        self.assertTrue(audit_owned_specifications(s))

    def test_wrong_count(self):
        s=self.fixture(); s['final_estimate']['material_rows'][0]['qty_per_unit']=4
        self.assertTrue(audit_owned_specifications(s))

    def test_order_quantity_not_per_product(self):
        s=self.fixture(); s['final_estimate']['material_rows'][0]['qty_per_unit']=80
        self.assertTrue(audit_owned_specifications(s))

    def test_duplicate_row(self):
        s=self.fixture(); s['final_estimate']['material_rows'].append(dict(s['final_estimate']['material_rows'][0]))
        self.assertTrue(audit_owned_specifications(s))

    def test_zero_and_text_money_not_evidence(self):
        for value in [0, '10', True, None, float('nan')]:
            s=self.fixture(); s['final_estimate']['material_rows'][0]['total_value_gbp']=value
            self.assertTrue(audit_owned_specifications(s))

    def test_missing_parent(self):
        s=self.fixture(); s['estimate_summary']['canonical_route_shadow']['nodes']=[]
        self.assertTrue(audit_owned_specifications(s))


if __name__ == '__main__':
    unittest.main()
