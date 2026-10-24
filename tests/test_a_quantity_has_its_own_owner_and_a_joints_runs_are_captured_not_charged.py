"""Exercise generic ownership, corrupted roll-ups and explicit weld requirements (D-598h).

From the reviewer's quantity-and-joints package of 24 Oct; runs under the project suite.
"""
import copy
import ast
from pathlib import Path
import unittest
from quantity_flow_contract import audit
from joint_scope_evidence import joint_scope


def fixture():
    return {'estimate_summary': {'canonical_part_estimates': [
        {'part_number': 'UNIT', 'quantity': 1}, {'part_number': 'MEMBER', 'quantity': 2}],
        'canonical_route_shadow': {'product_root': 'UNIT', 'nodes': [
            {'part_number': 'UNIT', 'qty_per_unit': 1, 'children': [{'part_number': 'MEMBER', 'qty': 2}]},
            {'part_number': 'MEMBER', 'qty_per_unit': 2, 'parents': ['UNIT'],
             'qty_by_parent': {'UNIT': 2}}]}},
        'read_ledger': {'unit': 'UNIT', 'raw_sha256': 'saved-read-digest', 'items': [
            {'kind': 'part', 'record': 'MEMBER', 'source_id': 'response/R1', 'as_read': {'quantity': 2}}]}}


def scope():
    return {'part': 'MEMBER', 'joint_id': 'J1', 'side': 'left', 'process': 'TIG',
            'runs_per_joint': 2, 'joints_per_product': 2, 'basis': 'per_finished_product',
            'source': {'document': 'drawing-or-model', 'locator': 'feature/weld-1'}}


class QuantityTests(unittest.TestCase):
    def test_real_audit_uses_source_corroborated_local_edge(self):
        s = fixture(); before = copy.deepcopy(s)
        result = audit(s)
        self.assertTrue(result['passed'])
        self.assertEqual(s, before)
        # The fallback says which basis it used; a record with its own parents adds no note.
        self.assertIn(('MEMBER', 'compiled_edges_checked_against_flat_read'),
                      [(n['part'], n['basis']) for n in result['notes']
                       if n['code'] == 'local_quantity_evidence'])

    def test_corrupted_graph_and_price_cannot_agree_themselves_clean(self):
        s = fixture(); es = s['estimate_summary']
        es['canonical_part_estimates'][1]['quantity'] = 6
        es['canonical_route_shadow']['nodes'][0]['children'][0]['qty'] = 6
        es['canonical_route_shadow']['nodes'][1].update(qty_per_unit=6, qty_by_parent={'UNIT': 6})
        self.assertIn('read_quantity_disagreement', [i['code'] for i in audit(s)['issues']])

    def test_missing_read_never_becomes_verified(self):
        s = fixture(); s.pop('read_ledger')
        self.assertIn('local_edge_source_unverified', [i['code'] for i in audit(s)['issues']])

    def test_missing_source_id_is_not_independent_evidence(self):
        s = fixture(); s['read_ledger']['items'][0].pop('source_id')
        self.assertFalse(audit(s)['passed'])

    def test_explicit_empty_edges_do_not_fall_back(self):
        s = fixture(); s['estimate_summary']['canonical_part_estimates'][1]['bom_parents'] = []
        self.assertIn('quantity_path_missing', [i['code'] for i in audit(s)['issues']])

    def test_duplicate_edges_stay_unresolved(self):
        s = fixture(); children = s['estimate_summary']['canonical_route_shadow']['nodes'][0]['children']
        children.append(copy.deepcopy(children[0]))
        self.assertFalse(audit(s)['passed'])

    def test_order_quantity_cannot_replace_product_quantity(self):
        s = fixture(); s['estimate_summary']['canonical_part_estimates'][1]['quantity'] = 2000
        self.assertFalse(audit(s)['passed'])

    def test_nested_local_edges_not_rolled_contributions(self):
        s = fixture(); es = s['estimate_summary']; nodes = es['canonical_route_shadow']['nodes']
        nodes[0]['children'] = [{'part_number': 'SUB', 'qty': 2}]
        nodes.append({'part_number': 'SUB', 'qty_per_unit': 2, 'parents': ['UNIT'],
                      'qty_by_parent': {'UNIT': 2}, 'children': [{'part_number': 'MEMBER', 'qty': 3}]})
        nodes[1].update(parents=['SUB'], qty_by_parent={'SUB': 6}, qty_per_unit=6)
        es['canonical_part_estimates'][1]['quantity'] = 6
        es['canonical_part_estimates'].append({'part_number': 'SUB', 'quantity': 2})
        s['manufacturing_writeup'] = {'parts': [
            {'part_number': 'SUB', 'bom_parents': [{'parent': 'UNIT', 'qty': 2}]},
            {'part_number': 'MEMBER', 'bom_parents': [{'parent': 'SUB', 'qty': 3}]}]}
        self.assertTrue(audit(s)['passed'])
        nodes[2]['children'][0]['qty'] = 6
        self.assertFalse(audit(s)['passed'])

    def test_original_canonical_edges_remain_authoritative(self):
        s = fixture(); s['estimate_summary']['canonical_part_estimates'][1]['bom_parents'] = [{'parent': 'UNIT', 'qty': 2}]
        self.assertTrue(audit(s)['passed'])

    def test_empty_canonical_population_is_not_revived(self):
        s = fixture(); s['estimate_summary']['canonical_part_estimates'] = []
        self.assertFalse(audit(s)['passed'])

    def test_shared_child_contributions_are_summed(self):
        s = fixture(); es = s['estimate_summary']; nodes = es['canonical_route_shadow']['nodes']
        nodes[0]['children'].append({'part_number': 'SUB', 'qty': 3})
        nodes.append({'part_number': 'SUB', 'qty_per_unit': 3, 'parents': ['UNIT'],
                      'qty_by_parent': {'UNIT': 3}, 'children': [{'part_number': 'MEMBER', 'qty': 4}]})
        nodes[1].update(parents=['UNIT', 'SUB'], qty_per_unit=14, qty_by_parent={'UNIT': 2, 'SUB': 12})
        es['canonical_part_estimates'][1].update(quantity=14, bom_parents=[{'parent': 'UNIT', 'qty': 2}, {'parent': 'SUB', 'qty': 4}])
        es['canonical_part_estimates'].append({'part_number': 'SUB', 'quantity': 3, 'bom_parents': [{'parent': 'UNIT', 'qty': 3}]})
        self.assertTrue(audit(s)['passed'])

    def test_cycle_is_a_finding(self):
        s = fixture(); s['estimate_summary']['canonical_part_estimates'][1]['bom_parents'] = [{'parent': 'MEMBER', 'qty': 2}]
        self.assertIn('quantity_cycle', [i['code'] for i in audit(s)['issues']])


