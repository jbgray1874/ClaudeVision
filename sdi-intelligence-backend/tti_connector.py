"""
SDI Intelligence — TTI despatch connector (ChatGPT / Claude app, chat and voice).

A Model Context Protocol server that lets Selina Kuddus, Lee Merril, Sue
Rogers and James ask the TTI Despatch Plan the same six questions the web app
answers, by typing or out loud, through the SAME code the web app uses
(tti_search.py, over tti_data.py) - so there is one reading of the workbook
and one set of rules about what it means.

    where is it      tti_find         search every weekly sheet at once
    what is going    tti_leaving_on   what is planned to leave SDI on a day
    what is stuck    tti_chase        what is blocked, and by what
    what was missed  tti_overdue      due date passed, no departure planned
    the summary      tti_morning      due out, slipped, missing information
    the workbook     tti_data_quality cells that cannot be read

── WHY A SEPARATE SERVICE FROM THE AM CRM CONNECTOR ─────────────────────────
A connector's tool list is the same for everybody who connects it. Putting
these tools beside the AM CRM tracker's would offer Sue a tool for Nick's
account tracker and offer Nick one for TTI despatch. Neither would work - the
object-ID list refuses - but a refused tool is still a tool somebody was
shown, and an assistant that is told to try everything will try it. Two
services, two audiences, nothing offered that the person cannot use.

── WHO IS CALLING, AND WHETHER THEY MAY ─────────────────────────────────────
Every request carries a Microsoft Entra access token for this API, obtained
when the person connected the app and signed in with their SDI account and
MFA. It is checked here - signature, tenant, audience, scope, client app, and
that it is about a person - and then the person must also be named in
SDI_TTI_OIDS, the SAME list the web app's view uses. A valid SDI token is not
permission: everybody in the company can get one. That second check happens
inside every tool, because a check anywhere else can be walked past.

The token is then exchanged on-behalf-of for a Microsoft Graph token, so the
workbook is read with that person's own SharePoint rights.

── WHAT IT CANNOT DO ────────────────────────────────────────────────────────
Every tool is read-only and annotated as such. There is no writer in any
module it imports, it never names a file (the workbook is configuration), and
it does not send email: the morning summary comes back as words for somebody
to send, which is a decision for Sue and Selina.

OFF unless SDI_TTI_CONNECTOR_ENABLED=yes. Runs as its own small service beside
the main app (default port 8074), published through Entra Application Proxy
with pass-through pre-authentication, because the caller is ChatGPT's or
Claude's cloud presenting a token rather than a browser with a cookie.
See TTI_CONNECTOR_SETUP.md.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import date, datetime, timezone

import config  # noqa: F401  (loads .env before the modules below read it)
import auth
import connector_identity as identity
import connector_oauth
import tti_data
import project_tracker
import tti_files
from sue_despatch import going_out, going_out_week
from tti_search import (chase, data_quality, find, morning, overdue_undated,
                        summary_text)

import uvicorn
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations


def _opt(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


ENABLED = _opt("SDI_TTI_CONNECTOR_ENABLED", "no").lower() in ("1", "yes", "true", "on")
HOST = _opt("SDI_TTI_CONNECTOR_HOST", "0.0.0.0")
PORT = int(_opt("SDI_TTI_CONNECTOR_PORT", "8074") or 8074)
# The address ChatGPT / Claude use, e.g. https://sdi-tti-sdidisplays.msappproxy.net/mcp
PUBLIC_URL = _opt("SDI_TTI_CONNECTOR_URL").rstrip("/")
SCOPE = _opt("SDI_TTI_CONNECTOR_SCOPE", "tracker.access")
CLIENTS = {c.strip().lower() for c in
           _opt("SDI_TTI_CONNECTOR_CLIENTS").split(",") if c.strip()}
TENANT = auth.TENANT_ID
API_ID = auth.CLIENT_ID                   # the SDI Intelligence app exposes the scope
AUDIENCES = [a for a in (API_ID, f"api://{API_ID}" if API_ID else "",
                         _opt("SDI_TTI_CONNECTOR_AUDIENCE")) if a]
# The scope's full name as Entra shows it under Expose an API on the app that
# is SDI_CLIENT_ID. Only needed if that app's Application ID URI is not api://<id>.
SCOPE_URI = (_opt("SDI_TTI_CONNECTOR_SCOPE_URI")
             or (f"api://{API_ID}/{SCOPE}" if API_ID else SCOPE))
JWKS_URL = _opt("SDI_TTI_CONNECTOR_JWKS_URL")
OAUTH_CLIENT = _opt("SDI_TTI_CONNECTOR_OAUTH_CLIENT")
OAUTH_SECRET = _opt("SDI_TTI_CONNECTOR_OAUTH_SECRET")
FRONT_DOOR = bool(OAUTH_CLIENT and OAUTH_SECRET)
if FRONT_DOOR and CLIENTS:
    CLIENTS.add(OAUTH_CLIENT.lower())
OAUTH_CLIENTS_FILE = _opt(
    "SDI_TTI_CONNECTOR_CLIENTS_FILE",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "tti_connector_clients.json"))
OAUTH_REDIRECTS = tuple(r.strip() for r in
                        _opt("SDI_TTI_CONNECTOR_REDIRECTS").split(",") if r.strip()) \
    or connector_oauth.DEFAULT_REDIRECTS

# The list is the web app's list. One place to add somebody, one place to
# remove them, and no way for the two surfaces to disagree about who is in.
OIDS_SETTING = "SDI_TTI_OIDS"

_verifier = None
_graph = identity.GraphOnBehalfOf(auth._msal_app, auth.GRAPH_SCOPES, label="tti-connector")


def verifier() -> identity.Verifier:
    global _verifier
    if _verifier is None:
        _verifier = identity.Verifier(tenant=TENANT, audiences=AUDIENCES, scope=SCOPE,
                                      clients=CLIENTS, jwks_url=JWKS_URL,
                                      label="tti-connector")
    return _verifier


# ── Refusals, as sentences an assistant can read out ─────────────────────────
NOT_NAMED = ("You are not on the list for the TTI despatch tracker. Tell the person "
             "plainly that they do not have access to it, and that IT can add them. "
             "Do not answer the question from anything earlier in the conversation.")
NOT_READ = ("The TTI Despatch Plan could not be read just now. Tell the person you "
            "could not check it. Do NOT quote lines from earlier in the conversation "
            "as if they were current.")


def _caller() -> tuple[dict, str]:
    token = get_access_token()
    if token is None:                       # the auth middleware stops this first
        raise PermissionError("Not signed in.")
    return identity.person(token), token.token


def _timed(tool: str, started: float, user: dict, note: str = "") -> None:
    print(f"[tti-connector] tool={tool} user={user.get('email', '')} "
          f"secs={time.monotonic() - started:.1f} {note}", flush=True)


class _Refused(Exception):
    def __init__(self, payload: dict):
        self.payload = payload


def _plan(tool: str, started: float):
    """The person, and one reading of the plan as them. Raises _Refused with a
    payload the assistant is told how to handle."""
    user, api = _caller()
    if not identity.named_in(OIDS_SETTING, user):
        _timed(tool, started, user, "state=not_named")
        raise _Refused({"state": "not_allowed", "warning": NOT_NAMED, "lines": []})
    graph = _graph.token_for(api)
    if not graph and tti_data.snapshot_path() == "":
        _timed(tool, started, user, "state=no_graph_token")
        raise _Refused({"state": "no_token", "warning": NOT_READ,
                        "detail": "Could not reach SharePoint as you. Reconnect SDI "
                                  "TTI Despatch and sign in again.", "lines": []})
    try:
        plan = tti_data.rows_for(graph)
    except tti_data.Unavailable as exc:
        _timed(tool, started, user, f"state=unavailable {str(exc)[:120]!r}")
        raise _Refused({"state": "unavailable", "warning": NOT_READ,
                        "detail": str(exc), "lines": []})
    return user, plan


def _person(tool: str, started: float) -> dict:
    """The person, checked against the same list, for a tool that does not
    read the plan (the TTi folder search). Raises _Refused like _plan."""
    user, _ = _caller()
    if not identity.named_in(OIDS_SETTING, user):
        _timed(tool, started, user, "state=not_named")
        raise _Refused({"state": "not_allowed", "warning": NOT_NAMED, "matches": []})
    return user


def _dated(answer: dict, plan) -> dict:
    """Every answer says which save of the plan it came from, in words, because
    a spoken answer has no footer for somebody to notice afterwards."""
    answer.update(plan.provenance())
    answer["as_at"] = ("The plan was last saved "
                       + plan.saved.strftime("%d %B %Y at %H:%M")
                       + " UTC; this answer is only as current as that save.")
    return answer


def _day_meant(day: str, plan) -> date:
    """A date from the assistant, or the plan's own save date when it gives none.

    Speech gives "today" and "Thursday" as words; those are the assistant's to
    resolve into a date, and it is told so. What arrives here is either a date
    or nothing, and nothing means the day the plan was saved rather than the
    hour this ran - so a Monday question about a Friday save is not silently
    answered about Monday.
    """
    text = str(day or "").strip()
    if not text:
        return plan.saved.date()
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        raise _Refused({"state": "bad_date", "lines": [],
                        "detail": f"“{text}” is not a date. Work out the date the "
                                  f"person means and send it as YYYY-MM-DD.",
                        "warning": "Ask the person which date they mean."})


# ── Answers shaped for the ear as well as the screen ─────────────────────────
#
# A voice answer cannot be a list of sixty cards. Each tool returns a `spoken`
# sentence to say first and a `lines` list to answer follow-up questions from,
# and the instructions tell the assistant to lead with the sentence. Getting
# this wrong does not read as a bug: it reads as an assistant reciting a
# spreadsheet for ninety seconds.
SAY_FIRST = 5


def _brief(lines: list[dict], keep: int = 12) -> list[dict]:
    """The columns worth carrying into a conversation, and no more.

    A full line has thirty fields. Sending all of them for sixty rows fills the
    assistant's context with the workbook and leaves no room for the question.
    """
    out = []
    for line in lines[:keep]:
        kept = {k: line[k] for k in
                ("source", "order", "customer_po", "part", "description", "qty",
                 "departs", "departs_cell", "due", "pick_note", "delivery_note",
                 "pallets_as_recorded", "invoice_number", "booked_in_with_tti",
                 "label_and_batch_done",
                 "trailer", "loaded", "tti_account", "delivery_address", "comments")
                if line.get(k)}
        # going_out names its date fields dispatch_cell / date_basis / tentative;
        # the other answers say departs_*. Without these, "what is leaving on
        # Thursday" reached the assistant with no date and no doubt flag.
        for extra in ("because", "missing", "overdue_by_days", "slipped_by_days",
                      "departs_basis", "departs_tentative", "dispatch_cell", "date_basis",
                      "tentative"):
            if line.get(extra):
                kept[extra] = line[extra]
        out.append(kept)
    return out


def _said_day(d: date) -> str:
    """"Monday 2 November", as it is said - not "Monday 02 November"."""
    return f"{d.strftime('%A')} {d.day} {d.strftime('%B')}"


def _lines_have(n: int) -> str:
    return f"{n} line has" if n == 1 else f"{n} lines have"


def _pallets_said(n) -> str:
    return f"{n} pallet" if n == 1 else f"{n} pallets"


def _either(names) -> str:
    """"Monday, Tuesday or Thursday"."""
    names = list(names)
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " or " + names[-1]


def _name_of(line: dict) -> str:
    bits = [line.get("order") or "", line.get("part") or ""]
    return " ".join(b for b in bits if b) or "a line with no order number"


READS = ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False)


def _tool(description: str, invoking: str = "Reading the TTI Despatch Plan…",
          invoked: str = "Read the TTI Despatch Plan"):
    """Registered read-only, with the invocation wording ChatGPT shows.

    read_only_hint is not a comment: ChatGPT and the Claude app use it to
    decide what may run without asking. Every tool here reads, so every one
    says so, and there is nothing in this service for the hint to be wrong
    about.
    """
    def register(fn):
        _TOOLS.append((fn, {"annotations": READS, "description": description,
                            "meta": {"openai/toolInvocation/invoking": invoking,
                                     "openai/toolInvocation/invoked": invoked}}))
        return fn
    return register


# Plain tools, added to the server in build_server. (mcp's Apps extension is
# only for tools that render a ui:// card; none of these do.)
_TOOLS: list = []


def _add_tools(server: MCPServer) -> MCPServer:
    for fn, settings in _TOOLS:
        server.add_tool(fn, **settings)
    return server


INSTRUCTIONS = """You are connected to SDI's TTI Despatch Plan: the workbook
Customer Services use to plan what leaves SDI for TTI, a sheet per week.

