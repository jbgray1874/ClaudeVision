"""Offline regressions: no pricing service, CAD, Excel, job submission or saved book edit."""
import copy
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import openpyxl
from openpyxl.styles import PatternFill
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.formula import ArrayFormula
from openpyxl.workbook.defined_name import DefinedName
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
os.environ.setdefault('SDI_OFFLINE', '1')
import estimator as E
import wb_populate as W
from workbook_labour_capacity import ensure_labour_capacity, shifted_formula


def book(cap=100):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Estimate'
    first, last = 151, 222
    ws.cell(first-1, 3, 'Operation')
    for col, label in ((4,'Description'), (6,'Part numbers'), (7,'Department'),
                       (8,'Qty Per Unit'), (9,'Rate Per Hour'), (10,'Total Hours'),
                       (11,'Labour Cost'), (12,'Setup Minutes'), (13,'Total Value')):
        ws.cell(first-1, col, label)
    for r in range(first, last+1):
        ws.cell(r, 10, f'=(H{r}/I{r})*$D$6+L{r}/60')
        ws.cell(r, 11, f'=VLOOKUP(C{r},$C$230:$M$250,9,FALSE)')
        ws.cell(r, 13, f'=J{r}*K{r}')
        ws.merge_cells(start_row=r, start_column=4, end_row=r, end_column=5)
        ws.row_dimensions[r].height = 30
        ws.cell(r, 3).fill = PatternFill('solid', fgColor='DDEEAA')
    ws['C223'] = 'Total Labour Cost'
    ws['M223'] = '=SUM(M151:M222)'
    ws['M225'] = '=(M147+M223)/(1-M227)/0.92'
    ws['M227'] = 0.018
    ws['D6'] = 1
    ws['M147'] = 1127.81
    ws['C230'] = 'Department rates'
    ws.merge_cells('C230:F230')
    ws.print_area = 'A1:M260'
    ws.add_data_validation(DataValidation(type='list', formula1='"one,two"', sqref='C151:C222'))
    ws.add_data_validation(DataValidation(type='list', formula1='$H$235:$H$266', sqref='D151:D222'))
    other = wb.create_sheet('Labour')
    for i in range(1, cap+1):
        other.cell(i, 1, f'=Estimate!G{first+i-1}')
        other.cell(i, 2, f'=Estimate!J{first+i-1}')
    other['C2'] = ArrayFormula('C2', f'=SUM(IF($A$1:$B${cap}=0,0,1))')
    other['F1'] = '=Estimate!$M$225'
    other['F2'] = '=SUM(Estimate!$J$151:$J$222)'
    other['F3'] = '=M225'  # local to Labour, not Estimate
    other['F4'] = '="Estimate!M225"'  # text is not a cell reference
    other['F5'] = "='[External.xlsx]Estimate'!M225"
    wb.defined_names.add(DefinedName('UnitPrice', attr_text="'Estimate'!$M$225"))
    cm = copy.deepcopy(W.CELL_MAP)
    cm['labour'].update(first_row=first, last_row=last)
    return wb, cm


def test_all_98_groups_fit_and_totals_follow_the_new_rows(tmp_path):
    wb, cm = book()
    flags = []
    assert ensure_labour_capacity(wb, cm, 98, flags) == 26
    ws = wb['Estimate']
    assert cm['labour']['last_row'] == 248
    assert ws['C249'].value == 'Total Labour Cost'
    assert ws['M249'].value == '=SUM(M151:M248)'
    assert ws['M251'].value == '=(M147+M249)/(1-M253)/0.92'
    assert ws['M253'].value == 0.018
    assert ws['C256'].value == 'Department rates'
    assert ws['K248'].value == '=VLOOKUP(C248,$C$256:$M$276,9,FALSE)'
    assert ws['M248'].value == '=J248*K248'
    assert wb['Labour']['F1'].value == '=Estimate!$M$251'
    assert wb['Labour']['F2'].value == '=SUM(Estimate!$J$151:$J$248)'
    assert wb['Labour']['F3'].value == '=M225'
    assert wb['Labour']['F4'].value == '="Estimate!M225"'
    assert wb['Labour']['F5'].value == "='[External.xlsx]Estimate'!M225"
    assert wb.defined_names['UnitPrice'].attr_text == "'Estimate'!$M$251"
    assert str(ws.data_validations.dataValidation[0].sqref) == 'C151:C248'
    assert ws.data_validations.dataValidation[1].formula1 == '$H$261:$H$292'
    assert str(ws.print_area) == "'Estimate'!$A$1:$M$286"
    assert 'D248:E248' in {str(x) for x in ws.merged_cells.ranges}
    assert 'C256:F256' in {str(x) for x in ws.merged_cells.ranges}
    assert ws.row_dimensions[248].height == 30
    assert ws['C248'].fill.fgColor.rgb == ws['C222'].fill.fgColor.rgb
    W.repair_labour_sheet_references(wb, cm, flags)
    assert W.labour_sheet_coverage(wb, cm)['ok']
    assert wb['Labour']['A98'].value == '=Estimate!G248'
    assert wb['Labour']['B98'].value == '=Estimate!J248'
    assert wb['Labour']['A99'].value is None
    # Saving only a disposable synthetic test book verifies native XML integrity.
    path = tmp_path/'capacity.xlsx'
    wb.save(path)
    reopened = openpyxl.load_workbook(path)
    assert reopened['Estimate']['M249'].value == '=SUM(M151:M248)'
    assert reopened['Labour']['C2'].value.text == wb['Labour']['C2'].value.text


