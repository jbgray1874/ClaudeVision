"""Replay 12110's finished evidence locally. No live pricing, CAD, queue or source writes.

Usage: python tools/audit_12110_remaining_offline.py --record RECORD --drawings PACK --output REPORT
The private record/drawings are deliberately external, never committed as test fixtures.
"""
import argparse
import ast
import contextlib
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import socket
import sys
from unittest.mock import patch

os.environ['SDI_OFFLINE'] = '1'
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))


def board_writer_inputs(pe, summary):
    """Execute the actual row writer without opening Excel or saving a workbook.

    It is a closure inside populate_workbook. Extract its AST unchanged and
    supply only its normal closure values and a cell capture object.
    """
    import wb_populate as wb
    import config
    tree = ast.parse(Path(wb.__file__).read_text(encoding='utf-8'))
    parent = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'populate_workbook')
    writer = next(n for n in parent.body if isinstance(n, ast.FunctionDef) and n.name == '_write_board_row')
    columns = dict(col_desc=3, col_qty=4, col_length=5, col_width=6, col_thick=7,
                   col_sheet_l=8, col_sheet_w=9, col_cost_per_sheet=12)
    flags = []
    ns = dict(vars(wb), config=config, o=columns, flags=flags, summary=summary)
    exec(compile(ast.Module(body=[writer], type_ignores=[]), str(wb.__file__), 'exec'), ns)
    class Cells:
        def __init__(self): self.values = {}
        def cell(self, row, column, value=None):
            if value is not None: self.values[row, column] = value
            class Cell: pass
            c = Cell()
            c.value = self.values.get((row, column))
            return c
    ws = Cells()
    ns['_write_board_row'](ws, 140, pe)
    return {key: ws.values.get((140, col)) for key, col in columns.items()}, flags


