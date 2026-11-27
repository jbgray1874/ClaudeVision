"""Actual pack evidence is delivered privately, not committed to the repository."""
import json
import os
from pathlib import Path
import pytest
from saved_scope_recovery import prepare

@pytest.fixture(scope='module')
def saved():
    p=Path(os.environ.get('HC_SAVED_SCOPE_FIXTURE','private-fixtures/hc_saved_scope.json'))
    if not p.exists():pytest.skip('Private Hotel Chocolat saved evidence is not installed')
    return json.loads(p.read_text(encoding='utf-8'))

def test_real_two_metre_desk_recovers_manufactured_children_without_reading_drawings(saved):
    before=saved['B.33792']
    prepared,audit=prepare(before)
    assert len(prepared['parts'])>40
    assert any('33793' in p['part_number'] for p in prepared['parts'])
    assert len(before['parts'])==5
    assert audit['priced'] is False and 'final_estimate' not in prepared

@pytest.mark.parametrize('ref',['A.33446','A.34225'])
def test_real_box_quantities_reach_every_level(saved,ref):
    prepared,audit=prepare(saved[ref])
    from drawing_reference import compact
    q={compact(k):v for k,v in audit['quantities_per_finished_product'].items()}
    assert q['D33496']==60 and q['D33498']==120
    assert q['C33497']==150 and q['E33488']==120
    assert not any(i.get('code')=='declared_product_not_resolved' for i in audit['issues'])

@pytest.mark.parametrize('ref,height',[('B.34487',750),('B.34490',900),('B.34493',1050)])
def test_real_plinth_blanks_are_component_specific(saved,ref,height):
    aliases={'B.34487':{'10100889':'A.34488'},'B.34490':{'10100890':'A.34491'},
             'B.34493':{'10100892':'A.34494'}}[ref]
    prepared,audit=prepare(saved[ref],identity_aliases=aliases,
        scope_basis='Reviewed GA assembly stock code. Keep the whole plinth root, including ballast; '
                    'join its tower assembly to the separately named assembly sheet.')
    p=[p for p in prepared['parts'] if p.get('component_caption_blank')]
    assert len(p)==3
    sizes={(x['blank_length_mm'],x['blank_width_mm']) for x in p}
    assert sizes=={(height,300),(300,300),(281,281)}
    assert sum(x['quantity'] for x in p)==6

def test_real_shelving_scope_correction_has_an_explicit_basis(saved):
    with pytest.raises(ValueError):prepare(saved['B.34471'],scope='B.34473')
    prepared,audit=prepare(saved['B.34471'],scope='B.34473',
        scope_basis='The product folder is the shelving assembly. B.34471 is its panel; '
                    'nc1-b34473.pdf carries the three-row assembly BOM.')
    assert len(prepared['parts'])>=3
