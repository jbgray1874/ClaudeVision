from test_native_hand_edges_and_final_print_quantity import model_case, ROOT, BASE, HAND
import route_compiler as rc


def test_inferred_cutting_is_not_new_evidence_against_two_purchases():
    parts, job, rows = model_case()
    base = next(p for p in parts if p['part_number'] == BASE)
    # estimate_part's late sheet-metal default can add this after make/buy was settled.
    base['textual_operations'] = ['laser_cutting']
    base['normalized_material'] = 'ALUMINIUM'
    graph = rc.build_part_graph(parts, {}, rows, job.assembly_pns, declared_product=ROOT)
    nodes = {n.part_number: n for n in graph['nodes']}
    assert nodes[BASE].kind == nodes[HAND].kind == 'bought_in'
    assert graph['quantities'][BASE] == graph['quantities'][HAND] == 6


def test_own_measured_flat_still_prevents_purchase_reclassification():
    parts, job, rows = model_case()
    base = next(p for p in parts if p['part_number'] == BASE)
    base['dxf_raw_geometry'] = {'blank_area_mm2': 10000, 'cut_length_mm': 400}
    base['geometry_source'] = 'dxf'
    graph = rc.build_part_graph(parts, {}, rows, job.assembly_pns, declared_product=ROOT)
    assert next(n for n in graph['nodes'] if n.part_number == BASE).kind == 'leaf'
