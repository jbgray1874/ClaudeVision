"""Prepare a separate saved-evidence correction, without pricing or engine submission."""
from __future__ import annotations
import copy
import hashlib
import json
from drawing_reference import compact
from supplier_sheet_identity import reconcile_saved_sheet_identities


def prepare(summary, *, scope=None, scope_basis=None, identity_aliases=None, allowances=None,
            owned_text=None):
    if scope and not str(scope_basis or '').strip():
        raise ValueError('A scope correction needs its drawing evidence/basis')
    result = copy.deepcopy(summary)
    if owned_text:
        from owned_component_manufacturing import apply_reviewed_text
        apply_reviewed_text(result, owned_text)
    before = {compact(p.get('part_number')): p for p in summary.get('parts', [])}
    reconcile_saved_sheet_identities(result)
    if identity_aliases:
        from drawing_reference import is_drawing_reference, reference_in_file_name
        if not str(scope_basis or '').strip():
            raise ValueError('Reviewed identity aliases need their drawing evidence/basis')
        if any(not str(k).isdigit() or not is_drawing_reference(v)
               for k,v in identity_aliases.items()):
            raise ValueError('Identity aliases must map supplier numeric stock codes to exact drawing references')
        rows=(result.get('document_analysis') or {}).get('bom_rows') or []
        if not rows:
            raise ValueError('No saved BOM to receive the reviewed identity aliases')
        stocks={str(r.get(k) or '') for r in rows for k in ('part_number','finished_part_no')}
        stocks.update(str(p.get('part_number') or '') for p in summary.get('parts') or [])
        opened={compact(reference_in_file_name(pg.get('source_pdf_name'))) for pg in result.get('pages') or []}
        for stock,ref in identity_aliases.items():
            if stock not in stocks or compact(ref) not in opened:
                raise ValueError(f'Reviewed alias must join a stock code and a drawing actually in this saved pack: {stock}')
        standing=rows[0].setdefault('sheet_identity_aliases',{})
        for stock,ref in identity_aliases.items():
            if stock in standing and compact(standing[stock])!=compact(ref):
                raise ValueError(f'Reviewed alias contradicts sheet evidence: {stock}')
            standing[stock]=ref
        result['reviewed_identity_aliases']={'aliases':identity_aliases,'basis':scope_basis}
    if scope:
        result['declared_product_original'] = result.get('declared_product')
        result['declared_product'] = scope
        result['scope_correction_basis'] = scope_basis
    reread = reread_title_block_materials(result)
    from document_builder import build_part_index
    writeup = copy.deepcopy(result.get('manufacturing_writeup') or {})
    writeup['parts'] = build_part_index(result)
    result['manufacturing_writeup'] = writeup
    parts = writeup['parts']
    # Keep genuine multi-component captions already extracted from a shared sheet.
    # Rebuilding an index keyed only on drawing number cannot rediscover those
    # separate identities; their own captions and page membership are the evidence.
    from component_caption_blanks import _CAPTION, _key
    keys={compact(p.get('part_number')) for p in parts}
    for old in before.values():
        if compact(old.get('part_number')) in keys or not _CAPTION.match(str(old.get('description') or '')):
            continue
        pages=[pg for pg in result.get('pages') or []
               if not old.get('pages') or pg.get('page_number') in old.get('pages')]
        if any(_key(old.get('description')) in _key(pg.get('pypdf_text') or pg.get('pdfplumber_text') or pg.get('normalized_text'))
               for pg in pages):
            parts.append(copy.deepcopy(old))
            keys.add(compact(old.get('part_number')))
    from component_caption_blanks import repair as repair_component_blanks
    repair_component_blanks(result)
    # Keep the original measured DXF/native evidence, never the old cost/quantity
    # or a whole-sheet PDF blank masquerading as a measured component.
    for part in parts:
        old = before.get(compact(part.get('part_number')), {})
        geometry = old.get('normalized_geometry') or {}
        if str(geometry.get('geometry_source') or '').lower() in ('dxf', 'solidworks', 'solidworks_api'):
            for key in ('normalized_geometry','geometry_rollup','manufacturing_features',
                        'dxf_augmented','dxf_source','blank_length_mm','blank_width_mm'):
                if old.get(key) is not None:
                    part[key] = copy.deepcopy(old[key])
    from owned_component_manufacturing import prepare as prepare_owned_manufacturing
    prepare_owned_manufacturing(result)
    if allowances:
        from reviewed_manufacturing_allowances import add as add_allowances
        add_allowances(result,allowances)
    from route_compiler import apply_canonical_evidence_to_parts, job_drawing_numbers
    from file_scan import assembly_page_owners
    graph = apply_canonical_evidence_to_parts(parts, result.get('llm_full_extract') or {},
        (result.get('document_analysis') or {}).get('bom_rows') or [],
        job_drawing_numbers(result), assembly_page_owners(result), summary=result)
    after = {compact(p.get('part_number')): p for p in parts}
    audit = {'schema':'saved_scope_recovery.v1', 'priced':False,
             'source_sha256': hashlib.sha256(json.dumps(summary,sort_keys=True,default=str).encode()).hexdigest(),
             'original_unit_gbp': (summary.get('final_estimate') or {}).get('totals',{}).get('unit_gbp'),
             'before_records':len(before), 'prepared_records':len(after),
             'added':sorted(set(after)-set(before)), 'set_aside':sorted(set(before)-set(after)),
             'quantity_changes':[{'part':k,'before':before[k].get('quantity'),'after':after[k].get('quantity')}
                 for k in sorted(set(before)&set(after))
                 if before[k].get('quantity') != after[k].get('quantity')],
             'issues':graph.get('issues') or [],
             'title_block_materials_reread':reread,
             'quantities_per_finished_product':{n.part_number:n.qty_per_unit for n in graph['nodes']},
             'note':'Prepared evidence only. Original estimates untouched. No corrected price is claimed.'}
    # A prepared input must not carry stale final prices, cached workbook paths or a
    # bundle token that could make it look like a completed replacement estimate.
    for key in ('estimate_summary','final_estimate','costed_job','money_provenance',
                'saved_output_paths','archived_output_paths','output_targets'):
        result.pop(key,None)
    result['parts'] = parts
    result['saved_scope_recovery'] = audit
    return result, audit


