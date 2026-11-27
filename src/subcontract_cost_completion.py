"""Connect missing subcontract finish and round-trip costs to evidenced allowances.

No prices, customers or drawing references are embedded. Confirmed prices win.
Only missing money is completed, through the existing injected research seam;
an unavailable answer remains an explicit gap, never a fabricated quotation.
"""
from math import isfinite
import re


def _number(value):
    try:
        n=float(value)
        return n if isfinite(n) and n>0 else None
    except (ValueError,TypeError):return None


def _research(line, order_qty, ask, as_of):
    from indicative_price import research_brief, resolve_indicative
    brief=research_brief(line,order_qty=order_qty)
    try:found=dict(ask(brief) or {})
    except Exception as exc:return {'missing':f'Research unavailable: {exc}'}
    unit=re.sub(r'[\s_/-]+','',str(found.get('unit') or '').lower()).removeprefix('per')
    chosen=dict(line)
    if brief['kind']=='subcontract_process':
        expected=set(re.findall(r'\b(?:ZINC|CHROME|NICKEL|BRASS|COPPER|GOLD|SILVER)\b',str(line.get('finish_spec') or '').upper()))
        answered=set(re.findall(r'\b(?:ZINC|CHROME|NICKEL|BRASS|COPPER|GOLD|SILVER)\b',str(found.get('item_priced') or '').upper()))
        if expected and answered and expected.isdisjoint(answered):
            return {'missing':'The researched process names a different plating family from the drawing; do not charge that rate as the specified finish.'}
        if unit in ('kg','kilogram','kilograms') and _number(line.get('mass_kg')):
            chosen.pop('coated_area_m2',None)
        elif unit in ('m2','m²','sqm','squaremetre','squaremetres') and _number(line.get('coated_area_m2')):
            chosen.pop('mass_kg',None)
        else:
            return {'missing':'Subcontract rate needs a matching measured kg or m2 basis; the returned unit does not match.'}
    else:
        if unit in ('leg','journey','oneway') or (unit in ('order','consignment') and re.search(r'(?i)one[- ]way|each[- ]way|per leg',str(found.get('quantity_basis') or ''))):
            if not _number(found.get('price_gbp')):return {'missing':'No usable per-leg transport rate.'}
            found=dict(found,price_gbp=float(found['price_gbp'])*2,unit='order',
                       quantity_basis=str(found.get('quantity_basis') or '')+'; two legs allowed: outward plus return')
        elif unit not in ('order','consignment','roundtrip'):
            return {'missing':'Plater freight needs a whole-order round-trip rate, or an explicit per-leg rate for two legs.'}
    # A minimum is a floor, not a second setup fee added to the running charge.
    minimum=_number(found.get('minimum_gbp'))
    answer=dict(found);answer.pop('minimum_gbp',None)
    result=resolve_indicative(chosen,order_qty=order_qty,as_of=as_of,ask=lambda _:answer)
    price=_number(result.get('price_gbp'))
    if price and minimum and brief['kind']=='subcontract_process':
        result['running_unit_gbp']=price
        price=max(price,minimum/order_qty)
        result['price_gbp']=round(price,4)
        result['calculation']['working']+=f'; order minimum GBP {minimum:g} is a floor, spread over {order_qty} finished units'
        result['order_minimum_gbp']=minimum
    return result


def _apply(pe,result,method):
    price=_number(result.get('price_gbp'))
    if not price:return False
    quantity=_number(pe.get('quantity')) or 1
    material=pe.setdefault('material_estimate',{})
    old=_number(material.get('unit_material_cost_gbp')) or 0
    old_unit=_number(pe.get('unit_total_cost_gbp')) or 0
    labour=max(0,old_unit-old)
    ext=round(price*quantity,4)
    evidence=result.get('evidence') or {}
    basis=('PROVISIONAL subcontract allowance, NOT a supplier quotation. '+
           (result.get('calculation') or {}).get('working','')+
           f". Source: {evidence.get('source','not recorded')}; date {evidence.get('as_of','not recorded')}. Confirm scope, specification and rate.")
    material.update(unit_material_cost_gbp=price,cost_per_part_gbp=price,
                    extended_material_cost_gbp=ext,cost_method=method,waste_included=True,
                    price_source={'source_class':'ai_estimate','source_type':'web_ai_fallback',
                      'price_class':'ai_estimate','provisional':True,'applied':True,
                      'review_required':True,'review_reason':basis,
                      'price_is_reproducible':bool(result.get('price_is_reproducible')),
                      'source':evidence.get('source'),'price_date':evidence.get('as_of')})
    pe.update(unit_material_cost_gbp=price,unit_cost_gbp=round(labour+price,4),
              unit_total_cost_gbp=round(labour+price,4),extended_total_cost_gbp=round((labour+price)*quantity,4),
              extended_total_cost_raw_gbp=(labour+price)*quantity,
              cost_source=method,costing_basis=method,price_verified=False,review_flag=True,
              _price_explicitly_withheld=False,subcontract_allowance=result)
    pe['review_flags']=[str(f) for f in pe.get('review_flags') or [] if not re.search(r'NOT PRICED|AWAITING.*QUOTE',str(f),re.I)]
    pe['review_flags'].append(basis)
    unmassed=(pe.get('subcontract_mass_basis') or {}).get('unmassed_members') or []
    if unmassed:
        pe['review_flags'].append('The provisional finish weight excludes members without a resolved piece mass: '+', '.join(map(str,unmassed))+'. Confirm their weight or add a disclosed completion allowance; the known-mass budget is partial.')
    specification=str((result.get('brief') or {}).get('finish_spec') or '').strip()
    pe['description']=str(pe.get('part_number') or '')+' '+('Plater round-trip freight' if pe.get('_plater_freight') else 'Subcontract finish '+specification)+' - PROVISIONAL allowance; confirm supplier price'
    if pe.get('_plater_freight'):
        order=max(1,int((result.get('brief') or {}).get('order_quantity') or 1))
        pe['commercial_line']={'schema':'commercial_lines.v1','code':pe.get('part_number'),
            'order_gbp':round(price*order,4),'unit_gbp':price,'quantity':order,
            'basis':'Provisional one-consignment round trip; recheck shipment count when quantity changes',
            'price_source':dict(material['price_source'])}
    elif result.get('order_minimum_gbp'):
        pe['unit_with_order_minimum']={'unit_gbp':result['running_unit_gbp'],
            'order_minimum_gbp':result['order_minimum_gbp']}
    return True


