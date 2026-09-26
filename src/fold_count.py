"""How many times this part goes in the press brake — one answer, one place.

James Gray, 18 September 2026, on 401912-02:

    "SolidWorks is not necessarily 'wrong'; its feature tree may correctly contain three CAD
     bend-related features. The defect is ours: we treated that model feature count as though
     it were the number of press-brake operations and gave it a higher generic source rank
     than the flat-pattern/DXF evidence. That is the wrong comparison... a flat pattern
     describes what must be bent; a CAD feature tree describes how somebody built the model."

THE DIVIDER HAS ONE FOLD AND THE SHEET CHARGED THREE. The flat DXF measured one bend axis --
`_extract_bend_data` collapses a bend line broken by cut-outs, counting distinct axes and not
entities, so it was right. The SolidWorks cut list reported three bend features, and the
connector wrote that straight into `geometry_rollup.estimated_bend_line_count` at rank 90,
over the top of the flat pattern's reading. Nothing was lying: three CAD features can make one
physical fold. They are simply not the same quantity, and only one of them is what the shop
does.

AND THE LABEL FOLLOWED THE WRONG NUMBER. `infer_bend_count` stamped `dxf_bendlines_layer`
from the DXF's one, the connector overwrote the count afterwards, and the review line read
"3 fold(s) charged, counted by dxf_bendlines_layer -- measured, not inferred." A provenance
label attached to a figure it did not produce, which is worse than no label: it invites a
reader to stop checking.

So the two facts are kept apart and one resolver answers the question every consumer asks.

WHERE THE DASHED-LINE PROXY SITS, AND WHY IT IS NOT WHERE THE BRIEF PUT IT. The brief ranks
"a clear drawing fold note/dashed bend line" above the model. A fold NOTE is a statement by
the drawing office and is ranked there. A DASHED-LINE COUNT is not a statement -- it is our
own inference from vector geometry in a PDF view, and `infer_bend_count` has always labelled
it `inferred_dashed_lines` for that reason. Ranking it above the model would undo the fix the
model override was built for: on job 12552 the dashed-line scan read 26 and 28 lines on parts
whose cut lists carried 6 and 8 bends, and the two largest fabricated lines on the bay were
being folded roughly twenty times for folds that are not there. So the proxy sits BELOW the
model, the two statements (flat pattern, drawing note) sit above it, and both of the jobs
that taught us anything come out right.
"""
from typing import Any, Dict, Optional

# The rungs, strongest first. The label is what the sheet prints, so it says what was counted
# rather than which module answered.
FLAT_PATTERN = "flat_pattern_bend_lines"
DRAWING_NOTE = "drawing_fold_note"
MODEL_FEATURES = "solidworks_bend_features"
DASHED_PROXY = "inferred_dashed_lines"
NO_EVIDENCE = "no_bend_evidence"
CALLOUTS_AND_MODEL = "drawing_callouts_agreeing_with_model"

_MEASURED = {FLAT_PATTERN, MODEL_FEATURES, CALLOUTS_AND_MODEL}

_LABEL = {
    FLAT_PATTERN: "the flat pattern's own bend lines",
    DRAWING_NOTE: "the drawing's fold callouts",
    MODEL_FEATURES: "the SolidWorks bend features",
    DASHED_PROXY: "dashed lines read off a drawing view",
    NO_EVIDENCE: "nothing on this part",
    CALLOUTS_AND_MODEL: "the drawing's bend callouts, which the SolidWorks model confirms",
}


def _int(value: Any) -> Optional[int]:
    try:
        if value is None:
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def flat_pattern_bend_lines(part: Dict[str, Any]) -> Optional[int]:
    """Distinct fold axes measured off the flat pattern's BENDLINES layer.

    What the press brake actually bends from. `_extract_bend_data` counts distinct axes, so a
    bend line the exporter broke into segments around a cut-out is one fold, not three.
    """
    if not isinstance(part, dict):
        return None
    return _int(part.get("bend_count_dxf"))


def drawing_fold_note(part: Dict[str, Any]) -> Optional[int]:
    """What the drawing office STATED: fold callouts, fold dimensions, bend angles.

    A statement about the part, not an inference from how it was drawn.
    """
    if not isinstance(part, dict):
        return None
    stated = [
        _int(part.get("fold_count_textual")),
        len(part.get("fold_values_mm") or []) or None,
        len(part.get("angles_deg") or []) or None,
    ]
    stated = [s for s in stated if s]
    return max(stated) if stated else None


