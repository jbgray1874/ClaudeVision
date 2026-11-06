#!/usr/bin/env python3
"""
Pack extract (D-640): a drawing pack read by ONE reader, organised, and handed back — no
estimate.

    python src/pack_extract.py sw  <folder>          --out <dir> --name <drawing>
    python src/pack_extract.py xai <folder|pdf ...>  --out <dir> --name <drawing>
    python src/pack_extract.py sw  --from-extract <_sw_native_extract.json> --out <dir>

JG, 2 Nov 2026: "can we build a SolidWorks drawing pack extract as a new button ... and
organise the output also so that it is meaningful data. Can we also do another button that
just runs an xAI and output exactly the organised, structured xAI output."

The estimate reads a pack through many readers and keeps only what survives arbitration;
the evidence each reader produced is buried in a record nobody opens. These two buttons
show one reader's evidence on its own:

  sw   the SolidWorks analyser (tools/solidworks/sw_native_analyse.py) on the pack's models,
       then the raw extract organised into the tables an estimator reads: every part with
       its material, gauge, flat blank, bends, cut length, mass, volume and envelope; the
       assembly tree with each edge's per-parent count DERIVED the way the engine derives
       it (product total over parent total, or the shared-child split, SCRUM-105) and the
       basis said; the full-depth product BOM; the drawings' own BOM tables; the custom
       properties; and everything the analyser rejected or could not read.
  xai  the whole-document xAI read (llm_full_extract.extract_full_pack) on the pack's PDFs,
       written EXACTLY as returned (JSON), plus the same content laid out as tables.

Outputs, in --out: <name>_solidworks_pack.xlsx / .json, or <name>_xai_extract.xlsx / .json.
The last line printed is PACK_EXTRACT_OUTPUTS=<json list of paths> for the runner.
Nothing is priced and nothing in the pack is changed: the analyser opens every model
read-only and closes it without saving.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

ROOT = Path(__file__).resolve().parents[1]
ANALYSER = ROOT / "tools" / "solidworks" / "sw_native_analyse.py"
OUTPUTS_MARKER = "PACK_EXTRACT_OUTPUTS="

Table = Tuple[List[str], List[List[Any]]]           # (header, rows)

_DOCTYPE = {1: "part", 2: "assembly", 3: "drawing"}


# ── SMALL HELPERS ────────────────────────────────────────────────────────────────────
def _num(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def _r(v: Any, nd: int = 2) -> Any:
    f = _num(v)
    return round(f, nd) if f is not None else (v if v not in (None, "") else "")


def _cell(v: Any) -> Any:
    """A value a spreadsheet cell can hold: scalars as they are, anything else as text."""
    if v is None:
        return ""
    if isinstance(v, (str, int, float, bool)):
        return v
    if isinstance(v, (list, tuple)) and all(isinstance(x, (str, int, float)) for x in v):
        return ", ".join(str(x) for x in v)
    return json.dumps(v, ensure_ascii=False, default=str)


def _code(s: Any) -> str:
    try:
        from source_connectors.solidworks import _clean_pn
        return _clean_pn(str(s or ""))
    except Exception:                                                # noqa: BLE001
        return os.path.splitext(str(s or "").strip())[0]


# ── SOLIDWORKS: THE RAW EXTRACT, ORGANISED ───────────────────────────────────────────
def organise_sw(extract: Dict[str, Any]) -> Dict[str, Table]:
    """The analyser's extract as the tables an estimator reads. Pure: no SolidWorks."""
    from source_connectors.solidworks import (_shared_child_split,
                                              normalize_native_extract)
    records = [r for r in (extract.get("records") or []) if isinstance(r, dict)]
    man = extract.get("_manifest") or {}
    job = normalize_native_extract(records)
    tables: Dict[str, Table] = {}

    # SUMMARY
    kinds: Dict[str, int] = {}
    for r in records:
        k = _DOCTYPE.get(int(r.get("doctype") or 1), "other")
        kinds[k] = kinds.get(k, 0) + 1
    failed = [r for r in records if r.get("errors") and not r.get("route_signals")
              and int(r.get("doctype") or 1) == 1]
    tables["Summary"] = (["item", "value"], [
        ["top assembly", (job.meta or {}).get("top_assembly") or ""],
        ["files read", len(records)],
        ["parts", kinds.get("part", 0)],
        ["assemblies", kinds.get("assembly", 0)],
        ["drawings", kinds.get("drawing", 0)],
        ["parts the analyser could not measure", len(failed)],
        ["assembly edges", sum(len(v) for v in (job.hierarchy or {}).values())],
        ["SolidWorks version", man.get("solidworks_version") or ""],
        ["extract schema", extract.get("schema") or ""],
        ["generated from", man.get("generated_from") or ""],
    ])

    # PARTS — one row per part file, the measured geometry first
    bom_total = {_code(b.part_number).upper(): b.quantity for b in (job.bom or [])}
    rows = []
    for r in records:
        if int(r.get("doctype") or 1) != 1:
            continue
        rs = r.get("route_signals") or {}
        pn = _code(r.get("title") or rs.get("part_number"))
        bbox = [x for x in (rs.get("bbox_mm") or r.get("bbox_mm") or []) if _num(x)]
        vol, area = _num(rs.get("volume_mm3")), _num(rs.get("surface_area_mm2"))
        sec = rs.get("section_profile") if isinstance(rs.get("section_profile"), dict) else {}
        props = r.get("custom_properties") or {}
        rows.append([
            pn,
            props.get("Description") or props.get("DESCRIPTION") or "",
            bom_total.get(pn.upper(), ""),
            rs.get("material") or "", rs.get("material_source") or "",
            "yes" if rs.get("is_sheet_metal") else "no",
            _r(rs.get("thickness_mm")),
            _r(rs.get("flat_length_mm")), _r(rs.get("flat_width_mm")),
            rs.get("bend_count") if rs else "", _r(rs.get("bend_radius_mm")),
            rs.get("hole_count_est") if rs else "", _r(rs.get("cut_length_mm")),
            _r(rs.get("mass_kg"), 4),
            _r(vol / 1000.0, 1) if vol else "", _r(area / 1e6, 4) if area else "",
            " x ".join(f"{float(x):g}" for x in bbox),
            _cell({k: v for k, v in sec.items() if v not in (None, "")}) if sec else "",
            "yes" if rs.get("likely_bought_in") else "",
            _cell(rs.get("ops_hint") or []),
            "; ".join(r.get("errors") or []) or ("not measured" if not rs else ""),
            r.get("path") or "",
        ])
    rows.sort(key=lambda x: str(x[0]))
    tables["Parts"] = ([
        "part", "description", "qty in product (model)", "material", "material source",
        "sheet metal", "gauge mm", "flat length mm", "flat width mm", "bends",
        "bend radius mm", "holes (est)", "cut length mm", "mass kg", "volume cm3",
        "surface m2", "envelope mm", "section", "likely bought-in", "operation hints",
        "read issues", "file"], rows)

    # ASSEMBLY TREE — each edge, with the per-parent count the engine would derive
    parent_total = dict(bom_total)
    for a in (job.assembly_pns or []):
        parent_total.setdefault(_code(a).upper(), 1.0)
    by_child: Dict[str, List[Tuple[str, float]]] = {}
    for parent, kids in (job.hierarchy or {}).items():
        for child, q in kids or ():
            by_child.setdefault(_code(child), []).append((_code(parent), float(q or 1)))
    rows = []
    for child, edges in sorted(by_child.items()):
        total = bom_total.get(child.upper())
        parents = sorted({p for p, _ in edges})
        derived: Dict[str, Any] = {}
        basis = ""
        if len(parents) == 1:
            p = parents[0]
            pt = parent_total.get(p.upper())
            if total and pt and abs(total / pt - round(total / pt)) < 1e-9:
                derived[p] = int(round(total / pt))
                basis = f"{total:g} in the product / {pt:g} of {p}"
            else:
                figs = sorted({q for _, q in edges})
                if len(figs) == 1:
                    derived[p] = figs[0]
                    basis = "the model's edge (no product total divides)"
        else:
            bp = {}
            for p in parents:
                figs = sorted({q for pp, q in edges if pp == p})
                if len(figs) == 1 and parent_total.get(p.upper()):
                    bp[p] = (figs[0], parent_total[p.upper()])
            split, basis = (_shared_child_split(total, bp) if len(bp) == len(parents)
                            else (None, "an edge figure is ambiguous"))
            derived = dict(split or {})
        for p in parents:
            figs = sorted({q for pp, q in edges if pp == p})
            rows.append([p, child, ", ".join(f"{f:g}" for f in figs),
                         _r(parent_total.get(p.upper())), _r(total),
                         derived.get(p, "not derivable"), basis])
    tables["Assembly tree"] = ([
        "parent", "child", "edge figure (as the model reports it)",
        "parent's product total", "child's product total", "per-parent count (derived)",
        "basis"], rows)

    # PRODUCT BOM — the top assembly's full-depth list
    tables["Product BOM"] = (["part", "qty in product", "assembly", "description"], [
        [_code(b.part_number), _r(b.quantity), "yes" if getattr(b, "is_assembly", False)
         else "", getattr(b, "description", "") or ""] for b in (job.bom or [])])

    # DRAWING BOM TABLES — what each SLDDRW's own tables print
    rows = []
    for r in records:
        if int(r.get("doctype") or 0) != 3:
            continue
        for ln in r.get("bom") or []:
            rows.append([_code(r.get("title")), _code(ln.get("part_number")),
                         ln.get("description") or "", _r(ln.get("qty"))])
    tables["Drawing BOM tables"] = (["drawing", "part", "description", "qty"], rows)

    # CUSTOM PROPERTIES
    rows = []
    for r in records:
        for k, v in sorted((r.get("custom_properties") or {}).items()):
            rows.append([_code(r.get("title")), _DOCTYPE.get(int(r.get("doctype") or 1), ""),
                         k, _cell(v)])
    tables["Custom properties"] = (["file", "kind", "property", "value"], rows)

    # READ ISSUES — errors and the analyser's own rejections, never silently dropped
    rows = []
    for r in records:
        for e in r.get("errors") or []:
            rows.append([_code(r.get("title")), "error", e])
        for n in ((r.get("route_signals") or {}).get("notes") or []):
            if "REJECT" in str(n).upper() or "WARNING" in str(n).upper():
                rows.append([_code(r.get("title")), "rejected / warning", n])
    for e in man.get("errors") or []:
        rows.append(["(run)", "error", _cell(e)])
    tables["Read issues"] = (["file", "kind", "detail"], rows)
    return tables


