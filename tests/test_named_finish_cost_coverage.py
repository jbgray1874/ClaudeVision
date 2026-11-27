import copy
import pytest
from named_finish_schedule import apply_times, mint_consumables


def schedule():
    return {'operation': 'wet_spray', 'stages': [
        {'passes': 1, 'description': 'Clear isolator'},
        {'passes': 1, 'description': 'Basecoat'}, {'passes': 1, 'description': 'Topcoat'}]}


def test_passes_scale_labour_not_physical_piece_quantity():
    from estimator import estimate_process_times, estimate_labour_costs
    p = {'part_number': 'A.45670', 'normalized_material': 'MDF', 'quantity': 4,
         'blank_length_mm': 500, 'blank_width_mm': 400, 'normalized_thickness_mm': 18,
         'textual_operations': ['wet_spray'], '_powder_members_coated_m2': 1.2}
    before = estimate_process_times(copy.deepcopy(p), quantity=4)
    p['finish_schedule'] = schedule()
    after = estimate_process_times(p, quantity=4)
    assert p['quantity'] == 4
    assert after['run_times_min_per_unit']['wet_spray'] == pytest.approx(
        before['run_times_min_per_unit']['wet_spray'] * 3, abs=.02)
    cash = estimate_labour_costs(after, job_quantity=4, material='MDF')
    assert cash['costs_gbp']['wet_spray'] > 0
    assert after['times_min']['wet_spray'] > before['times_min']['wet_spray']


def test_unannotated_finish_is_unchanged_and_named_setups_are_per_stage():
    assert apply_times({}, .75, 2) == (.75, 2)
    p = {'finish_schedule': {'operation': 'wet_spray',
         'stages': [{'passes': 2, 'description': 'Topcoat'}]}}
    assert apply_times(p, .75, 2) == (.75, 4)


def test_consumables_carry_positive_money_through_normal_costed_material_record(monkeypatch):
    import estimator
    parts = [{'part_number': 'A.45670', 'quantity': 1, 'finish_schedule': schedule(),
              '_powder_members_coated_m2': 1.2}]
    minted = mint_consumables(parts)
    assert len(minted) == 3 and mint_consumables(parts) == []
    monkeypatch.setattr(estimator, 'estimate_material', lambda p: {})
    # No catalogue, service or market request is permitted in this synthetic test.
    monkeypatch.setattr(estimator, '_resolve_part_system_cost',
                        lambda p: pytest.fail('A house allowance must not masquerade as a catalogue item'))
    for raw in parts[1:]:
        priced = estimator.estimate_part(copy.deepcopy(raw))
        assert priced['material_estimate']['unit_material_cost_gbp'] > 0
        assert priced['material_estimate']['extended_material_cost_gbp'] == pytest.approx(
            raw['named_finish_consumable']['allowance_gbp'])
        assert priced['named_finish_consumable']['basis'].startswith('PROVISIONAL')
        assert priced['material_estimate']['price_source']['source_class'] == 'config'
        assert 'Provisional house' in priced['material_estimate']['price_source']['review_reason']
        assert priced['labour_estimate']['total_labour_cost_gbp'] == 0


def test_explicit_material_bill_and_customer_supplied_finishes_do_not_get_another_allowance():
    parent = {'part_number': 'A.45670', 'finish_schedule': schedule(), '_powder_members_coated_m2': 1}
    assert mint_consumables([parent, {'part_number': 'PAINT', 'coating_material_for': 'A.45670'}]) == []
    assert mint_consumables([dict(parent, supplied_by_third_party=True)]) == []


def test_workbook_stated_time_registry_preserves_named_pass_hours_as_an_allowance():
    import wb_populate as wb
    group = {'parts': ['A.45670'], 'engine_ops': ['wet_spray'],
             'run_hours_per_unit': .3,
             'hours_by_part': {'A.45670': {'rh': .3, 'qty_per_unit': 1}}}
    result = wb.stated_row_hours(group, {'A.45670': 'named coat passes'},
                                {'A.45670': {'wet_spray': .3}}, {'A.45670': {'wet_spray'}})
    assert result and result[0] == pytest.approx(.3)
    assert any(m == 'finish_schedule_applied' and ops == ('wet_spray',)
               for m, ops, _ in wb._STATED_SHOP_TIME_MARKERS)
    assert 'finish_schedule_applied' in wb._ALLOWANCE_TIME_MARKERS
