import json
import sys
from pathlib import Path
from decimal import Decimal, InvalidOperation
from datetime import datetime
import uuid

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


def parse_uuid(value):
    s = to_str(value)
    if not s:
        return None
    return str(uuid.UUID(s))


def upsert_json_file(cur, data, source_name=None):
    runmeta = data.get('runmetadata', {}) or {}
    doc = data.get('documentanalysis', {}) or {}
    primary = doc.get('primaryfields', {}) or {}
    conf = doc.get('confidence', {}) or {}
    pdf = data.get('pdfmetadata', {}) or {}

    run_uuid = parse_uuid(get_ci(runmeta, 'runuuid'))
    if not run_uuid:
        raise ValueError(f'Missing valid runuuid in {source_name}')

    cur.execute("DELETE FROM dbo.drawing_part WHERE run_uuid = ?", run_uuid)
    cur.execute("DELETE FROM dbo.drawing_page WHERE run_uuid = ?", run_uuid)
    cur.execute("DELETE FROM dbo.drawing_document WHERE run_uuid = ?", run_uuid)
    cur.execute("DELETE FROM dbo.drawing_scan_run WHERE run_uuid = ?", run_uuid)

    scanned_at = get_ci(runmeta, 'scannedat') or get_ci(data, 'scannedat')
    if isinstance(scanned_at, str):
        try:
            scanned_at = datetime.fromisoformat(scanned_at.replace('Z', '+00:00'))
        except Exception:
            scanned_at = None

    cur.execute(
        """
        INSERT INTO dbo.drawing_scan_run (
            run_uuid, source_file_name, source_file_stem, source_file_version,
            source_file_version_label, source_file_versioned_name, source_pdf_path,
            scanned_at, page_count, validation_status, latest_json_path,
            archive_json_path, raw_summary_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        run_uuid,
        to_str(get_ci(runmeta, 'sourcefilename')) or source_name,
        to_str(get_ci(runmeta, 'sourcefilestem')),
        to_int(get_ci(runmeta, 'sourcefileversion')),
        to_str(get_ci(runmeta, 'sourcefileversionlabel')),
        to_str(get_ci(runmeta, 'sourcefileversionedname')),
        to_str(get_ci(runmeta, 'sourcepdfpath')) or to_str(get_ci(data, 'sourcefile')),
        scanned_at,
        to_int(get_ci(runmeta, 'pagecount')) or to_int(get_ci(data, 'pagecount')),
        to_str(get_ci(runmeta, 'validationstatus')),
        to_str(get_ci(runmeta, 'latestjsonpath')),
        to_str(get_ci(runmeta, 'archivejsonpath')),
        json_text(get_ci(runmeta, 'rawsummaryjson') or get_ci(data, 'rawsummaryjson') or data),
    )

    est = data.get('estimatesummary', {}) or {}
    cur.execute(
        """
        INSERT INTO dbo.drawing_document (
            run_uuid, drawing_number, revision, material, normalized_material,
            finish, normalized_finish, colour, quantity, thickness_mm,
            normalized_thickness_mm, overall_length_mm, overall_width_mm,
            titleblock_confidence, dimensions_confidence, processnotes_confidence,
            overall_confidence, document_total_estimated_cost_gbp,
            raw_document_analysis_json, raw_estimate_summary_json, raw_manual_review_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        run_uuid,
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
        json_text(get_ci(data, 'manualreviewitems')),
    )

    pages = get_ci(data, 'pages') or []
    for page in pages:
        pconf = get_ci(page, 'confidence') or {}
        pprimary = get_ci(page, 'primaryfields') or {}
        cur.execute(
            """
            INSERT INTO dbo.drawing_page (
                run_uuid, page_number, page_role, word_count, page_width, page_height,
                labels_found, pattern_summary, title_block_calibration, region_text,
                page_analysis, geometry_summary, text_preview
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            run_uuid,
            to_int(get_ci(page, 'pagenumber')),
            to_str(get_ci(page, 'pagerole')),
            to_int(get_ci(page, 'wordcount')),
            to_decimal(get_ci(page, 'pagewidth')),
            to_decimal(get_ci(page, 'pageheight')),
            join_list(get_ci(page, 'labelsfound')),
            to_str(get_ci(page, 'patternsummary')),
            json_text(get_ci(page, 'titleblockcalibration')),
            to_str(get_ci(page, 'regiontext')),
            json_text(get_ci(page, 'pageanalysis')),
            json_text(get_ci(page, 'geometrysummary')),
            to_str(get_ci(page, 'textpreview')),
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
                run_uuid, part_number, item_number, description, quantity, page_roles,
                pages, materials, surface_finishes, colours, revisions,
                drawing_numbers, thicknesses_mm, dimensions_mm, angles_deg,
                hole_sizes_mm, slot_sizes_mm, process_notes, operations,
                manufacturing_features, manufacturing_interpretation, geometry_rollup,
                part_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            run_uuid,
            pn,
            to_str(get_ci(part, 'itemnumber')),
            to_str(get_ci(part, 'description')),
            to_int(get_ci(part, 'quantity')),
            join_list(get_ci(part, 'pageroles')),
            join_list(get_ci(part, 'pages')),
            join_list(get_ci(part, 'materials')),
            join_list(get_ci(part, 'surfacefinishes')),
            join_list(get_ci(part, 'colours')),
            join_list(get_ci(part, 'revisions')),
            join_list(get_ci(part, 'drawingnumbers')),
            join_list(get_ci(part, 'thicknessesmm')),
            join_list(get_ci(part, 'dimensionsmm')),
            join_list(get_ci(part, 'anglesdeg')),
            join_list(get_ci(part, 'holesizesmm')),
            join_list(get_ci(part, 'slotsizesmm')),
            join_list(get_ci(part, 'processnotes')),
            join_list(get_ci(part, 'operations')),
            join_list(get_ci(part, 'manufacturingfeatures')),
            json_text(manuf),
            json_text(geom),
            json.dumps({'manufacturingwriteup_part': part, 'estimate_part': est_part}, ensure_ascii=False),
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