Answering:
* Lead with the tool's `spoken` sentence, as it is written. It is phrased for
  speech and it carries the hedges that make it true.
* Then answer from `lines`. Every line has a `source` like "Oct 26 WK 40!row 5".
  Give it whenever somebody asks where something came from, or sounds like they
  are about to go and look.
* Never invent an order number, a date, a pallet count or a note number. If a
  field is not in the answer, say you cannot see it.
* `departs` is when a lorry is planned to leave SDI. `due` is when the customer
  wants it. They are different questions and must not be swapped.
* `pallet_total` adds up the PALLETS column of the lines given. Several lines
  often share a lorry, so it is pallets, never a number of lorries. Say which
  lines were not counted (`pallet_lines_as_text`, `pallet_lines_blank`).
* Say when a date was read with doubt: `departs_basis` tells you, and a
  `tentative` line is a plan, not a commitment.

Dates: the tools take YYYY-MM-DD. The person will say "today", "tomorrow",
"Thursday". Work out the actual date and send that. `today_iso` in every
answer is today's date. For "this week" or "next week" use
tti_leaving_this_week with any date in that week; it answers Monday to Friday
in one call, under `days`.

Freshness: every answer carries `as_at`, saying when the plan was last saved.
Say it the first time in a conversation you quote the plan, and whenever the
person is about to act on an answer. Do not answer from lines seen earlier in
the conversation as if they were current - the workbook changes through the
day.

