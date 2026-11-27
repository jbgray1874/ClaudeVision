"""A component's own specification and explicit, provisional manufacturing coverage.

No customer, drawing-number, folder, quantity or price exceptions. Uses only already
read pages. Stronger model/DXF/human facts and explicit make/buy rulings remain intact.
"""
import re
import math
import hashlib
import json
from collections import defaultdict
import source_precedence as sp
from drawing_reference import compact, reference_in_file_name, sheet_drawing_reference


def text_of(page):
    text=page.get('reviewed_manufacturing_text')
    if text and page.get('reviewed_manufacturing_text_basis'):
        return str(text)
    return str(page.get('pypdf_text') or page.get('pdfplumber_text') or
               page.get('normalized_text') or (page.get('vision_extraction') or {}).get('ocr_text') or '')


def apply_reviewed_text(summary, decision):
    """Explicit transcription for an already-read raster sheet, never auto-loaded.

    The source page is bound by BOTH saved filename and page number. Raw reader
    text remains unchanged and the full decision/basis is retained for review.
    """
    if decision.get('schema') != 'owned_manufacturing_text.v1' or set(decision) != {'schema', 'pages'}:
        raise ValueError('Expected owned_manufacturing_text.v1 with pages')
    pending = []
    seen = set()
    for item in decision['pages']:
        if set(item) != {'source_pdf_name', 'page_number', 'text', 'basis'}:
            raise ValueError('Every transcription needs exact source, page, text and review basis')
        if not str(item['basis']).strip() or not str(item['text']).strip():
            raise ValueError('A reviewed transcription needs nonempty text and basis')
        identity = (item['source_pdf_name'], item['page_number'])
        if identity in seen:
            raise ValueError('Duplicate reviewed source page')
        seen.add(identity)
        hits = [p for p in summary.get('pages') or [] if
                (p.get('source_pdf_name'), p.get('page_number')) == identity]
        if len(hits) != 1:
            raise ValueError('Reviewed transcription must bind exactly one existing source page')
        candidate = dict(hits[0], reviewed_manufacturing_text=item['text'],
                         reviewed_manufacturing_text_basis=item['basis'])
        owner = _owner(candidate)
        previous = _owner(hits[0])
        if not owner or (previous and owner != previous):
            raise ValueError('Reviewed transcription must preserve the source page drawing identity')
        pending.append((hits[0], candidate))
    for page, candidate in pending:
        page['reviewed_manufacturing_text'] = candidate['reviewed_manufacturing_text']
        page['reviewed_manufacturing_text_basis'] = candidate['reviewed_manufacturing_text_basis']
    summary['reviewed_manufacturing_text'] = {'decision': decision,
        'sha256': hashlib.sha256(json.dumps(decision, sort_keys=True).encode()).hexdigest()}


def _key(value):
    return compact(str(value or '').strip().upper())


def _owner(page):
    name=str(page.get('source_pdf_name') or '')
    filename=reference_in_file_name(name) if re.match(r'(?i)^nc1-',name) else None
    printed=sheet_drawing_reference(text_of(page))
    if filename and printed and _key(filename)!=_key(printed):
        return None
    ids={_key(x) for x in ((page.get('page_analysis') or {}).get('title_block') or {}).get('drawing_numbers') or []}
    return _key(printed or filename) if printed or filename else next(iter(ids)) if len(ids)==1 else None


def _material(text):
    from json_normaliser import normalise_material
    # A labelled callout, never a material mentioned in a revision or a legend.
    match=re.search(r'(?im)^\s*MATERIAL\s*:\s*([^\n;]+)',text)
    if not match:
        return None
    raw=match.group(1).strip()
    if re.search(r'(?i)REFER|SEE\s+(?:DRAW|COMP|BOM)|BY\s+OTHERS',raw):
        return None
    gauge=re.search(r'(?i)(\d+(?:\.\d+)?)\s*mm\b',raw)
    return {'material':normalise_material(raw) or raw,
            'thickness':float(gauge.group(1)) if gauge else None,'specification':raw}


def _excluded(part):
    return any(part.get(k) for k in ('is_bought_in', 'supplied_by_third_party',
        'reference_only', 'is_reference_only', 'for_reference_only', 'special_finish_item'))