def complete_subcontract_costs(part_estimates,summary,parts,order_qty,ask):
    """Price unresolved process/freight placeholders before document totals, once only."""
    order_qty=max(1,int(order_qty or 1))
    by_id={str(p.get('part_number') or '').strip().upper():p for p in parts or []}
    costed_by_id={str(p.get('part_number') or '').strip().upper():p for p in part_estimates or []}
    graph=None
    priced=0
    for pe in part_estimates or []:
        if not isinstance(pe,dict) or not (pe.get('_plating_placeholder') or pe.get('_plater_freight')):continue
        if pe.get('supplied_by_third_party') or pe.get('_commercial_excluded'):continue
        material=pe.get('material_estimate') or {}
        if _number(material.get('unit_material_cost_gbp')) or _number(pe.get('unit_material_cost_gbp')):continue
        if pe.get('_plater_freight'):
            line={'code':'PLATER-FREIGHT','description':
                f'Budget for ONE round-trip delivery and return between fabrication shop and subcontract finisher for the WHOLE order of {order_qty} finished units. Include both outward and return legs; do not price customer delivery or multiply by component count. Destination and carrier are unconfirmed; identify the working route assumption.'}
            method='plater_freight_market_allowance'
        else:
            members=[by_id.get(str(m).upper(),{}) for m in pe.get('_plating_members') or []]
            finish_records=[by_id.get(str(pe.get('_plating_weldment') or '').upper(),{})]+members
            finish='; '.join(dict.fromkeys(str(value) for p in finish_records for value in
                [p.get('normalized_finish'),p.get('finish'),*(p.get('surface_finishes') or [])] if value))
            mass=_number(material.get('unit_material_mass_kg'))
            # Read the same nested multiplicities as the canonical BOM, not a local
            # qty=1 copied from each member's own sheet. Never rewrite those quantities.
            if graph is None:
                try:
                    import route_compiler as rc
                    graph=rc.build_part_graph(parts,(summary or {}).get('llm_full_extract') or {},
                        ((summary or {}).get('document_analysis') or {}).get('bom_rows') or [],
                        declared_product=rc.declared_product_of(summary or {}),
                        source_names=rc.source_names_of(summary or {}))
                except Exception:graph={}
            quantities=graph.get('quantities') or {};aliases=graph.get('aliases') or {}
            contributions=[]
            for member in pe.get('_plating_members') or []:
                code=str(member).upper();canonical=aliases.get(code,code)
                costed=costed_by_id.get(code) or costed_by_id.get(canonical) or {}
                kg=_number((costed.get('material_estimate') or {}).get('unit_material_mass_kg'))
                qty=_number(quantities.get(canonical)) or _number(costed.get('quantity'))
                if kg and qty:contributions.append({'part':code,'qty_per_product':qty,'kg_per_piece':kg,'kg_per_product':kg*qty})
            if contributions:
                mass=sum(c['kg_per_product'] for c in contributions)
                pe['subcontract_mass_basis']={'contributions':contributions,
                    'basis':'Canonical BOM quantities times the costed member piece masses; original quantities unchanged.',
                    'unmassed_members':[m for m in pe.get('_plating_members') or [] if str(m).upper() not in {c['part'] for c in contributions}]}
                material['unit_material_mass_kg']=round(mass,5)
            area=sum((_number(p.get('_powder_members_coated_m2')) or 0) for p in members)
            if not mass and not area:
                pe.setdefault('review_flags',[]).append('Subcontract allowance not resolved: establish a member mass or coated area; no arbitrary lump sum charged.')
                continue
            line={'code':'SUBCONTRACT-PLATING','description':
                f'Subcontract plating/finishing budget for the stated finish: {finish or "PLATED, precise process still to confirm"}; {mass or 0:g} kg and {area:g} m2 per finished product, {len(members)} contributing members. Exclude transport, our own packing and fabrication labour. Return the measured rate and order minimum, with the assumed process made explicit.',
                'mass_kg':mass,'coated_area_m2':area,'finish_spec':finish or 'PLATED - process unconfirmed'}
            method='subcontract_finish_market_allowance'
        result=_research(line,order_qty,ask,str((summary or {}).get('run_date') or ''))
        if _apply(pe,result,method):priced+=1
        else:
            pe['subcontract_allowance_attempt']=result
            pe.setdefault('review_flags',[]).append('Subcontract allowance remains unresolved: '+str(result.get('missing') or 'no usable researched rate'))
    return priced
