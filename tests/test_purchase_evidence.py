import copy
import pytest
import purchase_evidence as pe

BASE='50009-02-01X'
HAND=BASE+'-HANDED'
DESC='LED STRIP + END CAPS - EXAMPLE LIGHTING - PART-006 LED STRIP'


def parts():
    return [{'part_number': BASE, 'description': 'LED SET UP', 'is_bought_in': True, 'quantity': 6},
            {'part_number': HAND, 'description': DESC, 'is_bought_in': True, 'quantity': 6}]


def test_exact_bom_reference_reaches_each_purchase_without_merging_or_copying_price():
    p=parts()
    assert pe.stamp_bom_purchase_references(p,[{'part_number': x['part_number'], 'description': DESC}
                                               for x in p]) == 2
    assert [x['quantity'] for x in p] == [6,6]
    assert [x['part_number'] for x in p] == [BASE,HAND]
    assert all(pe.lookup_codes(x)==['PART-006'] for x in p)
    assert p[0]['description']=='LED SET UP'
    assert all(x['price_chain_description']==DESC for x in p)


def test_base_reference_is_not_inherited_by_hand():
    p=parts()
    pe.stamp_bom_purchase_references(p,[{'part_number': BASE, 'description': DESC}])
    assert pe.lookup_codes(p[0])==['PART-006']
    assert pe.lookup_codes(p[1])==[]


def test_conflicting_articles_do_not_choose_first():
    p=parts()
    pe.stamp_bom_purchase_references(p,[{'part_number':BASE,'description':d}
                                        for d in (DESC,DESC.replace('006','007'))])
    assert pe.lookup_codes(p[0])==[]
    assert 'Conflicting' in p[0]['review_flags'][0]


def test_later_conflict_does_not_keep_an_earlier_catalogue_alias():
    p=parts()
    pe.stamp_bom_purchase_references(p,[{'part_number':BASE,'description':DESC}])
    assert pe.lookup_codes(p[0])==['PART-006']
    pe.stamp_bom_purchase_references(p,[{'part_number':BASE,'description':d}
                                      for d in (DESC,DESC.replace('006','007'))])
    assert pe.lookup_codes(p[0])==[]
    assert 'price_chain_description' not in p[0]


def test_missing_bom_evidence_does_not_keep_stale_exact_alias():
    p=parts()
    pe.stamp_bom_purchase_references(p,[{'part_number':BASE,'description':DESC}])
    p[0]['price_chain_description']='independent size correction'
    pe.stamp_bom_purchase_references(p,[])
    assert pe.lookup_codes(p[0])==[]
    assert p[0]['price_chain_description']=='independent size correction'


def test_missing_purchase_survives_a_null_flags_field():
    p=parts()[0]
    p['review_flags']=None
    assert pe.mark_missing_purchase(p,0)
    assert p['review_flags'] and p['manufacturing_questions']


@pytest.mark.parametrize('description',['Dock PSU - GUESS','Charging Module x 16 Devices',
    'LED STRIP', 'LED - SUPPLIER - 750mm', 'LED - SUPPLIER - PART-006 GUESS'])
def test_no_catalogue_identity_invented(description):
    assert pe.catalogue_reference(description) is None


def test_existing_size_reading_is_not_replaced():
    p=parts();p[0]['price_chain_description']='a deliberately corrected size'
    pe.stamp_bom_purchase_references(p,[{'part_number': BASE, 'description': DESC}])
    assert pe.lookup_codes(p[0])==[]
    assert p[0]['price_chain_description']=='a deliberately corrected size'


@pytest.mark.parametrize('price',[None,0,-1,float('nan'),float('inf')])
def test_raw_material_or_handling_cannot_hide_missing_purchase(price):
    p=parts()[0];p['unit_total_cost_gbp']=.53
    assert pe.mark_missing_purchase(p,price)
    assert p['purchase_price_missing'] and p['manufacturing_questions']
    assert p['unit_total_cost_gbp']==.53  # reports, not fabricated replacement money
    before=copy.deepcopy(p)
    pe.mark_missing_purchase(p,price)
    assert p==before


def test_real_positive_purchase_needs_no_missing_price_ruling():
    p=parts()[0]
    assert not pe.mark_missing_purchase(p,8.0)
    assert 'purchase_price_missing' not in p


def test_resolver_asks_exact_supplier_code_after_internal_code(monkeypatch):
    import estimator as e
    p=parts()[0]
    pe.stamp_bom_purchase_references([p],[{'part_number':BASE,'description':DESC}])
    seen=[]
    def price(req):
        seen.append((req.part_code,req.description))
        return {'selected':{'price':8.5,'source':'supplier_catalogue','uom':'each'}} if req.part_code=='PART-006' else {}
    monkeypatch.setattr(e,'get_best_price',price)
    result=e._resolve_part_system_cost(p)
    assert result['applied_unit_cost']==8.5
    assert result['matched_part_code']=='PART-006'
    assert seen[0][0]==BASE and seen[-1]==('PART-006',DESC)
