import json
import sys
from pathlib import Path
from decimal import Decimal, InvalidOperation

import pyodbc


def first_scalar(value):
    if isinstance(value, list):
        for item in value:
            if item not in (None, '', []):
                return item
        return None
    return value


def join_list(value):
    if value is None:
        return None
    if isinstance(value, list):
        out = []
        for v in value:
            if isinstance(v, (dict, list)):
                continue
            if v is None:
                continue
            s = str(v).strip()
            if s:
                out.append(s)
        return ' | '.join(dict.fromkeys(out)) or None
    if isinstance(value, (dict, tuple, set)):
        return None
    s = str(value).strip()
    return s or None


def to_decimal(value):
    value = first_scalar(value)
    if value in (None, '', 'null'):
        return None
    try:
        return Decimal(str(value).replace(',', '').strip())
    except (InvalidOperation, ValueError):
        return None


def to_int(value):
    d = to_decimal(value)
    return int(d) if d is not None else None


def to_str(value):
    value = first_scalar(value)
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def get_ci(d, *keys):
    if not isinstance(d, dict):
        return None
    lower = {str(k).lower(): v for k, v in d.items()}
    for k in keys:
        if k.lower() in lower:
            return lower[k.lower()]
    return None


def json_text(value):
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False)


def upsert_json_file(cur, data, source_name=None):
    runmeta = data.get('runmetadata', {}) or {}
    doc = data.get('documentanalysis', {}) or {}
    primary = doc.get('primaryfields', {}) or {}
    conf = doc.get('confidence', {}) or {}
    pdf = data.get('pdfmetadata', {}) or {}

    run_uuid = to_str(get_ci(runmeta, 'runuuid'))
    if not run_uuid:
        raise ValueError(f'Missing runuuid in {source_name}')

    cur.execute("DELETE FROM dbo.drawing_part WHERE scan_run_id IN (SELECT scan_run_id FROM dbo.drawing_scan_run WHERE run_uuid = ?)", run_uuid)
    cur.execute("DELETE FROM dbo.drawing_page WHERE scan_run_id IN (SELECT scan_run_id FROM dbo.drawing_scan_run WHERE run_uuid = ?)", run_uuid)
    cur.execute("DELETE FROM dbo.drawing_document WHERE scan_run_id IN (SELECT scan_run_id FROM dbo.drawing_scan_run WHERE run_uuid = ?)", run_uuid)
    cur.execute("DELETE FROM dbo.drawing_scan_run WHERE run_uuid = ?", run_uuid)

    cur.execute(
        """
        INSERT INTO dbo.drawing_scan_run (
            run_uuid, source_file_stem, source_file_version, source_file_version_label,
            source_file_versioned_name, database_schema_version, source_file, full_path,
            scanned_at, page_count, pdf_title, pdf_author, pdf_creator, pdf_producer,
            pdf_creation_date, pdf_mod_date, raw_json
        )
        OUTPUT INSERTED.scan_run_id
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        run_uuid,
        to_str(get_ci(runmeta, 'sourcefilestem')),
        to_int(get_ci(runmeta, 'sourcefileversion')),
        to_str(get_ci(runmeta, 'sourcefileversionlabel')),
        to_str(get_ci(runmeta, 'sourcefileversionedname')),
        to_str(get_ci(runmeta, 'databaseschemaversion')),
        to_str(get_ci(data, 'sourcefile')),
        to_str(get_ci(data, 'fullpath')),
        to_str(get_ci(data, 'scannedat')),
        to_int(get_ci(data, 'pagecount')),
        to_str(get_ci(pdf, 'Title')),
        to_str(get_ci(pdf, 'Author')),
        to_str(get_ci(pdf, 'Creator')),
        to_str(get_ci(pdf, 'Producer')),
        to_str(get_ci(pdf, 'CreationDate')),
        to_str(get_ci(pdf, 'ModDate')),
        json.dumps(data, ensure_ascii=False)
    )
    scan_run_id = cur.fetchval()

    est = data.get('estimatesummary', {}) or {}
    cur.execute(
        """
        INSERT INTO dbo.drawing_document (
            scan_run_id, drawing_number, revision, material, normalized_material,
            finish, normalized_finish, colour, quantity, thickness_mm,
            normalized_thickness_mm, overall_length_mm, overall_width_mm,
            titleblock_confidence, dimensions_confidence, processnotes_confidence,
            overall_confidence, document_total_estimated_cost_gbp,
            raw_document_analysis_json, raw_estimate_summary_json, raw_manual_review_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        scan_run_id,
        to_str(get_ci(primary, 'drawingnumber')),
        to_str(get_ci(primary, 'revision')),
        to_str(get_ci(primary, 'material')),
        to_str(get_ci(primary, 'normalizedmaterial')),
        to_str(get_ci(primary, 'finish')),
        to_str(get_ci(primary, 'normalizedfinish')),
        to_str(get_ci(primary, 'colour')),
        to_decimal(get_ci(primary, 'quantity')),
        to_decimal(get_ci(primary, 'thicknessmm')),
        to_decimal(get_ci(primary, 'normalizedthicknessmm')),
        to_decimal(get_ci(primary, 'overalllengthmm')),
        to_decimal(get_ci(primary, 'overallwidthmm')),
        to_decimal(get_ci(conf, 'titleblock')),
        to_decimal(get_ci(conf, 'dimensions')),
        to_decimal(get_ci(conf, 'processnotes')),
        to_decimal(get_ci(conf, 'overall')),
        to_decimal(get_ci(data, 'documenttotalestimatedcostgbp')),
        json_text(doc),
        json_text(est),
        json_text(get_ci(data, 'manualreviewitems'))
    )

    pages = get_ci(data, 'pages') or []
    for page in pages:
        pconf = get_ci(page, 'confidence') or {}
        pprimary = get_ci(page, 'primaryfields') or {}
        cur.execute(
            """
            INSERT INTO dbo.drawing_page (
                scan_run_id, page_number, primary_role, page_role_hint, word_count,
                page_width_points, page_height_points, drawing_number, revision,
                material, normalized_material, finish, normalized_finish, colour,
                quantity, thickness_mm, normalized_thickness_mm, overall_length_mm,
                overall_width_mm, titleblock_confidence, dimensions_confidence,
                processnotes_confidence, overall_confidence, pdfplumber_text,
                pypdf_text, normalized_text, text_preview, raw_page_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            scan_run_id,
            to_int(get_ci(page, 'pagenumber')),
            to_str(get_ci(get_ci(page, 'pagerole') or {}, 'primaryrole')),
            to_str(get_ci(page, 'pagerolehint')),
            to_int(get_ci(page, 'wordcount')),
            to_decimal(get_ci(page, 'pagewidth')),
            to_decimal(get_ci(page, 'pageheight')),
            to_str(get_ci(pprimary, 'drawingnumber')),
            to_str(get_ci(pprimary, 'revision')),
            to_str(get_ci(pprimary, 'material')),
            to_str(get_ci(pprimary, 'normalizedmaterial')),
            to_str(get_ci(pprimary, 'finish')),
            to_str(get_ci(pprimary, 'normalizedfinish')),
            to_str(get_ci(pprimary, 'colour')),
            to_decimal(get_ci(pprimary, 'quantity')),
            to_decimal(get_ci(pprimary, 'thicknessmm')),
            to_decimal(get_ci(pprimary, 'normalizedthicknessmm')),
            to_decimal(get_ci(pprimary, 'overalllengthmm')),
            to_decimal(get_ci(pprimary, 'overallwidthmm')),
            to_decimal(get_ci(pconf, 'titleblock')),
            to_decimal(get_ci(pconf, 'dimensions')),
            to_decimal(get_ci(pconf, 'processnotes')),
            to_decimal(get_ci(pconf, 'overall')),
            to_str(get_ci(page, 'pdfplumbertext')),
            to_str(get_ci(page, 'pypdftext')),
            to_str(get_ci(page, 'normalizedtext')),
            to_str(get_ci(page, 'textpreview')),
            json.dumps(page, ensure_ascii=False)
        )

    part_map = {}
    mw = data.get('manufacturingwriteup', {}) or {}
    for part in get_ci(mw, 'parts') or []:
        pn = to_str(get_ci(part, 'partnumber'))
        if pn:
            part_map[pn] = part
    for part in get_ci(est, 'partestimates') or []:
        pn = to_str(get_ci(part, 'partnumber'))
        if pn and pn not in part_map:
            part_map[pn] = {}
        if pn:
            part_map[pn]['_estimate'] = part

    for pn, part in part_map.items():
        est_part = part.get('_estimate', {}) or {}
        manuf = get_ci(part, 'manufacturinginterpretation') or {}
        geom = get_ci(part, 'geometryrollup') or {}
        cur.execute(
            """
            INSERT INTO dbo.drawing_part (
                scan_run_id, part_number, item_number, description, quantity, page_refs,
                page_roles, drawing_numbers, revisions, materials, normalized_material,
                surface_finishes, normalized_finish, colours, thicknesses_mm,
                normalized_thickness_mm, overall_length_mm, overall_width_mm,
                process_notes, process_note_types, textual_operations, routing_confidence,
                review_required, geometry_reliability, estimated_cut_length_mm,
                estimated_hole_count, estimated_slotlike_features, estimated_bendline_count,
                estimated_pierce_count, unit_total_cost_gbp, extended_total_cost_gbp,
                raw_part_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            scan_run_id,
            pn,
            to_str(get_ci(part, 'itemnumber')),
            to_str(get_ci(part, 'description')),
            to_decimal(get_ci(part, 'quantity')),
            join_list(get_ci(part, 'pages')),
            join_list(get_ci(part, 'pageroles')),
            join_list(get_ci(part, 'drawingnumbers')),
            join_list(get_ci(part, 'revisions')),
            join_list(get_ci(part, 'materials')),
            to_str(get_ci(part, 'normalizedmaterial')),
            join_list(get_ci(part, 'surfacefinishes')),
            to_str(get_ci(part, 'normalizedfinish')),
            join_list(get_ci(part, 'colours')),
            join_list(get_ci(part, 'thicknessesmm')),
            to_decimal(get_ci(part, 'normalizedthicknessmm')),
            to_decimal(get_ci(part, 'overalllengthmm')),
            to_decimal(get_ci(part, 'overallwidthmm')),
            join_list(get_ci(part, 'processnotes')),
            join_list(get_ci(part, 'processnotetypes')),
            join_list(get_ci(part, 'textualoperations')),
            to_decimal(get_ci(manuf, 'routingconfidence')),
            1 if get_ci(manuf, 'reviewrequired') is True else 0 if get_ci(manuf, 'reviewrequired') is False else None,
            to_decimal(get_ci(manuf, 'geometryreliability')),
            to_decimal(get_ci(geom, 'estimatedcutlengthmm')),
            to_int(get_ci(geom, 'estimatedholecount')),
            to_int(get_ci(geom, 'estimatedslotlikefeatures')),
            to_int(get_ci(geom, 'estimatedbendlinecount')),
            to_int(get_ci(geom, 'estimatedpiercecount')),
            to_decimal(get_ci(est_part, 'unittotalcostgbp')),
            to_decimal(get_ci(est_part, 'extendedtotalcostgbp')),
            json.dumps({'manufacturingwriteup_part': part, 'estimate_part': est_part}, ensure_ascii=False)
        )


def load_folder(connection_string, folder):
    conn = pyodbc.connect(connection_string)
    conn.autocommit = False
    try:
        cur = conn.cursor()
        for path in sorted(Path(folder).glob('*.json')):
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            upsert_json_file(cur, data, source_name=path.name)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == '__main__':
    if len(sys.argv) < 3:
        raise SystemExit('Usage: python load_drawings.py "DRIVER={ODBC Driver 18 for SQL Server};SERVER=server;DATABASE=db;Trusted_Connection=yes;Encrypt=yes;TrustServerCertificate=yes" C:/path/to/jsons')
    load_folder(sys.argv[1], sys.argv[2])