def solidworks_bend_features(part: Dict[str, Any]) -> Optional[int]:
    """CAD bend-related features in the model. Evidence for review, not an operation count."""
    if not isinstance(part, dict):
        return None
    return _int(part.get("solidworks_bend_features"))


def dashed_line_proxy(part: Dict[str, Any]) -> Optional[int]:
    """Our own inference from dashed vectors in a PDF view. The weakest thing here."""
    if not isinstance(part, dict):
        return None
    rollup = part.get("geometry_rollup")
    if not isinstance(rollup, dict):
        return None
    return _int(rollup.get("dashed_long_axis_lines"))


def press_brake_folds(part: Dict[str, Any]) -> Dict[str, Any]:
    """{count, source, measured, disagreement} — the folds this part is CHARGED for.

    Every consumer asks this one function: the process time, the workbook labour row, the
    provenance, the report and the review flags. One number, one label, and they cannot drift.
    """
    rungs = (
        (FLAT_PATTERN, flat_pattern_bend_lines(part)),
        (DRAWING_NOTE, drawing_fold_note(part)),
        (MODEL_FEATURES, solidworks_bend_features(part)),
        (DASHED_PROXY, dashed_line_proxy(part)),
    )
    count, source = 0, NO_EVIDENCE
    for name, value in rungs:
        if value is not None:
            count, source = int(value), name
            break

    # TWO STATEMENTS THAT AGREE OUTRANK ONE EXPORT THAT FALLS SHORT. 12614-01 (26 Sep): the
    # fascia's DXF BENDLINES layer carried 6 bends where its sheet prints 10 UP/DOWN callouts
    # and the model has 10; the lock plate's DXF carried none where the sheet prints two
    # (DOWN 40.6°, DOWN 49.4°) and the model has two. A bend layer exported short is a
    # partial export, not a flatter part. The model alone never overrides the flat pattern
    # (401912-02: three CAD features, one fold); the drawing office's own callouts agreeing
    # with it does (D-255).
    _callouts = _int(part.get("drawing_bend_callouts")) if isinstance(part, dict) else None
    _model = solidworks_bend_features(part)
    # The model must CONFIRM the callouts (at least as many features), never supply the
    # number: 12614-01's side panels print 11 callouts where the model has 12 (D-259).
    if (source == FLAT_PATTERN and _callouts and _model and _model >= _callouts
            and _callouts > count):
        count, source = _callouts, CALLOUTS_AND_MODEL

    # EVERY READING THAT LOST IS STILL ON THE RECORD. A rung that disagreed with the charge is
    # a sentence an estimator should read: on 401912-02 the model carried three bend features
    # against the flat pattern's one, and on 12552 the dashed-line scan read 26 against a cut
    # list of 6. In both cases the only way a reader could have known is by opening both
    # files. None of them ever changes the charge.
    model = solidworks_bend_features(part)
    _others = [(name, value) for name, value in rungs
               if name != source and value is not None and int(value) != count]
    disagreement = None
    if _others:
        _said = "; ".join(f"{_LABEL[n]} read {int(v)}" for n, v in _others)
        # AND IT DOES NOT ASK FOR A CONFIRMATION IT ALREADY HAS.
        #
        # James Gray, 18 Sep 2026: "it still says 'confirm the fold count if this matters.'
        # That should be softened or removed for this job -- the drawing/DXF establishes one
        # fold already." He is right, and it generalises: where the winning rung MEASURED the
        # part, the count is established and the sentence's job is to explain why the other
        # readings differ, not to hand the question back. Asking anyway is how a page full of
        # dutiful confirmations stops being read -- the lesson three other flags in this
        # engine have already paid for. Where the charge rests on something UNMEASURED, the
        # ask is real and stays.
        _closing = (
            "The charge follows the measurement; no confirmation is needed."
            if source in _MEASURED else
            "The charge follows the strongest evidence available. Confirm the fold count "
            "if this matters to the price.")
        disagreement = (
            f"fold count: {count} from {_LABEL[source]} is CHARGED — {_said}. A CAD feature "
            f"tree describes how the model was built, a flat pattern describes what the brake "
            f"has to bend, and a dashed line on a view is neither. They are different "
            f"quantities. {_closing}")
    return {
        "count": count,
        "source": source,
        "source_label": _LABEL[source],
        "measured": source in _MEASURED,
        "model_features": model,
        "disagreement": disagreement,
    }