def reread_title_block_materials(summary):
    """Read each saved page's material callout again with today's reader, as a fresh run
    would (27 Nov 2026: "MATERIAL:1.5mm CR4 SHEET STEEL" was cut at SHEET, so 46 steel
    component sheets had no material and one had the ACRYLIC of a revision note). Only the
    material fields are refreshed, only where the reading changed. Returns what changed."""
    from extractor_patterns import extract_title_block_fields
    changed = []
    for page in summary.get('pages') or []:
        text = page.get('pdfplumber_text') or page.get('normalized_text') or ''
        analysis = page.get('page_analysis')
        if not text or not isinstance(analysis, dict) or not isinstance(analysis.get('title_block'), dict):
            continue
        fresh = extract_title_block_fields(text)
        block = analysis['title_block']
        thickness = (fresh.get('normalized') or {}).get('primary_thickness_mm')
        held = (block.get('normalized') or {}).get('primary_thickness_mm')
        if fresh.get('materials') == block.get('materials') and (not thickness or thickness == held):
            continue
        new_primary = (fresh.get('normalized') or {}).get('primary_material')
        changed.append({'page': page.get('page_number'), 'sheet': page.get('source_pdf_name'),
                        'was': block.get('materials'), 'now': fresh.get('materials'),
                        'gauge_was': held, 'gauge_now': thickness})
        block['materials'] = fresh.get('materials')
        block['material_stated_unresolved'] = fresh.get('material_stated_unresolved')
        block.setdefault('normalized', {})['primary_material'] = new_primary
        if new_primary and thickness:
            block['normalized']['primary_thickness_mm'] = thickness
        primary = analysis.get('primary_fields')
        if isinstance(primary, dict):
            # precedence: direct-write ok — refreshing a saved PAGE reading with today's reader
            # before the part index is rebuilt from it; no part fact is written here.
            primary['material'] = new_primary
            primary['normalized_material'] = new_primary  # precedence: direct-write ok — page reading refreshed
            if new_primary and thickness:
                primary['thickness_mm'] = primary['normalized_thickness_mm'] = thickness  # precedence: direct-write ok — page reading refreshed
    return changed
