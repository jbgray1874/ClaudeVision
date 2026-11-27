"""Explicit, job-scoped fabrication allowances for incomplete supplier detail.

No money or rates are invented here. These become ordinary material and operation
inputs for the existing costing engine, with their assumed sizes and basis visible.
Only an explicitly supplied decision file activates them. No file is auto-discovered.
"""
from __future__ import annotations
import hashlib
import json
import math
from drawing_reference import compact


def add(summary, decision):
    from concept_scan import parts_from_concept, SIGHTABLE_OPERATIONS
    if decision.get('schema') != 'estimating_allowances.v1':
        raise ValueError('Expected estimating_allowances.v1')
    if set(decision) - {'schema','drawing','members','notes'}:
        raise ValueError('Unsupported allowance section: no decision may be silently ignored')
    if compact(decision.get('drawing')) != compact(summary.get('declared_product')):
        raise ValueError('Allowance drawing does not match this saved product')
    token=hashlib.sha256(json.dumps(decision,sort_keys=True).encode()).hexdigest()
    if summary.get('reviewed_manufacturing_allowances'):
        if summary['reviewed_manufacturing_allowances']['sha256']==token:
            return []
        raise ValueError('A different allowance decision is already installed. Start from the original saved record.')
    parts=summary['manufacturing_writeup']['parts']
    by={compact(p.get('part_number')):p for p in parts}
    groups={}
    for member in decision.get('members') or []:
        parent=by.get(compact(member.get('parent')))
        if parent is None:
            raise ValueError(f"Allowance parent is not in the recovered product: {member.get('parent')}")
        if any(parent.get(k) for k in ('supplied_by_third_party','reference_only','is_reference_only','for_reference_only')):
            raise ValueError('A by-others/reference-only item is not a fabrication allowance')
        key=parent['part_number']
        # Existing detail wins. Never charge an equivalent carcase beside its cut list.
        children=list(parent.get('assembly_children') or [])+list(parent.get('native_assembly_children') or [])
        children += [p for p in parts if compact(p.get('bom_parent'))==compact(key)]
        if children:
            raise ValueError(f'{key} already has component detail; do not add a second allowance bill')
        groups.setdefault(key,[]).append(member)
    minted=[]
    for parent,members in groups.items():
        for number,member in enumerate(members,1):
            if set(member)-{'parent','description','material','length_mm','width_mm','thickness_mm',
                            'qty','folds','operations','basis','edge_basis','cutouts'}:
                raise ValueError('Unsupported allowance member field: no decision may be silently ignored')
            basis=str(member.get('basis') or '').strip()
            if not basis or not str(member.get('description') or '').strip() or not str(member.get('material') or '').strip():
                raise ValueError('Every allowance needs a description, material and stated estimating basis')
            values=[float(member.get(k) or 0) for k in ('length_mm','width_mm','thickness_mm','qty')]
            if not all(math.isfinite(v) and v>0 for v in values) or not values[3].is_integer():
                raise ValueError('Allowance dimensions and whole-piece quantity must be positive finite numbers')
            ops=list(dict.fromkeys(member.get('operations') or []))
            if not ops or set(ops)-set(SIGHTABLE_OPERATIONS)-{'dress_welds'}:
                raise ValueError('Allowance must name supported manufacturing operations')
            if 'folding' in ops and not float(member.get('folds') or 0)>0:
                raise ValueError('A folded allowance needs its assumed fold count')
            sighted={'name':member['description'],'kind':'fabricated','quantity':int(values[3]),
                'material_guess':member['material'],
                'assumed_blank_mm':dict(zip(('length','width','thickness'),values[:3])),
                'operations':[o for o in ops if o!='dress_welds'],
                'folds':member.get('folds',0),'why_size':basis,
                'quantity_basis':basis,'banded_edges':member.get('edge_basis',''),
                'cutouts':member.get('cutouts') or []}
            if 'edge_banding' in ops and not member.get('edge_basis'):
                raise ValueError('Edging needs an explicit assumed edge basis')
            generated=parts_from_concept({'parts':[sighted]},parent,sheet=True)
            if len(generated)!=1:
                raise ValueError('One allowance member must produce exactly one fabricated record')
            part=generated[0]
            part['part_number']=f'{parent}-ALW{number:02d}'
            if compact(part['part_number']) in by:
                raise ValueError('Allowance identity already exists')
            for field in ('read_id','read_fingerprint','read_origin'):
                part.pop(field,None)
            part['bom_parent']=parent
            part['bom_parents']=[{'parent':parent,'qty':int(values[3])}]
            part['inferred_operations']=ops
            part['provisional_allowance']={'basis':basis,'source':'reviewed decision file',
                'assumed_blank_mm':sighted['assumed_blank_mm'],'qty_per_parent':int(values[3]),
                'operations':ops,'decision_sha256':token}
            part.setdefault('review_flags',[]).append('PROVISIONAL MANUFACTURING ALLOWANCE: '+basis)
            minted.append(part)
    # Commit only after every member validates. A bad final member leaves no partial bill.
    for parent in groups:
        by[compact(parent)]['is_sub_assembly']=True
    parts.extend(minted)
    summary['reviewed_manufacturing_allowances']={'sha256':token,'decision':decision,
        'added':[p['part_number'] for p in minted],'priced':False}
    return [p['part_number'] for p in minted]