def run_analyser(folder: Path, out_json: Path, python_exe: str = sys.executable) -> Path:
    """Run the analyser on `folder`, writing its extract to `out_json`. Streams its console.

    In turn with every other run on this desktop (D-731): it waits for the desktop's one
    SolidWorks, as the engine's own read does, and a turn that never comes stops the extract."""
    import solidworks_turn                                         # noqa: PLC0415
    cmd = [python_exe, "-u", str(ANALYSER), str(folder), "--out", str(out_json)]
    with solidworks_turn.solidworks_turn() as turn:
        if turn["state"] == solidworks_turn.TIMED_OUT:
            raise SystemExit(solidworks_turn.timed_out_reason(turn))
        print("$ " + " ".join(cmd), flush=True)
        proc = subprocess.run(cmd, cwd=str(ROOT), text=True, encoding="utf-8",
                              errors="replace", stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, timeout=3600)
    path = None
    for line in (proc.stdout or "").splitlines():
        print(line, flush=True)
        if line.startswith("EXTRACT_PATH="):
            path = Path(line.split("=", 1)[1].strip())
    path = path or out_json
    if not path.is_file():
        raise SystemExit(f"the SolidWorks analyser wrote no extract (exit {proc.returncode})")
    return path


# ── xAI: THE WHOLE-DOCUMENT READ, EXACTLY, AND LAID OUT ──────────────────────────────
def _rows_of(items: Iterable[Any]) -> Table:
    """A list of records as one table: the union of their keys, in first-seen order."""
    items = [i for i in items if isinstance(i, dict)]
    keys: List[str] = []
    for i in items:
        for k in i:
            if k not in keys:
                keys.append(k)
    return keys, [[_cell(i.get(k)) for k in keys] for i in items]


