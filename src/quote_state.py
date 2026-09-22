"""Who this quotation is for, and whether it may go to them.

James Gray, 18 September 2026, on `1d77273`:

    "`PRICE PENDING` on a 'quotation' is still a customer-facing disclaimer. You were clear
     that incomplete estimates must not be released; the portal needs an editable quote view,
     not an incomplete quote for a customer to see."

    "Draft quote may always be generated in the portal. Internal workbook/report/email may be
     sent to estimators. A customer email may attach a quote only when the estimator has
     completed the commercial inputs and authorised release."

THE PENDING NOTICE WAS THE RIGHT FIX TO THE WRONG DOCUMENT. When a traceability check refuses
the price, a page headed with the SDI letterhead and the word "quotation" has to say something
about the hole where the figure was — otherwise it reads as a form somebody forgot to finish
and the next person types a number into it from memory. So it said PRICE PENDING, which is
honest, and which is a disclaimer, and a disclaimer is only ever needed because the wrong
document is being produced. **An incomplete quotation should not exist as a customer document
at all.** It should exist as an editable portal view, which is a different thing with a
different audience, and that view may say whatever an estimator needs it to say.

So the audience becomes a fact rather than a formatting decision:

    portal_editable       always true. A quote page is always generated, so the estimator has
                          something to work from. This never fails closed -- that was the
                          D-144 lesson and it does not get relearned.
    customer_releasable   true only when the price is traceable, the record has nothing
                          outstanding, the commercial inputs are recorded complete, and a
                          named estimator has authorised release.

WHAT FAILS CLOSED IS THE AUDIENCE, NOT THE DOCUMENT. Absent facts mean not releasable: no
authorisation record is not the same as no authorisation needed, and a gate whose default is
"release it" is not a gate. But nothing here suppresses the portal page, and no caller may use
this fact to withhold the workbook, the report or the covering note from an estimator.

AND IT IS ONE FACT, ASKED, NOT SIX CONDITIONS RE-DERIVED PER SURFACE. That is the whole
lesson of `displayed_charge` and `fold_count`: the £3.88 was found five times because five
renderers each worked out the answer for themselves. `main.py` already carried three separate
release conditions (`release.draft`, `money_provenance`, the requested-quantity mismatch) and
the quote page carried a fourth, and they could disagree about the same job. They are gates on
one question, so they are gathered here and every consumer asks.
"""
from typing import Any, Dict, List, Mapping, Optional

SCHEMA = "quote_state.v1"

# The two audiences. A renderer takes one and the page follows from it.
PORTAL = "portal"
CUSTOMER = "customer"

# ── THE VERDICT TRAVELS INSIDE THE DOCUMENT ─────────────────────────────────────────
#
# James Gray, 18 September 2026:
#
#     "Print CSS and `_PORTAL` filenames deter misuse but are not the actual security
#      boundary; download/share/export routes must enforce `customer_releasable`."
#
# He is right, and the awkward part is that the delivery routes live in a service that has
# never read an estimate and should not start: it holds no engine, no summary and no costed
# record, and giving it one would put a second opinion about the same question on the other
# side of a network boundary.
#
# So the quotation DECLARES its own audience, in its head, and every delivery route reads the
# file it is about to hand over. The check is then on the artefact being delivered rather than
# on a record that refers to it — a record can be stale, can describe a different run, or can
# be absent, and each of those failure modes releases the document. A file cannot disagree
# with itself.
RELEASE_META = "sdi-quote-release"


def release_meta_tag(audience: str) -> str:
    """The one line a delivery route reads. Kept here so the writer and the readers of this
    declaration cannot drift apart in wording."""
    value = CUSTOMER if audience == CUSTOMER else PORTAL
    return f'<meta name="{RELEASE_META}" content="{value}">'


class NotReleasable(RuntimeError):
    """Raised when a CUSTOMER document is asked for and the record does not allow one.

    Never raised for the portal view, which is always available.
    """


