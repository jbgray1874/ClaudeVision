r"""
test_the_drawing_picker_can_see_drawings.py

A JOB FOLDER OF THIRTY FILES LISTED AS TWO, AND OFFERED "Add all 2".

The share browser filtered what it displayed by config.ALLOWED_EXTENSIONS — a DOCUMENT
list, which answers "may this file be sent to a browser". That same listing is the drawing
picker on the estimating page, where the question is "may this file go into a job". The two
lists overlap on exactly one drawing type:

    staging.DRAWING_SUFFIXES   .pdf .dxf .dwg .sldprt .sldasm .slddrw .step .stp
    config.ALLOWED_EXTENSIONS  .doc .docx .htm .html .jpeg .jpg .json .log .md .pdf .png …

So 12552-InfinityDrawer — 19 SLDPRT, 7 SLDASM, 1 SLDDRW, 1 DWG, 1 PDF and the SolidWorks
sidecar — showed the PDF and the .json and nothing else, and read as a pack that had gone
missing off the share. It had not. "Use this folder" stages by DRAWING_SUFFIXES and had been
taking all 29 every run: `Staged 29 drawing(s)`, which is 19+7+1+1+1 exactly. The picker was
asking the wrong question and answering it accurately.

DXF IS THE ONE THAT WOULD HAVE COST MONEY. The picker cannot see a DXF, and a DXF drop is
what this pack is waiting on. An estimator adding files one at a time would have watched
nothing arrive with no reason to doubt the screen.

WHY THIS DOES NOT IMPORT app.py. Two modules in this repository are called `config` — the
engine's and the portal's — and under the full suite `src` is already on sys.path, so
`import app` binds the wrong one and dies in config.validate(). Importing it here would make
this test pass alone and break the run. So the constants are loaded from their own files by
path, and the wiring is checked against app.py's source: values from the real lists, and a
structural check that the listing consults the union rather than the document list.

LISTING IS NOT SERVING, AND THAT MUST NOT COLLAPSE. /api/file re-checks _allowed_ext and
returns 415, so a model appears in the browser and still cannot be fetched. The last test
pins that the two predicates stayed separate — widening a filter next to a writable share is
exactly where a quiet mistake would matter.
"""
from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "sdi-intelligence-backend"


def _load_by_path(name: str, path: Path):
    """Import one file under a private module name, so `config` cannot collide."""
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:                      # pragma: no cover
        pytest.skip(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def suffixes():
    if not (BACKEND / "staging.py").is_file():                   # pragma: no cover
        pytest.skip("the portal backend is not present in this checkout")
    staging = _load_by_path("_sdi_portal_staging", BACKEND / "staging.py")
    portal_config = _load_by_path("_sdi_portal_config", BACKEND / "config.py")
    return (tuple(s.lower() for s in staging.DRAWING_SUFFIXES),
            {str(s).lower() for s in portal_config.ALLOWED_EXTENSIONS})


def _listable(name: str, drawing_suffixes, allowed) -> bool:
    ext = Path(name).suffix.lower()
    return ext in allowed or ext in drawing_suffixes


# The real contents of 12552-InfinityDrawer, by extension and count.
JOB_FOLDER = [("a.SLDPRT", 19), ("b.SLDASM", 7), ("c.SLDDRW", 1),
              ("d.DWG", 1), ("e.PDF", 1), ("_sw_native_extract.json", 1)]


def test_the_whole_pack_would_be_visible_not_two_files_of_it(suffixes):
    drawing_suffixes, allowed = suffixes
    listed = sum(n for name, n in JOB_FOLDER if _listable(name, drawing_suffixes, allowed))
    assert listed == 30, (
        f"The picker would show {listed} of the 30 files in that job folder. It showed 2 — "
        f"the PDF and the sidecar — which is how a complete pack came to look like a lost one."
    )


def test_every_stageable_drawing_type_would_be_visible(suffixes):
    """Whatever staging accepts, the picker must show — DXF above all."""
    drawing_suffixes, allowed = suffixes
    invisible = [s for s in drawing_suffixes if s not in allowed and s not in drawing_suffixes]
    assert not invisible, invisible
    for suffix in drawing_suffixes:
        assert _listable("x" + suffix, drawing_suffixes, allowed), (
            f"{suffix} is invisible in the picker but staging accepts it. Anyone adding "
            f"files one at a time sees nothing arrive and no reason to doubt the screen."
        )


def test_the_two_lists_really_did_disagree(suffixes):
    """Pins the fault itself, so the fix cannot be quietly undone by editing one list.

    If someone later adds the model types to ALLOWED_EXTENSIONS instead, this fails and says
    so — that would make models DOWNLOADABLE off a writable share to fix a display problem.
    """
    drawing_suffixes, allowed = suffixes
    only_stageable = [s for s in drawing_suffixes if s not in allowed]
    assert ".dxf" in only_stageable and ".sldprt" in only_stageable, (
        f"Drawing types have been added to the document allow-list: {only_stageable!r}. The "
        f"picker needed to SEE them; the service was never meant to hand them out."
    )


def test_the_listing_consults_the_union_not_the_document_list():
    """Structural: the endpoint must filter on the widened predicate, not _allowed_ext."""
    source = (BACKEND / "app.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    listing = next((n for n in ast.walk(tree)
                    if isinstance(n, ast.FunctionDef) and "scandir" in ast.dump(n)), None)
    assert listing is not None, (
        "The folder listing no longer scans a directory in a way this test recognises. Find "
        "it and re-point this check rather than deleting it."
    )
    called = {n.func.id for n in ast.walk(listing)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "_listable_ext" in called, (
        f"The listing is filtering by something else again: {sorted(called)}. If that is "
        f"_allowed_ext, every model and every DXF is invisible in the drawing picker."
    )


def test_a_visible_model_is_still_not_downloadable(suffixes):
    """Listing answers 'can this go into a job'. Serving answers something else entirely."""
    _drawing_suffixes, allowed = suffixes
    for suffix in (".sldprt", ".sldasm", ".dxf", ".dwg", ".step"):
        assert suffix not in allowed, (
            f"{suffix} became servable. /api/file gates on ALLOWED_EXTENSIONS, and these are "
            f"shares anyone on the network can write to."
        )