def organise_xai(result: Dict[str, Any]) -> Dict[str, Table]:
    """The xAI read as tables. Every list of records becomes a sheet of its own; scalars
    go on the Summary. Private keys (the raw response, the batches) stay in the JSON only."""
    tables: Dict[str, Table] = {}
    summary: List[List[Any]] = []
    for k, v in result.items():
        if k.startswith("_raw"):
            continue
        if isinstance(v, list) and any(isinstance(x, dict) for x in v):
            tables[k.strip("_").replace("_", " ").title()[:31]] = _rows_of(v)
        elif isinstance(v, dict):
            for kk, vv in v.items():
                if isinstance(vv, list) and any(isinstance(x, dict) for x in vv):
                    tables[f"{k} {kk}".strip("_").replace("_", " ").title()[:31]] = \
                        _rows_of(vv)
                else:
                    summary.append([f"{k}.{kk}".strip("_"), _cell(vv)])
        else:
            summary.append([k.strip("_"), _cell(v)])
    out = {"Summary": (["item", "value"], summary)}
    out.update(tables)
    return out


def pdfs_in(paths: Sequence[str]) -> List[str]:
    found: List[str] = []
    for p in paths:
        pp = Path(p)
        if pp.is_dir():
            found += sorted(str(x) for x in pp.iterdir()
                            if x.is_file() and x.suffix.lower() == ".pdf")
        elif pp.suffix.lower() == ".pdf" and pp.is_file():
            found.append(str(pp))
    return found


