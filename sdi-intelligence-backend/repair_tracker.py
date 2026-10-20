"""Repair a tracker workbook that Excel Online refuses because cells typed as
numbers hold text - without losing a single value.

    python repair_tracker.py "NG Tracker.xlsx"
        -> writes "NG Tracker (repaired).xlsx" beside it, and lists every cell it changed

Nick's tracker, 14 October 2026: Excel Online answered FileCorruptTryRepair and
the morning review stopped on "could not convert string to float: 'Completed'".
The file had been rewritten outside Excel, leaving text such as "Completed" in
cells marked as numbers.

EXCEL'S OWN REPAIR DELETES THOSE CELLS. Excel desktop "recovers" such a file by
removing the offending cell values ("Removed Records: Cell information from
/xl/worksheets/sheet1.xml part") - so every Status that read "Completed" would
come back blank. This retypes each one as the text it holds, and copies every
other part of the file byte for byte. Standard library only, so it runs on any
machine with Python; it never touches the original.
"""
from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path

# What Excel itself accepts as a number in a cell's <v>.
_NUMBER = re.compile(r"^\s*[-+]?(\d+(\.\d*)?|\.\d+)([eE][-+]?\d+)?\s*$")
_CELL = re.compile(r"<c\b([^>]*?)(/>|>(.*?)</c>)", re.S)
_TYPE = re.compile(r'\s+t="[^"]*"')
_VALUE = re.compile(r"<v(?:\s[^>]*)?>(.*?)</v>", re.S)


def fix_sheet_xml(xml: str) -> tuple[str, list[tuple[str, str]]]:
    """(fixed xml, [(cell ref, text)]) for one worksheet part."""
    changed: list[tuple[str, str]] = []

    def one(m: re.Match) -> str:
        attrs, inner = m.group(1), m.group(3)
        if inner is None:                                   # <c .../>: no value
            return m.group(0)
        kind = re.search(r'\bt="([^"]*)"', attrs)
        if kind and kind.group(1) != "n":                   # already typed as text, bool, ...
            return m.group(0)
        value = _VALUE.search(inner)
        if not value or value.group(1) == "" or _NUMBER.match(value.group(1)):
            return m.group(0)
        text = value.group(1)
        ref = re.search(r'\br="([^"]*)"', attrs)
        changed.append((ref.group(1) if ref else "?", text))
        bare = _TYPE.sub("", attrs)
        if "<f" in inner:                                   # a formula whose result is text
            return f'<c{bare} t="str">{inner}</c>'
        return f'<c{bare} t="inlineStr"><is><t xml:space="preserve">{text}</t></is></c>'

    return _CELL.sub(one, xml), changed


def _sheet_names(book: zipfile.ZipFile) -> dict[str, str]:
    """Worksheet part ("xl/worksheets/sheet1.xml") -> the tab's name."""
    try:
        wb = book.read("xl/workbook.xml").decode("utf-8")
        rels = book.read("xl/_rels/workbook.xml.rels").decode("utf-8")
    except KeyError:
        return {}
    target = {m.group(1): m.group(2) for m in
              re.finditer(r'<Relationship\b[^>]*\bId="([^"]+)"[^>]*\bTarget="([^"]+)"', rels)}
    target.update({m.group(2): m.group(1) for m in
                   re.finditer(r'<Relationship\b[^>]*\bTarget="([^"]+)"[^>]*\bId="([^"]+)"', rels)})
    names = {}
    for m in re.finditer(r'<sheet\b[^>]*\bname="([^"]+)"[^>]*\br:id="([^"]+)"', wb):
        part = target.get(m.group(2), "")
        part = part.lstrip("/") if part.startswith("/") else "xl/" + part
        names[part] = m.group(1)
    return names


def repair(data: bytes) -> tuple[bytes, list[tuple[str, str, str]]]:
    """(repaired workbook, [(sheet, cell, text)]). Unchanged bytes if nothing is wrong."""
    import io
    src = zipfile.ZipFile(io.BytesIO(data))
    names = _sheet_names(src)
    out, report = io.BytesIO(), []
    with zipfile.ZipFile(out, "w") as dst:
        for info in src.infolist():
            raw = src.read(info.filename)
            if info.filename.startswith("xl/worksheets/") and info.filename.endswith(".xml"):
                fixed, changed = fix_sheet_xml(raw.decode("utf-8"))
                if changed:
                    raw = fixed.encode("utf-8")
                    report += [(names.get(info.filename, info.filename), ref, text)
                               for ref, text in changed]
            dst.writestr(info, raw, compress_type=info.compress_type)
    return (out.getvalue() if report else data), report


def main(argv: list[str]) -> int:
    if len(argv) != 1 or not Path(argv[0]).is_file():
        print(__doc__.split("\n\n")[1])
        return 2
    source = Path(argv[0])
    fixed, report = repair(source.read_bytes())
    if not report:
        print("Nothing to repair: no cell typed as a number holds text.")
        return 0
    target = source.with_name(f"{source.stem} (repaired){source.suffix}")
    target.write_bytes(fixed)
    print(f"{len(report)} cell(s) held text in a number cell; each is now text, value unchanged:")
    for sheet, ref, text in report[:200]:
        print(f"  {sheet}!{ref}: {text}")
    if len(report) > 200:
        print(f"  ... and {len(report) - 200} more")
    try:
        import io
        import openpyxl
        book = openpyxl.load_workbook(io.BytesIO(fixed), data_only=True)
        cells = sum(1 for ws in book.worksheets for row in ws.iter_rows() for _ in row)
        print(f"Checked: the repaired copy reads cleanly ({cells} cells).")
    except ImportError:
        pass
    except Exception as exc:  # noqa: BLE001
        print(f"!! The repaired copy still does not read cleanly: {type(exc).__name__}: {exc}")
        return 1
    print(f"Written: {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