def test_growth_is_idempotent_and_a_small_job_changes_nothing():
    wb, cm = book()
    assert ensure_labour_capacity(wb, cm, 60) == 0
    assert wb['Estimate']['M225'].value == '=(M147+M223)/(1-M227)/0.92'
    assert ensure_labour_capacity(wb, cm, 98) == 26
    assert ensure_labour_capacity(wb, cm, 98) == 0
    assert wb['Estimate']['M251'].value == '=(M147+M249)/(1-M253)/0.92'


def test_known_department_scan_can_expand_but_unknown_layout_is_not_mutated():
    wb, cm = book(cap=90)
    assert ensure_labour_capacity(wb, cm, 98) == 26
    assert '$A$1:$B$98' in wb['Labour']['C2'].value.text
    wb, cm = book(cap=90)
    wb['Estimate']['C223'] = 'Unknown'
    with pytest.raises(ValueError, match='unrecognised'):
        ensure_labour_capacity(wb, cm, 98)
    assert cm['labour']['last_row'] == 222


@pytest.mark.parametrize('description,mass,qty', [
    ('LH Drainage hole pipe', 3, 2), ('Bend tube', 0.4, 8), ('RH Drainage hole pipe', 3, 2)])
def test_pipe_material_is_a_numeric_disclosed_allowance_not_an_empty_sheet_row(monkeypatch, description, mass, qty):
    monkeypatch.setattr(E.config, 'SECTION_STOCK_PRICE_GBP_PER_KG', 7.29)
    p = {'part_number': 'PART', 'description': description, 'weights': [f'{mass}kg'],
         'normalized_material': 'MILD STEEL', 'quantity': qty,
         'blank_length_mm': 1836, 'blank_width_mm': 40}
    before = copy.deepcopy(p)
    me = E.section_weight_allowance(p, 'MILD STEEL', qty)
    assert me['cost_per_part_gbp'] == pytest.approx(mass*7.29*1.04, abs=0.00005)
    assert me['extended_material_cost_gbp'] == pytest.approx(me['cost_per_part_gbp']*qty, abs=0.00005)
    assert me['requires_flat_blank'] is False and me['stock_form'] == 'stated_weight'
    assert me['material_allowance']['provisional'] is True
    assert me['price_source']['source_class'] == 'config'
    assert me['price_source']['price_class'] != 'unpriced'
    assert me['price_source']['unit'] == 'gbp_per_kg'
    assert not E.price_provenance.price_firmness(me['price_source'])['firm']
    assert 'own printed piece weight' in p['review_flags'][0]
    assert not p.get('normalized_thickness_mm')
    assert p['quantity'] == before['quantity']
    assert p.get('stock_form') == before.get('stock_form')  # no change to manufacturing route
    pe = dict(p, material_estimate=me)
    assert W._bom_line_price(pe) == me['cost_per_part_gbp']
    assert W.waste_already_in_price(pe)  # cut loss was already charged once
    assert 'PROVISIONAL PIPE STOCK ALLOWANCE' in W.section_words_on_line(description, me)


@pytest.mark.parametrize('change', [
    {'description':'Tube clamp'}, {'description':'Shelf panel'}, {'weights':[]},
    {'is_assembly_parent':True}, {'is_bought_in':True},
    {'section_stock':{'a':20,'b':20,'t':1.2,'length_mm':600}}])
