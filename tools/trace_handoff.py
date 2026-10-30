"""Trace the document-role hand-off for a staged job, in seconds, with no run (D-480).

    C:\\ClaudeVision\\.venv\\Scripts\\python.exe tools\\trace_handoff.py "<staged job folder>" --product KWellnessFSDU

Three K-Wellness runs on 11 Oct 2026 priced a 101-page standards manual's example fixture
because the document-role declarations never reached the staged folder — and each discovery
cost a full run. This asks the four questions the reviewer set, against the exact folder the
engine will read, using the engine's OWN functions (never a copy of their logic):

  1. MARKERS   — is CONCEPT_DOCUMENT.json staged and valid? REFERENCE_DOCUMENTS.json, naming what?
  2. SPLIT     — which PDFs would the scan read as the PRODUCT, which are held OUT as reference?
  3. GATE      — would the concept read fire (client-document mode), or do the ordinary readers rule?
  4. PRODUCT   — does the declared product name match a PRODUCT document (not a reference one)?

Run it the moment the portal says "Staged N drawing(s) into <folder>" — if any line reads
FAIL, stop the run there and fix the named segment. It reads files only: no model, no
pricing, no SDI Live, nothing written.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def trace(folder: Path, product: str = "") -> dict:
    """The four checkpoint answers for one staged folder. Pure reads."""
    import concept_scan as cs

    out: dict = {"folder": str(folder), "ok": True, "lines": []}

    def say(ok: bool, text: str) -> None:
        out["lines"].append(("PASS" if ok else "FAIL", text))
        if not ok:
            out["ok"] = False

    pdfs = sorted(p.name for p in folder.glob("*.pdf")) + \
        sorted(p.name for p in folder.glob("*.PDF") if p.name not in
               {q.name for q in folder.glob("*.pdf")})
    out["pdfs"] = pdfs
    if not pdfs:
        say(False, f"no PDFs in {folder} — nothing staged here")
        return out

    # 1. MARKERS — the portal writes both AFTER staging; absence means the submission
    #    carried no declaration (the service removes stale ones on purpose, D-360/D-474).
    cd = folder / cs.DOCUMENT_MODE_FILENAME
    if cd.is_file():
        try:
            _cd_ok = json.loads(cd.read_text(encoding="utf-8")).get("mode") == "client_document"
        except ValueError:
            _cd_ok = False
        say(_cd_ok, f"{cs.DOCUMENT_MODE_FILENAME}: "
                    + ("valid — client-document mode ON" if _cd_ok else "present but INVALID"))
    else:
        say(False, f"{cs.DOCUMENT_MODE_FILENAME} ABSENT — the submission carried no "
                   f"client-document tick; the concept read will not be forced")
    declared = cs.reference_documents_declared([folder])
    if declared:
        missing = [n for n in declared if n not in pdfs]
        say(not missing, f"{cs.REFERENCE_DOCUMENTS_FILENAME}: declares {declared}"
                         + (f" — NOT among the staged PDFs: {missing}" if missing else ""))
    else:
        say(len(pdfs) == 1,
            f"{cs.REFERENCE_DOCUMENTS_FILENAME} ABSENT — no reference declaration"
            + ("" if len(pdfs) == 1 else
               f"; ALL {len(pdfs)} PDFs will be read as the product"))

    # 2. SPLIT — the same names the scan will hold out (D-477 splits by these basenames).
    held = [n for n in pdfs if n in set(declared)]
    product_docs = [n for n in pdfs if n not in set(declared)]
    out["product_docs"], out["reference_docs"] = product_docs, held
    say(bool(product_docs), f"PRODUCT read: {product_docs or '(nothing!)'}"
                            + (f" · held OUT as reference: {held}" if held else ""))

    # 4. PRODUCT — the declared name should live in a PRODUCT document's own name, never
    #    only in a reference one (D-465's recognition is by containment, space-insensitive).
    if product:
        _p = "".join(ch for ch in product.upper() if ch.isalnum())
        _hit = [n for n in product_docs
                if _p and _p in "".join(ch for ch in n.upper() if ch.isalnum())]
        _ref_hit = [n for n in held
                    if _p and _p in "".join(ch for ch in n.upper() if ch.isalnum())]
        say(bool(_hit), f"declared product {product!r} "
                        + (f"matches product document(s): {_hit}" if _hit else
                           (f"matches only a REFERENCE document: {_ref_hit}" if _ref_hit
                            else "matches NO staged document — the bill will not be its")))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("folder", help="the STAGED job folder the engine will read")
    ap.add_argument("--product", default="", help="the declared product / drawing number")
    args = ap.parse_args()
    res = trace(Path(args.folder), args.product)
    print(f"hand-off trace: {res['folder']}")
    for status, text in res["lines"]:
        print(f"  [{status}] {text}")
    print("  => " + ("HAND-OFF COMPLETE — let the run proceed"
                     if res["ok"] else
                     "STOP — fix the FAIL line(s) above before spending a run"))
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
