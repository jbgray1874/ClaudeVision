"""A component's own specification and explicit, provisional manufacturing coverage.

No customer, drawing-number, folder, quantity or price exceptions. Uses only already
read pages. Stronger model/DXF/human facts and explicit make/buy rulings remain intact.
"""
import re
import math
import hashlib
import json
import copy
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
        # Some suppliers print the material next to the component rather than
        # under a MATERIAL heading. Read a complete spec line, not board words
        # in the border's generic edging/tolerance notes.
        match=re.search(r'(?im)^\s*(\d+(?:\.\d+)?\s*MM\s+(?:(?:MR|FR|B|THICK)\s+)*'
                        r'(?:MDF|PLYWOOD|MFC|MFMDF)\b[^\n;]*)',text)
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
    envelope is not a measured flat. A proven stock-sheet/weak assembly envelope
    may be displaced, but accepted component/DXF/model/human dimensions win.
    """
    if part.get('section_stock'):
        return  # A round section buys linear stock, not a rectangular flat nest.
    geometry = part.get('normalized_geometry') or {}
    src=str(geometry.get('geometry_source') or part.get('geometry_source') or '').lower()
    if src in ('solidworks', 'solidworks_api', 'model', 'mirror_of_measured'):
        return
    # A rejected alternate file does not invalidate an accepted measured flat.
    if src in ('dxf','dxf_flat_pattern','flat_pattern') or part.get('dxf_augmented'):
        return
    if any(sp.rank(sp.source_of(part,k))>71 for k in ('blank_length_mm','blank_width_mm')):
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
    elif page.get('printed_dimension_axes'):
        values=list(page['printed_dimension_axes']['axes_mm'])
        source='geometry_inference'
        basis=page['printed_dimension_axes']['basis']
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
    current=[part.get('blank_length_mm'),part.get('blank_width_mm')]
    stock=re.search(r'(?i)MATERIAL[^\n]*?(\d{3,5})\s*[xX]\s*(\d{3,5})',text)
    is_stock=bool(stock and sorted(float(x) for x in stock.groups())==sorted(float(x or 0) for x in current))
    old_source=sp.source_of(part,'blank_length_mm')
    explicit=source=='drawing_deterministic'
    replace=not all(current) or is_stock or old_source in ('assembly_envelope_allowance','geometry_inference','overall_dimensions')
    if not replace and not explicit:
        return
    if current==values and part.get('owned_blank_basis'):
        return
    part.setdefault('owned_blank_displaced',{'axes_mm':current,'source':old_source,
        'normalized_geometry':copy.deepcopy(geometry)})
    for field, value in zip(('blank_length_mm', 'blank_width_mm'), values):
        # Withdraw the proven stock/assembly envelope. A measured flat or human
        # decision returned above. Preserve the displaced reading for the audit.
        part[field]=None
        sp.apply_field(part, field, value, source, note=basis)
        geometry[field]=value
        geometry[field+'_source']=source
    geometry.update({'bounding_box_flat_mm':{'length':values[0],'width':values[1],
                                             'height':part.get('normalized_thickness_mm')},
                     'developed_length_mm':values[0],'developed_width_mm':values[1],
                     'smallest_enclosing_rectangle_mm':{'length':values[0],'width':values[1]},
                     'blank_area_m2':values[0]*values[1]/1e6,'blank_basis':'owned_printed_dimension_allowance'})
    part['normalized_geometry']=geometry
    part.pop('_blank_capped_to_assembly',None)
    part.pop('_cut_path_not_bounded',None)
    part['owned_blank_basis'] = {'axes_mm': values, 'page': page.get('page_number'),
                               'provisional': source == 'geometry_inference', 'basis': basis}
    if basis not in part.setdefault('review_flags', []):
        part['review_flags'].append(basis)
    from detail_page_geometry import bound_cutting_to_blank
    old_cut=max(float((part.get(h) or {}).get(k) or 0) for h in
        ('geometry_rollup','normalized_geometry','manufacturing_features') for k in
        ('estimated_cut_length_mm','cut_length_mm','raw_cut_length_mm'))
    notes=bound_cutting_to_blank(part,values[0],values[1])
    if notes:
        part['drawing_cut_displaced_mm']=old_cut
        allow=float((part.get('_cut_allowance') or {}).get('cut_mm') or 0)
        # Printed hole counts are actual evidence, unlike circles from a whole
        # drawing's vectors. Keep their work, and allow for unread internal detail.
        explicit_holes=[]
        for diameter,count in re.findall(r'(?i)(\d+(?:\.\d+)?)\s*mm\s+HOLES?\s*\(\s*[xX]\s*(\d+)\s*\)',text):
            explicit_holes.append((int(count),float(diameter)))
        for count,diameter in re.findall(r'(?i)\b(\d+)\s*[xX]\s*[Øø⌀]?\s*(\d+(?:\.\d+)?)\s*(?:mm)?\s+THRU',text):
            explicit_holes.append((int(count),float(diameter)))
        explicit_holes=list(dict.fromkeys(explicit_holes))
        if allow:
            from config import UNREAD_PROFILE_ALLOWANCE_FACTOR
            hole_cut=sum(count*math.pi*diameter for count,diameter in explicit_holes)
            allow=round(max(allow,2*sum(values)+hole_cut)*UNREAD_PROFILE_ALLOWANCE_FACTOR,1)
            part['_cut_allowance']['cut_mm']=allow
            part['_cut_allowance']['internal_detail_factor']=UNREAD_PROFILE_ALLOWANCE_FACTOR
            for holder in ('normalized_geometry','geometry_rollup','manufacturing_features'):
                h=part.setdefault(holder,{})
                for k in ('cut_length_mm','raw_cut_length_mm','estimated_cut_length_mm'):
                    if k in h:h[k]=allow
            if explicit_holes:
                count=sum(count for count,_ in explicit_holes)
                part['owned_stated_holes']={'count':count,'diameter_counts':explicit_holes,'page':page.get('page_number')}
                for holder in ('normalized_geometry','geometry_rollup','manufacturing_features'):
                    h=part.setdefault(holder,{})
                    h['hole_count']=count
                    if holder=='geometry_rollup':h['estimated_hole_count']=count
                geometry['pierce_count']=count+1
            part.setdefault('review_flags',[]).append(
                f'PROVISIONAL profile budget: owned outline and explicitly counted hole cutting, '
                f'plus {(UNREAD_PROFILE_ALLOWANCE_FACTOR-1):.0%} for unread internal detail; '
                f'{allow:g} mm a piece, not the drawing-layout vectors.')
        # _raw remains an active fallback for some consumers. The original page
        # vectors belong in the audit, not in a second live path to the price.
        roll=part.get('geometry_rollup') or {}
        raw=roll.get('_raw') or {}
        if allow and raw:
            part.setdefault('drawing_vector_original',dict(raw))
            for key in ('estimated_cut_length_mm','raw_cut_length_mm','cut_length_mm'):
                if key in raw:raw[key]=allow


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
    rows=(summary.get('document_analysis') or {}).get('bom_rows') or []
    for stock,ref in ((rows[0].get('sheet_identity_aliases') or {}) if rows else {}).items():
        if str(stock).isdigit() and _key(ref) in by_owner:
            stock_aliases.setdefault(stock,_key(ref))
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
    if rows:
        aliases=rows[0].setdefault('sheet_identity_aliases',{})
        for stock,owner in stock_aliases.items():
            refs=[str(p['part_number']) for p in parts if _key(p.get('part_number'))==owner]
            if len(refs)==1 and (stock not in aliases or _key(aliases[stock])==owner):aliases[stock]=refs[0]
    changed=[]
    for part in parts:
        key=_key(part.get('part_number'));owner=stock_aliases.get(key,key)
        owned=by_owner.get(owner,[])
        _repeat_supply(part,owned)
        if _excluded(part):continue
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
            _owned_section(part,page,spec)
            part['owned_manufacturing_pages']=[p.get('page_number') for p,_ in specs]
            part['pages']=list(dict.fromkeys(part['owned_manufacturing_pages']))
            part['owned_manufacturing_text']='\n'.join(text_of(p) for p,_ in specs)
            own_body=re.split(r'(?i)GENERAL\s+DIMENSION|MODIFICATIONS|DISCLAIMER|GENERAL\s+TOLERANCES',
                              text_of(page))[0]
            if (re.search(r'MDF|PLYWOOD',spec['material']) and re.search(r'(?i)\bSPRAY\b|\bPAINT',own_body)
                    and not re.search(r'(?i)LAMINAT|MELAMINE|VENEER|\bHPL\b|\bMFMDF\b|\bMFC\b',own_body)):
                part['owned_board_construction']={'mode':'raw_board_with_wet_finish',
                    'basis':'Own component spec names a raw board and sprayed finish; do not inherit laminate from border/other pages.'}
                _apply(part,'normalized_finish','WET SPRAY',page)
                _ops(part,['wet_spray'],part['owned_board_construction']['basis'])
                _flag_section_thickness(part,own_body,spec)
                features=part.get('manufacturing_features') or {}
                if (features.get('bend_count_source')=='inferred_dashed_lines' and
                        not re.search(r'(?i)\bBEND|\bFOLD|\bKERF|\bCURV',own_body)):
                    for key in ('textual_operations','inferred_operations','operations'):
                        if isinstance(part.get(key),list):
                            part[key]=[op for op in part[key] if op not in ('folding','fold')]
                    part.setdefault('owned_board_displaced_bends',features.get('bend_count'))
                    features['bend_count']=0
                    features['fold_required']=False
                    # The same dashed lines feed costing's fold resolver as its weakest proxy;
                    # withdraw them there too, keeping the readings for the audit.
                    roll=part.get('geometry_rollup') if isinstance(part.get('geometry_rollup'),dict) else {}
                    geo=part.get('normalized_geometry') if isinstance(part.get('normalized_geometry'),dict) else {}
                    held={k:roll.get(k) for k in ('dashed_long_axis_lines','estimated_bend_line_count') if roll.get(k)}
                    if geo.get('bend_count'):
                        held['normalized_geometry.bend_count']=geo.get('bend_count')
                    if held:
                        part.setdefault('owned_board_dashed_lines_displaced',held)
                    for k in ('dashed_long_axis_lines','estimated_bend_line_count'):
                        if k in roll:roll[k]=0
                    if 'bend_count' in geo:geo['bend_count']=0
                    part.setdefault('review_flags',[]).append('Dashed drawing lines are not press-brake folds on this own-sheet raw-board panel; CNC/bench and spray remain costed.')
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
            materials={p.get('normalized_material') for p in board_children if p.get('normalized_material')}
            if len(materials)==1 and not part.get('normalized_material'):
                sp.apply_field(part,'normalized_material',next(iter(materials)),'assembly_members')
            _ops(part,['assembly','glue'],'Provisional board-assembly allowance: fit, join and clamp the stated members once at their parent; confirm fixing/joint method.')
        schedules=[(page,finish_schedule(text_of(page))) for page in own]
        schedules=[(page,schedule) for page,schedule in schedules if schedule]
        if not schedules and own and part.get('owned_board_construction') and not part.get('finish_schedule'):
            import config
            rule=config.UNCOUNTED_SPRAY_FINISH_BUDGET
            schedules=[(own[0],{'operation':'wet_spray','stages':list(rule['stages']),
                'passes':sum(s['passes'] for s in rule['stages']),
                'inferred':True,'basis':rule['basis']})]
        # A raster assembly GA with visible raw-board members must not mean
        # free finishing. This is a HOUSE ALLOWANCE, not a reading of unread ink.
        if (not schedules and len(board_children)>1 and
                all(str(p.get('normalized_material') or '').upper() in ('MDF','PLYWOOD','PLY') for p in board_children) and own and
                all(not text_of(page).strip() for page in own) and
                not part.get('normalized_finish') and not part.get('finish_schedule')):
            import config
            rule=config.RASTER_BOARD_FINISH_BUDGET
            if rule.get('enabled'):
                schedule={'operation':'wet_spray','stages':list(rule['stages']),
                          'passes':sum(s['passes'] for s in rule['stages']),
                          'inferred':True,'basis':rule['basis']}
                schedules=[(own[0],schedule)]
        if len({json.dumps(schedule,sort_keys=True) for _,schedule in schedules})>1:
            flag='Conflicting named coating schedules on owned sheets; confirm the issued finish schedule.'
            if flag not in part.setdefault('review_flags',[]):part['review_flags'].append(flag)
            continue
        for page,schedule in schedules[:1]:
            if schedule.get('inferred'):
                sp.apply_field(part,'normalized_finish','WET SPRAY','geometry_inference',note=schedule['basis'])
            else:
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


def _repeat_supply(part, pages):
    """Infer a repeat-supplied complete component, not a generic item of similar name."""
    from bought_in_policy import make_or_buy_ruling, strip_fabrication_ops
    if (part.get('repeat_supply_basis') or any(part.get(k) for k in
            ('supplied_by_third_party','reference_only','is_reference_only','for_reference_only')) or make_or_buy_ruling(part)=='make'
            or part.get('is_assembly_parent') or part.get('assembly_children')):
        return
    for page in pages:
        body=re.split(r'(?i)MODIFICATIONS|DISCLAIMER|GENERAL\s+DIMENSION',text_of(page))[0]
        article=re.search(r'(?im)^\s*PART\s+NO\.?\s*:\s*(\d{7,8})\b',body)
        if not (article and re.search(r'(?i)SAME\s+SPEC(?:IFICATION)?\s+AS\s+PREVIOUSLY\s+SUPPLIED',body)):
            continue
        if _material(body):
            continue  # An owned stock specification still says this may be made here.
        basis={'source_pdf_name':page.get('source_pdf_name'),'page_number':page.get('page_number'),
               'article':article[1],'source_text':body.strip(),
               'provisional':True,'basis':'Repeat-supplied complete component with its own article; make/buy and supplier specification require confirmation.'}
        part['repeat_supply_basis']=basis
        part['is_bought_in']=True
        part['supplier_part_number']=part.get('supplier_part_number') or article[1]
        part['price_chain_description']=(str(part.get('description') or '')+
            ' - COMPLETE component as detailed, not merely a spring/feed insert. '+body.strip())
        strip_fabrication_ops(part)
        part.setdefault('review_flags',[]).append(
            'PROVISIONAL procurement assumption: price the complete repeat-supplied component, including its housing/mechanism as shown. Confirm supplier and make/buy; its drawing is not a generic catalogue pusher. Assembly to its separately costed backing remains separate.')
        break


def _owned_section(part,page,spec):
    from section_profile import stock_in_material_words
    stock=stock_in_material_words(spec['specification'])
    if not stock or not stock.get('t'):
        return
    body=re.split(r'(?im)^\s*(?:FINISHED\s+)?PART\s+NO\.?|^\s*MATERIAL\s*:',text_of(page))[0]
    dimensions=[]
    for line in body.splitlines():
        if re.fullmatch(r'\s*(?:\d+(?:\.\d+)?\s*)+',line):
            dimensions.extend(float(v) for v in line.split())
    lengths=[v for v in dimensions if stock['a'] < v < 20000]
    existing=part.get('section_stock') or {}
    if existing.get('length_mm'):
        stock['length_mm']=existing['length_mm']
        if existing.get('length_basis'):stock['length_basis']=existing['length_basis']
    elif lengths:
        stock['length_mm']=max(lengths)
        stock['length_basis']='Provisional largest body dimension on component-owned sheet; not the raw-stock purchase length.'
    else:
        return
    stock.update(source='own_sheet_title_block',source_pdf_name=page.get('source_pdf_name'),page_number=page.get('page_number'))
    _apply(part,'section_stock',stock,page)
    if part.get('section_stock')==stock:
        part['material_text_as_printed']=spec['specification']
        _ops(part,['tube_cut'],'Cut the component from its stated section stock; do not flat-nest the round profile.')
        note=f"Section stock {stock['a']:g} x {stock['t']:g} mm; cut length {stock['length_mm']:g} mm from its own sheet. Confirm the body-dimension reading; the purchased bar length is not the part length."
        if note not in part.setdefault('review_flags',[]):part['review_flags'].append(note)


# Common sheet-board gauges. A lone printed number of one of these on a board panel's
# own sheet may be a section's thickness. Below 6 mm such numbers are usually groove,
# rebate or edging depths on these sheets, so they are not read as a board thickness.
_BOARD_GAUGES_MM=(6,9,12,15,18,19,22,25,30)


def _flag_section_thickness(part,own_body,spec):
    """Keep a disagreement between the material note and a section's printed thickness visible.

    The material note stays the provisional thickness; nothing is costed differently.
    A standalone dimension that is a standard board gauge, and not the stated one, is
    put to the estimator as a review item rather than silently resolved either way.
    """
    stated=spec.get('thickness')
    if not stated:
        return
    lone={float(v) for v in re.findall(r'(?m)^\s*(\d+(?:\.\d+)?)\s*$',own_body)}
    if float(stated) in lone:
        return  # its own sections print the stated thickness: no disagreement to raise
    printed=sorted(v for v in lone if v in _BOARD_GAUGES_MM)
    if not printed:
        return
    shown=[int(v) if v==int(v) else v for v in printed]
    note=(f"Thickness conflict on its own sheet: the material note says {stated:g} mm, a section "
          f"prints {', '.join(f'{v:g} mm' for v in shown)}. Priced at {stated:g} mm provisionally; "
          f"Design/estimator to confirm.")
    part['owned_thickness_conflict']={'stated_mm':stated,'printed_mm':shown,'basis':note}
    flags=part.setdefault('review_flags',[])
    if note not in flags:
        flags.append(note)
