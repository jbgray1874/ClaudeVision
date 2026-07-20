"""
STANDALONE BOM Extractor to SQL Server
- PDF folder mode: reads BOM tables from drawings (ITEM / DWG / DESCRIPTION / QTY or LENGTH layouts).
  By default scans **recursively** under the given folder (``**/*.pdf``). Pass ``--no-recurse`` for
  top-level PDFs only.
- JSON mode (--json): reads the full scan + estimate JSON and inserts one row per part from
  ``manufacturing_writeup.parts`` merged with ``estimate_summary.part_estimates`` (materials,
  thicknesses, finishes, operations, geometry rollup, risk flags — **no pricing**).

Dynamic INSERT from ``sys.columns`` (non-identity, non-computed). Add nullable columns in SQL
then map them in row dicts; see ``sql/extend_drawing_bom_items_pipeline_columns.sql`` for suggested
pipeline columns.

Optional env: BOM_SQL_DRIVER, BOM_SQL_SERVER, BOM_SQL_DATABASE, BOM_SQL_USERNAME, BOM_SQL_PASSWORD.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pdfplumber
import pyodbc

# ========================== DB CONFIG (override with BOM_SQL_* env vars) ==========================
DB_CONFIG = {
    "driver": "ODBC Driver 18 for SQL Server",
    "server": "10.0.0.200",
    "database": "SDILive",
    "username": "AIBot",
    "password": "AIAgentPW2026",
}

TABLE_NAME = "dbo.drawing_bom_items"

# Optional columns this script can populate once added on the server (all NULL-safe):
#   ALTER TABLE dbo.drawing_bom_items ADD drawing_revision NVARCHAR(16) NULL;
#   ALTER TABLE dbo.drawing_bom_items ADD bom_table_sequence INT NULL;
#   ALTER TABLE dbo.drawing_bom_items ADD extraction_engine NVARCHAR(64) NULL;
#   ALTER TABLE dbo.drawing_bom_items ADD extraction_trace NVARCHAR(MAX) NULL;
# Pipeline JSON mode also maps: material, thickness_mm, finish, colour, width_mm, operations,
# risk_flags, extraction_source, pipeline_part_json, source_json_path, process_notes, page_roles,
# json_part_confidence, routing_steps_json, primary_operation, estimated_route_time_min
# (see sql/extend_drawing_bom_items_pipeline_columns.sql).


def _env(name: str, default: Optional[str] = None) -> Optional[str]:
    v = os.environ.get(name, "")
    v = v.strip() if isinstance(v, str) else ""
    return v if v else default


def get_db_connection():
    driver = _env("BOM_SQL_DRIVER", DB_CONFIG["driver"])
    server = _env("BOM_SQL_SERVER", DB_CONFIG["server"])
    database = _env("BOM_SQL_DATABASE", DB_CONFIG["database"])
    username = _env("BOM_SQL_USERNAME", DB_CONFIG["username"])
    password = _env("BOM_SQL_PASSWORD", DB_CONFIG["password"])
    conn_str = (
        f"DRIVER={{{driver}}};"
        f"SERVER={server};"
        f"DATABASE={database};"
        f"UID={username};"
        f"PWD={password};"
        "Encrypt=yes;TrustServerCertificate=yes;"
    )
    return pyodbc.connect(conn_str, timeout=30)


def get_text_column_lengths(cursor) -> Dict[str, Optional[int]]:
    cursor.execute(
        """
        SELECT COLUMN_NAME, CHARACTER_MAXIMUM_LENGTH
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = 'dbo'
          AND TABLE_NAME = 'drawing_bom_items'
          AND DATA_TYPE IN ('varchar', 'nvarchar', 'char', 'nchar')
        """
    )
    lengths: Dict[str, Optional[int]] = {}
    for col, max_len in cursor.fetchall():
        lengths[str(col).lower()] = None if int(max_len) == -1 else int(max_len)
    return lengths


def get_insert_column_names(cursor) -> List[str]:
    """Ordered non-identity, non-computed columns suitable for INSERT."""
    cursor.execute(
        """
        SELECT LOWER(c.name)
        FROM sys.columns c
        WHERE c.object_id = OBJECT_ID(N'dbo.drawing_bom_items')
          AND c.is_identity = 0
          AND c.is_computed = 0
        ORDER BY c.column_id
        """
    )
    return [str(r[0]) for r in cursor.fetchall()]


def trim_to_max(value: Any, max_len: Optional[int]) -> str:
    text = "" if value is None else str(value)
    if max_len is None:
        return text
    return text[:max_len]


def sql_bracket_ident(name: str) -> str:
    if not re.match(r"^[a-z0-9_]+$", name, re.I):
        raise ValueError(f"Unsafe SQL column name: {name!r}")
    return f"[{name}]"


def revision_from_drawing_stem(stem: str) -> Optional[str]:
    """
    Typical GA PDF filenames end with _REVD / _REVC / _REVE etc.
    Returns e.g. 'REVD' or None if no match.
    """
    u = (stem or "").upper().strip()
    m = re.search(r"_(REV[A-Z]+\d?)$", u)
    return m.group(1) if m else None


def optional_trace_json(page_number: int, bom_table_sequence: int) -> str:
    """Compact JSON for an optional ``extraction_trace`` / ``raw_extraction_json`` style column."""
    return json.dumps({"page": page_number, "bom_table_sequence": bom_table_sequence}, separators=(",", ":"))


# ========================== PARSING HELPERS ==========================
def extract_upc_from_text(text: str) -> Optional[str]:
    match = re.search(r"\b0\d{6}\b", text or "")
    return match.group(0) if match else None


def norm_header(cell: Any) -> str:
    text = str(cell or "").upper().replace("\n", " ").strip()
    text = re.sub(r"[^A-Z0-9 ]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def looks_like_bom_header(header_cells: List[str]) -> bool:
    h = " | ".join(header_cells)
    has_item = ("ITEM" in h) or ("BE ITEM" in h)
    has_desc = "DESCRIPTION" in h
    has_qty_or_len = ("QTY" in h) or ("QUANTITY" in h) or ("LENGTH" in h)
    return has_item and has_desc and has_qty_or_len


def build_column_map(header_row: List[Any]) -> Dict[str, int]:
    mapping: Dict[str, int] = {}
    normalized = [norm_header(col) for col in header_row]
    for idx, token in enumerate(normalized):
        if not token:
            continue
        if "ITEM" in token and "item" not in mapping:
            mapping["item"] = idx
        if ("DWG" in token or "DRAWING" in token) and "dwg_no" not in mapping:
            mapping["dwg_no"] = idx
        if "DESCRIPTION" in token and "description" not in mapping:
            mapping["description"] = idx
        if ("QTY" in token or "QUANTITY" in token) and "quantity" not in mapping:
            mapping["quantity"] = idx
        if "LENGTH" in token and "length" not in mapping:
            mapping["length"] = idx
    return mapping


def safe_cell(row: List[Any], idx: Optional[int]) -> str:
    if idx is None or idx < 0 or idx >= len(row):
        return ""
    return str(row[idx] or "").strip()


def parse_quantity(text: str) -> int:
    if not text:
        return 0
    try:
        return int(round(float(text)))
    except Exception:
        return 0


def parse_length_mm(text: str) -> Optional[float]:
    if not text:
        return None
    m = re.search(r"[-+]?\d+(?:\.\d+)?", text)
    if not m:
        return None
    try:
        return float(m.group(0))
    except Exception:
        return None


def normalize_item_number(item_text: str) -> str:
    text = (item_text or "").strip()
    nums = re.findall(r"\d+", text)
    if len(nums) >= 2 and len(set(nums)) == 1:
        # Common OCR/table artifact: "1 1" -> "1"
        return nums[0]
    return text


def normalize_dwg_no(dwg_text: str, expected_prefix: Optional[str]) -> str:
    text = (dwg_text or "").strip().upper()
    if expected_prefix and text.startswith("1234-") and expected_prefix.startswith("11234"):
        # Common missing-leading-digit artifact for this drawing family.
        text = "1" + text
    return text


def split_merged_row(
    item_number: str,
    dwg_no: str,
    description: str,
    quantity: int,
    length_mm: Optional[float],
    length_raw: str,
) -> List[Dict[str, Any]]:
    item_tokens = re.findall(r"\d+", item_number or "")
    dwg_tokens = re.findall(r"\b\d{4,6}-[A-Z0-9-]+\b", (dwg_no or "").upper())

    unique_items = []
    for token in item_tokens:
        if token not in unique_items:
            unique_items.append(token)
    unique_dwgs = []
    for token in dwg_tokens:
        if token not in unique_dwgs:
            unique_dwgs.append(token)

    split_count = max(len(unique_items), len(unique_dwgs))
    if split_count <= 1:
        return [
            {
                "item_number": item_number,
                "dwg_no": dwg_no,
                "description": description,
                "quantity": quantity,
                "length_mm": length_mm,
                "length_raw": length_raw,
            }
        ]

    # Split quantity safely when merged row has 0/empty quantity.
    per_row_qty = quantity if quantity > 0 else 1
    rows: List[Dict[str, Any]] = []
    for i in range(split_count):
        rows.append(
            {
                "item_number": unique_items[i] if i < len(unique_items) else (unique_items[-1] if unique_items else item_number),
                "dwg_no": unique_dwgs[i] if i < len(unique_dwgs) else (unique_dwgs[-1] if unique_dwgs else dwg_no),
                # Description tokenization is unreliable in OCR tables; keep full text to avoid data loss.
                "description": description,
                "quantity": per_row_qty,
                "length_mm": length_mm,
                "length_raw": length_raw,
            }
        )
    return rows


def fix_description_clipping(row: List[Any], desc_idx: Optional[int], description: str, mapped_indices: set) -> str:
    # Handles cases like "SEND" extracted as ["S", "END"] across adjacent columns.
    if desc_idx is None:
        return description
    if desc_idx > 0 and desc_idx < len(row):
        left_idx = desc_idx - 1
        if left_idx not in mapped_indices:
            left = str(row[left_idx] or "").strip()
            if len(left) == 1 and left.isalpha() and description and not description.startswith(left):
                return f"{left}{description}"
    return description


def extract_bom_tables(pdf_path: str) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    upc: Optional[str] = None
    drawing_number = Path(pdf_path).stem.upper()
    drawing_revision = revision_from_drawing_stem(drawing_number)
    bom_table_sequence = 0

    expected_dwg_prefix_match = re.search(r"_(\d{5})_", drawing_number)
    expected_dwg_prefix = expected_dwg_prefix_match.group(1) if expected_dwg_prefix_match else None

    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages, 1):
            text = page.extract_text() or ""
            if not upc:
                upc = extract_upc_from_text(text)

            for table in page.extract_tables() or []:
                if not table or len(table) < 2:
                    continue

                header_idx = None
                col_map: Dict[str, int] = {}
                for i in range(min(3, len(table))):
                    header_cells = [norm_header(c) for c in (table[i] or [])]
                    if looks_like_bom_header(header_cells):
                        candidate_map = build_column_map(table[i])
                        if "item" in candidate_map and "description" in candidate_map and (
                            "quantity" in candidate_map or "length" in candidate_map or "dwg_no" in candidate_map
                        ):
                            header_idx = i
                            col_map = candidate_map
                            break
                if header_idx is None:
                    continue

                bom_table_sequence += 1
                mapped = set(col_map.values())
                for row in table[header_idx + 1 :]:
                    if not row:
                        continue
                    item_number = normalize_item_number(safe_cell(row, col_map.get("item")))
                    dwg_no = normalize_dwg_no(safe_cell(row, col_map.get("dwg_no")), expected_dwg_prefix)
                    description = safe_cell(row, col_map.get("description"))
                    quantity_text = safe_cell(row, col_map.get("quantity"))
                    length_text = safe_cell(row, col_map.get("length"))

                    description = fix_description_clipping(row, col_map.get("description"), description, mapped)
                    quantity = parse_quantity(quantity_text)
                    length_mm = parse_length_mm(length_text)

                    split_rows = split_merged_row(
                        item_number=item_number,
                        dwg_no=dwg_no,
                        description=description,
                        quantity=quantity,
                        length_mm=length_mm,
                        length_raw=length_text,
                    )
                    for parsed in split_rows:
                        if not parsed["item_number"] and not parsed["description"]:
                            continue
                        base: Dict[str, Any] = {
                            "drawing_number": drawing_number,
                            "upc": upc or "UNKNOWN",
                            "page_number": page_num,
                            "item_number": parsed["item_number"],
                            "dwg_no": parsed["dwg_no"],
                            "description": parsed["description"],
                            "quantity": parsed["quantity"],
                            "length_mm": parsed["length_mm"],
                            "length_raw": parsed["length_raw"],
                            "bom_table_sequence": bom_table_sequence,
                            "extraction_engine": "pdfplumber_v1",
                            "extraction_source": "table",
                        }
                        if drawing_revision is not None:
                            base["drawing_revision"] = drawing_revision
                        trace = optional_trace_json(page_num, bom_table_sequence)
                        base["extraction_trace"] = trace
                        results.append(base)
    return results


# ========================== PIPELINE JSON (v4) ==========================
def _safe_join(items: Any, sep: str = ", ") -> Optional[str]:
    if not items:
        return None
    if isinstance(items, str):
        t = items.strip()
        return t or None
    if isinstance(items, (list, tuple)):
        bits = [str(x).strip() for x in items if str(x).strip()]
        return sep.join(bits) if bits else None
    return str(items)


def _first_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def _first_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _first_page_number(part: Dict[str, Any]) -> int:
    pages = part.get("pages")
    if isinstance(pages, list) and pages:
        v = _first_int(pages[0])
        return int(v) if v is not None else 0
    return 0


def _index_part_estimates(estimates: Any) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    if not isinstance(estimates, list):
        return out
    for row in estimates:
        if not isinstance(row, dict):
            continue
        key = str(row.get("part_number") or row.get("item_number") or "").strip().upper()
        if key:
            out[key] = row
    return out


def _material_line_no_pricing(est: Dict[str, Any]) -> Dict[str, Any]:
    me = est.get("material_estimate")
    if not isinstance(me, dict):
        return {}
    allow = {
        "material",
        "thickness_mm",
        "blank_length_mm",
        "blank_width_mm",
        "blank_area_m2",
        "unit_material_mass_kg",
        "stock_form",
        "requires_flat_blank",
        "stock_estimate",
        "powder_consumable",
    }
    return {k: me.get(k) for k in allow if k in me}


def _process_line_no_pricing(est: Dict[str, Any]) -> Dict[str, Any]:
    pe = est.get("process_estimate")
    if not isinstance(pe, dict):
        return {}
    return {
        "unit_time_min": pe.get("unit_time_min"),
        "total_time_min": pe.get("total_time_min"),
        "times_min": pe.get("times_min"),
    }


def _pipeline_json_blob(mfg: Optional[Dict[str, Any]], est: Optional[Dict[str, Any]]) -> str:
    blob: Dict[str, Any] = {
        "normalized_geometry": None,
        "geometry_rollup": None,
        "manufacturing_features": (mfg or {}).get("manufacturing_features") if mfg else None,
        "manufacturing_interpretation": (mfg or {}).get("manufacturing_interpretation") if mfg else None,
        "textual_operations": (mfg or {}).get("textual_operations") if mfg else None,
        "inferred_operations": (mfg or {}).get("inferred_operations") if mfg else None,
        "material_estimate": _material_line_no_pricing(est or {}),
        "process_estimate": _process_line_no_pricing(est or {}),
    }
    if isinstance((mfg or {}).get("geometry_rollup"), dict):
        blob["geometry_rollup"] = mfg.get("geometry_rollup")
    elif isinstance((est or {}).get("geometry_rollup"), dict):
        blob["geometry_rollup"] = est.get("geometry_rollup")
    if isinstance((est or {}).get("normalized_geometry"), dict):
        blob["normalized_geometry"] = est.get("normalized_geometry")
    elif isinstance((mfg or {}).get("normalized_geometry"), dict):
        blob["normalized_geometry"] = mfg.get("normalized_geometry")
    try:
        return json.dumps(blob, ensure_ascii=False, default=str, separators=(",", ":"))
    except TypeError:
        return "{}"


def _drawing_number_from_json(data: Dict[str, Any], json_path: Path) -> str:
    tb = (data.get("document_analysis") or {}).get("title_block") or {}
    dns = tb.get("drawing_numbers") or []
    if isinstance(dns, list) and dns:
        return str(dns[0]).strip().upper()
    src = str(data.get("source_file") or json_path.name)
    return Path(src).stem.upper()


def _upc_from_json(data: Dict[str, Any]) -> Optional[str]:
    for page in data.get("pages") or []:
        if not isinstance(page, dict):
            continue
        hit = extract_upc_from_text(page.get("pdfplumber_text") or "")
        if hit:
            return hit
    ps = (data.get("document_analysis") or {}).get("pattern_summary") or {}
    for blob in ps.get("part_numbers") or []:
        hit = extract_upc_from_text(str(blob))
        if hit:
            return hit
    return None


def _merge_operations(mfg: Optional[Dict[str, Any]]) -> Optional[str]:
    if not mfg:
        return None
    ops: List[str] = []
    for key in ("textual_operations", "inferred_operations"):
        raw = mfg.get(key)
        if isinstance(raw, list):
            for op in raw:
                s = str(op).strip()
                if s and s not in ops:
                    ops.append(s)
    return ", ".join(ops) if ops else None


def _json_part_confidence(mfg: Optional[Dict[str, Any]], est: Optional[Dict[str, Any]]) -> Optional[float]:
    """
    Best available overall confidence for the part (0..1), from estimate JSON first, then manufacturing.
    """
    for src in (est, mfg):
        if not isinstance(src, dict):
            continue
        me = src.get("material_estimate")
        if isinstance(me, dict):
            v = me.get("part_confidence_overall")
            f = _first_float(v)
            if f is not None:
                return round(min(1.0, max(0.0, f)), 4)
        conf = src.get("confidence")
        if isinstance(conf, dict):
            v = conf.get("overall")
            if v is None and conf:
                nums = [_first_float(x) for x in conf.values()]
                nums = [x for x in nums if x is not None]
                if nums:
                    v = sum(nums) / len(nums)
            f = _first_float(v)
            if f is not None:
                return round(min(1.0, max(0.0, f)), 4)
    return None


def _routing_steps_json(mfg: Optional[Dict[str, Any]]) -> Optional[str]:
    """Serialised process_router steps from ``manufacturing_interpretation.routing``."""
    if not mfg:
        return None
    mi = mfg.get("manufacturing_interpretation")
    if not isinstance(mi, dict):
        return None
    r = mi.get("routing")
    if not isinstance(r, list) or not r:
        return None
    try:
        return json.dumps(r, ensure_ascii=False, default=str, separators=(",", ":"))
    except TypeError:
        return None


def _primary_operation(mfg: Optional[Dict[str, Any]]) -> Optional[str]:
    """First meaningful operation from routing, else first textual/inferred op (excluding handling)."""
    if not mfg:
        return None
    mi = mfg.get("manufacturing_interpretation")
    if isinstance(mi, dict):
        r = mi.get("routing")
        if isinstance(r, list):
            for step in r:
                if not isinstance(step, dict):
                    continue
                op = str(step.get("operation") or "").strip()
                if op and op.lower() != "handling":
                    return op
    for key in ("textual_operations", "inferred_operations"):
        raw = mfg.get(key)
        if isinstance(raw, list):
            for op in raw:
                s = str(op).strip()
                if s and s.lower() != "handling":
                    return s
    return None


def _estimated_route_time_min(est: Optional[Dict[str, Any]]) -> Optional[float]:
    """Total routed process time from estimate ``process_estimate.total_time_min`` (minutes)."""
    if not est:
        return None
    pe = est.get("process_estimate")
    if not isinstance(pe, dict):
        return None
    return _first_float(pe.get("total_time_min"))


def _build_pipeline_row(
    *,
    data: Dict[str, Any],
    mfg: Optional[Dict[str, Any]],
    est: Optional[Dict[str, Any]],
    drawing_number: str,
    upc: str,
    json_path: Path,
) -> Optional[Dict[str, Any]]:
    src = mfg or est
    if not isinstance(src, dict):
        return None
    pn = str(src.get("part_number") or src.get("item_number") or "").strip()
    if not pn:
        return None

    quantity = _first_int(src.get("quantity")) or 1
    description = str(src.get("description") or "").strip()

    mats = (mfg or {}).get("materials") if mfg else None
    material = (
        str((mfg or {}).get("normalized_material") or "").strip()
        or (_safe_join(mats) or "")
        or str(((est or {}).get("material_estimate") or {}).get("material") or "").strip()
        or None
    )

    thickness: Optional[float] = None
    if mfg:
        thickness = _first_float(mfg.get("normalized_thickness_mm"))
        if thickness is None and isinstance(mfg.get("thicknesses_mm"), list) and mfg["thicknesses_mm"]:
            thickness = _first_float(mfg["thicknesses_mm"][0])
    if thickness is None and est:
        thickness = _first_float((est.get("material_estimate") or {}).get("thickness_mm"))

    finish = _safe_join((mfg or {}).get("surface_finishes")) if mfg else None
    colour = _safe_join((mfg or {}).get("colours")) if mfg else None

    length_mm = _first_float((mfg or {}).get("overall_length_mm")) if mfg else None
    width_mm = _first_float((mfg or {}).get("overall_width_mm")) if mfg else None
    if length_mm is None and est:
        length_mm = _first_float((est.get("material_estimate") or {}).get("blank_length_mm"))
    if width_mm is None and est:
        width_mm = _first_float((est.get("material_estimate") or {}).get("blank_width_mm"))

    risk_list: List[str] = []
    if est and isinstance(est.get("risk_flags"), list):
        risk_list.extend(str(x).strip() for x in est["risk_flags"] if str(x).strip())
    if mfg and isinstance(mfg.get("risk_flags"), list):
        for rf in mfg["risk_flags"]:
            s = str(rf).strip()
            if s and s not in risk_list:
                risk_list.append(s)

    page_no = _first_page_number(mfg) if mfg else 0
    process_notes = _safe_join((mfg or {}).get("process_notes"), sep="; ") if mfg else None
    page_roles = _safe_join((mfg or {}).get("page_roles")) if mfg else None

    stem = Path(str(data.get("source_file") or json_path.name)).stem
    drawing_revision = revision_from_drawing_stem(stem.upper())

    trace = {
        "part_number": pn,
        "source_file": str(data.get("source_file") or json_path.name),
        "schema": data.get("schema"),
    }

    row: Dict[str, Any] = {
        "drawing_number": drawing_number,
        "upc": upc or "UNKNOWN",
        "page_number": page_no,
        "item_number": pn,
        "dwg_no": str((mfg or {}).get("dwg_no") or "").strip() or drawing_number,
        "description": description or None,
        "quantity": quantity,
        "material": material,
        "thickness_mm": thickness,
        "finish": finish,
        "colour": colour,
        "length_mm": length_mm,
        "width_mm": width_mm,
        "operations": _merge_operations(mfg),
        "risk_flags": ", ".join(risk_list) if risk_list else None,
        "process_notes": process_notes,
        "page_roles": page_roles,
        "extraction_source": "json_pipeline",
        "extraction_engine": "professional_manufacturing_json_v4",
        "extraction_trace": json.dumps(trace, separators=(",", ":")),
        "pipeline_part_json": _pipeline_json_blob(mfg, est),
        "source_json_path": str(json_path.resolve()),
        "json_part_confidence": _json_part_confidence(mfg, est),
        "routing_steps_json": _routing_steps_json(mfg),
        "primary_operation": _primary_operation(mfg),
        "estimated_route_time_min": _estimated_route_time_min(est),
    }
    if drawing_revision is not None:
        row["drawing_revision"] = drawing_revision
    return row


def extract_from_pipeline_json(data: Dict[str, Any], json_path: Path) -> List[Dict[str, Any]]:
    """
    Build BOM rows from the rich scan JSON (manufacturing_writeup.parts + estimate_summary.part_estimates).
    Omits pricing fields; keeps geometry / operations / risk / material context.
    """
    mfg_parts = (data.get("manufacturing_writeup") or {}).get("parts") or data.get("parts") or []
    if not isinstance(mfg_parts, list):
        mfg_parts = []
    estimates = (data.get("estimate_summary") or {}).get("part_estimates") or []
    idx = _index_part_estimates(estimates)

    drawing_number = _drawing_number_from_json(data, json_path)
    upc = _upc_from_json(data) or "UNKNOWN"

    seen: set[str] = set()
    rows: List[Dict[str, Any]] = []

    for mfg in mfg_parts:
        if not isinstance(mfg, dict):
            continue
        key = str(mfg.get("part_number") or mfg.get("item_number") or "").strip().upper()
        if not key:
            continue
        seen.add(key)
        est = idx.get(key)
        built = _build_pipeline_row(data=data, mfg=mfg, est=est, drawing_number=drawing_number, upc=upc, json_path=json_path)
        if built:
            rows.append(built)

    for est in estimates if isinstance(estimates, list) else []:
        if not isinstance(est, dict):
            continue
        key = str(est.get("part_number") or est.get("item_number") or "").strip().upper()
        if not key or key in seen:
            continue
        built = _build_pipeline_row(data=data, mfg=None, est=est, drawing_number=drawing_number, upc=upc, json_path=json_path)
        if built:
            rows.append(built)

    return rows


def build_insert_row(
    raw: Dict[str, Any],
    insert_columns: Sequence[str],
    col_lengths: Dict[str, Optional[int]],
) -> Tuple[List[str], List[Any], bool]:
    """
    Pick values from ``raw`` for columns that exist on the server.
    String columns are trimmed to max length when metadata is present.
    Returns (columns, values, any_string_was_trimmed).
    """
    cols: List[str] = []
    vals: List[Any] = []
    trimmed_hit = False
    for c in insert_columns:
        if c not in raw:
            continue
        v = raw[c]
        if c in col_lengths:
            if isinstance(v, str) and col_lengths[c] is not None and len(v) > col_lengths[c]:
                trimmed_hit = True
            v = trim_to_max(v, col_lengths[c])
        cols.append(c)
        vals.append(v)
    return cols, vals, trimmed_hit


def qualified_table_sql(table: str) -> str:
    parts = [p.strip() for p in table.split(".") if p.strip()]
    return ".".join(sql_bracket_ident(p) for p in parts)


def execute_dynamic_insert(cursor, table: str, cols: List[str], vals: List[Any]) -> None:
    if not cols:
        raise RuntimeError("No columns to insert (row had no matching table columns)")
    ident = qualified_table_sql(table)
    col_sql = ", ".join(sql_bracket_ident(c) for c in cols)
    placeholders = ", ".join("?" * len(cols))
    cursor.execute(f"INSERT INTO {ident} ({col_sql}) VALUES ({placeholders})", *vals)


def iter_pdf_files(root: Path, *, recursive: bool) -> List[Path]:
    """PDF paths under ``root``, sorted for stable runs. Recursive by default (nested job folders)."""
    if recursive:
        paths = list(root.rglob("*.pdf"))
    else:
        paths = list(root.glob("*.pdf"))
    return sorted(paths, key=lambda p: str(p).lower())


def _pdf_display_path(pdf_file: Path, root: Path) -> str:
    try:
        return str(pdf_file.relative_to(root))
    except ValueError:
        return str(pdf_file)


# ========================== MAIN ==========================
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract BOM from PDF tables or from full pipeline JSON into dbo.drawing_bom_items"
    )
    parser.add_argument(
        "folder",
        nargs="?",
        default=None,
        help="Folder containing PDF drawings (table extraction). Scans subfolders by default; see --no-recurse.",
    )
    parser.add_argument(
        "--no-recurse",
        action="store_true",
        help="PDF folder mode: only *.pdf in the top-level folder (no subfolders).",
    )
    parser.add_argument(
        "--json",
        type=str,
        default=None,
        help="Path to a full scan/estimate JSON file (v4 pipeline). Inserts rich BOM rows (no pricing).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse only; print row count and first row keys (no INSERT).",
    )
    parser.add_argument(
        "--list-columns",
        action="store_true",
        help="Print insertable columns for dbo.drawing_bom_items and exit (no PDF/JSON scan).",
    )
    args = parser.parse_args()

    conn = get_db_connection()
    cursor = conn.cursor()
    insert_columns = get_insert_column_names(cursor)
    col_lengths = get_text_column_lengths(cursor)

    if args.list_columns:
        print("Insertable columns on dbo.drawing_bom_items (in order):")
        for c in insert_columns:
            ln = col_lengths.get(c)
            ln_s = "max" if ln is None else str(ln)
            print(f"  - {c}  (nvarchar max len: {ln_s})")
        conn.close()
        return

    if args.json:
        json_path = Path(args.json)
        if not json_path.is_file():
            print(f"ERROR: JSON file not found: {json_path}")
            conn.close()
            return
        with json_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            print("ERROR: JSON root must be an object.")
            conn.close()
            return

        bom_rows = extract_from_pipeline_json(data, json_path)
        print(f"Pipeline JSON: {json_path}")
        print(f"  -> {len(bom_rows)} BOM row(s) built from manufacturing_writeup / estimate_summary")

        if args.dry_run:
            if bom_rows:
                print("  [dry-run] sample keys:", sorted(bom_rows[0].keys()))
            conn.close()
            return

        total_trimmed = 0
        for row in bom_rows:
            cols, vals, was_trimmed = build_insert_row(row, insert_columns, col_lengths)
            if was_trimmed:
                total_trimmed += 1
            execute_dynamic_insert(cursor, TABLE_NAME, cols, vals)
        conn.commit()
        conn.close()
        print(f"\nDONE: {len(bom_rows)} BOM row(s) saved to {TABLE_NAME}")
        if total_trimmed:
            print(f"WARNING: {total_trimmed} row(s) had text trimmed to fit SQL column lengths")
        return

    if not args.folder:
        print("ERROR: Provide a PDF folder, or use --json <path>, or --list-columns.")
        conn.close()
        return

    folder = Path(args.folder)
    if not folder.exists():
        print(f"ERROR: Folder not found: {folder}")
        conn.close()
        return

    total_inserted = 0
    total_trimmed = 0
    recursive = not args.no_recurse

    print(f"Scanning folder: {folder} ({'recursive **/*.pdf' if recursive else 'top-level *.pdf only'})\n")

    pdf_files = iter_pdf_files(folder, recursive=recursive)
    if not pdf_files:
        print(f"WARNING: No PDF files found under {folder}")
        conn.close()
        return

    for pdf_file in pdf_files:
        rel = _pdf_display_path(pdf_file, folder)
        print(f"Processing: {rel}")
        bom_rows = extract_bom_tables(str(pdf_file))

        for row in bom_rows:
            cols, vals, was_trimmed = build_insert_row(row, insert_columns, col_lengths)
            if was_trimmed:
                total_trimmed += 1
            if args.dry_run:
                continue
            execute_dynamic_insert(cursor, TABLE_NAME, cols, vals)
            total_inserted += 1

        if args.dry_run:
            print(f"   [dry-run] {len(bom_rows)} rows would be inserted")
        else:
            conn.commit()
            print(f"   -> {len(bom_rows)} rows inserted")

    conn.close()
    if args.dry_run:
        print(f"\nDRY-RUN: no rows written. Would process {len(pdf_files)} PDF(s) under {folder}")
        return

    print(f"\nDONE: {total_inserted} BOM rows saved to {TABLE_NAME}")
    if total_trimmed:
        print(f"WARNING: {total_trimmed} row(s) had text trimmed to fit SQL column lengths")


if __name__ == "__main__":
    main()
