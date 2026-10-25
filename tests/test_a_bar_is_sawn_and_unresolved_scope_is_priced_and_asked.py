"""A bar is sawn, and unresolved scope is priced and asked (D-598r; SCRUM-100, 104, 105, 107).

9439-07-04-GA, the 300 x 100 x 200 riser, 24 Oct 2026 19:58: four 5 x 5 mm square-bar cross
members were sawn and also charged a laser cut from lines traced off the PDF; the frame's own
sheet states TIG and the book charged CO2 calling the weld inferred; one hot-melt note became
two glue rows; the coating area was the members' blanks, quoted as the area actually coated.
Unsupported page-line laser on an owned bar comes off. A confirmed contradiction blocks the
firm price; unresolved scope keeps its money and is put to a person as a ruling.
"""
import copy
import unittest

from owned_route_evidence import (own_pages, solid_bar, stamp, bar_area, filter_cutting,
                                  audit, findings, unresolved)


def page(pn='P-1', text='ITEM QTY DESCRIPTION LENGTH\n1 1 5 x 5mm BAR 290', number=1):
    return dict(page_number=number, source_pdf_path='pack.pdf', pdfplumber_text=text,
                page_analysis={'title_block': {'drawing_numbers': [pn]}})


def part(pn='P-1'):
    return dict(part_number=pn, pages=[1], textual_operations=['saw', 'laser_cutting'],
                normalized_geometry={'raw_cut_length_mm': 7000})


def row(pn, op, cell='Estimate!M151'):
    return dict(part_numbers=pn, operation=op, charged_cell=cell, total_value_gbp=12)


def summary(parts, pages, rows=()):
    return dict(manufacturing_writeup={'parts': parts}, pages=pages,
                final_estimate={'labour_rows': list(rows)})


