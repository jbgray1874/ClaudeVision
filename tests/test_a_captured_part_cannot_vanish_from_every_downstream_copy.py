"""Production audit exercised with lost nodes, bad ownership and agreeing corrupt copies (D-598i).

A part must not disappear just because every downstream copy lost it. From the reviewer's Day 1
ownership package of 24 Oct; runs under the project suite.
"""
import copy
import unittest
from quantity_flow_contract import audit, printed_rows_audit


def fixture():
    return {'estimate_summary': {'canonical_part_estimates': [
        {'part_number': 'ROOT', 'quantity': 1},
        {'part_number': 'CHILD', 'quantity': 2, 'bom_parents': [{'parent': 'ROOT', 'qty': 2}]}],
        'canonical_route_shadow': {'product_root': 'ROOT', 'nodes': [
            {'part_number': 'ROOT', 'kind': 'assembly', 'qty_per_unit': 1,
             'children': [{'part_number': 'CHILD', 'qty': 2}]},
            {'part_number': 'CHILD', 'kind': 'leaf', 'qty_per_unit': 2,
             'parents': ['ROOT'], 'qty_by_parent': {'ROOT': 2}, 'children': []}]}},
        'document_analysis': {'bom_rows': [
            {'part_number': 'CHILD', 'bom_parent': 'ROOT', 'quantity': 2,
             'bom_item_no': '1', 'bom_sheet': 'assembly#0', 'source_pdf': 'drawing'}]}}


def codes(s):
    return {i['code'] for i in audit(s)['issues']}


def lose_child(s):
    es = s['estimate_summary']
    es['canonical_part_estimates'] = es['canonical_part_estimates'][:1]
    es['canonical_route_shadow']['nodes'] = es['canonical_route_shadow']['nodes'][:1]
    es['canonical_route_shadow']['nodes'][0]['children'] = []


class CapturedMembers(unittest.TestCase):
    def test_valid_source_owned_part_passes_without_mutation(self):
        s = fixture(); before = copy.deepcopy(s)
        self.assertTrue(audit(s)['passed'])
        self.assertEqual(s, before)

    def test_entire_part_lost_from_both_downstream_copies_is_found(self):
        s = fixture(); lose_child(s)
        self.assertIn('captured_part_missing_from_graph', codes(s))

    def test_missing_price_is_found(self):
        s = fixture(); s['estimate_summary']['canonical_part_estimates'].pop()
        self.assertIn('captured_part_missing_from_prices', codes(s))

    def test_whole_lost_subassembly_does_not_hide_its_children(self):
        s = fixture(); s['document_analysis']['bom_rows'].append(
            {'part_number': 'GRANDCHILD', 'bom_parent': 'CHILD', 'quantity': 3})
        lose_child(s)
        result = audit(s)
        missing = {i['part'] for i in result['issues'] if i['code'] == 'captured_part_missing_from_graph'}
        self.assertEqual(missing, {'CHILD', 'GRANDCHILD'})

    def test_unselected_product_is_not_added(self):
        s = fixture(); s['document_analysis']['bom_rows'].append(
            {'part_number': 'OTHER', 'bom_parent': 'OTHER_ROOT', 'quantity': 5})
        self.assertTrue(audit(s)['passed'])
        self.assertEqual(audit(s)['source_population']['outside_selected_product_rows'], 1)

    def test_missing_parent_link_is_explicit(self):
        s = fixture(); s['estimate_summary']['canonical_route_shadow']['nodes'][1]['parents'] = []
        self.assertIn('captured_parent_link_missing', codes(s))

    def test_missing_source_is_reported_as_coverage_limit(self):
        s = fixture(); s.pop('document_analysis')
        self.assertEqual(audit(s)['source_population']['coverage'], 'no_selected_source_rows')

    def test_engine_set_aside_does_not_prove_exclusion(self):
        s = fixture(); lose_child(s)
        s['set_aside_outside_product'] = [{'part_number': 'CHILD', 'reason': 'not_linked_to_the_product'}]
        self.assertIn('captured_part_missing_from_graph', codes(s))

    def test_nonpositive_or_text_source_quantity_is_not_accepted(self):
        for q in (None, True, 0, -2, '2'):
            with self.subTest(quantity=q):
                s = fixture(); s['document_analysis']['bom_rows'][0]['quantity'] = q
                self.assertIn('captured_local_quantity_unverified', codes(s))

    def test_normalized_identity_collision_not_last_record_wins(self):
        s = fixture(); node = copy.deepcopy(s['estimate_summary']['canonical_route_shadow']['nodes'][1])
        node['part_number'] = 'C H I L D'
        s['estimate_summary']['canonical_route_shadow']['nodes'].append(node)
        self.assertIn('ambiguous_normalized_graph_identity', codes(s))

    def test_parent_child_quantity_disagreement_without_source_adapter(self):
        s = fixture(); s.pop('document_analysis')
        s['estimate_summary']['canonical_route_shadow']['nodes'][0]['children'][0]['qty'] = 9
        self.assertIn('compiled_local_edge_disagreement', codes(s))

    def test_dangling_child_without_source_adapter(self):
        s = fixture(); s.pop('document_analysis')
        s['estimate_summary']['canonical_route_shadow']['nodes'].pop()
        self.assertIn('compiled_child_missing', codes(s))

    def test_duplicate_compiled_edge_is_not_a_second_quantity(self):
        s = fixture(); children = s['estimate_summary']['canonical_route_shadow']['nodes'][0]['children']
        children.append(copy.deepcopy(children[0]))
        self.assertIn('duplicate_or_missing_compiled_child', codes(s))