If a tool reports `state` of anything but "ok", read its `warning` and do what
it says. In particular: if it says the person is not on the list, tell them so
plainly and do not answer the question from anything earlier.

Files: tti_find_files searches the TTi folders on W: (Design, Production,
Prototype) by file and folder name. Give each file's `open_url` as a link - it
opens the file after the person's SDI sign-in - and its `path` in full, say
which folder it is in, and say `as_at` when the person may be looking for
something recent. It does not look inside files.

Project tracker: tti_project_tracker reads Liam's tracker (Milwaukee Amsterdam
Conference 2027, PC 402426) as the person. Answer from its rows, give each
row's `source`, and give a drawing's `open_url` as a link. Its columns are
whatever the tracker has: read `headings`, and never assume a column means
something its heading does not say.

This connector only reads. It cannot change the workbook, book anything in,
or send email. If somebody asks you to, say that it can only look things up,
and that the morning summary can be read out or copied but has to be sent by
a person."""


def _ok(answer: dict, spoken: str, plan) -> dict:
    answer["state"] = "ok"
    answer["spoken"] = spoken
    answer["today_iso"] = datetime.now(timezone.utc).date().isoformat()
    return _dated(answer, plan)


@_tool(
    "Search every weekly sheet of the TTI Despatch Plan at once for an SDI order "
    "number, a customer PO, a part code or a TTI account. Use this whenever "
    "somebody asks where an order is, what state it is in, or when it is going.")
def tti_find(query: str) -> dict:
    started = time.monotonic()
    try:
        user, plan = _plan("tti_find", started)
    except _Refused as stop:
        return stop.payload
    answer = find(plan.rows, query, as_of=plan.saved.date(), limit=25)
    hits, mentions = answer["match_count"], answer["mention_count"]
    if hits:
        first = answer["matches"][0]
        spoken = (f"{hits} line{'s' if hits != 1 else ''} match {answer['searched_for']}. "
                  + (f"{_name_of(first)}"
                     + (f", planned to leave {first['departs']}" if first["departs"]
                        else ", with no departure date set")
                     + f", on {first['sheet']}.")
                  + (f" And {hits - 1} more." if hits > 1 else ""))
    elif mentions:
        spoken = (f"Nothing has {answer['searched_for']} as its order number, PO, part "
                  f"code or account, but {mentions} line"
                  f"{'s' if mentions != 1 else ''} mention it, usually in the comments.")
    else:
        spoken = (f"Nothing in any of the weekly sheets matches {answer['searched_for']}.")
    answer["matches"] = _brief(answer["matches"], 25)
    answer["mentions"] = _brief(answer["mentions"], 10)
    _timed("tti_find", started, user, f"q={query[:40]!r} hits={hits} mentions={mentions}")
    return _ok(answer, spoken, plan)


@_tool(
    "What is planned to leave SDI on one day, from the LORRY FROM SDI column. Send "
    "the date as YYYY-MM-DD. This is the departure plan, not the customer due date.")
def tti_leaving_on(day: str = "") -> dict:
    started = time.monotonic()
    try:
        user, plan = _plan("tti_leaving_on", started)
        asked = _day_meant(day, plan)
    except _Refused as stop:
        return stop.payload
    answer = going_out(plan.rows, day=asked, as_of=plan.saved.date())
    count, unread = answer["line_count"], answer["unresolved_date_count"]
    # ── "NOTHING IS LEAVING" IS ONLY SAFE WHEN NOTHING IS UNREADABLE ─────────
    # A line whose date could not be read cannot be ruled OUT of the day asked
    # about. Spoken aloud, an unqualified "nothing is going out" is the
    # sentence somebody acts on, and there is no footnote in a voice answer.
    if count:
        spoken = (f"{count} line{'s' if count != 1 else ''}"
                  + (f", {_pallets_said(answer['pallet_total'])}," if answer["pallet_total"] else "")
                  + f" planned to leave on {_said_day(asked)}: "
                  + "; ".join(_name_of(l) for l in answer["lines"][:SAY_FIRST])
                  + (f"; and {count - SAY_FIRST} more." if count > SAY_FIRST else "."))
        if unread:
            spoken += (f" {_lines_have(unread).replace('line', 'other line', 1)} a date "
                       f"I could not read, so this may not be all of them.")
    elif unread:
        spoken = (f"Nothing I can read is set to leave on {_said_day(asked)}, "
                  f"but {_lines_have(unread)} a departure date "
                  f"I could not read and cannot rule out. Those need checking in the "
                  f"workbook before relying on this.")
    else:
        spoken = (f"Nothing in the plan is set to leave SDI on "
                  f"{_said_day(asked)}.")
    answer["lines"] = _brief(answer["lines"], 25)
    answer["unresolved_date_lines"] = _brief(answer["unresolved_date_lines"], 10)
    answer["no_date_lines"] = _brief(answer["no_date_lines"], 5)
    _timed("tti_leaving_on", started, user, f"day={asked} n={count} unread={unread}")
    return _ok(answer, spoken, plan)


@_tool(
    "What is planned to leave SDI in one week, Monday to Friday, a day at a time, "
    "from the LORRY FROM SDI column. Send any date in that week as YYYY-MM-DD: "
    "today for 'this week', a date next week for 'next week'. A Saturday or Sunday "
    "is included only when something leaves on it. This is the departure plan, not "
    "the customer due date.")
def tti_leaving_this_week(day: str = "") -> dict:
    started = time.monotonic()
    try:
        user, plan = _plan("tti_leaving_this_week", started)
        asked = _day_meant(day, plan)
    except _Refused as stop:
        return stop.payload
    answer = going_out_week(plan.rows, day=asked, as_of=plan.saved.date())
    count, unread = answer["line_count"], answer["unresolved_date_count"]
    first, last = (date.fromisoformat(answer[k]) for k in ("week_start", "week_end"))
    span = f"between {_said_day(first)} and {_said_day(last)}"
    # Said as a count per day: five days of order numbers read aloud is the
    # ninety-second recital. The lines per day are there for "and Tuesday?".
    if count:
        spoken = (f"{count} line{'s' if count != 1 else ''}"
                  + (f", {_pallets_said(answer['pallet_total'])}," if answer["pallet_total"] else "")
                  + f" planned to leave {span}: "
                  + "; ".join(f"{d['line_count']} on {date.fromisoformat(d['day']).strftime('%A')}"
                              + (f" ({_pallets_said(d['pallet_total'])})" if d["pallet_total"] else "")
                              for d in answer["days"] if d["line_count"])
                  + (". Nothing on " + _either(date.fromisoformat(d["day"]).strftime("%A")
                                               for d in answer["days"] if not d["line_count"])
                     if any(not d["line_count"] for d in answer["days"]) else "")
                  + ".")
        if unread:
            spoken += (f" {_lines_have(unread).replace('line', 'other line', 1)} a date "
                       f"I could not read, so this may not be all of them.")
    elif unread:
        spoken = (f"Nothing I can read is set to leave {span}, but {_lines_have(unread)} "
                  f"a departure date I could not read and cannot rule out. Those need "
                  f"checking in the workbook before relying on this.")
    else:
        spoken = f"Nothing in the plan is set to leave SDI {span}."
    for one in answer["days"]:
        one["lines"] = _brief(one["lines"], 12)
    answer["unresolved_date_lines"] = _brief(answer["unresolved_date_lines"], 10)
    answer["no_date_lines"] = _brief(answer["no_date_lines"], 5)
    _timed("tti_leaving_this_week", started, user,
           f"week={first} n={count} unread={unread}")
    return _ok(answer, spoken, plan)


@_tool(
    "The chase list: what is blocked and by what — no customer PO, picked with no "
    "delivery note, gone and not invoiced, not booked in with TTI, labels not done, "
    "no proof of export. horizon_days is how far ahead paperwork is chased, 7 by "
    "default.")
def tti_chase(horizon_days: int = 7) -> dict:
    started = time.monotonic()
    try:
        user, plan = _plan("tti_chase", started)
    except _Refused as stop:
        return stop.payload
    # 0 is a real answer ("only what is already late"), not "use the default".
    horizon = max(0, min(7 if horizon_days is None else int(horizon_days), 90))
    answer = chase(plan.rows, as_of=plan.saved.date(), horizon=horizon)
    if answer["line_count"]:
        biggest = answer["groups"][:3]
        spoken = (f"{answer['line_count']} things to chase. "
                  + "; ".join(f"{g['count']} {g['heading'].lower()}" for g in biggest)
                  + (f"; and {answer['group_count'] - len(biggest)} other heading(s)."
                     if answer["group_count"] > len(biggest) else "."))
    else:
        spoken = ("Nothing is blocked on the things this checks: POs, pick and delivery "
                  "notes, invoices, booking in with TTI, labels, and proof of export.")
    for group in answer["groups"]:
        group["lines"] = _brief(group["lines"], 10)
    _timed("tti_chase", started, user,
           f"horizon={horizon} n={answer['line_count']} groups={answer['group_count']}")
    return _ok(answer, spoken, plan)


@_tool(
    "Lines whose customer due date has already passed while the departure cell is "
    "still empty — the ones nobody updated, as distinct from the ones not yet "
    "planned. Use this for 'what have we missed?'.")
def tti_overdue() -> dict:
    started = time.monotonic()
    try:
        user, plan = _plan("tti_overdue", started)
    except _Refused as stop:
        return stop.payload
    answer = overdue_undated(plan.rows, as_of=plan.saved.date(), limit=25)
    count = answer["line_count"]
    if count:
        worst = answer["lines"][:SAY_FIRST]
        spoken = (f"{count} line{'s' if count != 1 else ''} have a customer due date in "
                  f"the past and no planned departure. The oldest: "
                  + "; ".join(f"{_name_of(l)}, {l['overdue_by_days']} days overdue"
                              for l in worst)
                  + (f"; and {count - SAY_FIRST} more." if count > SAY_FIRST else "."))
    else:
        spoken = ("No line has a customer due date in the past with the departure cell "
                  "left empty.")
    answer["lines"] = _brief(answer["lines"], 25)
    _timed("tti_overdue", started, user, f"n={count}")
    return _ok(answer, spoken, plan)


@_tool(
    "The morning despatch summary for a day: what is due out, what was planned to "
    "have left and is still not invoiced, and what is going today with information "
    "missing. Returns the words of the summary in `as_text` for reading out or "
    "copying into an email. It does NOT send anything.")
def tti_morning(day: str = "") -> dict:
    started = time.monotonic()
    try:
        user, plan = _plan("tti_morning", started)
        asked = _day_meant(day, plan)
    except _Refused as stop:
        return stop.payload
    answer = morning(plan.rows, day=asked, as_of=plan.saved.date())
    answer["as_text"] = summary_text(answer)
    out, slipped, short = (answer["due_out_count"], answer["slipped_count"],
                           answer["incomplete_count"])
    parts = [f"{out} line{'s' if out != 1 else ''} due out on "
             f"{_said_day(asked)}" if out
             else f"Nothing due out on {_said_day(asked)}"]
    if short:
        parts.append(f"{short} of them with something missing")
    if slipped:
        parts.append(f"{slipped} line{'s' if slipped != 1 else ''} planned to have left "
                     f"earlier and still not invoiced")
    if answer["unreadable_date_count"]:
        parts.append(f"{answer['unreadable_date_count']} with a date I could not read")
    answer["due_out"] = _brief(answer["due_out"], 20)
    answer["slipped"] = _brief(answer["slipped"], 15)
    answer["incomplete"] = _brief(answer["incomplete"], 15)
    answer["unreadable_date_lines"] = _brief(answer["unreadable_date_lines"], 5)
    answer["sending"] = ("Nothing here sends email. Offer to read the summary out or to "
                         "give it as text to paste; the person sends it.")
    spoken = ", ".join(parts) + "."
    _timed("tti_morning", started, user, f"day={asked} out={out} slipped={slipped}")
    return _ok(answer, spoken, plan)


@_tool(
    "Cells in the workbook that cannot be read or contradict each other: unreadable "
    "dates, pallet counts and quantities stored as text, order lines with no order "
    "number, the same order and part on more than one row, and month spellings that "
    "were corrected. Use this when somebody asks why an answer was hedged.")
def tti_data_quality() -> dict:
    started = time.monotonic()
    try:
        user, plan = _plan("tti_data_quality", started)
    except _Refused as stop:
        return stop.payload
    answer = data_quality(plan.rows, as_of=plan.saved.date(), limit=15)
    if answer["problem_count"]:
        spoken = (f"{answer['problem_count']} cells cannot be read or disagree with each "
                  f"other. "
                  + "; ".join(f"{g['count']} {g['heading'].lower()}"
                              for g in answer["groups"][:3])
                  + (f"; and {answer['duplicate_count']} order and part pairs on more "
                     f"than one row." if answer["duplicate_count"] else "."))
    else:
        spoken = "Nothing in the workbook is unreadable on the checks this makes."
    _timed("tti_data_quality", started, user, f"n={answer['problem_count']}")
    return _ok(answer, spoken, plan)


@_tool(
    "Liam's project tracker: the Milwaukee Amsterdam Conference 2027 tracker (PC 402426) "
    "in the TTi Projects SharePoint site, read as the person. Send words to find the rows "
    "that contain all of them (a name, a part, a status, a date); send nothing for the "
    "headings and the first rows. Every row has its source (file › sheet › row) and, for "
    "any W:\\ drawing path in it, an open_url that opens the file after SDI sign-in.",
    invoking="Reading the project tracker…", invoked="Read the project tracker")
def tti_project_tracker(query: str = "") -> dict:
    started = time.monotonic()
    try:
        user = _person("tti_project_tracker", started)
    except _Refused as stop:
        return stop.payload
    _, api = _caller()
    try:
        read_ = project_tracker.read_all(_graph.token_for(api))
    except project_tracker.Unavailable as exc:
        _timed("tti_project_tracker", started, user, f"state=unavailable {str(exc)[:120]!r}")
        return {"state": "unavailable", "detail": str(exc), "matches": [],
                "warning": "Tell the person the tracker could not be read, and why, in "
                           "the detail's words. Do not answer from earlier in the conversation."}
    answer = project_tracker.search(read_, query, limit=25)
    for m in answer["matches"]:
        for p in m["paths"]:
            if p["is_file"]:
                p["open_url"] = tti_files.open_url(p["path"])
    n = answer["match_count"]
    files = [f for t in read_ for f in t["files"]]
    answer["headings"] = {f"{f['name']} › {s['sheet']}": s["headings"] for f in files for s in f["sheets"]}
    answer["saved"] = {f["name"]: f["saved"] for f in files}
    if not files:
        spoken = "The project tracker could not be found on the TTi Projects site."
    elif answer["searched_for"]:
        spoken = (f"{n} row{'s' if n != 1 else ''} in the project tracker "
                  f"{'contain' if n != 1 else 'contains'} {answer['searched_for']}."
                  if n else f"Nothing in the project tracker contains {answer['searched_for']}.")
    else:
        spoken = f"The project tracker has {n} row{'s' if n != 1 else ''}; here are the first."
    answer["state"] = "ok"
    answer["spoken"] = spoken
    answer["as_at"] = ("Read from SharePoint just now; the tracker was last saved "
                       + ", ".join(f"{k}: {v}" for k, v in answer["saved"].items()) + ".")
    _timed("tti_project_tracker", started, user, f"q={query[:40]!r} n={n}")
    return answer


@_tool(
    (
        "Find files and folders by name in SDI's TTi folders on W: - Design "
        "(W:\\Design\\Customers April 08 Onwards\\TTi), Production (W:\\Production\\TTi) "
        "and Prototype (W:\\Prototype\\TTi). Send words that appear in the file or folder "
        "name or path, such as a job number, drawing number, part code or product name. "
        "folder narrows to Design, Production or Prototype; kind narrows to drawings, "
        "models, images, documents or folders. Searches names only, not inside files."),
    invoking="Searching the TTi folders…", invoked="Searched the TTi folders")
def tti_find_files(query: str, folder: str = "", kind: str = "") -> dict:
    started = time.monotonic()
    try:
        user = _person("tti_find_files", started)
    except _Refused as stop:
        return stop.payload
    try:
        answer = tti_files.search(query, folder=folder, kind=kind, limit=25)
    except ValueError as exc:
        return {"state": "bad_query", "detail": str(exc), "matches": [],
                "warning": "Ask the person what to search for, or which folder or kind."}
    except tti_files.NotReady as exc:
        _timed("tti_find_files", started, user, "state=no_index")
        return {"state": "unavailable", "detail": str(exc), "matches": [],
                "warning": "Tell the person the TTi folder search is not available just now."}
    n = answer["match_count"]
    if n:
        first = answer["matches"][0]
        spoken = (f"{n} file{'s' if n != 1 else ''} or folder{'s' if n != 1 else ''} match "
                  f"{answer['searched_for']}. The best match is {first['name']}, in "
                  f"{first['folder']}." + (f" And {n - 1} more." if n > 1 else ""))
    else:
        spoken = f"Nothing in the TTi folders has {answer['searched_for']} in its name or path."
    answer["state"] = "ok"
    answer["spoken"] = spoken
    answer["as_at"] = (f"The folder index was built {answer['index_age_hours']:.0f} hours ago; "
                       f"files added since then are not in it."
                       if answer["index_age_hours"] is not None else "")
    for match in answer["matches"]:
        if not match["is_folder"]:
            match["open_url"] = tti_files.open_url(match["path"])
    answer["opening"] = ("Give each file's open_url as a link: it opens the file in the "
                         "person's browser after their SDI sign-in, a PDF or picture on "
                         "screen and anything else as a download. Give the path too, for "
                         "the W: drive in the office. Nothing here changes a file.")
    _timed("tti_find_files", started, user, f"q={query[:40]!r} n={n}")
    return answer


def build_server() -> MCPServer:
    if not FRONT_DOOR:
        return _add_tools(MCPServer(
            name="SDI TTI Despatch", instructions=INSTRUCTIONS,
            token_verifier=verifier(),
            auth=AuthSettings(issuer_url=verifier().issuers[0],
                              resource_server_url=PUBLIC_URL,
                              required_scopes=[SCOPE_URI], validate_token_resource=False)))
    door = connector_oauth.FrontDoor(
        public_url=PUBLIC_URL, tenant=TENANT, client_id=OAUTH_CLIENT,
        client_secret=OAUTH_SECRET, api_scope=SCOPE_URI, scope=SCOPE,
        verify=verifier().check, clients_file=OAUTH_CLIENTS_FILE,
        redirects=OAUTH_REDIRECTS, name="SDI TTI Despatch",
        purpose=("look up the TTI Despatch Plan and search the TTi folders as you. "
                 "It can only read: it cannot change anything or send email"))
    server = MCPServer(
        name="SDI TTI Despatch", instructions=INSTRUCTIONS,
        auth_server_provider=door,
        auth=AuthSettings(issuer_url=door.base, resource_server_url=PUBLIC_URL,
                          required_scopes=[SCOPE], validate_token_resource=False,
                          client_registration_options=ClientRegistrationOptions(
                              enabled=True, valid_scopes=door.scopes,
                              default_scopes=door.scopes)))
    server.custom_route(connector_oauth.CONSENT_PATH, methods=["GET", "POST"])(door.consent)
    server.custom_route(connector_oauth.CALLBACK_PATH, methods=["GET"])(door.callback)
    return _add_tools(server)


def build_app():
    problems = [n for n, v in (("SDI_TTI_CONNECTOR_URL", PUBLIC_URL),
                               ("SDI_TENANT_ID", TENANT),
                               ("SDI_CLIENT_ID", API_ID),
                               ("SDI_CLIENT_SECRET", auth.CLIENT_SECRET)) if not v]
    if problems:
        raise SystemExit("TTI connector not started - missing: " + ", ".join(problems))
    if not os.getenv(OIDS_SETTING, "").strip():
        # Starting with nobody named would refuse every call and look like a
        # broken connector. Saying so here costs one line and saves an evening.
        raise SystemExit(f"TTI connector not started - {OIDS_SETTING} is empty, so "
                         f"nobody could use it. Name the people who may, by Entra "
                         f"object ID, comma separated.")
    tail = PUBLIC_URL.split("://", 1)[-1]
    path = "/" + tail.split("/", 1)[-1] if "/" in tail else "/mcp"
    return build_server().streamable_http_app(
        streamable_http_path=path, stateless_http=True, json_response=True, host=HOST,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))


class _QuietSignIn(logging.Filter):
    """Keep sign-in codes and states out of the access log: show the path only."""
    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str) and \
                args[2].startswith(("/oauth/", "/authorize", "/token")):
            record.args = (*args[:2], args[2].split("?", 1)[0], *args[3:])
        return True


logging.getLogger("uvicorn.access").addFilter(_QuietSignIn())


if __name__ == "__main__":
    if not ENABLED:
        raise SystemExit("The TTI connector is off. Set SDI_TTI_CONNECTOR_ENABLED=yes "
                         "to start it.")
    named = len([v for v in os.getenv(OIDS_SETTING, "").split(",") if v.strip()])
    print(f"[tti-connector] starting on {HOST}:{PORT} for {PUBLIC_URL} "
          f"(scope {SCOPE_URI}; {named} person(s) named in {OIDS_SETTING}; read only; "
          f"sign-in {'front door as ' + OAUTH_CLIENT if FRONT_DOOR else 'direct to Entra'})",
          flush=True)
    uvicorn.run(build_app(), host=HOST, port=PORT)