def test_allowance_does_not_replace_a_complete_section_or_other_scope(change):
    p = {'description':'Bend tube', 'weights':['0.4kg'], **change}
    assert E.section_weight_allowance(p, 'MILD STEEL', 1) is None


def actual():
    path = os.environ.get('SDI_12517_COST_FIXTURE')
    if not path:
        pytest.skip('Private saved-run fixture not supplied; not a pack proof.')
    return json.loads(Path(path).read_text(encoding='utf-8'))


@pytest.mark.parametrize('order_qty', [1, 2, 3])
def test_actual_12517_98_groups_fit_with_every_decision_and_quantity_retained(monkeypatch, order_qty):
    s = actual()
    pes = s['estimate_summary']['canonical_part_estimates']
    before = [(p['part_number'], p.get('quantity')) for p in pes]
    expected = {'12517-05-05A':36, '12517-07-05A':60, '12517-12-01M':164,
                '12517-12-02M':44, '12517-04-05M':12, '12517-06-03M':20}
    quantities = dict(before)
    assert {pn: quantities[pn] for pn in expected} == expected
    groups = W.canonical_labour_groups(s, pes, order_qty)
    assert len(groups) == 98
    wb, cm = book()
    ensure_labour_capacity(wb, cm, len(groups))
    assert len(groups) == cm['labour']['last_row'] - cm['labour']['first_row'] + 1
    assert before == [(p['part_number'], p.get('quantity')) for p in pes]
    targets = {(g['wb_op'], pn) for g in groups.values() for pn in g.get('parts', [])}
    for pn in ('12517-15-01M','12517-15-02M','12517-15-04M','12517-15-05M'):
        assert ('Laser (Metal)', pn) in targets
    assert ('Fold', '12517-15-04M') in targets
    # Resizing is not a merger of operations/setups and creates no duplicate decisions.
    ids = [i for g in groups.values() for i in g.get('decision_ids', [])]
    assert len(ids) == len(set(ids))
    required = {d['decision_id'] for d in s['estimate_summary']['canonical_route_shadow']['decisions']
                if d.get('status') == 'required'}
    assert set(ids) == required
    # Simulated calculated cells, not a re-estimate: prove the production adapter
    # reads every expanded row and preserves its identity, not just its total.
    ws = wb['Estimate']
    for row, g in enumerate(groups.values(), start=151):
        ws.cell(row, 3, g['wb_op'])
        ws.cell(row, 6, ', '.join(g.get('parts', [])))
        ws.cell(row, 8, g['qty'])
        ws.cell(row, 10, 1)
        ws.cell(row, 11, 1)
        ws.cell(row, 13, 1)
    class Sheet:
        def Cells(self, row, col):
            return SimpleNamespace(Value=ws.cell(row, col).value)
    monkeypatch.setattr(W, 'CELL_MAP', cm)
    from wep_readback_from_xlsx import read_final_rows
    priced = read_final_rows(Sheet(), 13)['labour_rows']
    assert len(priced) == 98
    assert {x['workbook_row'] for x in priced} == set(range(151, 249))


def test_actual_12517_all_three_pipe_weights_price_without_invented_gauges():
    s = actual()
    pipes = {'12517-01-01M': (3,2), '12517-01-05M':(.4,8), '12517-01-10M':(3,2)}
    pes = s['estimate_summary']['canonical_part_estimates']
    for p in s['manufacturing_writeup']['parts']:
        if p['part_number'] not in pipes:
            continue
        mass, qty = pipes[p['part_number']]
        me = E.section_weight_allowance(p, p['normalized_material'], qty)
        assert me and me['unit_material_mass_kg'] == mass
        assert me['cost_per_part_gbp'] > 0
        pe = next(x for x in pes if x['part_number'] == p['part_number'])
        assert pe['quantity'] == qty
        assert not p.get('normalized_thickness_mm')


def test_production_writer_expands_before_rendering_and_calls_the_material_fallback():
    # Wiring checks complement arithmetic/fixture tests: a correct orphan helper
    # cannot fix a production estimate. The existing integration stays canonical.
    import inspect
    writer = inspect.getsource(W.populate_workbook)
    assert writer.index('grow_labour_block(wb, cm, len(_groups), flags)') < writer.index(
        'for _key in sorted(_groups.keys(), key=_group_order):')
    assert 'ensure_labour_capacity(wb, cm, required, flags)' in inspect.getsource(W.grow_labour_block)
    assert 'section_weight_allowance(part, material, quantity)' in inspect.getsource(E.estimate_material)