class JointTests(unittest.TestCase):
    def test_captured_scope_is_never_charge_proof(self):
        s = {'weld_joint_requirements': [scope()]}; before = copy.deepcopy(s)
        result = joint_scope(s, 'MEMBER')
        self.assertTrue(result['scope_verified'])
        self.assertFalse(result['charge_verified'])
        self.assertEqual(result['requirements'][0]['runs_per_product'], 4)
        self.assertEqual(s, before)

    def test_missing_inventory_stays_unknown(self):
        self.assertFalse(joint_scope({}, 'MEMBER')['scope_verified'])

    def test_another_parts_runs_do_not_cover_this_part(self):
        self.assertFalse(joint_scope({'weld_joint_requirements': [scope()]}, 'OTHER')['scope_verified'])

    def test_duplicate_sides_are_not_added(self):
        self.assertFalse(joint_scope({'weld_joint_requirements': [scope(), scope()]}, 'MEMBER')['scope_verified'])

    def test_two_sides_are_explicit(self):
        right = scope(); right['side'] = 'right'
        self.assertTrue(joint_scope({'weld_joint_requirements': [scope(), right]}, 'MEMBER')['scope_verified'])

    def test_bad_count_basis_source_and_process_are_rejected(self):
        for field, value in [('runs_per_joint', True), ('runs_per_joint', 1.5),
                             ('runs_per_joint', '2'), ('joints_per_product', 0),
                             ('basis', 'per_order'), ('source', {}), ('process', '')]:
            with self.subTest(field=field, value=value):
                item = scope(); item[field] = value
                self.assertFalse(joint_scope({'weld_joint_requirements': [item]}, 'MEMBER')['scope_verified'])

    def test_estimator_scope_needs_author(self):
        item = scope(); s = {'estimator_decisions': {'weld_joint_requirements': [item]}}
        self.assertFalse(joint_scope(s, 'MEMBER')['scope_verified'])
        item['confirmed_by'] = 'reviewer'
        self.assertTrue(joint_scope(s, 'MEMBER')['scope_verified'])

    def test_malformed_inventory_is_a_finding(self):
        self.assertFalse(joint_scope({'weld_joint_requirements': 'bad'}, 'MEMBER')['scope_verified'])

    def test_real_ledger_hook_keeps_captured_joint_unresolved(self):
        # Execute the changed production nested function, with workbook boundary stubbed.
        # This proves hook behaviour, not Excel or the full release gate.
        path = Path(__file__).resolve().parents[1] / 'src' / 'read_charge_contract.py'
        tree = ast.parse(path.read_text(encoding='utf-8-sig'))
        fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == 'joint_cover')
        fn.args.args[0].annotation = None; fn.returns = None
        captured = []
        row = {'wb_row': 157, 'title': 'Weld', 'parts': {'MEMBER'}}
        env = {'book': type('Book', (), {'calculated': True})(),
               'summary': {'weld_joint_requirements': [scope()]},
               'ruled': lambda item: False, '_pn': lambda p: p,
               'weld_rows_for': lambda p: [row], '_families': lambda op: [op],
               'labour_evidence': lambda *args: None, 'UNRESOLVED': 'unresolved',
               'done': lambda *args, **kw: captured.append((args, kw))}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), str(path), 'exec'), env)
        env['joint_cover']({'record': 'MEMBER'})
        self.assertEqual(captured[0][0][1], 'unresolved')
        self.assertTrue(captured[0][1]['joint_scope']['scope_verified'])
        self.assertFalse(captured[0][1]['joint_scope']['charge_verified'])


if __name__ == '__main__':
    unittest.main()