# ── WRITING ──────────────────────────────────────────────────────────────────────────
def write_xlsx(tables: Dict[str, Table], path: Path, title: str = "") -> Path:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    wb = Workbook()
    wb.remove(wb.active)
    head = PatternFill("solid", fgColor="1F3A5F")
    for name, (header, rows) in tables.items():
        ws = wb.create_sheet(name[:31] or "Sheet")
        ws.append(header)
        for c in ws[1]:
            c.font = Font(bold=True, color="FFFFFF")
            c.fill = head
            c.alignment = Alignment(wrap_text=True, vertical="top")
        for row in rows:
            ws.append([_cell(v) for v in row])
        ws.freeze_panes = "A2"
        if header:
            ws.auto_filter.ref = f"A1:{get_column_letter(len(header))}{max(1, len(rows) + 1)}"
        for i, h in enumerate(header, 1):
            width = max([len(str(h))] + [len(str(r[i - 1])) for r in rows[:200]
                                         if i - 1 < len(r)])
            ws.column_dimensions[get_column_letter(i)].width = min(60, max(10, width + 2))
    if title:
        wb.properties.title = title
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(path))
    return path


def _write_json(obj: Any, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False, default=str),
                    encoding="utf-8")
    return path


def _stem(name: str) -> str:
    import re
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]+', " ", name or "pack").strip(" .") or "pack"


# ── THE TWO JOBS ─────────────────────────────────────────────────────────────────────
def sw_pack(folder: Optional[Path], out: Path, name: str,
            from_extract: Optional[Path] = None, python_exe: str = sys.executable) -> List[Path]:
    stem = _stem(name)
    if from_extract is None:
        if folder is None or not folder.is_dir():
            raise SystemExit(f"no pack folder to read: {folder}")
        from_extract = run_analyser(folder, out / f"{stem}_sw_native_extract.json", python_exe)
    extract = json.loads(Path(from_extract).read_text(encoding="utf-8"))
    tables = organise_sw(extract)
    organised = {name_: {"columns": h, "rows": rows} for name_, (h, rows) in tables.items()}
    return [write_xlsx(tables, out / f"{stem}_solidworks_pack.xlsx",
                       f"{name} — SolidWorks pack extract"),
            _write_json({"pack": name, "tables": organised, "extract": extract},
                        out / f"{stem}_solidworks_pack.json")]


def xai_pack(paths: Sequence[str], out: Path, name: str) -> List[Path]:
    stem = _stem(name)
    pdfs = pdfs_in(paths)
    if not pdfs:
        raise SystemExit("no PDF drawings to read: the xAI extract reads PDFs")
    print(f"   [xai] reading {len(pdfs)} PDF(s): {', '.join(Path(p).name for p in pdfs)}",
          flush=True)
    import llm_full_extract as lfe
    result = lfe.extract_full_pack(pdfs)
    if not result.get("found"):
        print(f"   [xai] the read returned nothing usable: {result.get('error')}", flush=True)
    return [_write_json(result, out / f"{stem}_xai_extract.json"),
            write_xlsx(organise_xai(result), out / f"{stem}_xai_extract.xlsx",
                       f"{name} — xAI extract")]


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Read a drawing pack with one reader and "
                                             "organise what it found (no estimate).")
    ap.add_argument("kind", choices=("sw", "xai"))
    ap.add_argument("paths", nargs="*", help="the pack folder (sw), or folders/PDFs (xai)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--name", default="")
    ap.add_argument("--from-extract", default="",
                    help="sw only: organise an existing _sw_native_extract.json")
    args = ap.parse_args(argv)
    out = Path(args.out)
    name = args.name or (Path(args.paths[0]).name if args.paths else "pack")
    if args.kind == "sw":
        written = sw_pack(Path(args.paths[0]) if args.paths else None, out, name,
                          Path(args.from_extract) if args.from_extract else None)
    else:
        written = xai_pack(args.paths, out, name)
    for p in written:
        print(f"   wrote {p}", flush=True)
    print(OUTPUTS_MARKER + json.dumps([str(p) for p in written]), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
