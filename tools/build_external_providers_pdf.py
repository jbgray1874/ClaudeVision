"""Render the consolidated external-providers review as a presentation-quality PDF.

Written for a reader who is a solicitor, not an engineer: the structure carries the
argument, the tables carry the evidence, and the three items that need a decision are
visually separated from the items that merely need confirming.
"""
from __future__ import annotations

import sys
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (BaseDocTemplate, Frame, KeepTogether, PageBreak,
                                PageTemplate, Paragraph, Spacer, Table, TableStyle)

OUT = sys.argv[1] if len(sys.argv) > 1 else "external_providers_review.pdf"

INK       = colors.HexColor("#1a1a1a")
MUTED     = colors.HexColor("#5b5b5b")
RULE      = colors.HexColor("#c8c8c8")
BAND      = colors.HexColor("#f2f2f2")
HEADBG    = colors.HexColor("#33413f")
ALERT     = colors.HexColor("#8a2b20")
ALERTBG   = colors.HexColor("#faf0ee")
OKBG      = colors.HexColor("#eef3ef")
ACCENT    = colors.HexColor("#33413f")

ss = getSampleStyleSheet()


def S(name, **kw):
    base = dict(fontName="Helvetica", fontSize=9.2, leading=13.2, textColor=INK,
                alignment=TA_LEFT, spaceAfter=5)
    base.update(kw)
    return ParagraphStyle(name, **base)


BODY      = S("body")
BODY_S    = S("bodyS", fontSize=8.3, leading=11.6)
LEAD      = S("lead", fontSize=10.4, leading=15.4, spaceAfter=8)
H1        = S("h1", fontName="Helvetica-Bold", fontSize=17, leading=21,
              textColor=ACCENT, spaceBefore=2, spaceAfter=9)
H2        = S("h2", fontName="Helvetica-Bold", fontSize=12.2, leading=15.5,
              textColor=ACCENT, spaceBefore=13, spaceAfter=6)
H3        = S("h3", fontName="Helvetica-Bold", fontSize=9.8, leading=13,
              spaceBefore=9, spaceAfter=4)
META      = S("meta", fontSize=8.4, leading=12, textColor=MUTED)
TH        = S("th", fontName="Helvetica-Bold", fontSize=8.1, leading=10.6,
              textColor=colors.white, spaceAfter=0)
TD        = S("td", fontSize=8.1, leading=10.8, spaceAfter=0)
TDB       = S("tdb", fontName="Helvetica-Bold", fontSize=8.1, leading=10.8, spaceAfter=0)
ALERTH    = S("alerth", fontName="Helvetica-Bold", fontSize=10, leading=13.5,
              textColor=ALERT, spaceAfter=4)
QUOTE     = S("quote", fontSize=9, leading=13.4, textColor=INK,
              leftIndent=8, rightIndent=8, spaceBefore=3, spaceAfter=3)

PAGE_W, PAGE_H = A4
LM = RM = 19 * mm
TMARG = 17 * mm
BMARG = 17 * mm
CONTENT_W = PAGE_W - LM - RM

TITLE = "External Providers — Consolidated Review"
SUBTITLE = ("SDI in-house software: Estimating Intelligence, SOLIDWORKS COM automation, "
            "Document Manager")


def on_page(canv, doc):
    canv.saveState()
    canv.setFont("Helvetica", 7.2)
    canv.setFillColor(MUTED)
    canv.drawString(LM, PAGE_H - TMARG + 6 * mm,
                    "External Providers — Consolidated Review   |   "
                    "Prepared for Matthew Evans, for the solicitors   |   10 August 2026")
    canv.setStrokeColor(RULE)
    canv.setLineWidth(0.5)
    canv.line(LM, PAGE_H - TMARG + 4 * mm, PAGE_W - RM, PAGE_H - TMARG + 4 * mm)
    canv.line(LM, BMARG - 3 * mm, PAGE_W - RM, BMARG - 3 * mm)
    canv.drawString(LM, BMARG - 7.5 * mm,
                    "Confidential — prepared for legal advice. "
                    "Contains no credential values and no repository identifiers.")
    canv.drawRightString(PAGE_W - RM, BMARG - 7.5 * mm, f"Page {doc.page}")
    canv.restoreState()


def p(text, style=BODY):
    return Paragraph(text, style)


