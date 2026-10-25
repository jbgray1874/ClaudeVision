"""Owned stock and manufacturing coverage, independent of job and input format.

This adapter only removes unsupported page-vector cutting on positively identified
solid bar. It does not decide weld rates, joinery stages or internal features.
Unresolved coverage uses the existing owned-specification release invariant.
"""
import re


def key(value):
    return str(value or '').strip().upper()


def own_pages(part, pages):
    pn = key(part.get('part_number'))
    if not pn:
        return []
    result = []
    for page in pages or []:
        tb = (page.get('page_analysis') or {}).get('title_block') or {}
        owners = {key(x) for x in tb.get('drawing_numbers') or []}
        # Recover only a single exact title-block suffix, never a BOM mention.
        fallback = (owners <= {'', 'REVISION'} and
                    page.get('page_number') in (part.get('pages') or []) and
                    any(key(x).endswith(' ' + pn) for x in tb.get('project_titles') or []))
        if owners == {pn} or fallback:
            result.append(page)
    return result


def page_text(page):
    return str(page.get('pdfplumber_text') or page.get('normalized_text') or '')


def solid_bar(part, pages):
    """Read only a headed cut-list row, not arbitrary page dimensions."""
    found = []
    number = r'(\d+(?:[.,]\d+)?)'
    pattern = re.compile(r'^\s*\d+\s+1\s+' + number + r'\s*[X×]\s*' + number +
                         r'\s*(?:MM\s*)?(?:SQUARE\s+|FLAT\s+)?BAR\s+' + number + r'\s*(?:MM)?\s*$', re.I)
    for page in own_pages(part, pages):
        text = page_text(page)
        if not re.search(r'ITEM\s+QTY\s+DESCRIPTION\s+LENGTH', text, re.I):
            continue
        for line in text.splitlines():
            match = pattern.fullmatch(line)
            if not match:
                continue
            a, b, length = [float(x.replace(',', '.')) for x in match.groups()]
            if min(a, b, length) <= 0 or length <= max(a, b):
                continue
            found.append(dict(a=a, b=b, length_mm=length, stock_form='solid_bar',
                              source='own_sheet_cut_list', page=page.get('page_number'),
                              file=page.get('source_pdf_path') or page.get('source_pdf_name'), text=line.strip()))
    shapes = {(x['a'], x['b'], x['length_mm']) for x in found}
    return found[0] if len(shapes) == 1 else None


def stamp(parts, summary):
    for part in parts:
        bar = solid_bar(part, summary.get('pages'))
        if bar:
            part['owned_bar_evidence'] = bar
        notes = []
        for page in own_pages(part, summary.get('pages')):
            for line in page_text(page).splitlines():
                # A standalone process label is captured, not used to infer runs/rates.
                if line.strip().upper() == 'TIG':
                    notes.append(dict(process='TIG', page=page.get('page_number'),
                                      file=page.get('source_pdf_path'), text=line.strip()))
        if notes:
            part['owned_weld_process_evidence'] = notes


def bar_area(part):
    e = part.get('owned_bar_evidence') or {}
    if e.get('source') != 'own_sheet_cut_list':
        return 0.0
    # Outer faces plus both ends; contact masking remains an allowance.
    return (2 * (e['a'] + e['b']) * e['length_mm'] + 2 * e['a'] * e['b']) / 1e6


def filter_cutting(part, operations):
    """A saw does not itself disprove laser work. All guards must hold."""
    if not part.get('owned_bar_evidence') or not {'saw', 'laser_cutting'} <= set(operations):
        return operations
    if (part.get('flat_pattern_detected') or part.get('dxf_files') or part.get('dxf_sources')
            or part.get('dxf_pieces') or part.get('flat_pattern_source')
            or (part.get('operation_evidence') or {}).get('laser_cutting')):
        return operations
    from detail_page_geometry import machining_is_measured
    if machining_is_measured(part):
        return operations
    source = (part.get('operation_sources') or {}).get('laser_cutting', '')
    if source not in ('', 'inference', 'geometry', 'page_vectors'):
        return operations
    geom = part.get('normalized_geometry') or {}
    if not geom.get('raw_cut_length_mm'):
        return operations
    reason = ('Own cut list identifies solid bar, already sawn; unsupported page-vector laser '
              'removed. Internal machining remains unverified; confirm features separately.')
    part.setdefault('operations_ruled_out', {})['laser_cutting'] = reason
    part['owned_bar_cutting_review'] = reason
    for field in ('textual_operations', 'inferred_operations', 'operations'):
        if isinstance(part.get(field), list):
            part[field] = [x for x in part[field] if x != 'laser_cutting']
    return [x for x in operations if x != 'laser_cutting']


