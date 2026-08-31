"""Which readers looked at this pack, named, with what each one is and is not.

WHY THIS FILE EXISTS. James, reading the LLM-only report for 10575-02:

    "in the HTML report, it states when solidworks was used but not what was used to read the
     PDF? Was it pdfplumber and / or something else? it must have been LLM. why does it state
     SOLIDWORKS model was used on some drawing files when it couldn't have been as it was an
     llm run?"

Three separate faults in one paragraph, and they share a cause.

  1. THE REPORT NAMED THE READER IT DID NOT USE AND NOT THE ONES IT DID. A SolidWorks file in
     the folder printed "SOLIDWORKS model" under a column headed *What it contributed*. The two
     PDFs — which produced every number on the job — printed "read".

  2. IT SAID "SOLIDWORKS" ON A RUN WITH SOLIDWORKS SWITCHED OFF. Section 4.1 was reporting the
     CONTENTS OF THE FOLDER in a column that claims to report CONTRIBUTIONS. Section 4.2, two
     paragraphs below, said "No DXFs or SolidWorks models are matched on this job." Both
     sentences were true of their own source and the document contradicted itself.

  3. NOBODY COULD TELL WHICH RUN THEY WERE READING. --llm-only set three environment variables
     in the launching process. The summary dict every deliverable is built from carried no
     trace, so the report described a one-reader run in the vocabulary of a four-reader one.

THE ANSWER IS NOT A WARNING, IT IS A LIST. An estimator asked to trust a number is entitled to
know what read the drawing, in the same words every time, whether or not the run was ordinary.
So the readers are enumerated here — once — with a plain-English account of what each produces
and what it cannot see, and both the engine and the report speak from this one list.

A READER THAT WAS SWITCHED OFF IS AS MUCH OF A FACT AS ONE THAT RAN. Each entry carries `ran`
either way, so "the SolidWorks extract was off for this run" is something the report can state
rather than something the reader has to infer from an absence.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

__all__ = ["READERS", "readers_that_ran", "run_was_llm_only", "reader_by_key",
           "pdf_reader_summary"]


# The order is the order the pack is read in, which is also the order that makes the list
# legible: the two that always run, then the corroborating readers, strongest last.
READERS: List[Dict[str, str]] = [
    {
        "key": "pdf_text",
        "name": "PDF text and tables",
        "library": "pdfplumber",
        # WHAT THIS READER DOES AND WHAT THE NEXT ONE DOES, KEPT APART. This said "…and BOM
        # table cells", which is the deterministic BOM reader's job — and on an LLM-only run
        # that reader is off while this one is not, so the entry described a contribution that
        # had not happened. The text layer supplies the WORDS; walking them into a table of
        # parts and quantities is the row below.
        "produces": "The drawing's own words — title-block fields, material and thickness "
                    "callouts, finish, part numbers, dimensions and notes — read straight out "
                    "of the PDF's text layer. This is where a part's material and gauge come "
                    "from on most jobs, and it runs on every run including --llm-only.",
        "limits": "Nothing here is interpreted: it returns what the drawing office typed. It "
                  "supplies text, not structure — turning a BOM table into rows is the "
                  "deterministic BOM reader below. A scanned or flattened PDF has no text "
                  "layer and this reader returns nothing from it.",
        "shows_as": "the drawing",
    },
    {
        "key": "pdf_vector",
        "name": "PDF vector geometry",
        "library": "PyMuPDF",
        "produces": "Cut length, hole and pierce counts and bend-line counts, measured off the "
                    "vector paths the CAD system drew.",
        "limits": "It measures the VIEW, not the part. A folded part drawn in three views has "
                  "no flat pattern on the page, so its blank size is inferred from overall "
                  "dimensions rather than measured — which is what a DXF or a model would give.",
        "shows_as": "the drawing's overall dimensions",
    },
    {
        "key": "bom_reader",
        "name": "Deterministic BOM reader",
        "library": "SDI (table geometry)",
        "produces": "The bill of materials, walked by the ruled lines and column positions of "
                    "the table itself rather than by reading it.",
        "limits": "It needs a table with rules or consistent columns. Its value is that it and "
                  "the vision model read the same table independently, so where they agree the "
                  "BOM is corroborated by two readers that share no failure mode.",
        "shows_as": "the bill of materials",
    },
    {
        "key": "vision",
        "name": "Grok vision (xAI)",
        "library": "grok-4.3, pages rendered at 300 dpi",
        "produces": "Everything a person reads off a drawing and no parser can: which view is "
                    "which, what a leader line points at, welding and finish notes in free "
                    "text, a BOM in a layout nothing has seen before.",
        "limits": "It is a reading, not a measurement. It can be right and still cannot be held "
                  "against the drawing, because two runs may read the same page differently. "
                  "This is why the engine ranks it below every reader that measures.",
        "shows_as": "Grok (xAI)",
    },
    {
        "key": "dxf",
        "name": "DXF flat patterns",
        "library": "ezdxf",
        "produces": "The measured flat pattern: true blank length and width, exact cut path, "
                    "hole positions, bend lines. The blank a part is nested from.",
        "limits": "Only for parts the drawing office exported. A part with no DXF has its blank "
                  "inferred, and an inferred blank is the single largest source of material "
                  "error on a folded part.",
        "shows_as": "the DXF flat pattern",
    },
    {
        "key": "solidworks",
        "name": "SolidWorks native extract",
        "library": "SolidWorks COM",
        "produces": "The model's own cut list and assembly structure — the quantities and "
                    "material the shop actually builds from, taken from the model rather than "
                    "from a drawing of it.",
        "limits": "Needs SolidWorks open on the machine running the job and a licence seat. "
                  "SLDPRT and SLDASM files sitting in the folder contribute nothing on their "
                  "own; they are only a source when this extract runs against them.",
        "shows_as": "the SolidWorks model",
    },
]

_BY_KEY = {r["key"]: r for r in READERS}


def reader_by_key(key: str) -> Dict[str, str]:
    return dict(_BY_KEY.get(str(key), {}))


def _env_on(name: str, default: str = "") -> bool:
    return os.environ.get(name, default).strip().lower() in {"1", "true", "yes", "on"}


def run_was_llm_only(summary: Optional[Dict[str, Any]] = None) -> bool:
    """BOTH SIGNALS, for the same reason client_quote_html takes both.

    The summary key answers for every reader afterwards — a JSON re-rendered days later by a
    process that never set the variable. The environment answers for the run in flight, and for
    a summary written before this key existed. Either alone leaves a real case unanswered.
    """
    if isinstance(summary, dict) and summary.get("llm_only"):
        return True
    return _env_on("SDI_LLM_ONLY")


def readers_that_ran(*, llm_only: bool, dxf_enabled: bool = True,
                     solidworks_enabled: Optional[bool] = None) -> List[Dict[str, Any]]:
    """The catalogue with `ran` decided for THIS run, and why, where it is off.

    The three readers --llm-only switches off are exactly the three named in main.py's own
    block: the deterministic BOM reader, the DXF flat patterns and the SolidWorks extract. The
    two PDF readers are NOT among them and never were — a point worth stating on the page,
    because "LLM-only" is read as "the model made all of it up" and the part numbers, the
    quantities and the material callouts still came off the drawing's text.
    """
    if solidworks_enabled is None:
        # SDI_APPLY_SOLIDWORKS is the documented force-off and defaults to on.
        solidworks_enabled = os.environ.get(
            "SDI_APPLY_SOLIDWORKS", "1").strip().lower() not in {"0", "false", "no", "off"}

    _off_llm = "switched off for this run by --llm-only"
    state = {
        "pdf_text":   (True, ""),
        "pdf_vector": (True, ""),
        "bom_reader": (not llm_only, _off_llm if llm_only else ""),
        "vision":     (True, ""),
        "dxf":        (bool(dxf_enabled) and not llm_only,
                       _off_llm if llm_only else
                       ("switched off for this run by --no-dxf-augment"
                        if not dxf_enabled else "")),
        "solidworks": (bool(solidworks_enabled) and not llm_only,
                       _off_llm if llm_only else
                       ("not run — SDI_APPLY_SOLIDWORKS is off, or SolidWorks was not open on "
                        "this machine" if not solidworks_enabled else "")),
    }
    out: List[Dict[str, Any]] = []
    for reader in READERS:
        ran, why_off = state[reader["key"]]
        entry = dict(reader)
        entry["ran"] = bool(ran)
        entry["why_off"] = why_off
        out.append(entry)
    return out


def pdf_reader_summary(summary: Optional[Dict[str, Any]] = None) -> str:
    """One line naming what actually read a PDF on this run, for the file table.

    THE COLUMN SAID "read". That is the answer to "was it read", and the question an estimator
    is asking is "by what" — because the answer decides whether the number underneath can be
    held against the drawing.
    """
    llm = run_was_llm_only(summary)
    parts = ["page text and tables (pdfplumber)",
             "vector geometry (PyMuPDF)",
             "rendered to an image and read by Grok (xAI)"]
    if not llm:
        parts.insert(2, "deterministic BOM reader")
    return " · ".join(parts)
