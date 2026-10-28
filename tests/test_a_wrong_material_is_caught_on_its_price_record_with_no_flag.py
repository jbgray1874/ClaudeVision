"""A wrong material is caught on its price record, with or without a flag (D-598p).

9287-10-GA, 24 Oct 2026: D-598o's guard caught a named material priced as another only
where the pricing step stamped the swap. The price record itself names the material it
priced, so a swap that leaves no stamp is caught too, and the covering note's section 9
lists every recorded blocking finding the opening panel points at.
"""
import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from owned_specification import priced_as_issues


def record(actual='MDF'):
    p={'part_number':'P-1','normalized_material':'ACRYLIC',
       'owned_material_evidence':{'value':'ACRYLIC','page':1}}
    s={'manufacturing_writeup':{'parts':[p]},
       'estimate_summary':{'part_estimates':[{'part_number':'P-1',
            'normalized_material':'ACRYLIC','material_estimate':{'material':actual}}]},
       'final_estimate':{'material_rows':[{'description':'P-1 PANEL',
            'block':'other_sheet','charged_cell':'Estimate!M139','total_value_gbp':10}]}}
    return s,p


class Tests(unittest.TestCase):
    def test_same_block_wrong_material_without_flag_is_caught(self):
        s,p=record(); findings=priced_as_issues(s,[p])
        self.assertEqual(len(findings),1)
        self.assertIn('actual material estimate prices MDF',findings[0])
        self.assertIn('Estimate!M139',findings[0])

    def test_matching_material_passes(self):
        s,p=record('ACRYLIC');self.assertEqual(priced_as_issues(s,[p]),[])

    def test_case_and_underscore_convention_unchanged(self):
        s,p=record('mild steel');p['normalized_material']='MILD_STEEL'
        self.assertEqual(priced_as_issues(s,[p]),[])

    def test_stamp_and_payload_are_one_finding(self):
        s,p=record();s['estimate_summary']['part_estimates'][0]['material_priced_as']={'priced_material':'MDF'}
        self.assertEqual(len(priced_as_issues(s,[p])),1)

    def test_stale_stamp_still_caught_when_payload_matches(self):
        s,p=record('ACRYLIC');p['material_priced_as']={'priced_material':'MDF'}
        self.assertEqual(len(priced_as_issues(s,[p])),1)

    def test_costed_payload_precedes_raw_payload(self):
        s,p=record();p['material_estimate']={'material':'ACRYLIC'}
        self.assertTrue(priced_as_issues(s,[p]))

    def test_raw_payload_fallback(self):
        s,p=record();p['material_estimate']={'material':'MDF'}
        s['estimate_summary']['part_estimates']=[]
        self.assertTrue(priced_as_issues(s,[p]))

    def test_missing_payload_is_not_invented_material(self):
        s,p=record(None);self.assertEqual(priced_as_issues(s,[p]),[])

    def test_scope_stays_drawing_office_material(self):
        s,p=record();p.pop('owned_material_evidence')
        self.assertEqual(priced_as_issues(s,[p]),[])

    def test_another_parts_cell_not_claimed(self):
        s,p=record();s['final_estimate']['material_rows'][0]['description']='P-10 PANEL'
        finding=priced_as_issues(s,[p])[0]
        self.assertNotIn('M139',finding)
        self.assertIn('No matching',finding)

    def test_part_code_locator(self):
        s,p=record();row=s['final_estimate']['material_rows'][0]
        row['description']='Panel';row['part_code']='P-1'
        self.assertIn('M139',priced_as_issues(s,[p])[0])

    def test_the_estimators_own_family_name_is_not_a_substitute(self):
        s,p=record('MDF');p['normalized_material']='MR MDF'
        s['estimate_summary']['part_estimates'][0]['normalized_material']='MDF'
        self.assertEqual(priced_as_issues(s,[p]),[])

    def test_input_unchanged(self):
        s,p=record();before=copy.deepcopy(s);priced_as_issues(s,[p]);self.assertEqual(s,before)

    def test_real_invariant_and_release_and_email(self):
        from invariants import check_owned_specifications_survive
        from costed_facts import costed_job
        from estimate_explained import release_section_html
        s,p=record();v=check_owned_specifications_survive(s)
        self.assertEqual(len(v),1);self.assertEqual(v[0]['severity'],'blocking')
        s['invariants']={'verified':True,'checks_run':['check_owned_specifications_survive'],'violations':v}
        job=costed_job(s)
        self.assertTrue(job['release']['draft'])
        self.assertGreater(job['release']['blocking_checks'],0)
        html=release_section_html(job,s)
        self.assertIn('actual material estimate prices MDF',html)
        self.assertIn('Estimate!M139',html)

    def test_email_deduplicates_and_escapes(self):
        from estimate_explained import release_section_html
        v={'severity':'blocking','message':'P-1 <bad> & wrong'}
        s={'invariants':{'violations':[v,v,{'severity':'warning','message':'not blocking'}]}}
        r={'release':{'draft':True,'status':'provisional','reasons':['1 check']}}
        h=release_section_html(r,s)
        self.assertEqual(h.count('P-1 &lt;bad&gt; &amp; wrong'),1)
        self.assertNotIn('not blocking',h)

    def test_empty_email_findings_add_no_heading(self):
        from estimate_explained import release_section_html
        self.assertNotIn('Recorded blocking findings',release_section_html({'release':{}},{}))


if __name__=='__main__':unittest.main()
