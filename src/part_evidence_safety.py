"""Owned evidence, before pricing: withdraw what is not a reading, state every judgement.

No job/customer exceptions, prices, quantities, CAD launches or network requests.
Withdraw only an identified unsupported reading (a date read as a size, a screw's 10mm
handed to every plate). Where the pack leaves a gap, take the sensible judgement, price
it, and say on the part what was assumed and why. Nothing here blocks a price.
"""
import re
import math
from collections import defaultdict

import source_precedence as sp

_MEASURED = {'dxf', 'dxf_flat_pattern', 'solidworks_api', 'solidworks_flat_pattern',
             'solidworks_docmgr', 'mirror_of_measured', 'estimator_confirmed'}
_CONTEXT = re.compile(r'\b(?:STORE|EXISTING|BUILDING|SITE)\s+(?:COLUMN|WALL|FLOOR)\b', re.I)


def _key(value):
    return str(value or '').strip().upper()


def _num(value):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) and result > 0 else None


def _parts(summary):
    return (summary.get('manufacturing_writeup') or {}).get('parts') or summary.get('parts') or []


def _owned(pages):
    out = defaultdict(list)
    for pg in pages or []:
        tb = (pg.get('page_analysis') or {}).get('title_block') or {}
        owners = {_key(x) for x in tb.get('drawing_numbers') or [] if x}
        if len(owners) == 1:
            out[next(iter(owners))].append(pg)
    return out


def _measured_geometry(part):
    return (str(part.get('geometry_source') or '') in _MEASURED
            or str(part.get('blank_length_mm_source') or '') in _MEASURED)


def _issue(part, name, message, assumption=None, **evidence):
    issues = part.setdefault('evidence_safety_issues', {})
    issues.setdefault(name, dict(message=message, **evidence))
    sp.raise_manufacturing_question(part, message,
        assumption or 'Priced on the reading stated here: a judgement, not a measurement.',
        'Confirm or correct it from the part\'s own drawing or model.',
        'part_evidence_safety')


def _withdraw(part, field, reason):
    old = part.get(field)
    if old is None:
        return
    part.setdefault('withdrawn_evidence', []).append(
        dict(field=field, value=old, source=sp.source_of(part, field), reason=reason))
    # Arbitration is withdrawing a counterfeit rank, not introducing a replacement.
    # precedence: direct-write ok -- unsupported evidence removal, audit kept above.
    part[field] = None