def _blank_allowance(part, page):
    """An owned detail's CUT axes, or a disclosed envelope until its DXF is read.

    Never use the stock size in MATERIAL or title-block dates. The provisional
    envelope is not a measured flat and is used only when both axes are missing.
    Existing component/DXF/human dimensions always win.
    """
    if part.get('blank_length_mm') or part.get('blank_width_mm'):
        return
    geometry = part.get('normalized_geometry') or {}
    if str(geometry.get('geometry_source') or '').lower() in ('dxf', 'solidworks', 'solidworks_api'):
        return
    text = text_of(page)
    cut = [float(x) for x in re.findall(r'(?im)^\s*(\d+(?:\.\d+)?)\s+CUT\s*$', text)]
    # Two standalone axes directly after MATERIAL describe a flat on several
    # supplier sheet formats; stock dimensions stay on the MATERIAL line itself.
    after = re.search(r'(?im)^\s*MATERIAL\s*:[^\n]*\n((?:\s*\d+(?:\.\d+)?\s*\n){2})', text)
    if len(cut) == 2:
        values = cut
        source = 'drawing_deterministic'
        basis = 'Two explicitly labelled CUT axes on this component\'s own sheet.'
    elif after and all(float(x) > 30 for x in after.group(1).split()):
        values = [float(x) for x in after.group(1).split()]
        source = 'drawing_deterministic'
        basis = 'Two standalone flat axes immediately after this component\'s MATERIAL callout.'
    else:
        body = re.split(r'(?im)^\s*(?:FINISHED\s+)?PART\s+NO\.?|^\s*MATERIAL\s*:', text)[0]
        dimensions = sorted({float(x) for x in re.findall(r'(?m)^\s*(\d+(?:\.\d+)?)\s*$', body)
                             if 30 < float(x) < 20000}, reverse=True)
        if len(dimensions) < 2:
            return
        values = dimensions[:2]
        source = 'geometry_inference'
        basis = ('PROVISIONAL blank-envelope allowance: largest two distinct standalone '
                 'body dimensions on the owned detail, excluding stock size and title block; '
                 'not a measured flat. Confirm against its DXF before quotation.')
    if not all(math.isfinite(v) and 0 < v < 20000 for v in values):
        return
    for field, value in zip(('blank_length_mm', 'blank_width_mm'), values):
        sp.apply_field(part, field, value, source, note=basis)
    part['owned_blank_basis'] = {'axes_mm': values, 'page': page.get('page_number'),
                               'provisional': source == 'geometry_inference', 'basis': basis}
    if basis not in part.setdefault('review_flags', []):
        part['review_flags'].append(basis)


def _apply(part,field,value,page):
    if value is None:
        return
    old=part.get(field)
    if old == value and sp.source_of(part, field) == 'own_sheet_title_block':
        return
    if sp.apply_field(part,field,value,'own_sheet_title_block',note='Explicit component-owned material callout'):
        if old!=value:
            part.setdefault('owned_manufacturing_changes',[]).append(
                {'field':field,'before':old,'after':value,'page':page.get('page_number')})


def _ops(part,operations,basis):
    if _excluded(part):
        return
    ruled={str(k).lower() for k in (part.get('operations_ruled_out') or {})}
    inferred=part.setdefault('inferred_operations',[])
    for op in operations:
        if op not in ruled and op not in inferred and op not in (part.get('textual_operations') or []):
            inferred.append(op)
            part.setdefault('operation_sources',{}).setdefault(op,'inference')
    notes=part.setdefault('manufacturing_allowance_basis',[])
    if basis not in notes:notes.append(basis)
    if basis not in part.setdefault('review_flags',[]):part['review_flags'].append(basis)


def finish_schedule(text):
    """Named coats with their printed counts. A repeat of one line is not another pass."""
    stages=[]
    for count,description in re.findall(r'(?im)^\s*(\d+)\s*[xX]\s*COAT\s+OF\s+([^\n]+)',text):
        stage={'passes':int(count),'description':' '.join(description.split())}
        if stage['passes']>0 and stage not in stages:stages.append(stage)
    if not stages or not any(re.search(r'(?i)ISOLATOR|PRIMER|BASECOAT|TOPCOAT|SPRAY|PAINT|LACQUER',s['description']) for s in stages):
        return None
    return {'operation':'wet_spray','stages':stages,'passes':sum(s['passes'] for s in stages),
            'basis':'Named coats on the coated object\'s own drawing; stage times use the normal area/rate model, provisionally.'}