def row_parts(row):
    value = row.get('part_numbers') or []
    return {key(x) for x in (re.split(r'[,;\s]+', value) if isinstance(value, str) else value) if x}


# A hot-melt bonding note, as printed: hyphenated, run together, or with a dropped letter.
_HOT_MELT = re.compile(r'\b(?:HOT|HOLT)\s*-?\s*MELT(?:\s+(?:GLUE|ADHESIVE))?\b', re.I)


def findings(summary):
    """Calculated rows, not proposed operations, decide what reached the book.

    Each finding is graded (D-598r). A CONTRADICTION - the drawing states work the book does
    not charge at all - blocks a firm price through the existing release invariant. UNRESOLVED
    scope - a priced allowance, a likely overlap, a basis not yet verified - keeps its money
    and is put to a person as a ruling; it holds the firm price without hiding the estimate.
    """
    parts = [p for p in (summary.get('manufacturing_writeup') or {}).get('parts') or [] if isinstance(p, dict)]
    # A STAMPED READ-BACK IS AUTHORITATIVE EVEN WHEN ITS LABOUR TABLE IS EMPTY (D-598s): the
    # book was calculated and charges no labour, so a stated weld with no row is a
    # contradiction. With no read-back at all nothing was checked, and each requirement the
    # rows would have settled is raised as not evaluated, never passed in silence. A labour
    # block the adapter could not read is stamped empty too; that is no read-back, not a
    # book that charges nothing.
    fe = summary.get('final_estimate')
    read_back = (isinstance(fe, dict) and isinstance(fe.get('labour_rows'), list)
                 and not any(isinstance(p, dict) and p.get('block') == 'labour'
                             for p in fe.get('adapter_problems') or []))
    rows = fe['labour_rows'] if read_back else []
    prices = {key(p.get('part_number')): p for p in
              (summary.get('estimate_summary') or {}).get('part_estimates') or []}
    pages = summary.get('pages') or []
    out = []

    def add(kind, part_number, operation, message, assumption, action):
        out.append(dict(kind=kind, part=part_number, operation=operation, message=message,
                        assumption=assumption, action=action))

    for part in parts:
        pn = key(part.get('part_number'))
        mine = [r for r in rows if pn in row_parts(r)]
        bar = part.get('owned_bar_evidence') or solid_bar(part, pages)
        if bar:
            laser = [r for r in mine if 'LASER' in key(r.get('operation'))]
            saw = [r for r in mine if 'SAW' in key(r.get('operation'))]
            if not read_back:
                add('not_evaluated', pn, 'laser_cutting',
                    f'{pn}: its own sheet identifies solid bar, and its cutting rows could not be '
                    'checked: no calculated workbook was read back.', '', '')
            elif laser and saw:
                add('unresolved', pn, 'laser_cutting',
                    f'{pn}: solid bar has saw and laser charges at ' +
                    ', '.join(str(r.get('charged_cell')) for r in saw + laser) +
                    '. Confirm distinct cutting features; page lines do not establish laser work.',
                    'both cutting rows stay charged', 'confirm the laser features, or strike the laser row')
            if part.get('owned_bar_cutting_review'):
                add('unresolved', pn, 'laser_cutting', f'{pn}: {part["owned_bar_cutting_review"]}',
                    'sawn to length, no internal machining charged',
                    'confirm the bar has no holes or slots, or add them to the route')
            mat = (prices.get(pn) or {}).get('material_estimate') or {}
            if mat.get('stock_form') not in ('solid_bar', 'section'):
                add('unresolved', pn, '',
                    f'{pn}: drawing identifies solid bar, but its purchase/price basis is not '
                    'a recorded bar or section basis. Verify the stock rate; do not borrow a tube rate.',
                    'the material line stands at the price it was given',
                    'confirm the bar purchase rate and unit')
        tig = part.get('owned_weld_process_evidence') or [
            pg for pg in own_pages(part, pages) if re.search(r'^\s*TIG\s*$', page_text(pg), re.M)]
        if tig and not read_back:
            add('not_evaluated', pn, 'welding',
                f'{pn}: its own sheet states TIG, and its weld charge could not be checked: no '
                'calculated workbook was read back.', '', '')
        elif tig:
            weld = [r for r in mine if 'WELD' in key(r.get('operation')) and 'DRESS' not in key(r.get('operation'))]
            wrong = [r for r in weld if 'TIG' not in key(r.get('operation')) + ' ' + key(r.get('department'))]
            if not weld:
                add('contradiction', pn, 'welding',
                    f'{pn}: its own sheet states TIG and no weld is charged. Charge the weld, or '
                    'record why it is not this part\'s.', '', '')
            elif wrong:
                add('unresolved', pn, 'welding',
                    f'{pn}: own-sheet TIG is charged on a non-TIG row (' +
                    ', '.join(str(r.get('charged_cell')) for r in wrong) + '). CO2 is not proof of '
                    'TIG pricing: confirm a sourced TIG rate and the joint/run coverage.',
                    'the weld is priced at the CO2 rate as a TIG allowance',
                    'give the TIG rate, or confirm the CO2 rate stands for this job')
        pc = ((prices.get(pn) or {}).get('material_estimate') or {}).get('powder_consumable') or {}
        if pc.get('coated_area_source') == 'sum_of_members_blanks':
            add('unresolved', pn, 'powder_coating',
                f'{pn}: powder area uses member blank/section allowances, not verified coated surfaces. '
                'Confirm included and excluded members, openings, edges and contact masking.',
                'coated on the members\' blank and section areas',
                'confirm the coated members and surface, or accept the allowance')
    # One assembly note and multiple glue rows is a coverage question, not proof
    # of duplicate work. Keep all money until distinct stages or a correction exist.
    # THE COMPILED ROUTE KNOWS THE ASSEMBLIES (D-598s): a GA is often a node with children and
    # no part record of its own, and its sheet is where the bonding note is printed.
    graph = {key(n.get('part_number')): n for n in
             ((summary.get('estimate_summary') or {}).get('canonical_route_shadow') or {}).get('nodes') or []
             if isinstance(n, dict) and n.get('part_number')}
    known = {key(p.get('part_number')) for p in parts}
    candidates = parts + [n for k, n in graph.items() if k not in known and n.get('kind') == 'assembly']
    for parent in candidates:
        owned = own_pages(parent, pages)
        if not any(_HOT_MELT.search(' '.join(page_text(pg).split())) for pg in owned):
            continue
        children = {key(x) for x in parent.get('assembly_children') or []}
        children.update(key(p.get('part_number')) for p in parts for edge in p.get('bom_parents') or []
                        if key(edge.get('parent')) == key(parent.get('part_number')))
        children.update(key(c.get('part_number') if isinstance(c, dict) else c) for c in
                        (graph.get(key(parent.get('part_number'))) or {}).get('children') or [])
        children.discard('')
        scope = children | {key(parent.get('part_number'))}
        glue = [r for r in rows if 'GLUE' in key(r.get('operation')) and row_parts(r) & scope]
        if not read_back:
            add('not_evaluated', str(parent.get('part_number')), 'glue',
                f'{parent.get("part_number")}: its own sheet states hot-melt bonding, and its glue '
                'charges could not be checked: no calculated workbook was read back.', '', '')
        elif not glue:
            add('unresolved', str(parent.get('part_number')), 'glue',
                f'{parent.get("part_number")}: its own sheet states hot-melt bonding and no glue '
                'row charges it. Confirm it is inside an assembly row, or add the bonding.',
                'no separate bonding charge', 'name the row that covers the bond, or add a glue row')
        elif len(glue) > 1:
            add('unresolved', str(parent.get('part_number')), 'glue',
                f'{parent.get("part_number")}: stated hot-melt bonding reaches multiple rows (' +
                ', '.join(str(r.get('charged_cell')) for r in glue) +
                '). Joint/stage allocation is unresolved; retain charges until evidenced, not silently deduplicated.',
                'every glue row stays charged', 'rule: separate bonding stages, or strike the duplicate row')
    seen, unique = set(), []
    for f in out:
        if f['message'] not in seen:
            seen.add(f['message'])
            unique.append(f)
    return unique


def audit(summary):
    """Confirmed contradictions only, for the existing blocking release invariant."""
    return [f['message'] for f in findings(summary) if f['kind'] == 'contradiction']


def unresolved(summary):
    """Unresolved scope, raised as rulings: priced, visible, and holding the firm price."""
    return [f for f in findings(summary) if f['kind'] == 'unresolved']


def not_evaluated(summary):
    """Requirements the calculated rows would settle, where no rows were read back (D-598s)."""
    return [f for f in findings(summary) if f['kind'] == 'not_evaluated']