def audit(record_path, drawings):
    import bom_pipeline as bp
    import part_identity as pi
    import route_compiler as rc
    import estimator
    import wb_populate as wb
    from costed_facts import other_sheet_parts_per_sheet
    import pymupdf

    raw = Path(record_path).read_bytes()
    record = json.loads(raw.decode('utf-8'))
    assert record['declared_product'] == '12110-01-GA1'
    evidence = {}
    specifications = {
        'fixing_tube': ('12110-02-GA', 6, '12.7mm DIA x 1.2mm WALL'),
        'pin_tube': ('12110-05-GA', 14, '12.7mm DIA x 1.2mm WALL'),
        'backing_panel': ('12110-04-GA', 2, 'BACKING PANEL'),
        'frame': ('12110-02-GA', 3, 'DRESS FRONT FACE'),
        'roof_bom': ('12110-07-GA', 2, '12110-07-05M'),
        'unused_rib_detail': ('12110-07-GA', 8, '12110-07-06M'),
        'top_ga': ('12110-01-GA1', 3, '12110-07-05M'),
    }
    for key, (drawing, page, expected) in specifications.items():
        candidates=[p for p in Path(drawings).glob('*.pdf')
                    if p.stem == drawing or any(p.stem.startswith(drawing+s) for s in (' ', '_'))]
        assert len(candidates)==1, (drawing,'expected one PDF',len(candidates))
        path=candidates[0]
        with pymupdf.open(path) as doc:
            text = ' '.join(doc[page-1].get_text().split())
        assert expected in text, (key, expected)
        if key in ('roof_bom', 'top_ga'):
            assert '12110-07-06M' not in text, key
        evidence[key] = dict(file=path.name, page=page, sha256=hashlib.sha256(path.read_bytes()).hexdigest())

    summary = copy.deepcopy(record)
    parts = copy.deepcopy(record['parts'])
    rows = copy.deepcopy(record['document_analysis']['bom_rows'])
    reset = []
    for row in rows:
        # Undo only the old classifier's invented identity. The original printed
        # description, quantity, owning sheet and model evidence are unchanged.
        if (row.get('identity_source') == 'uncoded_row' and row.get('printed_code') == ''
                and row.get('description') == '12.7mm DIA x 1.2mm WALL 50'):
            reset.append(row['bom_parent'])
            row['part_number'] = ''
            for field in ('identity_source', 'row_role', 'consumed'): row.pop(field, None)
    assert sorted(reset) == ['12110-02-05M', '12110-05-12M']
    pi.mint_uncoded_row_identities(rows)
    bp.apply_stated_cut_list_to_parts(parts, rows)
    summary['manufacturing_writeup']['parts'] = parts
    summary['document_analysis']['bom_rows'] = rows
    # The projection was made by the old classifier; it is not fresh evidence.
    summary['document_analysis']['bay_bom_rows'] = []
    route = rc.compile_route_without_pricing(summary)
    nodes = {n['part_number']: n for n in route['nodes']}
    targets = {'12110-02-201':7, '12110-02-02M':7, '12110-02-03M':14,
               '12110-02-05M':42, '12110-03-01A':4, '12110-05-12M':6, '12110-07-05M':2}
    for pn, qty in targets.items(): assert nodes[pn]['qty_per_unit'] == qty, pn
    assert '12110-07-06M' not in nodes
    decisions = {(d['target_id'],d['operation']):d for d in route['decisions']}
    tubes = {}
    with patch.object(estimator, '_resolve_part_system_cost', return_value={}):
        for p in parts:
            pn = p['part_number']
            if pn not in ('12110-02-05M','12110-05-12M'): continue
            assert p['section_stock']['cut_lengths_mm'] == [50]
            assert p['section_stock']['profile_form'] == 'CHS'
            me = estimator.estimate_material(p)
            assert me['stock_form'] == 'tube' and me['unit_material_cost_gbp'] > 0
            assert me['stock_estimate']['section_length_mm'] == 50
            for op in ('welding','dress_welds'):
                assert decisions[pn,op]['status'] == 'not_applicable'
            tubes[pn] = dict(qty=nodes[pn]['qty_per_unit'], length_mm=50,
                             outside_diameter_mm=12.7, wall_mm=1.2,
                             material_basis=me['cost_method'],
                             offline_config_cost_each_gbp=me['unit_material_cost_gbp'],
                             weld_owner=decisions[pn,'welding']['field_provenance']['weld_owner'])
    for pn in ('12110-02-201','12110-05-201','12110-02-02M'):
        assert decisions[pn,'welding']['status'] == 'required', pn
    assert decisions['12110-02-02M','dress_welds']['status'] == 'required'
    frame_times = {}
    for p in parts:
        if not p.get('weldment_from_own_cut_list'): continue
        if len((p.get('section_stock') or {}).get('cut_lengths_mm') or []) < 2: continue
        times = estimator.estimate_process_times(copy.deepcopy(p), quantity=1)
        frame_times[p['part_number']] = {
            'run_minutes_each': {k:v for k,v in times['run_times_min_per_unit'].items()
                                 if k in ('welding','dress_welds')},
            'basis': 'Existing shop weldment allowance unless the record states joint count or weld length; not measured cycle time'}
    assert frame_times['12110-02-02M']['run_minutes_each']['welding'] == 30
    assert frame_times['12110-02-02M']['run_minutes_each']['dress_welds'] == 20

    estimates=copy.deepcopy(record['estimate_summary']['part_estimates'])
    groups=wb.canonical_labour_groups(summary,estimates,1)
    weld_groups=[g for g in groups.values() if 'weld' in g['wb_op'].lower()]
    assert not any(set(g['parts']) & set(tubes) for g in weld_groups)
    board=next(p for p in estimates if p['part_number']=='12110-04-01J')
    board['quantity']=3  # compiler's declared-product total, not its raw per-parent count
    assert nodes['12110-04-01J']['qty_per_unit']==3
    inputs, flags=board_writer_inputs(board,summary)
    assert [inputs['col_length'],inputs['col_width'],inputs['col_thick']]==[2430,1210,6]
    assert [inputs['col_sheet_l'],inputs['col_sheet_w']]==[3050,1525]
    yield_n=other_sheet_parts_per_sheet(inputs['col_length'],inputs['col_width'],
                                        inputs['col_sheet_l'],inputs['col_sheet_w'])
    assert yield_n==1 and inputs['col_cost_per_sheet']>0
    charged_before={r['operation']:r['dept_rate_gbp_per_hour'] for r in record['final_estimate']['labour_rows']
                    if 'weld' in r['operation'].lower()}
    removal=24*charged_before['Weld (CO2)']+16*charged_before['Dress Welds']
    return dict(record_sha256=hashlib.sha256(raw).hexdigest(), drawings=evidence,
                original_unit_cost_gbp=record['final_estimate']['totals']['unit_gbp'],
                quantities=targets, tubes=tubes, board_writer_inputs=inputs,
                board_parts_per_sheet=yield_n, board_flags=flags,
                removed_tube_weld_hours=24, removed_tube_dress_hours=16,
                removed_tube_labour_gbp=round(removal,2),
                route_groups_using_saved_other_part_times=weld_groups,
                corrected_frame_timing_replay=frame_times,
                central_rib=dict(required='12110-07-05M',qty=2,
                                 detail_only='12110-07-06M', charged=False),
                limitations=['Offline config tube rate is not a newly verified catalogue quote.',
                             'No Excel recalculation or new complete estimate was produced.',
                             'Remaining weld durations still need shop review: a weld symbol is not a joint count.',
                             'The larger MDF sheet is a configured stock allowance, not confirmed supplier availability.'])


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--record',type=Path,required=True)
    ap.add_argument('--drawings',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args()
    if args.output.resolve() == args.record.resolve(): ap.error('output must not overwrite the source record')
    def no_network(*a,**kw): raise AssertionError('Offline replay attempted network access')
    with patch.object(socket.socket,'connect',no_network), contextlib.redirect_stdout(io.StringIO()):
        result=audit(args.record,args.drawings)
    args.output.write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
    print('PASS: actual record, drawing pages, target quantities, tube stock, weld ownership and board writer inputs')
    print('Report:',args.output)
    print('Not a corrected approved estimate. No queue, publish, CAD or source writes.')

if __name__=='__main__': main()
