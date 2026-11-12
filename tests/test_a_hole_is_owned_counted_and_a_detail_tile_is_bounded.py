"""Generic deliberate-loss cases; no customer part dimensions or IDs are hard-coded."""
import copy
from pathlib import Path
import sys
import unittest
import ast
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from detail_evidence import hole_row_coverage, profile_extent, purchase_basis, weld_run_coverage
from normal_pdf_audit import evaluate
from page_detail import plan


class EvidenceTests(unittest.TestCase):
    def test_writer_hole_metadata_blocks(self):
        # Execute the added writer statements themselves, not a second implementation.
        path=Path(__file__).resolve().parents[1]/'src'/'wb_populate.py'
        tree=ast.parse(path.read_text(encoding='utf-8-sig'))
        blocks=[]
        for node in ast.walk(tree):
            if isinstance(node,ast.If) and isinstance(node.test,ast.Call):continue
            if isinstance(node,ast.If) and any(isinstance(x,ast.Constant)
                and x.value=='holes_cut_by_part' for x in ast.walk(node)):
                if ast.unparse(node.test).startswith('isinstance(_hc,'):
                    blocks.append(node)
        self.assertEqual(len(blocks),2)
        for block in blocks:
            env=dict(_hc=1,group={},g={},representative_id='A',_pn='A',qty=2,_qty_pu=2)
            exec(compile(ast.Module(body=[block],type_ignores=[]),str(path),'exec'),env)
            result=env['group'] or env['g']
            self.assertEqual(result['holes_cut_by_part'],{'A':2})
            self.assertEqual(result['holes_cut_basis'],'per_finished_product')

    def test_live_shadow_hook_precedes_invariants(self):
        text=(Path(__file__).resolve().parents[1]/'src'/'main.py').read_text(encoding='utf-8-sig')
        start=text.index('from normal_pdf_audit import record')
        self.assertIn('_normal_pdf_record(_target, xlsx_path)',text[start:start+300])
        self.assertGreater(text.index('_inv = _check_job(_target)',start),start)

    def test_holes_basis(self):
        row={'holes_cut_basis':'per_finished_product','holes_cut_by_part':{'A':2}}
        self.assertIsNone(hole_row_coverage([row],'A',1,2))
        for rows in ([],[{'holes_cut':2}],[dict(row,holes_cut_basis='per_order')],
                     [dict(row,holes_cut_by_part={'B':2})],[row,row]):
            with self.subTest(rows=rows):
                self.assertIsNotNone(hole_row_coverage(rows,'A',1,2))
        self.assertIsNotNone(hole_row_coverage([row],'A',2,2))

    def test_profile_base_not_envelope(self):
        base=dict(part='P',document='d.pdf',page=2,source_region=[0,0,1,1],
                  length_mm=80,width_mm=20,role='base_dimension')
        self.assertFalse(profile_extent([base],'P')['verified'])
        extent=dict(base,role='overall_profile',width_mm=42)
        result=profile_extent([base,extent],'P')
        self.assertTrue(result['verified'])
        self.assertFalse(result['contour_verified'])
        self.assertFalse(result['holes_verified'])
        self.assertFalse(profile_extent([extent,dict(extent,width_mm=43)],'P')['verified'])

    def test_purchase_units(self):
        e=dict(article='CAP-X',source='supplier quotation',observed_at='2026-10-24',
               price_gbp=20,pieces_per_purchase_unit=100)
        self.assertEqual(purchase_basis('CAP-X',e)['piece_price_gbp'],.2)
        for key in e:
            broken=dict(e);del broken[key]
            self.assertFalse(purchase_basis('CAP-X',broken)['verified'])
        self.assertFalse(purchase_basis('CAP-Y',e)['verified'])

    def test_joint_sides_not_piece_count(self):
        req=[dict(id=f'J1-{side}',joint_id='J1',side=side,document='d',page=1,process='TIG')
             for side in ('left','right')]
        row=dict(joint_run_ids=['J1-left','J1-right'],process='TIG',rate_source='approved card',
                 rate_gbp_h=40,saved_cells_verified=True)
        self.assertEqual(weld_run_coverage(req,[row]),[])
        self.assertTrue(weld_run_coverage([], [row]))
        self.assertTrue(weld_run_coverage(req,[row,row]))
        for k in ('rate_source','saved_cells_verified','joint_run_ids'):
            bad=dict(row);del bad[k]
            self.assertTrue(weld_run_coverage(req,[bad]))

    def test_shadow_real_shape_and_mutations(self):
        s={'llm_full_extract':{'raw_response':'read','bom':[
            dict(part_number='A',qty=2,document='a.pdf',page=1)]},
           'estimate_summary':{'canonical_part_estimates':[dict(part_number='A',quantity=2)]},
           'final_estimate':{'material_rows':[
            dict(part_code='A',charged_cell='Estimate!M11',total_value_gbp=5)]},
           'verified_charge_bases':{'Estimate!M11':True}}
        snap={'cells':{'Estimate!M11':5}}
        self.assertTrue(evaluate(s,snap)['passed'])
        for mode in ('part','quantity','charge','source','basis','cached'):
            b=copy.deepcopy(s);c=copy.deepcopy(snap)
            if mode=='part':b['estimate_summary']['canonical_part_estimates']=[]
            if mode=='quantity':b['estimate_summary']['canonical_part_estimates'][0]['quantity']=4
            if mode=='charge':b['final_estimate']['material_rows']=[]
            if mode=='source':b['llm_full_extract']['bom'][0]['page']=None
            if mode=='basis':b['verified_charge_bases']={}
            if mode=='cached':c['cells']['Estimate!M11']=0
            with self.subTest(mode=mode):self.assertFalse(evaluate(b,c)['passed'])

    def test_tile_coverage_bounds(self):
        tiles=plan(2384,1684)
        self.assertTrue(len(tiles)>1)
        self.assertTrue(all(t['width']<=1800 and t['height']<=1800 for t in tiles))
        self.assertEqual(min(t['x'] for t in tiles),0)
        with self.assertRaises(ValueError):plan(2384,1684,max_tiles=1)
        with self.assertRaises(ValueError):plan(100,100,overlap_px=1800)


if __name__=='__main__':unittest.main()