def _mapping(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _clean(value: Any) -> str:
    return str(value if value is not None else "").strip()


def _num(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        f = float(value)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def _price_fact(summary: Mapping[str, Any]) -> Dict[str, Any]:
    """The traceable unit cost, or the refusal — computed ONCE, for every surface.

    The quote used to call `publishable_total` itself, which meant the page and the release
    decision could in principle answer differently about the same job. They are the same
    question. The fail-closed handler lives here too, so every caller inherits it rather than
    each one remembering to write a try/except of its own.
    """
    es = _mapping(summary.get("estimate_summary"))
    totals = _mapping(_mapping(summary.get("final_estimate")).get("totals"))
    unit = _mapping(es.get("workbook_equivalent_pricing")).get("m105_total_unit_cost_gbp")
    # ── THE FIGURE THE WORKBOOK HOLDS, KEPT EVEN WHEN IT IS REFUSED ──────────────────
    #
    # James Gray, 22 Sep 2026, on the Plan A render run: "Quote needs to have a price —
    # even if a bad one since we know it's only indicative... it keeps being over ridden."
    #
    # He was right, and the report proved it against itself. Its headline read "Unit cost
    # PENDING — NOT TRACEABLE TO A WORKBOOK CELL" while its own Q&A twenty lines lower read
    # "What does a unit cost? £102.70 — material £92.78 + labour £0.00". ONE DOCUMENT, BOTH
    # ANSWERS, because the refusal discarded the figure instead of labelling it.
    #
    # `amount` keeps its meaning exactly: the figure a CUSTOMER document may print, refused
    # unless it traces to a workbook cell. `workbook_amount` is the number the sheet
    # actually holds, carried through the refusal so an INTERNAL page can show it and say
    # what it is. A quote that says nothing where the workbook says £102.70 does not protect
    # anybody — it just moves the estimator to a second document to find out.
    # UNTRACED IS NOT THE SAME AS CONTRADICTED, and only one of them may be shown.
    #
    # An UNTRACED figure is the Plan A case: the workbook holds £102.70, nothing anywhere
    # disagrees with it, and all that is missing is a recorded cell to cite. An internal page
    # may print that and say so.
    #
    # A CONTRADICTED figure is the 401912-02 case that built this guard in the first place:
    # the engine proposes 149.87 and the cell it cites holds 321.88. There is no "the
    # workbook's figure" there — there are two figures and no way to tell which is the
    # estimate, so showing either one picks a winner on no evidence. That is the same rule
    # as D-152's blank: a pair assembled from two readings is not a reading.
    _cell_value = totals.get("unit_cell_value")
    _raw = unit if isinstance(unit, (int, float)) else None
    if _raw is None and isinstance(_cell_value, (int, float)):
        _raw = _cell_value
    elif (isinstance(_raw, (int, float)) and isinstance(_cell_value, (int, float))
            and abs(_raw - _cell_value) > 0.005):
        _raw = None
    try:
        from displayed_charge import publishable_total
        fact = publishable_total({"run": {
            "unit_cost_gbp": unit,
            "unit_cell": totals.get("unit_cell") or "",
            "unit_cell_value": totals.get("unit_cell_value"),
        }})
    except Exception as exc:                                          # noqa: BLE001
        # FAIL CLOSED ON THE PRICE, NOT ON THE DOCUMENT. A check that cannot run refuses the
        # figure; it does not take the page down with it.
        #
        # AND IT REFUSES THE INDICATIVE FIGURE TOO. "Untraced" is a thing the check SAID —
        # it ran, found no cell to cite, and nothing contradicted the number. A check that
        # THREW said nothing: we do not know whether the workbook agrees, disagrees, or
        # holds anything at all. Showing a figure on that basis would be inventing the one
        # piece of evidence we just failed to obtain.
        return {"amount": None, "cell": None, "basis": "none",
                "workbook_amount": None,
                "why": f"the traceability check could not run ({exc})"}
    fact.setdefault("workbook_amount", _raw)
    return fact


def _outstanding_on_the_record(summary: Mapping[str, Any]) -> List[str]:
    """What the costed record itself says is still open. Never re-derived here."""
    try:
        from costed_facts import costed_job
        release = _mapping(costed_job(summary).get("release"))
    except Exception:                                                 # noqa: BLE001
        return ["the costed record could not be read"]
    if not release.get("draft"):
        return []
    reasons = [_clean(r) for r in (release.get("reasons") or []) if _clean(r)]
    return reasons or ["the costed record is still a draft"]


def _quantity_mismatch(summary: Mapping[str, Any]) -> Optional[str]:
    """Costed at a quantity nobody asked for.

    Every setup amortisation and per-order division on the sheet is for that batch, so a book
    costed at 1 against a request for 50 is wrong in each of them. `main.py` has refused on
    this for some time; it is a release gate and belongs with the others.
    """
    asked = summary.get("requested_order_quantity")
    used = summary.get("quantity") or summary.get("assumed_job_quantity")
    try:
        if asked and used and int(asked) != int(used):
            return (f"the run was asked for {asked} off and the record was costed at "
                    f"{used} off")
    except (TypeError, ValueError):
        return None
    return None


def commercial_inputs(summary: Mapping[str, Any]) -> Dict[str, Any]:
    """The estimator's own figures: margin, delivery, packaging, and anything they add.

    THE ENGINE DOES NOT DECIDE WHEN THESE ARE DONE, AND DOES NOT INVENT THE LIST. It would be
    easy to hard-code the five headings 401912-02 happened to need and call it generic; the
    next job with a fitting charge or a tooling amortisation would be released with that
    heading missing and nothing would notice. So completion is a RECORDED statement -- the
    portal writes `commercial_inputs.complete` when the estimator says so -- and any items the
    block does name are carried through so the portal can list what is still open.

    Absent means not complete. An estimate nobody has priced commercially is not one an
    estimator has silently approved.

    ── AND A FIGURE WITHOUT A SOURCE IS NOT A COMPLETED INPUT ──────────────────────────

    James Gray, 18 September 2026: "commercial inputs should ultimately record a
    source/reference alongside the value -- not only `name=value` -- so a completed input
    remains traceable to SDI Live, a supplier quote, or evidenced research."

    THIS IS THE PRICING WATERFALL, ARRIVING AT THE LAST FIELDS THAT ESCAPED IT. Every other
    number on the estimate names where it came from: the material lines carry
    `price_provenance.source_system_label`, the totals carry their workbook cell, the labour
    carries the department rate card. The commercial inputs were the one place a figure could
    be typed and released with nothing behind it -- and they are exactly the figures with no
    drawing to check them against, which is what makes the reference the only evidence there
    will ever be.

    "A number copied from an estimator's sheet is not a price source, even as a reference."
    The point of the field is that six months later somebody can ask where £45 delivery came
    from and get an answer that is not "somebody typed it".
    """
    block = _mapping(summary.get("commercial_inputs"))
    items = block.get("items")
    outstanding: List[str] = []
    unsourced: List[str] = []

    def _judge(name: str, value: Any, source: Any) -> None:
        name = _clean(name) or "an unnamed input"
        if value in (None, "", []):
            outstanding.append(name)
        elif not _clean(source):
            unsourced.append(name)

    if isinstance(items, Mapping):
        for name, value in items.items():
            # EITHER SHAPE. A bare `{"margin": 0.25}` is the old record and still readable --
            # it is simply missing its source, which is the thing being asked for, so it
            # reports as unsourced rather than as broken.
            if isinstance(value, Mapping):
                _judge(name, value.get("value"), value.get("source") or value.get("reference"))
            else:
                _judge(name, value, "")
    elif isinstance(items, (list, tuple)):
        for item in items:
            row = _mapping(item)
            if row.get("complete") and not row.get("value"):
                continue
            _judge(row.get("name"), row.get("value"),
                   row.get("source") or row.get("reference"))

    complete = bool(block.get("complete")) and not outstanding and not unsourced
    return {"complete": complete, "outstanding": outstanding, "unsourced": unsourced,
            "recorded": bool(block)}


def authorisation(summary: Mapping[str, Any],
                  price: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Who released this, when, and whether it is still the figure they released.

    An authorisation with no name on it is not an authorisation: the point of the record is
    that somebody is answerable for the figure that went out.

    ── AND A SIGNATURE COVERS WHAT IT WAS GIVEN ────────────────────────────────────────
    #
    Dave authorises 401912-02 at £149.87. A drawing is revised, the job is re-estimated, the
    unit cost comes back £212.40 — and a record that says only "Dave authorised this job"
    releases the new figure on the old signature. Nobody was careless and a price goes out
    that nobody approved.

    So where the record names the figure it was signed against, it is checked against what the
    estimate says now, and a job whose price has moved goes back to the portal for somebody to
    look at again. Same tolerance as `publishable_total`: half a penny is two reads of one
    number, not a change anybody made.

    An older record carrying no figure is accepted on its name and time alone — that is what
    it is, and refusing it would invalidate authorisations made before this existed rather
    than protecting anybody.
    """
    block = _mapping(summary.get("quote_release"))
    by = _clean(block.get("authorised_by"))
    at = _clean(block.get("authorised_at"))
    signed = _num(block.get("authorised_unit_gbp"))
    now = _num((price or {}).get("amount"))

    stale = ""
    if by and at and signed is not None:
        if now is None:
            stale = (f"{by} authorised a unit figure of £{signed:,.2f} and this estimate no "
                     f"longer produces a traceable one")
        elif abs(now - signed) > 0.005:
            stale = (f"{by} authorised £{signed:,.2f} and this estimate now reads "
                     f"£{now:,.2f} — the price has moved since it was released")
    return {"authorised": bool(by and at) and not stale,
            "by": by, "at": at, "signed_for": signed, "stale": stale}


def quote_state(summary: Any) -> Dict[str, Any]:
    """The one fact: who may see this quotation, and what is stopping the customer seeing it.

    blocking is a list of {gate, what} — the gate so a caller can act on a kind of problem,
    and `what` in the estimator's language, because the portal shows it to a person.
    """
    source = _mapping(summary)
    price = _price_fact(source)
    inputs = commercial_inputs(source)
    auth = authorisation(source, price)

    # ── TWO LENGTHS, ONE PRODUCER ────────────────────────────────────────────────
    #
    # `what` is the full sentence, with figures, cells and part numbers in it. It goes to the
    # run log and to the internal report, where somebody chases it.
    #
    # `short` is what the portal QUOTE PAGE lists, and it carries none of that. The page is
    # internal now, which is not a licence to put the engine's workings on it: the first cut
    # listed `release.reasons` verbatim and the quotation acquired "2 consistency check(s)
    # blocking", "the consistency checks have not run" and the part numbers of every unpriced
    # line — the exact material the invariant banner and the gap list were taken off this page
    # for, arriving by a new door. The detail has one home and the report is it.
    #
    # They are two fields of ONE entry rather than two derivations, because a fact with two
    # producers is how this session lost five afternoons.
    blocking: List[Dict[str, str]] = []
    if price.get("amount") is None:
        blocking.append({
            "gate": "traceable_price",
            "what": (_clean(price.get("why"))
                     or "the sheet's own unit total could not be traced to the cell it was "
                        "read from"),
            "short": "the unit price is not yet traceable to the workbook cell it came from",
        })

    outstanding = _outstanding_on_the_record(source)
    if outstanding:
        blocking.append({
            "gate": "record_outstanding",
            "what": "; ".join(outstanding),
            "short": (f"{len(outstanding)} item(s) on the costed record are still open — "
                      f"the job report lists them"),
        })

    money = source.get("money_provenance")
    if isinstance(money, Mapping) and money and not money.get("can_evidence_a_price"):
        blocking.append({
            "gate": "money_not_evidenced",
            "what": (f"this record cannot evidence a price "
                     f"({_clean(money.get('state')) or 'no state recorded'})"),
            "short": "the price on this record cannot be evidenced",
        })

    mismatch = _quantity_mismatch(source)
    if mismatch:
        blocking.append({
            "gate": "wrong_quantity", "what": mismatch,
            "short": "the record is costed at a different quantity from the one requested",
        })

    if not inputs["complete"]:
        _named = ", ".join(inputs["outstanding"])
        _unsourced = ", ".join(inputs.get("unsourced") or [])
        if _named:
            _what = f"the commercial inputs are still open: {_named}"
            _short = f"commercial inputs outstanding: {_named}"
        elif _unsourced:
            # A DIFFERENT SENTENCE, BECAUSE IT IS A DIFFERENT JOB. "Still open" sends somebody
            # looking for a figure that is already there; what is missing is where it came
            # from, and saying so is the difference between a minute's work and a puzzle.
            _what = (f"these commercial inputs carry a figure with no source: {_unsourced} — "
                     f"name SDI Live, the supplier quote or the evidenced research behind it")
            _short = f"no source recorded against: {_unsourced}"
        else:
            _what = "the estimator has not recorded the commercial inputs as complete"
            _short = "the commercial inputs are not recorded as complete"
        # The estimator's OWN headings are safe to print: they are their words, not ours.
        blocking.append({"gate": "commercial_inputs", "what": _what, "short": _short})
    if not auth["authorised"]:
        blocking.append({
            "gate": "authorisation",
            "what": (auth["stale"] or
                     "no estimator has authorised this quotation for release"),
            "short": ("the price has moved since it was released — it needs authorising again"
                      if auth["stale"] else "no estimator has authorised release"),
        })

    return {
        "schema": SCHEMA,
        # ALWAYS TRUE, AND IT IS A CONSTANT BECAUSE IT IS A PROMISE. Anything that could make
        # this false is a condition somebody would eventually meet, and the portal would lose
        # the page an estimator works from.
        "portal_editable": True,
        "customer_releasable": not blocking,
        "blocking": blocking,
        "price": price,
        "commercial_inputs": inputs,
        "authorisation": auth,
        "headline": ("authorised for release" if not blocking else
                     f"{len(blocking)} thing(s) outstanding before this may go to a customer"),
    }


def audience_for(summary: Any) -> str:
    """PORTAL or CUSTOMER — what this record may currently produce."""
    return CUSTOMER if quote_state(summary).get("customer_releasable") else PORTAL