class SourceQuantities(unittest.TestCase):
    def ledger(self):
        s = fixture(); s.pop('document_analysis')
        s['read_ledger'] = {'unit': 'ROOT', 'raw_sha256': 'retained-digest', 'items': [
            {'id': 'R1', 'kind': 'part', 'record': 'CHILD', 'source_id': 'response/R1',
             'work': True, 'as_read': {'quantity': 2}}]}
        return s

    def test_canonical_links_no_longer_skip_original_read(self):
        s = self.ledger(); es = s['estimate_summary']
        es['canonical_part_estimates'][1].update(quantity=6, bom_parents=[{'parent': 'ROOT', 'qty': 6}])
        es['canonical_route_shadow']['nodes'][0]['children'][0]['qty'] = 6
        es['canonical_route_shadow']['nodes'][1].update(qty_per_unit=6, qty_by_parent={'ROOT': 6})
        self.assertIn('read_quantity_disagreement', codes(s))

    def test_lost_ledger_part_is_found_even_with_no_graph_edge(self):
        s = self.ledger(); lose_child(s)
        self.assertIn('captured_part_missing_from_graph', codes(s))

    def test_duplicate_read_identity_is_not_selected_arbitrarily(self):
        s = self.ledger(); s['read_ledger']['items'].append(copy.deepcopy(s['read_ledger']['items'][0]))
        self.assertIn('ambiguous_captured_part_identity', codes(s))

    def test_malformed_read_quantity_is_unverified(self):
        s = self.ledger(); s['read_ledger']['items'][0]['as_read'] = 'bad'
        self.assertIn('captured_quantity_source_unverified', codes(s))

    def test_explicit_named_exclusion_is_traced_not_reinserted(self):
        s = self.ledger(); lose_child(s)
        s['estimator_decisions'] = {'decided_by': 'Reviewer', 'read_rulings': {
            'R1': {'ruling': 'excluded', 'reason': 'Customer supplies this component'}}}
        self.assertNotIn('captured_part_missing_from_graph', codes(s))
        self.assertEqual(audit(s)['source_population']['trace'][0]['state'], 'explicitly_excluded')

    def test_exclusion_without_reason_does_not_hide_loss(self):
        s = self.ledger(); lose_child(s)
        s['estimator_decisions'] = {'decided_by': 'Reviewer', 'read_rulings': {'R1': {'ruling': 'excluded'}}}
        self.assertIn('captured_part_missing_from_graph', codes(s))

    def test_malformed_edges_do_not_crash_audit(self):
        s = fixture(); s['estimate_summary']['canonical_part_estimates'][1]['bom_parents'] = 'bad'
        self.assertIn('malformed_local_edges', codes(s))

    def test_fallback_edge_compared_with_printed_quantity(self):
        s = fixture(); s['estimate_summary']['canonical_part_estimates'][1].pop('bom_parents')
        s['document_analysis']['bom_rows'][0]['quantity'] = 3
        self.assertIn('local_edge_disagrees_with_printed_row', codes(s))

    def test_cad_native_parent_evidence_is_checked_too(self):
        s = fixture(); s.pop('document_analysis')
        s['manufacturing_writeup'] = {'parts': [{'part_number': 'CHILD', 'bom_parents': [
            {'parent': 'ROOT', 'qty': 3}], 'quantity_source': 'solidworks'}]}
        self.assertIn('reader_local_edge_disagreement', codes(s))


class PrintedRows(unittest.TestCase):
    def test_repeat_of_same_bom_sheet_item_is_not_multiplied(self):
        s = fixture(); rows = s['document_analysis']['bom_rows']; rows.append(copy.deepcopy(rows[0]))
        self.assertEqual(printed_rows_audit(s)['trace'][0]['used_local'], 2)

    def test_conflicting_repeat_is_not_silently_discarded(self):
        s = fixture(); rows = s['document_analysis']['bom_rows']; extra = copy.deepcopy(rows[0])
        extra['quantity'] = 3; rows.append(extra)
        self.assertIn('conflicting_source_row_quantity', codes(s))

    def test_different_item_numbers_add(self):
        s = fixture(); rows = s['document_analysis']['bom_rows']; extra = copy.deepcopy(rows[0])
        extra['bom_item_no'] = '2'; rows.append(extra)
        self.assertEqual(printed_rows_audit(s)['trace'][0]['used_local'], 4)

    def test_same_item_on_other_sheet_is_not_silently_deduplicated(self):
        s = fixture(); rows = s['document_analysis']['bom_rows']; extra = copy.deepcopy(rows[0])
        extra['bom_sheet'] = 'assembly#1'; rows.append(extra)
        self.assertEqual(printed_rows_audit(s)['trace'][0]['used_local'], 4)


if __name__ == '__main__':
    unittest.main()