def prepare(summary):
    """Idempotent safety pass. Keeps all BOM records, edges and quantity fields."""
    parts = _parts(summary)
    pages = summary.get('pages') or []
    owned = _owned(pages)
    doc = summary.get('document_analysis') or {}
    blanket = (doc.get('primary_fields') or {}).get('thickness_mm')
    if blanket is None:
        blanket = ((doc.get('title_block') or {}).get('normalized') or {}).get('primary_thickness_mm')
    blanket = _num(blanket)

    # A repeated ID on distinct detail sheets is a decision, never an alias onto
    # a similar number. Multi-sheet drawings may legitimately do this: flag, don't
    # delete sheets or merge/rename parts. Assembly BOM pages are not detail pages.
    duplicates = {}
    twins = {}
    listed = {_key(p.get('part_number')):p for p in parts if isinstance(p,dict)}
    def description_key(p):
        return re.sub(r'\s+', ' ', str(p.get('description') or '').strip().upper())
    for pn, sheets in owned.items():
        detail = [p for p in sheets if not re.search(
            r'ITEM\s+(?:NO\.?\s+)?(?:PART\s+NUMBER|DWG\s+NO)',
            str(p.get('pdfplumber_text') or ''), re.I)]
        if len(detail) > 1:
            from extractor_patterns import dimension_text_without_border
            bodies = {re.sub(r'\s+', '', dimension_text_without_border(
                p.get('pdfplumber_text') or '')) for p in detail}
            # Multiple sheets of one part are ordinary. Only escalate this identity
            # pattern when another listed component of the same family/description
            # has NO own detail sheet: the duplicate may have stolen that identity.
            source = listed.get(pn) or {}
            unbound = [code for code,p in listed.items()
                       if code not in owned and code.split('-')[0] == pn.split('-')[0]
                       and description_key(source) and description_key(p)==description_key(source)]
            if len(bodies) > 1 and unbound:
                duplicates[pn] = sorted(p['page_number'] for p in detail)
                twins[pn] = unbound

    for part in parts:
        if not isinstance(part, dict):
            continue
        pn = _key(part.get('part_number'))
        sheets = owned.get(pn, [])

        # Repair the old saved-record signature too. A freshly built part no longer
        # receives this figure at all (part_index.document_gauge_to_hand_down).
        own_gauges = [((p.get('page_analysis') or {}).get('title_block') or {}).get(
            'normalized', {}).get('primary_thickness_mm') for p in sheets]
        value = _num(part.get('normalized_thickness_mm'))
        if (len(owned) > 1 and sheets and blanket is not None and value == blanket
                and part.get('thickness_source') == 'drawing_deterministic'
                and not any(v is not None for v in own_gauges)):
            reason = 'document gauge repeated without this part\'s own thickness evidence'
            _withdraw(part, 'normalized_thickness_mm', reason)
            part['thickness_source'] = 'unknown'  # precedence: direct-write ok -- withdrawn source
            part['thicknesses_mm'] = [v for v in part.get('thicknesses_mm') or []
                                     if str(v) not in (str(blanket), f'{float(blanket):g}')]
            ng = part.get('normalized_geometry') or {}
            if (ng.get('bounding_box_flat_mm') or {}).get('height') == value:
                ng['bounding_box_flat_mm']['height'] = None
            _issue(part, 'unowned_gauge',
                f"{part.get('part_number')}: the inherited {value:g} mm is not an owned "
                'gauge; obtain a part-local thickness before firm costing.')

        ng = part.get('normalized_geometry') or {}
        flat = ng.get('bounding_box_flat_mm') or {}
        years = {int(y) for pg in sheets for y in re.findall(
            r'\b((?:19|20)\d{2})[/.\-]\d{1,2}[/.\-]\d{1,2}\b',
            str(pg.get('pdfplumber_text') or ''))}
        metadata_blank = (flat.get('length') in years or flat.get('width') in years)
        no_own_blank = (part.get('blank_length_mm_source') == 'document_text_largest_numbers'
                        and len(sheets) != 1)
        if not _measured_geometry(part) and (metadata_blank or no_own_blank):
            reason = 'unmeasured blank contains metadata or has no unique owned sheet'
            for field in ('overall_length_mm', 'overall_width_mm', 'blank_length_mm', 'blank_width_mm'):
                _withdraw(part, field, reason)
            for field in ('developed_length_mm', 'developed_width_mm', 'blank_length_mm',
                          'blank_width_mm', 'blank_area_m2', 'projected_area_m2', 'longest_edge_mm'):
                if field in ng:
                    ng[field] = None
            for field in ('bounding_box_flat_mm', 'bounding_box_formed_mm', 'smallest_enclosing_rectangle_mm'):
                if isinstance(ng.get(field), dict):
                    ng[field]['length'] = ng[field]['width'] = None
            ng['blank_basis'] = 'unresolved_owned_geometry'
            part['flat_pattern_detected'] = False
            part['overall_sizes_mm'] = []
            _issue(part, 'metadata_blank',
                f"{part.get('part_number')}: metadata/unowned blank withdrawn; a flat-pattern "
                'label is not a measured blank. Obtain this component\'s own cutting size.')
        elif (part.get('flat_pattern_detected') and not _measured_geometry(part)
                and not part.get('native_flat_pattern') and not part.get('flat_pattern_measured')):
            ng['blank_basis'] = 'pdf_flat_pattern_candidates'
            _issue(part, 'unmeasured_flat_pattern',
                f"{part.get('part_number')}: a printed flat-pattern label/candidate pair "
                'does not establish a measured cutting blank; confirm the actual flat dimensions.')

        if _CONTEXT.search(str(part.get('description') or part.get('part_number') or '')):
            _issue(part, 'context_supply_scope',
                f"{part.get('part_number')}: confirm whether this building/context item is "
                'existing/free issue or something SDI supplies. No automatic exclusion or zero price.')

        # Correct an existing TIG default only with the welded part's OWN annotation.
        prior_process = part.get('weld_process_stated') or {}
        if not prior_process or prior_process.get('default'):
            from extractor_patterns import weld_process_stated
            from weld_symbols import note_weld_process
            for pg in sheets:
                text = pg.get('pypdf_text') or pg.get('pdfplumber_text') or ''
                process = weld_process_stated(text)
                if process and not process.get('default'):
                    note_weld_process(part, text)
                    # Remove only a superseded automatically generated rate question.
                    # Human rulings and unrelated welding questions remain untouched.
                    part['manufacturing_questions'] = [q for q in part.get('manufacturing_questions') or []
                        if q.get('source') != 'weld_symbols.weld_rate_gap_question'
                        or process['process'] in str(q.get('issue') or '')]
                    break
    for pn, codes in twins.items():
        _bind_twins(listed[pn], [listed[c] for c in codes], duplicates[pn])
    return parts


