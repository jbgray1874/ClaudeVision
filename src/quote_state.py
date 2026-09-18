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
    try:
        from displayed_charge import publishable_total
        return publishable_total({"run": {
            "unit_cost_gbp": unit,
            "unit_cell": totals.get("unit_cell") or "",
            "unit_cell_value": totals.get("unit_cell_value"),
        }})
    except Exception as exc:                                          # noqa: BLE001
        # FAIL CLOSED ON THE PRICE, NOT ON THE DOCUMENT. A check that cannot run refuses the
        # figure; it does not take the page down with it.
        return {"amount": None, "cell": None, "basis": "none",
                "why": f"the traceability check could not run ({exc})"}


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
    """
    block = _mapping(summary.get("commercial_inputs"))
    items = block.get("items")
    outstanding: List[str] = []
    if isinstance(items, Mapping):
        for name, value in items.items():
            if value in (None, "", []) or (isinstance(value, Mapping)
                                           and not value.get("value")):
                outstanding.append(_clean(name))
    elif isinstance(items, (list, tuple)):
        for item in items:
            row = _mapping(item)
            if not row.get("value") and not row.get("complete"):
                outstanding.append(_clean(row.get("name")) or "an unnamed input")
    complete = bool(block.get("complete")) and not outstanding
    return {"complete": complete, "outstanding": outstanding, "recorded": bool(block)}


def authorisation(summary: Mapping[str, Any]) -> Dict[str, Any]:
    """Who released this, and when. A named person and a time, or nothing.

    An authorisation with no name on it is not an authorisation: the point of the record is
    that somebody is answerable for the figure that went out.
    """
    block = _mapping(summary.get("quote_release"))
    by = _clean(block.get("authorised_by"))
    at = _clean(block.get("authorised_at"))
    return {"authorised": bool(by and at), "by": by, "at": at}


def quote_state(summary: Any) -> Dict[str, Any]:
    """The one fact: who may see this quotation, and what is stopping the customer seeing it.

    blocking is a list of {gate, what} — the gate so a caller can act on a kind of problem,
    and `what` in the estimator's language, because the portal shows it to a person.
    """
    source = _mapping(summary)
    price = _price_fact(source)
    inputs = commercial_inputs(source)
    auth = authorisation(source)

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
        blocking.append({
            "gate": "commercial_inputs",
            "what": (f"the commercial inputs are still open: {_named}" if _named else
                     "the estimator has not recorded the commercial inputs as complete"),
            # The estimator's OWN headings are safe to print: they are their words, not ours.
            "short": (f"commercial inputs outstanding: {_named}" if _named else
                      "the commercial inputs are not recorded as complete"),
        })
    if not auth["authorised"]:
        blocking.append({
            "gate": "authorisation",
            "what": "no estimator has authorised this quotation for release",
            "short": "no estimator has authorised release",
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
