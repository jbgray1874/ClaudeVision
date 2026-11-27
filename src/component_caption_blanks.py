"""Separate blanks for named flat panels sharing one drawing, never a stock-sheet size."""
import re
import source_precedence as sp

_CAPTION = re.compile(r'^.+\b(?:SIDE|TOP|BASE) PANEL\s*$', re.I)
_NUMBER = re.compile(r'^\s*(\d+(?:\.\d+)?)\s*$')

def _key(text):
    return re.sub(r'[^A-Z0-9]+', '', str(text or '').upper())

def repair(summary):
    parts=(summary.get('manufacturing_writeup') or {}).get('parts') or summary.get('parts') or []
    changed=[]
    for page in summary.get('pages') or []:
        # pypdf preserves the reading order of rotated numeric text on these sheets;
        # pdfplumber reverses 1050 to 0501. Never reverse digits heuristically.
        text=page.get('pypdf_text') or page.get('pdfplumber_text') or page.get('normalized_text') or ''
        lines=text.splitlines()
        captions=[i for i,line in enumerate(lines) if _CAPTION.match(line.strip())]
        if len(captions)<2:
            continue
        previous=-1
        for index in captions:
            caption=lines[index].strip()
            # Two printed axes immediately before this component's own caption.
            values=[float(m.group(1)) for m in (_NUMBER.match(line) for line in lines[previous+1:index])
                    if m and float(m.group(1))>30]
            previous=index
            if len(values)!=2:
                continue
            caption_pages=[pg for pg in summary.get('pages') or []
                if _key(caption) in _key(pg.get('pypdf_text') or pg.get('pdfplumber_text') or pg.get('normalized_text'))]
            hits=[p for p in parts if _key(p.get('description'))==_key(caption)
                  and (page.get('page_number') in (p.get('pages') or [])
                       or (not p.get('pages') and len(caption_pages)==1))]
            if len(hits)!=1:
                continue
            part=hits[0]
            if (part.get('component_caption_blank')
                    and [part.get('blank_length_mm'),part.get('blank_width_mm')]==values):
                continue
            if any(sp.rank(sp.source_of(part,k))>70 for k in ('blank_length_mm','blank_width_mm')):
                continue
            geom=part.get('normalized_geometry') or {}
            if str(geom.get('geometry_source') or '').lower() in ('dxf','solidworks','solidworks_api'):
                continue
            old=(part.get('component_caption_blank') or {}).get('replaced') or {
                k:part.get(k) for k in ('blank_length_mm','blank_width_mm')}
            for field,value in zip(('blank_length_mm','blank_width_mm'),values):
                # Withdraw the sheet-wide envelope before submitting the component's
                # own printed axes. Original values remain in the evidence record.
                part[field]=None
                sp.apply_field(part,field,value,'drawing_deterministic')
            part['component_caption_blank']={'caption':caption,'page':page.get('page_number'),
                'source_pdf':page.get('source_pdf_name'),'printed_axes_mm':values,'replaced':old}
            part['blank_length_mm_source']='drawing_deterministic'
            part['blank_width_mm_source']='drawing_deterministic'
            flag=(
                f"Separate component blank from '{caption}' on page {page.get('page_number')}: "
                f'{values[0]:g} x {values[1]:g} mm; not the shared stock-sheet dimensions.')
            if flag not in part.setdefault('review_flags',[]):
                part['review_flags'].append(flag)
            changed.append(part.get('part_number'))
    return changed