class TestOwnedRoutes(unittest.TestCase):
    def test_owned_bar_has_dimensions_and_page(self):
        e = solid_bar(part(), [page()])
        self.assertEqual((e['a'], e['b'], e['length_mm'], e['page']), (5, 5, 290, 1))

    def test_other_page_cannot_supply_bar(self):
        self.assertIsNone(solid_bar(part(), [page('OTHER')]))

    def test_ambiguous_owners_cannot_supply_bar(self):
        p = page(); p['page_analysis']['title_block']['drawing_numbers'].append('OTHER')
        self.assertIsNone(solid_bar(part(), [p]))

    def test_bom_mention_is_not_ownership(self):
        self.assertFalse(own_pages(part(), [page('GA', 'P-1 TIG')]))

    def test_revision_recovery_requires_exact_suffix_and_bound_page(self):
        p = page('REVISION', 'TIG')
        p['page_analysis']['title_block']['project_titles'] = ['PROJECT P-1']
        self.assertEqual(own_pages(part(), [p]), [p])
        p['page_number'] = 9
        self.assertFalse(own_pages(part(), [p]))

    def test_conflicting_cut_lists_are_not_resolved_by_weight(self):
        self.assertIsNone(solid_bar(part(), [page(), page(text='ITEM QTY DESCRIPTION LENGTH\n1 1 6 x 6mm BAR 290')]))

    def test_decimal_comma_and_other_sizes(self):
        e = solid_bar(part(), [page(text='ITEM QTY DESCRIPTION LENGTH\n1 1 12,5 x 8mm FLAT BAR 750')])
        self.assertEqual((e['a'], e['b'], e['length_mm']), (12.5, 8, 750))

    def test_no_header_no_invented_length(self):
        self.assertIsNone(solid_bar(part(), [page(text='1 1 5 x 5mm BAR 290')]))

    def test_multiple_cut_pieces_not_silently_collapsed(self):
        self.assertIsNone(solid_bar(part(), [page(text='ITEM QTY DESCRIPTION LENGTH\n1 2 5 x 5mm BAR 290')]))

    def test_bar_surface_is_per_piece_not_order(self):
        p = part(); p['quantity'] = 1000
        stamp([p], {'pages': [page()]})
        self.assertAlmostEqual(bar_area(p), .00585)

    def test_unowned_bar_area_is_unknown(self):
        self.assertEqual(bar_area(part()), 0)

    def test_page_laser_removed_with_explicit_unresolved_note(self):
        p = part(); stamp([p], {'pages': [page()]})
        self.assertEqual(filter_cutting(p, p['textual_operations']), ['saw'])
        self.assertIn('unverified', p['owned_bar_cutting_review'])
        self.assertIn('laser_cutting', p['operations_ruled_out'])

    def test_saw_alone_cannot_remove_laser(self):
        p = part()
        self.assertEqual(filter_cutting(p, p['textual_operations']), ['saw', 'laser_cutting'])

    def test_stated_laser_is_preserved(self):
        for field, value in [('flat_pattern_detected', True), ('dxf_files', ['shape.dxf']),
                             ('operation_evidence', {'laser_cutting': 'slots'}),
                             ('operation_sources', {'laser_cutting': 'drawing_deterministic'})]:
            p = part(); stamp([p], {'pages': [page()]}); p[field] = value
            self.assertIn('laser_cutting', filter_cutting(p, p['textual_operations']))

    def test_unknown_geometry_cannot_be_removed(self):
        p = part(); stamp([p], {'pages': [page()]}); p['normalized_geometry'] = {}
        self.assertIn('laser_cutting', filter_cutting(p, p['textual_operations']))

    def test_tig_does_not_acquire_a_rate(self):
        p = part(); stamp([p], {'pages': [page(text='TIG')]})
        self.assertEqual(p['owned_weld_process_evidence'][0]['process'], 'TIG')
        self.assertNotIn('weld_rate', p)

    def test_tig_on_a_co2_row_is_an_allowance_put_to_a_person(self):
        s = summary([part()], [page(text='TIG')], [row('P-1', 'Weld (CO2)')])
        self.assertFalse(audit(s), 'priced on the CO2 row: unresolved, not a contradiction')
        self.assertTrue(any('TIG' in f['message'] and f['operation'] == 'welding'
                            for f in unresolved(s)))

    def test_a_stated_weld_charged_nowhere_is_a_contradiction(self):
        self.assertTrue(audit(summary([part()], [page(text='TIG')], [row('P-1', 'Saw')])))

    def test_an_empty_calculated_labour_table_is_not_a_pass(self):
        # D-598s: a stamped read-back with no labour rows is a book that charges no weld.
        s = summary([part()], [page(text='TIG')])
        self.assertEqual(s['final_estimate']['labour_rows'], [])
        self.assertTrue(audit(s))

    def test_no_read_back_is_unverified_never_a_pass(self):
        from invariants import check_owned_route_scope_is_ruled, check_owned_specifications_survive
        gap = part('GA'); gap['assembly_children'] = ['TOP', 'FRAME']
        s = dict(manufacturing_writeup={'parts': [part(), gap]},
                 pages=[page(text='ITEM QTY DESCRIPTION LENGTH\n1 1 5 x 5mm BAR 290\nTIG'),
                        page('GA', 'HOT MELT GLUE', 2)])
        self.assertFalse(check_owned_specifications_survive(s), 'no read-back is not a contradiction')
        v = check_owned_route_scope_is_ruled(s)
        missing = [x for x in v if x['code'] == 'owned_route_rows_not_evaluated']
        self.assertEqual({x['detail']['operation'] for x in missing},
                         {'welding', 'laser_cutting', 'glue'})
        self.assertTrue(all(x['severity'] == 'unverified' for x in missing))

    def test_a_stated_bond_charged_nowhere_is_asked(self):
        p = part('GA'); p['assembly_children'] = ['TOP', 'FRAME']
        s = summary([p], [page('GA', 'HOT MELT GLUE')], [row('TOP', 'Saw')])
        self.assertTrue(any('no glue row' in f['message'] for f in unresolved(s)))
        self.assertFalse(audit(s), 'bonding may sit inside an assembly row: asked, not blocked')

    def test_tig_charge_does_not_fail_process_comparison(self):
        self.assertFalse(findings(summary([part()], [page(text='TIG')], [row('P-1', 'Weld (TIG)')])))

    def test_wrong_part_weld_does_not_cover_requirement(self):
        self.assertTrue(audit(summary([part()], [page(text='TIG')], [row('P-10', 'Weld (TIG)')])))

    def test_multiple_glue_rows_are_questioned_not_deleted(self):
        p = part('GA'); p['assembly_children'] = ['TOP', 'FRAME']
        s = summary([p], [page('GA', 'TOP SECURED USING HOLT MELT\nGLUE')],
                    [row('TOP', 'Glue'), row('FRAME', 'Glue', 'Estimate!M152')])
        before = copy.deepcopy(s)
        self.assertTrue(any('stage allocation' in f['message'] for f in unresolved(s)))
        self.assertFalse(audit(s), 'a likely overlap is a ruling, never a block')
        self.assertEqual(s, before)

    def test_unrelated_glue_is_not_same_joint(self):
        p = part('GA'); p['assembly_children'] = ['TOP']
        s = summary([p], [page('GA', 'HOT MELT GLUE')], [row('TOP', 'Glue'), row('OTHER', 'Glue')])
        self.assertFalse(findings(s))

    def test_bar_price_fallback_is_exposed(self):
        s = summary([part()], [page()])
        self.assertTrue(any('purchase/price basis' in f['message'] for f in unresolved(s)))

    def test_coating_allowance_not_verified_surface(self):
        s = summary([part()], [])
        s['estimate_summary'] = {'part_estimates': [dict(part_number='P-1', material_estimate={
            'powder_consumable': {'coated_area_source': 'sum_of_members_blanks'}})]}
        self.assertTrue(any('allowances' in f['message'] for f in unresolved(s)))

    def test_existing_release_invariant_receives_contradictions(self):
        from invariants import check_owned_specifications_survive
        s = summary([part()], [page(text='TIG')], [row('P-1', 'Saw')])
        self.assertEqual(check_owned_specifications_survive(s)[0]['severity'], 'blocking')

    def test_unresolved_scope_is_a_ruling_with_its_own_words(self):
        from invariants import check_owned_route_scope_is_ruled, check_owned_specifications_survive
        from costed_facts import costed_job
        s = summary([part()], [page(text='TIG')], [row('P-1', 'Weld (CO2)')])
        self.assertFalse(check_owned_specifications_survive(s), 'no false hold')
        v = check_owned_route_scope_is_ruled(s)
        self.assertTrue(v and all(x['severity'] == 'warning' and x['detail']['needs_ruling']
                                  for x in v))
        s['invariants'] = {'verified': True, 'violations': v,
                           'checks_run': ['check_owned_route_scope_is_ruled']}
        rows = [d for d in costed_job(s)['decisions_required'] if d.get('kind') == 'ruling']
        self.assertTrue(any('TIG allowance' in d['assumption'] and 'TIG rate' in d['action']
                            for d in rows))

    def test_hot_melt_is_read_however_it_is_printed(self):
        for text in ('HOT-MELT ADHESIVE', 'HOTMELT GLUE', 'HOT MELT'):
            p = part('GA'); p['assembly_children'] = ['TOP', 'FRAME']
            s = summary([p], [page('GA', text)], [row('TOP', 'Glue'), row('FRAME', 'Glue', 'Estimate!M152')])
            self.assertTrue(unresolved(s), text)

    def test_a_ga_known_only_to_the_route_graph_has_its_bond_checked(self):
        # D-598s: on 9439-07-04 the GA is a compiled-route node with children and no part
        # record; its own sheet carries the hot-melt note.
        def graph_only(rows):
            s = summary([part('TOP'), part('FRAME')], [page('GA', 'HOT MELT GLUE', 2)], rows)
            s['estimate_summary'] = {'canonical_route_shadow': {'nodes': [
                dict(part_number='GA', kind='assembly',
                     children=[dict(part_number='TOP', qty=1), dict(part_number='FRAME', qty=1)]),
                dict(part_number='TOP', kind='leaf', children=[]),
                dict(part_number='FRAME', kind='leaf', children=[])]}}
            return s
        two = graph_only([row('TOP', 'Glue'), row('FRAME', 'Glue', 'Estimate!M152')])
        self.assertTrue(any(f['part'] == 'GA' and 'stage allocation' in f['message']
                            for f in unresolved(two)))
        self.assertTrue(any(f['part'] == 'GA' and 'no glue row' in f['message']
                            for f in unresolved(graph_only([]))), 'empty labour table')
        self.assertFalse(findings(graph_only([row('TOP', 'Glue')])), 'one row covers one note')

    def test_an_unreadable_labour_block_is_unverified_not_a_missing_weld(self):
        from invariants import check_owned_route_scope_is_ruled, check_owned_specifications_survive
        s = summary([part()], [page(text='TIG')])
        s['final_estimate']['adapter_problems'] = [
            dict(block='labour', code='header_row_not_found', message='', detail={})]
        self.assertFalse(check_owned_specifications_survive(s), 'nothing was read, so no contradiction')
        v = check_owned_route_scope_is_ruled(s)
        self.assertTrue(any(x['code'] == 'owned_route_rows_not_evaluated' and
                            x['detail']['operation'] == 'welding' for x in v))
        s['final_estimate']['adapter_problems'][0]['block'] = 'tube'
        self.assertTrue(audit(s), 'a material block problem does not excuse the labour table')

    def test_real_process_adapter_removes_only_page_laser(self):
        import estimator
        p = part(); p['normalized_material'] = 'MILD STEEL'; p['normalized_thickness_mm'] = 5
        stamp([p], {'pages': [page()]})
        estimator.estimate_process_times(p)
        self.assertIn('laser_cutting', p['operations_ruled_out'])


if __name__ == '__main__':
    unittest.main()