def table(rows, widths, header=True, zebra=True, small=False):
    st = TD if not small else S("tds", fontSize=7.5, leading=10)
    data = []
    for r_i, row in enumerate(rows):
        out = []
        for c in row:
            if isinstance(c, Paragraph):
                out.append(c)
            else:
                out.append(Paragraph(str(c), TH if (header and r_i == 0) else st))
        data.append(out)
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0, hAlign="LEFT")
    cmds = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, RULE),
        ("BOX", (0, 0), (-1, -1), 0.6, RULE),
    ]
    if header:
        cmds += [("BACKGROUND", (0, 0), (-1, 0), HEADBG),
                 ("BOTTOMPADDING", (0, 0), (-1, 0), 5),
                 ("TOPPADDING", (0, 0), (-1, 0), 5)]
    if zebra:
        start = 1 if header else 0
        for i in range(start, len(data)):
            if (i - start) % 2 == 1:
                cmds.append(("BACKGROUND", (0, i), (-1, i), BAND))
    t.setStyle(TableStyle(cmds))
    return t


def callout(title, body_paras, tone="alert"):
    bg = ALERTBG if tone == "alert" else OKBG
    edge = ALERT if tone == "alert" else ACCENT
    inner = [Paragraph(title, ALERTH if tone == "alert" else H3)]
    for b in body_paras:
        inner.append(Paragraph(b, BODY))
    t = Table([[inner]], colWidths=[CONTENT_W], hAlign="LEFT")
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), bg),
        ("BOX", (0, 0), (-1, -1), 0.6, edge),
        ("LINEBEFORE", (0, 0), (0, -1), 2.4, edge),
        ("LEFTPADDING", (0, 0), (-1, -1), 9),
        ("RIGHTPADDING", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    return t


story = []
A = story.append

# ── COVER ───────────────────────────────────────────────────────────────────────────
A(Spacer(1, 22 * mm))
A(p(TITLE, S("t", fontName="Helvetica-Bold", fontSize=25, leading=29, textColor=ACCENT,
             spaceAfter=7)))
A(p(SUBTITLE, S("st", fontSize=12.4, leading=17, textColor=MUTED, spaceAfter=16)))
A(Spacer(1, 3 * mm))
A(table([
    ["Prepared for", "Matthew Evans, for the solicitors’ request"],
    ["Scope", "The three software tools built in-house by SDI, and every external party "
              "able to access, receive or store SDI code or data through them"],
    ["Basis", "Read directly from source code, configuration and complete version-control "
              "history. Every count and every “none found” is the output of a "
              "check that can be re-run and will produce the same answer"],
    ["Consolidates", "The two reviews by Yogesh Kumar dated 7 August 2026 (SOLIDWORKS COM "
                     "tool, rev 4; Document Manager tool, rev 2), together with a review of "
                     "the Estimating Intelligence codebase carried out on the same basis"],
    ["Date", "10 August 2026"],
], [30 * mm, CONTENT_W - 30 * mm], header=False, zebra=True))
A(PageBreak())

# ── 1. EXECUTIVE SUMMARY ────────────────────────────────────────────────────────────
A(p("1.  Executive summary", H1))
A(p("<b>The three tools are not in the same position, and the document must not blur "
    "them.</b>", LEAD))
A(p("The <b>SOLIDWORKS COM tool</b> and the <b>Document Manager tool</b> make no outbound "
    "network calls at all. They process client CAD entirely on SDI infrastructure. For "
    "those two, every external provider is a <i>development-tooling</i> exposure — the "
    "code-hosting provider, and the AI coding assistants used to build them. That is a "
    "strong, checkable position."))
A(p("<b>Estimating Intelligence is different by design.</b> It is an AI system. It "
    "transmits customer drawing content to an external AI provider at runtime, as its "
    "normal operation, because that is what it is for. It also holds SDI’s historical "
    "quotation corpus, calls supplier and search websites, and integrates with the HR "
    "platform. Its external-provider footprint is a <i>product</i> question, not only a "
    "development-hygiene one."))
A(Spacer(1, 3 * mm))
A(p("Three findings need a decision before a position is settled", H3))
A(table([
    ["#", "Finding", "Why it matters", "Status"],
    ["1", "<b>An extract of SDI’s historical quotation corpus was committed to source "
          "control</b> — approximately 104,000 records. <b>Removed 10 August 2026; still "
          "present in the repository’s history</b>",
     "Customer names, job numbers, sell prices, cost breakdowns, rebate fractions, "
     "overhead divisors, and the names of the estimators who prepared them. The system of "
     "record is internal; what was in the repository was a 66 MB extract of it",
     "<b>Decision needed on history</b>"],
    ["2", "<b>A configuration file carrying live credentials is tracked in source "
          "control</b>",
     "The production database password and the HR platform client secret. Anyone with "
     "read access since 16 July 2026 has had both",
     "<b>Live exposure</b>"],
    ["3", "<b>The portal binds to all network interfaces with its access key unset</b>",
     "On that configuration any machine on the network can reach an API that reads "
     "customer drawing folders, without authentication",
     "<b>Live exposure</b>"],
], [8 * mm, 46 * mm, 78 * mm, CONTENT_W - 132 * mm]))
A(Spacer(1, 4 * mm))
A(p("None of the three is a defect in how the software estimates. All three are squarely "
    "within the scope of what has been asked about."))

# ── 2. WHAT EACH TOOL IS ────────────────────────────────────────────────────────────
A(p("2.  What each tool is", H1))
A(table([
    ["", "Estimating Intelligence", "SOLIDWORKS COM tool", "Document Manager tool"],
    ["Purpose",
     "Reads a customer drawing pack (PDF, DXF, SOLIDWORKS models) and produces a bill of "
     "materials, a manufacturing route and a costed estimate workbook",
     "Drives an installed SOLIDWORKS seat to generate drawings and packs, extract BOMs and "
     "export DXF / STEP / IGES",
     "Reads CAD through the SOLIDWORKS Document Manager SDK to extract assembly structure, "
     "BOMs, cut lists and exports, and to index projects"],
    ["Built from", "25 April 2026", "24 July 2026", "10 July 2026"],
    ["Front ends", "Command line; API service; browser portal",
     "Command line; read-only agent server; optional local web UI",
     "Command line; read-only agent server; REST API with an operator console"],
    ["Network reach",
     "<b>Binds to all interfaces</b> (§7.3)",
     "Loopback only — unreachable from the network",
     "Loopback by default; intended for intranet use behind Windows Authentication or an "
     "API key"],
    ["Outbound calls at runtime", "<b>Yes — by design</b>", "<b>None</b>", "<b>None</b>"],
    ["Developers",
     "Principally AI-assisted development under one SDI author, plus commits under a "
     "personal (non-company) account — §7.5",
     "Sole developer, SDI company email", "Sole developer, SDI company email"],
], [26 * mm, (CONTENT_W - 26 * mm) / 3, (CONTENT_W - 26 * mm) / 3,
    (CONTENT_W - 26 * mm) / 3], small=True))

A(PageBreak())

# ── 3. SOURCE CONTROL ───────────────────────────────────────────────────────────────
A(p("3.  How the code is source-controlled", H1))
A(p("All three repositories are held with the <b>same external code-hosting provider</b> "
    "(a Microsoft company). None has automated build or deployment configured; nothing "
    "builds or ships automatically."))
A(table([
    ["", "Estimating Intelligence", "SOLIDWORKS COM tool", "Document Manager tool"],
    ["Tracked files", "~1,478 (1,374 Python)", "133", "92"],
    ["Commits", "471 on the working branch", "5", "25"],
    ["Repository visibility", "[to confirm]", "Reported private [confirm]",
     "Reported private [confirm]"],
    ["Account", "<b>A personal account, not a company one</b> (§7.5)",
     "SDI company email", "SDI company email"],
    ["Customer CAD ever committed", "<b>None</b>",
     "<b>None</b> (two generic, non-client bracket templates only)",
     "<b>None</b> — client job folders sit in the working folder but were never tracked"],
    ["Customer PDFs ever committed", "<b>None</b>", "None", "None"],
    ["Credentials in history", "<b>Yes — still tracked (§7.2)</b>", "None found",
     "None found"],
    ["Client names in tracked files", "<b>Yes (§7.1)</b> — reduced by the 10 August "
     "corpus removal, and still present in code and documentation",
     "None — only the committer’s SDI email",
     "Previously present; <b>remediated</b>, verified clean"],
], [34 * mm, (CONTENT_W - 34 * mm) / 3, (CONTENT_W - 34 * mm) / 3,
    (CONTENT_W - 34 * mm) / 3], small=True))
A(Spacer(1, 4 * mm))
A(callout("A statement that holds across all three tools", [
    "<b>No customer CAD model, drawing export or PDF has ever been committed to source "
    "control by any of the three tools.</b> This was verified by a full-history file-type "
    "scan across all references, not by inspection of the current files. It is clean, it "
    "is checkable, and it holds.",
], tone="ok"))

# ── 4. EXTERNAL PROVIDERS ───────────────────────────────────────────────────────────
A(p("4.  External providers", H1))
A(p("Providers are grouped by whether the <i>application itself</i> transmits data — a "
    "product exposure — or whether the exposure arises from <i>how the software was "
    "built</i>, a development-tooling exposure."))

A(p("4.1  Runtime — Estimating Intelligence only", H2))
A(p("These receive SDI or customer data as part of normal operation. <b>Neither of the "
    "other two tools has any entry in this section.</b>"))
A(table([
    ["Provider", "Used for", "What is sent", "Terms"],
    ["<b>xAI</b><br/>(AI model provider)",
     "Reading the drawing’s own parts list; whole-job extraction; market price "
     "estimates for un-catalogued bought-in parts",
     "<b>Full drawing pages rendered as images</b>, at 300 dpi, encoded and posted — "
     "plus extracted text: part numbers, materials, finishes, thicknesses, BOM tables, "
     "drawing notes, quantities, job numbers and customer names",
     "Self-service API; online terms accepted at sign-up. <b>No negotiated agreement, no "
     "order form, no statement of work</b> [to confirm]"],
    ["<b>Anthropic</b><br/>(AI model provider, runtime)",
     "A price-lookup fallback, and a technology-radar feature in the portal",
     "Material, thickness, finish and description of the part being priced",
     "Distinct from the development-assistant use at §4.2, which is far broader"],
    ["<b>SerpAPI</b> and <b>Google</b><br/>(Custom Search)",
     "Web search behind the price lookup",
     "Query strings assembled from material, thickness, part code, finish and quantity "
     "— e.g. “CR4 mild steel 1.5mm powder coated bracket”",
     "Discloses <i>what</i> SDI is pricing, not <i>for whom</i>"],
    ["<b>BrightHR</b><br/>(HR platform)",
     "Pulling the active employee list and clock-in / clock-out records for the portal",
     "Employee identifiers, first name, surname, work email and clocking times — "
     "approximately <b>192 employees</b>",
     "<b>This is personal data of SDI staff.</b> It engages UK GDPR in its own right, "
     "separately from any client-confidentiality question"],
    ["<b>Supplier websites</b><br/>(eight metal, board and fastener suppliers)",
     "Fetching catalogue pages behind the price lookup",
     "<b>Nothing is posted to them.</b> From their server logs they can infer that someone "
     "looked up a given product at a given time",
     "Listed for completeness rather than because they hold data"],
    ["<b>Dassault Systèmes</b><br/>(all three tools)",
     "The CAD application and SDK the tools read through",
     "Client CAD files stay local in all three tools. Licence activation and any product "
     "telemetry are the only outbound channels",
     "Licence type, reseller and telemetry settings [to confirm — finance / IT]"],
    ["<b>Two content-delivery networks</b>",
     "Fonts and script libraries loaded by the portal pages",
     "The <i>viewer’s</i> IP address and browser details. No SDI data",
     "The other two tools serve every asset locally and load nothing externally"],
], [30 * mm, 34 * mm, 60 * mm, CONTENT_W - 124 * mm], small=True))

A(Spacer(1, 4 * mm))
A(callout("Correction to the earlier register", [
    "The earlier Estimating Intelligence register stated <i>“Images sent: No. Text "
    "only.”</i> <b>That is wrong.</b> The vision reader renders each drawing page to a "
    "PNG at 300 dpi and sends it to xAI as an inline image. A page image carries "
    "everything a person sees — the geometry, the title block, the customer name, the "
    "revision table, and the confidentiality notice printed on the drawing itself.",
    "This is a materially larger disclosure than the earlier document described, and it "
    "makes xAI the <b>largest single disclosure of customer intellectual property across "
    "all three tools</b> — and the one vendor with no negotiated terms at all. The "
    "corrected version is the one to rely on.",
]))

A(PageBreak())
A(p("4.2  Development tooling — all three tools", H2))
A(p("The exposure here is the same in kind for all three: these tools run on the same "
    "machines, with the same access to the network CAD drives and local job folders, and "
    "transmit whatever a developer opens or points them at."))
A(table([
    ["Provider", "Product", "Tier", "Data terms"],
    ["Code-hosting provider<br/>(a Microsoft company)", "Repository hosting",
     "[Confirm plan]", "Published terms of service and data-protection agreement"],
    ["Anthropic", "Claude Code / Cowork", "Consumer (Pro)",
     "<b>Model-training setting OFF</b> (confirmed); 30-day retention; "
     "<b>no data-processing agreement on the consumer tier</b>"],
    ["Anthropic", "Managed remote development container", "—",
     "Has held the complete Estimating Intelligence source tree, including the tracked "
     "credentials file at §7.2"],
    ["OpenAI", "Codex / ChatGPT", "<b>Business</b>",
     "Not used for training by default; <b>DPA available</b> — confirm it is "
     "accepted. Best-covered of the three"],
    ["Anysphere", "Cursor", "Pro (individual)",
     "<b>Privacy Mode ON</b> (confirmed) — code not stored or trained on. Only "
     "enforced organisation-wide on Business, so re-check periodically"],
], [40 * mm, 40 * mm, 26 * mm, CONTENT_W - 106 * mm], small=True))

A(p("4.3  Open-source registries, and one licensing point", H2))
A(p("Dependencies are downloaded from PyPI (all three tools) and npm (Document Manager "
    "tool only). Nothing is sent to them; the exposure is one-way supply-chain integrity "
    "risk (§7.9). No agreement is required or available."))
A(p("One licensing point specific to Estimating Intelligence: it depends on <b>PyMuPDF</b>, "
    "published under <b>AGPL-3.0</b> [confirm the version and licence in use]. AGPL is a "
    "strong copyleft licence. It has <b>no effect while the software is used only inside "
    "SDI</b>, but it becomes a live question if SDI ever distributes the tool or offers it "
    "to customers as a hosted service. Worth raising now rather than at the point of sale."))

# ── 5. ITEMS ASKED ABOUT ────────────────────────────────────────────────────────────
A(p("5.  Items specifically asked about", H1))
A(p("Searched across the entire codebase, configuration, dependency lists, documentation "
    "and full version-control history of all three tools."))
A(table([
    ["Item requested", "SOLIDWORKS COM tool", "Document Manager tool",
     "Estimating Intelligence"],
    ["<b>Hatz AI</b>", "Not used — no reference anywhere",
     "Not used — no reference anywhere",
     "<b>Not used</b> — no code, no configuration, no credentials, no reference in "
     "history. Whatever that engagement covers is not visible from any of the three "
     "systems and must be described from commercial records"],
    ["<b>Grok / xAI</b>", "Not used — zero references", "Not used — zero references",
     "<b>USED — a core runtime integration</b> (§4.1)"],
    ["Other external AI model or API", "None", "None",
     "<b>Anthropic at runtime</b> (§4.1)"],
    ["Cloud hosting platform", "None", "None", "None — runs on internal infrastructure"],
    ["Cloud storage or backup", "None in code [IT to confirm drive backup]",
     "None in code [same]",
     "<b>Yes</b> — the live enquiry drawings are held on Microsoft OneDrive / "
     "SharePoint and synchronised to individual machines. This is customer intellectual "
     "property on a third-party platform"],
    ["External support provider with system access", "[IT to confirm]", "[IT to confirm]",
     "[IT to confirm]"],
    ["Telemetry, analytics or usage tracking", "None", "None", "None"],
    ["External fonts, scripts or CDN content in the UI", "None — all local",
     "None — all local", "<b>Yes</b> — two content-delivery networks"],
    ["Email sending, FTP or webhooks", "None", "None",
     "An SMTP configuration exists for an enquiry collector; credentials are in an example "
     "template only"],
], [36 * mm, 34 * mm, 34 * mm, CONTENT_W - 104 * mm], small=True))

A(PageBreak())

# ── 6. WHERE DATA SITS ──────────────────────────────────────────────────────────────
A(p("6.  Where the data actually sits", H1))
A(table([
    ["Location", "What is there", "Inside SDI?"],
    ["Network CAD drives and file shares",
     "All client CAD, drawings, briefs and exports. All three tools read these", "Yes"],
    ["Local machines — generated output, job folders",
     "BOMs, drawings, DXF exports and extracted specifications for real jobs. Excluded "
     "from source control in every case", "Yes"],
    ["Microsoft OneDrive / SharePoint",
     "Live enquiry drawing packs, synchronised per machine", "<b>No — external</b>"],
    ["Code-hosting provider",
     "Source and documentation for all three tools. <b>Plus, for Estimating Intelligence: "
     "the historical quotation corpus and a live-credentials file</b> (§7.1, §7.2)",
     "<b>No — external</b>"],
    ["AI coding assistants",
     "Source code, plus whatever was shown during development sessions — including "
     "client file and folder names", "<b>No — external</b>"],
    ["xAI", "<b>Customer drawing page images and extracted drawing content</b>",
     "<b>No — external</b>"],
    ["BrightHR", "Employee records and clockings", "<b>No — external</b>"],
], [46 * mm, CONTENT_W - 46 * mm - 24 * mm, 24 * mm], small=True))

# ── 7. RISKS ────────────────────────────────────────────────────────────────────────
A(p("7.  Risks to SDI, ordered by materiality", H1))

A(p("7.1  HIGH — SDI’s quotation history was in source control", H2))
A(p("<i>Estimating Intelligence only.</i> <b>The system of record is internal — the Access "
    "database and the estimating spreadsheets. What was in the repository was a 66 MB "
    "EXTRACT of it</b>, committed on 16 July 2026: three client corpus files and a general "
    "corpus file, totalling approximately <b>104,000 records</b>. "
    "They carry, per record: customer name, job number, description and revision; sell "
    "price, unit cost, material cost and labour cost; bought-in cost breakdown, part counts "
    "and quantities; <b>rebate fraction and derived overhead divisor</b> — SDI’s "
    "own margin and overhead structure; and <b>the named estimator who prepared it</b>, "
    "across 39 distinct names in the general corpus. They span roughly twenty years and "
    "reference several hundred distinct customers."))
A(callout("Why this is the top item", [
    "The other two tools’ clean position rests on “no client data in source "
    "control”. Estimating Intelligence cannot make that statement.",
    "This is not CAD — no drawing or model has ever been committed, and that remains "
    "true. But commercially it is arguably <b>more</b> sensitive than CAD: it is what SDI "
    "charged, to whom, at what margin. In the hands of a competitor or a client it is "
    "directly damaging, and the client side of it may engage the same confidentiality "
    "clauses as design data. The estimator names make it personal data as well.",
    "<b>An extract of the historical quotation corpus was present in the repository from "
    "16 July 2026 until 10 August 2026. It has been removed from the tracked tree. "
    "Recovery from history is still possible for anyone with read access to the commits in "
    "that window; a history rewrite is a separate decision.</b>",
    "Nothing in the engine read it — it was an intermediate staging file between the "
    "internal spreadsheets and the database — so its removal broke nothing, and the "
    "working copies remain on the internal machine where the system of record already "
    "lives. Until the history question is settled, treat repository access as equivalent "
    "to access to the quotation archive and restrict it accordingly.",
]))

A(p("7.2  HIGH — Live credentials tracked in source control", H2))
A(p("<i>Estimating Intelligence only.</i> A backend configuration file has been tracked "
    "since <b>16 July 2026</b> and contains the <b>production database password</b> and the "
    "<b>HR platform client secret</b>. The repository’s ignore rules do name this file "
    "— but ignore rules have no effect on a file that is already tracked, which is "
    "exactly what happened here."))
A(p("Anyone with read access to the repository, at any point since that date, has had both "
    "credentials. That includes the hosting provider, the managed development container, "
    "and every working copy. The database account reaches live company data; the HR secret "
    "reaches staff personal data."))
A(callout("This is the only item on the list that is a live exposure rather than a "
          "documentation gap", [
    "<b>Rotate both secrets now.</b> Rotation, not deletion, is what closes it — "
    "removing the file going forward does not remove it from history, so the historical "
    "exposure has to be treated as having happened.",
    "Then remove the file from tracking; note that doing so deletes it from other working "
    "copies on merge, so back it up locally first. Take advice on whether the HR "
    "secret’s exposure requires any notification.",
    "<b>This has been flagged repeatedly over several weeks and is still outstanding.</b> "
    "It should not be presented as resolved.",
]))

A(p("7.3  HIGH — The portal is network-reachable with its access gate off", H2))
A(p("<i>Estimating Intelligence only.</i> The service binds to <b>all network "
    "interfaces</b>, not loopback. Its API-key gate is implemented correctly, but is "
    "<b>skipped entirely when the key is blank</b> — and in the tracked configuration "
    "the key is blank. The code itself prints a warning to that effect at start-up."))
A(p("On that configuration, any machine on the network can call the API, and the API reads "
    "customer drawing folders. The two other tools are materially safer here: one is "
    "loopback-only and unreachable from the network; the other is loopback by default and "
    "designed to sit behind Windows Authentication. <b>Recommended:</b> set a key and "
    "confirm the gate is active wherever the service runs, or bind to loopback and put "
    "authentication in front of it. Confirm which is in force on the live machine."))

A(PageBreak())
A(p("7.4  HIGH — Client-confidential data reaching AI vendors", H2))
A(p("This applies to all three tools, but in two different forms, and the distinction "
    "matters."))
A(table([
    ["", "SOLIDWORKS COM and Document Manager", "Estimating Intelligence"],
    ["Form", "<b>Ad hoc.</b> The applications send nothing. The exposure is that the "
             "developer tooling runs on the same machine with the same access, and "
             "transmits whatever is opened or pasted — named client jobs, internal "
             "share paths, a client roster inferable from folder listings, and, for the "
             "Document Manager tool, live client CAD in the same working folder",
     "<b>By design.</b> Sending customer drawing content to an external AI provider is not "
     "a lapse; it is the product working as built"],
    ["Can policy remove it?", "<b>Yes</b> — controllable by a working practice",
     "<b>No.</b> The only levers are the commercial terms it happens under, and whether the "
     "content can be reduced"],
], [30 * mm, (CONTENT_W - 30 * mm) * 0.52, (CONTENT_W - 30 * mm) * 0.48], small=True))
A(Spacer(1, 3 * mm))
A(p("Position across the AI vendors, with tiers now confirmed", H3))
A(table([
    ["Vendor", "Position"],
    ["<b>OpenAI</b> (Business)", "Best covered. Not used for training by default; a DPA is "
     "available. Confirm it has been accepted"],
    ["<b>Cursor</b> (Pro)", "Privacy Mode enabled, so code is not stored or trained on. "
     "Only enforced organisation-wide on Business, so re-check periodically"],
    ["<b>Anthropic</b> (Pro, consumer)", "Model-training setting off, retention 30 days "
     "— materially improved. <b>Residual gap: the consumer tier carries no DPA even "
     "with training off</b>"],
    ["<b>xAI</b> (runtime)", "<b>The one with no negotiated terms at all — and the one "
     "receiving customer drawing images</b>"],
], [40 * mm, CONTENT_W - 40 * mm], small=True))
A(Spacer(1, 3 * mm))
A(p("<b>Why this is a legal question, not hygiene.</b> SDI’s contracts with retail "
    "clients of this profile commonly restrict disclosure of client designs and project "
    "information to third parties, sometimes with express sub-processor-approval "
    "requirements. Routing client-identifying design data through an AI vendor may engage "
    "those clauses — most acutely where the terms are weakest, which is precisely "
    "where the largest disclosure sits."))
A(p("<b>Recommended actions.</b> Keep the Anthropic training setting off and Cursor Privacy "
    "Mode on, and re-check both periodically. Confirm the OpenAI Business DPA. Move "
    "Anthropic to a commercial agreement with zero-retention terms. <b>Establish what "
    "commercial terms xAI offers</b> — this is the biggest single gap on the list. "
    "Have the solicitors review the client contracts for confidentiality and sub-processor "
    "clauses. Take advice on whether historic sessions, before the settings were changed, "
    "require client notification. Adopt a policy of never pointing a general AI coding tool "
    "at live client job folders — noting this policy <i>cannot</i> apply to Estimating "
    "Intelligence itself, which must read live packs to do its job."))

A(p("7.5  MEDIUM — Repository and account control", H2))
A(p("For the SOLIDWORKS COM and Document Manager tools the position is good: the hosting "
    "account is registered to an SDI company email and commits are authored under it. The "
    "remaining point is to confirm the account is structured as an <b>SDI-owned "
    "organisation with more than one administrator</b>, rather than a single individual "
    "account under a company address."))
A(p("<b>For Estimating Intelligence it is weaker.</b> The repository sits under a personal "
    "account, and a substantial share of commits are authored under a personal, non-company "
    "email address; the large majority are authored by an AI assistant identity under an AI "
    "vendor’s address, reflecting AI-assisted development. Consequences to put to the "
    "solicitors: ownership of the work product should be confirmed as SDI’s; "
    "continuity depends on an individual’s personal account; and there is a "
    "single-person dependency on all three tools. <b>Actions:</b> transfer to an SDI-owned "
    "organisation, enforce two-factor authentication and branch protection, and ensure a "
    "second SDI administrator has access to each."))

A(p("7.6  MEDIUM — No provider register or data-processing terms in place", H2))
A(p("The request implies none of this was documented. Under UK GDPR a controller must keep "
    "records of processing (Article 30) and hold Article 28 terms with its processors. Two "
    "categories of personal data are in scope: <b>client personal data</b> (contact names "
    "on drawings and in correspondence), and — specific to Estimating Intelligence "
    "— <b>SDI staff personal data</b>, both through the HR integration and through the "
    "estimator names in the quotation corpus. This document is intended to serve as the "
    "technical half of the Article 30 record; the commercial half still needs gathering."))

A(p("7.7  MEDIUM — Concentration of client data on workstations and drives", H2))
A(p("All three tools read client CAD across the network drives, and all three leave "
    "generated output locally. The Document Manager tool’s working folder physically "
    "contains entire client job folders. Anyone obtaining a machine, the shares or the "
    "backups can reach that material. <b>Mitigations:</b> full-disk encryption, tight share "
    "permissions, separating code repositories from live client job folders, and confirming "
    "backups are covered by an agreement with appropriate terms."))

A(p("7.8  UNQUANTIFIED [to confirm] — External IT support access", H2))
A(p("Whether an outsourced IT provider holds administrative access to the workstations, "
    "servers, network drives or backups cannot be established from a code review. If one "
    "does, it can reach all client CAD and all three tools’ data, and requires a "
    "written agreement with confidentiality and data-processing terms. To be answered by "
    "whoever manages IT."))

A(p("7.9  LOW — Open-source supply chain", H2))
A(p("Dependencies are installed from PyPI, and from npm for one tool. A compromised package "
    "could run code on a machine with access to client data. No SDI data flows outward, so "
    "there is no disclosure obligation, but pinning and reviewing dependency versions is "
    "prudent — the npm tree in particular is large and transitive."))

A(PageBreak())

# ── 8. WHAT SDI CAN SAFELY STATE ────────────────────────────────────────────────────
A(p("8.  What SDI can safely state", H1))
A(p("On the SOLIDWORKS COM tool and the Document Manager tool", H3))
A(callout("A strong position, and it should be stated plainly", [
    "Both applications process client CAD data entirely on SDI infrastructure. Neither "
    "makes outbound network calls, neither contains an AI or cloud SDK, and neither "
    "transmits data to any external provider at runtime — verified by source review. "
    "No client CAD file, design file, export or licence key has ever been committed to "
    "source control, verified against the complete history of both repositories. Client "
    "names once present in one tool’s committed documentation have been removed and "
    "verified absent. The external-provider exposure for these two arises not from the "
    "applications but from the code-hosting provider and the AI coding assistants used to "
    "build them — all now on improved data terms.",
], tone="ok"))
A(Spacer(1, 3 * mm))
A(p("On Estimating Intelligence", H3))
A(callout("The defensible statement is narrower, and should not be stretched", [
    "The engine runs on SDI infrastructure and reads customer drawings from SDI drives. No "
    "customer CAD model, drawing export or PDF has ever been committed to source control, "
    "verified against the complete history. <b>However</b>, the system transmits customer "
    "drawing content — including full drawing page images — to an external AI "
    "provider at runtime as part of its normal operation, and its repository additionally "
    "holds SDI’s historical quotation corpus and, at present, a live-credentials file. "
    "These are matters of configuration and commercial terms, and are being addressed.",
    "<b>Do not extend the first statement to cover all three tools.</b> The difference is "
    "real, it is checkable, and a statement that blurred it would not survive scrutiny.",
]))

# ── 10. BASIS ───────────────────────────────────────────────────────────────────────
A(p("9.  Basis and confirmation", H1))
A(p("The technical findings in sections 2 to 6 were established by reading source code, "
    "configuration, dependency manifests, documentation and complete version-control "
    "history for all three tools. Every count, date and “none found” in this "
    "document is the output of a check that can be re-run and will produce the same "
    "answer."))
A(p("Items marked <b>[to confirm]</b> are outside what a code review can establish — "
    "subscription tiers, signed agreements, repository visibility settings, IT access "
    "arrangements and licence terms — and must be sourced from commercial and IT "
    "records before being presented to the solicitors as confirmed."))
A(p("Two things this document deliberately does not contain: any credential value, and the "
    "names or locations of the hosting accounts and repositories. Both are available "
    "separately to whoever needs them."))
A(p("Sections covering the SOLIDWORKS COM and Document Manager tools consolidate the "
    "reviews by Yogesh Kumar dated 7 August 2026. The Estimating Intelligence sections were "
    "reviewed on the same basis and supersede the earlier register for that tool, including "
    "the correction at §4.1."))

doc = BaseDocTemplate(OUT, pagesize=A4,
                      leftMargin=LM, rightMargin=RM,
                      topMargin=TMARG, bottomMargin=BMARG,
                      title=TITLE, author="SDI Displays Limited",
                      subject="External providers with access to SDI code or data")
frame = Frame(LM, BMARG, CONTENT_W, PAGE_H - TMARG - BMARG, id="body",
              leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
doc.addPageTemplates([PageTemplate(id="main", frames=[frame], onPage=on_page)])
doc.build(story)
print(f"written: {OUT}")