def prepare(summary):
    parts=(summary.get('manufacturing_writeup') or {}).get('parts') or summary.get('parts') or []
    pages=summary.get('pages') or []
    by_owner=defaultdict(list);stock_claims=defaultdict(set)
    for page in pages:
        owner=_owner(page)
        if not owner:continue
        by_owner[owner].append(page)
        text=text_of(page)
        # A detail's PART NO. is an alias for that sheet, not a second manufactured item.
        if not re.search(r'(?i)ITEM\s+NO\.?',text):
            for stock in re.findall(r'(?im)^\s*(?:FINISHED\s+)?PART\s+NO\.?\s*[:\-\s]*(\d{7,8})(?!\d)',text):
                stock_claims[stock].add(owner)
    stock_aliases={k:next(iter(v)) for k,v in stock_claims.items() if len(v)==1}
    by_id=defaultdict(list)
    for part in parts:
        key=_key(part.get('part_number'))
        by_id[stock_aliases.get(key,key)].append(part)
    folded=[]
    for owner,members in by_id.items():
        # Only fold the exact stock-vs-own-drawing duplicate. No description similarity.
        drawn=[p for p in members if _key(p.get('part_number'))==owner]
        if len(drawn)!=1:continue
        keeper=drawn[0]
        for other in members:
            if other is keeper or str(other.get('part_number')) not in stock_aliases:continue
            for field in ('bom_parent','bom_parents','quantity','quantity_source'):
                if other.get(field) is not None:
                    if field=='quantity':
                        sp.apply_field(keeper,field,other[field],sp.source_of(other,field) or 'bom_tree')
                    elif not keeper.get(field):keeper[field]=other[field]
            if other['part_number'] not in keeper.setdefault('raw_aliases',[]):
                keeper['raw_aliases'].append(other['part_number'])
            folded.append(other)
    if folded:
        summary.setdefault('owned_manufacturing_folded_records',[]).extend(folded)
        parts[:]=[p for p in parts if all(p is not old for old in folded)]
    rows=(summary.get('document_analysis') or {}).get('bom_rows') or []
    if rows:
        aliases=rows[0].setdefault('sheet_identity_aliases',{})
        for stock,owner in stock_aliases.items():
            refs=[str(p['part_number']) for p in parts if _key(p.get('part_number'))==owner]
            if len(refs)==1 and (stock not in aliases or _key(aliases[stock])==owner):aliases[stock]=refs[0]
    changed=[]
    for part in parts:
        if _excluded(part):continue
        key=_key(part.get('part_number'));owner=stock_aliases.get(key,key)
        owned=by_owner.get(owner,[])
        caption=part.get('component_caption_blank') or {}
        if caption:
            owned=[p for p in pages if p.get('page_number')==caption.get('page')]
        specs=[]
        for page in owned:
            text=text_of(page)
            if caption:
                position=text.upper().find(str(caption.get('caption') or '').upper())
                text=text[position+len(caption.get('caption') or ''):] if position>=0 else ''
            elif len(re.findall(r'(?im)^\s*MATERIAL\s*:',text))>1:
                continue  # shared-component page is not one blank/material for its parent
            spec=_material(text)
            if spec:specs.append((page,spec))
        signatures={(s['material'],s['thickness'],s['specification']) for _,s in specs}
        if len(signatures)==1:
            page,spec=specs[0]
            _apply(part,'normalized_material',spec['material'],page)
            _apply(part,'normalized_thickness_mm',spec['thickness'],page)
            part['material_specification']=spec['specification']
            part['owned_manufacturing_pages']=[p.get('page_number') for p,_ in specs]
            part['pages']=list(dict.fromkeys(part['owned_manufacturing_pages']))
            part['owned_manufacturing_text']='\n'.join(text_of(p) for p,_ in specs)
        if (not owned or part.get('canonical_kind')=='assembly' or part.get('is_sub_assembly')
                or part.get('assembly_children')):
            continue
        material=str(part.get('normalized_material') or '').upper()
        # Either spelling of one material ("MILD STEEL" as read, MILD_STEEL as coded).
        from json_normaliser import normalise_material
        material=' '.join(filter(None,(material,normalise_material(material) or '')))
        if not specs or len(signatures)!=1:continue
        if len(owned)==1 and not caption:
            _blank_allowance(part, owned[0])
        own_text='\n'.join(text_of(p) for p in owned)
        if re.search(r'MDF|PLYWOOD|MFMDF|MFC',material):
            _ops(part,['cnc_routing','bench_work'],
                 'Provisional manufacture: cut/machine this owned board component and bench-prepare it; normal shop rates, not a bought-in panel price.')
        elif (re.search(r'CR4|SHEET\s*STEEL|MILD_STEEL|STAINLESS|ALUMINIUM|ZINTEC',material)
              and not part.get('section_stock')
              and not re.search(r'(?i)\bTUBE\b|\bRHS\b|\bSHS\b|\bBAR\b|\bSECTION\b|\bANGLE\b',
                                part.get('material_specification') or '')):
            _ops(part,['laser_cutting','deburring'],
                 'Provisional manufacture: cut and deburr this owned sheet component; internal detail and cycle time remain reviewable.')
            bends=max([float((p.get('geometry_summary') or {}).get('estimated_bend_line_count') or 0) for p in owned]+[0])
            if not part.get('native_flat_solid') and (bends>0 or re.search(r'(?i)\bUPSTANDS?\b|\bRETURN\b|\bCHANNEL\b',own_text.split('DISCLAIMER')[0])):
                _ops(part,['folding'],'Provisional forming: this component\'s own drawing shows bend/return evidence; preserve any measured bend count.')
                features=part.setdefault('manufacturing_features',{})
                if not features.get('bend_count'):features['bend_count']=max(1,int(bends))
        changed.append(part.get('part_number'))
    # The object is joined/coated once at its own level, not once on every child too.
    for part in parts:
        if _excluded(part):continue
        owner=stock_aliases.get(_key(part.get('part_number')),_key(part.get('part_number')))
        own=by_owner.get(owner,[])
        children=[p for p in parts if _key(p.get('bom_parent')) in (owner,_key(part.get('part_number')))]
        child_counts={}
        for row in rows:
            parent_key=_key(row.get('bom_parent'))
            parent_key=stock_aliases.get(parent_key,parent_key)
            if parent_key!=owner:continue
            child_key=_key(row.get('part_number'))
            child_key=stock_aliases.get(child_key,child_key)
            for child in parts:
                if _key(child.get('part_number'))==child_key:
                    if child not in children:children.append(child)
                    child_counts[child_key]=float(row.get('quantity') or 1)
        board_children=[p for p in children if re.search(r'MDF|PLYWOOD|MFMDF|MFC',str(p.get('normalized_material') or ''))]
        if len(board_children)>1:
            _ops(part,['assembly','glue'],'Provisional board-assembly allowance: fit, join and clamp the stated members once at their parent; confirm fixing/joint method.')
        schedules=[(page,finish_schedule(text_of(page))) for page in own]
        schedules=[(page,schedule) for page,schedule in schedules if schedule]
        if len({json.dumps(schedule,sort_keys=True) for _,schedule in schedules})>1:
            flag='Conflicting named coating schedules on owned sheets; confirm the issued finish schedule.'
            if flag not in part.setdefault('review_flags',[]):part['review_flags'].append(flag)
            continue
        for page,schedule in schedules[:1]:
            _apply(part,'normalized_finish','WET SPRAY',page)
            if str(part.get('normalized_finish') or '').upper() not in ('WET SPRAY','WET_SPRAY'):
                continue
            part['finish_schedule']=dict(schedule,page=page.get('page_number'))
            _ops(part,['wet_spray'],schedule['basis'])
            area=sum(float(p.get('blank_length_mm') or 0)*float(p.get('blank_width_mm') or 0)*
                     child_counts.get(_key(p.get('part_number')),float(p.get('quantity') or 1))*2/1e6 for p in board_children)
            if area and not part.get('_powder_members_coated_m2'):
                part['_powder_members_coated_m2']=area
                part.setdefault('review_flags',[]).append('Coated area allowance: both faces of the stated board members, before masking; confirm exposed surfaces.')
    from named_finish_schedule import mint_consumables
    mint_consumables(parts)
    return changed
