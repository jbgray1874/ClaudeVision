import copy
from component_caption_blanks import repair

def _summary():
    names=['PLINTH TOWER 1050mm HIGH SIDE PANEL','PLINTH TOWER X 1050mm HIGH TOP PANEL',
           'PLINTH TOWER X 1050mm HIGH BASE PANEL']
    return {'pages':[{'page_number':2,'source_pdf_name':'detail.pdf','normalized_text':
        '\n'.join(['1050','300',names[0],'MATERIAL:18mm FR B MDF 3050 X 1220mm',
                   '18','18','300','300',names[1],'MATERIAL:18mm FR B MDF 3050 X 1220mm',
                   '18','18','281','281',names[2]])}],
        'manufacturing_writeup':{'parts':[{'part_number':str(i),'description':n,'pages':[2],
            'quantity':q,'blank_length_mm':3050,'blank_width_mm':1220}
            for i,(n,q) in enumerate(zip(names,[4,1,1]))]}}

def test_separate_side_top_base_blanks_preserve_the_good_quantities():
    s=_summary()
    assert len(repair(s))==3
    p=s['manufacturing_writeup']['parts']
    assert [(x['blank_length_mm'],x['blank_width_mm'],x['quantity']) for x in p]==[
        (1050,300,4),(300,300,1),(281,281,1)]
    before=copy.deepcopy(s)
    assert repair(s)==[] and s==before

def test_a_caption_on_another_parts_page_cannot_supply_a_blank():
    s=_summary()
    for p in s['manufacturing_writeup']['parts']:p['pages']=[5]
    assert repair(s)==[]

def test_measured_dxf_and_confirmed_sizes_are_preserved():
    s=_summary()
    for p in s['manufacturing_writeup']['parts']:
        p['normalized_geometry']={'geometry_source':'dxf'}
    assert repair(s)==[]


def test_reading_order_of_rotated_dimensions_uses_the_independent_text_reader():
    s=_summary()
    pg=s['pages'][0]
    pg['pypdf_text']=pg['normalized_text']
    pg['normalized_text']=pg['normalized_text'].replace('1050\n','0501 ').replace('\n',' ')
    pg['pdfplumber_text']=pg['normalized_text']
    assert len(repair(s))==3
    assert s['manufacturing_writeup']['parts'][0]['blank_length_mm']==1050


def test_missing_page_membership_can_use_a_unique_exact_caption_but_not_two_copies():
    s=_summary()
    for p in s['manufacturing_writeup']['parts']:p['pages']=[]
    assert len(repair(s))==3
    s=_summary()
    for p in s['manufacturing_writeup']['parts']:p['pages']=[]
    s['pages'].append(dict(s['pages'][0],page_number=3))
    assert repair(s)==[]


def test_replay_restores_component_axes_if_an_earlier_pass_reintroduces_the_stock_envelope():
    s=_summary();repair(s)
    p=s['manufacturing_writeup']['parts'][0]
    p['blank_length_mm']=3050;p['blank_width_mm']=1220
    assert repair(s)==['0']
    assert (p['blank_length_mm'],p['blank_width_mm'])==(1050,300)
    assert p['component_caption_blank']['replaced']=={'blank_length_mm':3050,'blank_width_mm':1220}