def _bind_twins(source, twins, pages):
    """One number printed on two detail sheets, and a listed twin with no sheet of its own.

    The usual cause is a drawing office copying a sheet and not renumbering it (12517: the
    acrylic bracket 05-05A on pages 25 and 38, while 07-05A, 60 off, had no sheet). The
    judgement: each twin takes the first duplicate sheet after the page that lists it, and
    the same material and gauge as the part it was copied from; its size is its own model's
    where it has one. It is priced, and the line says so.
    """
    spare = list(pages)
    for twin in twins:
        if twin.get('bound_detail_sheet'):
            spare = [p for p in spare if p != twin['bound_detail_sheet'].get('page')]
            continue
        listing = [int(p) for p in twin.get('pages') or [] if str(p).isdigit()]
        after = [p for p in spare if listing and p > max(listing)]
        if len(spare) < 2 and not after:
            break
        sheet = min(after) if after else max(spare)
        spare.remove(sheet)
        if sheet not in (twin.get('pages') or []):
            twin['pages'] = list(twin.get('pages') or []) + [sheet]
        taken = []
        for field, label in (('normalized_material', 'material'),
                             ('normalized_thickness_mm', 'gauge')):
            if twin.get(field) in (None, '') and source.get(field) not in (None, ''):
                sp.apply_field(twin, field, source.get(field), 'inference')
                taken.append(f"{label} {source.get(field)}")
        bbox = (twin.get('normalized_geometry') or {}).get('bbox_mm') or []
        sizes = sorted((float(v) for v in bbox if _num(v)), reverse=True)[:2]
        if len(sizes) == 2 and not _num(twin.get('blank_length_mm')):
            sp.apply_field(twin, 'blank_length_mm', sizes[0], 'inference')
            sp.apply_field(twin, 'blank_width_mm', sizes[1], 'inference')
            taken.append(f"blank {sizes[0]:g} x {sizes[1]:g} from its own model's outline")
        twin['bound_detail_sheet'] = dict(page=sheet, twin_of=source.get('part_number'))
        why = (f"{twin.get('part_number')} has no drawing of its own; {source.get('part_number')}'s "
               f"number is printed on pages {', '.join(str(p) for p in pages)}. Page {sheet} is taken "
               f"as {twin.get('part_number')}'s sheet (the first after the page that lists it)"
               + (f", priced with {source.get('part_number')}'s " + '; '.join(taken) if taken else '')
               + '.')
        _issue(twin, 'twin_detail_sheet', why,
               assumption=f"Page {sheet} is {twin.get('part_number')}'s drawing, misnumbered.",
               candidate=source.get('part_number'), pages=pages, sheet=sheet)
        _issue(source, 'twin_detail_sheet',
               f"{source.get('part_number')} is printed on pages {', '.join(str(p) for p in pages)}; "
               f"page {sheet} is taken as {twin.get('part_number')}'s drawing, the rest as this part's.",
               assumption='One sheet was copied and not renumbered.', pages=pages, sheet=sheet)


def unresolved(summary):
    """Every judgement this pass took, with its reason. Stated; never a block."""
    out = []
    for part in _parts(summary):
        for issue, finding in (part.get('evidence_safety_issues') or {}).items():
            if (issue == 'unowned_gauge' and part.get('normalized_thickness_mm') is not None
                    and part.get('thickness_source') in _MEASURED | {'llm_assisted', 'title_block'}):
                continue
            if issue in ('metadata_blank', 'unmeasured_flat_pattern') and _measured_geometry(part):
                continue
            out.append(dict(part=part.get('part_number'), issue=issue, **finding))
    return out
