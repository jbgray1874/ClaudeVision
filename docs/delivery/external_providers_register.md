# External Providers — consolidated review

**Scope** The three in-house software tools SDI has built: the **Estimating Intelligence**
engine and portal, the **SOLIDWORKS COM automation** tool, and the **Document Manager**
tool.
**Prepared for** Matthew Evans, for the solicitors' request.
**Basis** Read directly from source code, configuration and complete version-control
history. Findings marked *[to confirm]* cannot be established from a code review and must
come from commercial or IT records.
**Date** 10 August 2026.

This consolidates the two reviews by Yogesh Kumar dated 7 August 2026 (SOLIDWORKS COM
tool, rev 4; Document Manager tool, rev 2) with a review of the Estimating Intelligence
codebase carried out on the same basis. It supersedes the earlier Estimating Intelligence
register, and corrects one statement in it — see §4.1.

Repository names, hosting accounts and URLs are deliberately omitted throughout. Where a
repository must be distinguished it is called by its tool name.

---

## 1. Executive summary

**The three tools are not in the same position, and the difference matters.**

The SOLIDWORKS COM tool and the Document Manager tool make **no outbound network calls at
all**. They process client CAD entirely on SDI infrastructure. For those two, every
external provider is a *development-tooling* exposure — the code-hosting provider, and the
AI coding assistants used to build them. That is a strong, defensible position.

**Estimating Intelligence is different by design.** It is an AI system. It transmits
customer drawing content to an external AI provider at runtime, as its normal operation,
because that is what it is for. Its repository also held an extract of SDI's historical
quotation corpus until 10 August 2026, and it calls
supplier and search websites, and integrates with the HR platform. Its external-provider
footprint is therefore a *product* question, not only a development-hygiene one.

Three findings on Estimating Intelligence need decisions before the solicitors settle a
position. All three are stated in full at §7.1–§7.3:

1. **An extract of SDI's historical quotation corpus was committed to source control** —
   approximately 104,000 records including customer names, job numbers, sell prices, cost
   breakdowns, rebate fractions, overhead divisors and the names of the estimators who
   prepared them. **Removed from the tracked tree on 10 August 2026; still recoverable from
   the repository's history.** The system of record is and always was internal.
2. **A configuration file carrying live credentials is tracked in source control** — the
   production database password and the HR platform client secret.
3. **The portal binds to all network interfaces with its access key unset**, so on that
   configuration any machine on the network can reach it without authentication.

None of the three is a defect in how the software estimates. All three are within the scope
of what the solicitors have asked about.

---

## 2. What each tool is

| | **Estimating Intelligence** | **SOLIDWORKS COM tool** | **Document Manager tool** |
|---|---|---|---|
| **Purpose** | Reads a customer drawing pack (PDF, DXF, SOLIDWORKS models) and produces a bill of materials, a manufacturing route and a costed estimate workbook | Drives an installed SOLIDWORKS seat to generate drawings and packs, extract BOMs and export DXF / STEP / IGES | Reads CAD through the SOLIDWORKS Document Manager SDK to extract assembly structure, BOMs, cut lists and exports, and to index projects |
| **Built from** | 25 April 2026 | 24 July 2026 | 10 July 2026 |
| **Front ends** | Command line; FastAPI service; browser portal | Command line; read-only MCP server; optional local web UI | Command line; read-only MCP server; REST API with an operator console |
| **Network reach** | **Binds to all interfaces** (see §7.3) | Loopback only — not reachable from the network | Loopback by default; **intended** for intranet use behind IIS with Windows Authentication or an API key |
| **Outbound calls at runtime** | **Yes — by design** (§4) | **None** | **None** |
| **Developers** | Principally AI-assisted development under one SDI author, plus commits under a personal (non-company) account — see §7.5 | Sole developer, SDI company email | Sole developer, SDI company email |

---

## 3. How the code is source-controlled

All three repositories are held with the **same external code-hosting provider** (a
Microsoft company). None has automated build or deployment configured; nothing builds or
ships automatically.

| | **Estimating Intelligence** | **SOLIDWORKS COM tool** | **Document Manager tool** |
|---|---|---|---|
| Tracked files | ~1,478 (1,374 Python) | 133 | 92 |
| Commits | 471 on the working branch | 5 | 25 |
| Repository visibility | *[to confirm on the hosting provider directly]* | Reported private *[confirm]* | Reported private *[confirm]* |
| Account | **A personal account, not a company one** (§7.5) | SDI company email | SDI company email |
| CAD / drawing files ever committed | **None** — verified across full history | **None** (two generic, non-client bracket templates only) | **None** — client job folders sit in the working folder but are excluded and were never tracked |
| Customer PDFs ever committed | **None** | None | None |
| Credentials in history | **Yes — still tracked (§7.2)** | None found | None found |
| Client names in tracked files | **Yes (§7.1)** — reduced by the 10 August corpus removal, still present in code and documentation | None — only the committer's SDI email | Previously present; **remediated**, verified clean |

**Verification method.** For every "none" above: a full-history file-type scan
(`--diff-filter=A` across all refs), a name scan for the client roster, and a credential
scan. These can be re-run on request and produce the same output.

**Worth stating plainly to the solicitors:** across all three tools, **no customer CAD
model, drawing export or PDF has ever been committed to source control.** That is a clean
and checkable statement, and it holds.

---

## 4. External providers

Providers are grouped by whether the **application itself** transmits data (a product
exposure) or whether the exposure arises from **how the software was built** (a
development-tooling exposure).

### 4.1 Runtime — Estimating Intelligence only

These receive SDI or customer data as part of normal operation. **Neither of the other two
tools has any entry in this section.**

#### xAI — AI model provider

| | |
|---|---|
| **Used for** | Reading the drawing's own parts list; whole-job extraction; market price estimates for un-catalogued bought-in parts |
| **Model** | `grok-4.3` (the code also references `grok-4.5` and an older model) |
| **What is sent** | **Full drawing pages rendered as images**, at 300 dpi, encoded and posted to the provider — plus extracted text: part numbers, materials, finishes, thicknesses, BOM tables, drawing notes, quantities, job numbers and customer names |
| **Credential** | An API key held in configuration |
| **Character** | Self-service API, online terms accepted at sign-up. No negotiated agreement, no order form, no SOW *[to confirm]* |

> **Correction to the earlier register.** That document stated *"Images sent: No. Text
> only."* **That is wrong.** The vision reader renders each drawing page to a PNG at 300 dpi
> and sends it to xAI as an inline image. A page image carries everything a person sees —
> the geometry, the title block, the customer name, the revision table and the
> confidentiality notice printed on the drawing itself. This is a materially larger
> disclosure than the earlier document described, and the solicitors should be given the
> corrected version.

This is the **largest single disclosure of customer intellectual property to an external
party** across all three tools.

#### Anthropic — AI model provider (runtime)

| | |
|---|---|
| **Used for** | A price-lookup fallback, and a technology-radar feature in the portal service |
| **What is sent** | Material, thickness, finish and description of the part being priced |
| **Credential** | An API key held in configuration |

Distinct from the development-assistant use at §4.2, which is far broader.

#### SerpAPI, and Google (Custom Search)

| | |
|---|---|
| **Used for** | Web search behind the price lookup |
| **What is sent** | Query strings assembled from material, thickness, part code, finish and quantity — e.g. *"CR4 mild steel 1.5mm powder coated bracket"* |
| **Exposure** | Discloses **what** SDI is pricing, not **for whom** |

#### BrightHR — HR platform

| | |
|---|---|
| **Used for** | Pulling the active employee list and clock-in / clock-out records for the portal |
| **What is exchanged** | Employee identifiers, first name, surname, work email and clocking times — approximately **192 employees** |
| **Character** | **This is personal data of SDI staff.** It engages UK GDPR in its own right, separately from any client-confidentiality question |
| **Credential** | A client secret — **currently in a tracked file** (§7.2) |

#### Supplier websites — outbound fetches only

Catalogue pages are fetched from eight metal, board and fastener suppliers. **No SDI data
is posted to them.** From their server logs they can infer that someone looked up a given
product at a given time. Listed for completeness rather than because they hold data.

#### Dassault Systèmes — SOLIDWORKS (all three tools)

Client CAD files stay local in all three tools. Licence activation and any product
telemetry are the only outbound channels. The Document Manager tool additionally requires a
licence key issued by Dassault or a reseller; that key is correctly kept out of source
control. Licence type, reseller and telemetry settings are *[to confirm — finance / IT]*.

#### Browser-side content delivery

The Estimating Intelligence portal pages load fonts and script libraries from two external
content-delivery networks. These receive the **viewer's** IP address and browser details.
They receive no SDI data. **The other two tools serve every asset locally and load nothing
externally** — verified across their templates, JavaScript and CSS.

### 4.2 Development tooling — all three tools

The exposure here is the same in kind for all three: these tools run on the same machines,
with the same access to the network CAD drives and local job folders, and transmit whatever
a developer opens or points them at.

| Provider | Product | Tier | Data terms |
|---|---|---|---|
| Code-hosting provider (a Microsoft company) | Repository hosting | *[Confirm plan]* | Published terms of service and data-protection agreement |
| Anthropic | Claude Code / Cowork | Consumer (Pro) | **Model-training setting OFF** (confirmed); 30-day retention; **no DPA on the consumer tier** |
| Anthropic | Managed remote development container | — | Has held the complete Estimating Intelligence source tree, including the tracked credentials file at §7.2 |
| OpenAI | Codex / ChatGPT | **Business** | Not used for training by default; **DPA available** — confirm it is accepted. Best-covered of the three |
| Anysphere | Cursor | Pro (individual) | **Privacy Mode ON** (confirmed) — code not stored or trained on. Only enforced organisation-wide on Business, so re-check periodically |

### 4.3 Open-source registries

Dependencies are downloaded from **PyPI** (all three tools) and **npm** (Document Manager
tool only). Nothing is sent to them; the exposure is one-way supply-chain integrity risk
(§7.8). No agreement is required or available.

One licensing point specific to Estimating Intelligence: it depends on **PyMuPDF**, which
is published under **AGPL-3.0** *[confirm the version and licence in use]*. AGPL is a
strong copyleft licence. It has no effect while the software is used only inside SDI, but
it is a live question if SDI ever distributes the tool or offers it to customers as a
hosted service. Worth putting in front of the solicitors now rather than at the point of
sale.

---

## 5. Items specifically asked about

Searched across the entire codebase, configuration, dependency lists, documentation and
full version-control history of all three tools.

| Item requested | SOLIDWORKS COM tool | Document Manager tool | Estimating Intelligence |
|---|---|---|---|
| **Hatz AI** | Not used — no reference anywhere | Not used — no reference anywhere | **Not used** — no code, no configuration, no credentials, no reference in history. Whatever that engagement covers is not visible from any of the three systems and must be described from commercial records |
| **Grok / xAI** | Not used — zero references | Not used — zero references | **USED — a core runtime integration** (§4.1) |
| Other external AI model or API | None | None | **Anthropic at runtime** (§4.1) |
| Cloud hosting platform | None | None | None — runs on internal infrastructure |
| Cloud storage / backup | None in code *[IT to confirm drive backup]* | None in code *[same]* | **Yes — the live enquiry drawings are held on Microsoft OneDrive / SharePoint** and synchronised to individual machines. This is customer intellectual property on a third-party platform |
| External support provider with system access | *[IT to confirm]* | *[IT to confirm]* | *[IT to confirm]* |
| Telemetry / analytics / usage tracking | None | None | None |
| External fonts, scripts or CDN content in the UI | None — all local | None — all local | **Yes** — two CDNs (§4.1) |
| Email, FTP or webhooks | None | None | An SMTP configuration exists for an enquiry collector; credentials are in an example template only |

---

## 6. Where the data actually sits

| Location | What is there | Inside SDI? |
|---|---|---|
| Network CAD drives and file shares | All client CAD, drawings, briefs and exports. All three tools read these | Yes |
| Local machines — generated output, job folders | BOMs, drawings, DXF exports, extracted specifications for real jobs. Excluded from source control in every case | Yes |
| Microsoft OneDrive / SharePoint | Live enquiry drawing packs, synchronised per machine | **No — external** |
| Code-hosting provider | Source and documentation for all three tools. **Plus, for Estimating Intelligence: the historical quotation corpus and a live-credentials file** (§7.1, §7.2) | **No — external** |
| AI coding assistants | Source code, plus whatever was shown during development sessions — including client file and folder names | **No — external** |
| xAI | **Customer drawing page images and extracted drawing content** | **No — external** |
| BrightHR | Employee records and clockings | **No — external** |

---

## 7. Risks to SDI — ordered by materiality

### 7.1 HIGH — SDI's quotation history and client commercial data were in source control

**Estimating Intelligence only.** Three client corpus files and a general corpus file are
tracked in the repository, totalling approximately **104,000 records**. They carry, per
record:

- customer name, job number, description, revision
- sell price, unit cost, material cost, labour cost
- bought-in cost breakdown, part counts, quantities
- **rebate fraction and derived overhead divisor** — SDI's own margin and overhead structure
- **`prepared_by`** — the named estimator, across 39 distinct names in the general corpus

They span roughly twenty years of quotations and reference several hundred distinct
customers. Client names also appear in ordinary tracked source and documentation files
across the repository.

**Why this is the top item.** The two other tools' clean position rests on "no client data
in source control." Estimating Intelligence cannot make that statement. This is not CAD —
no drawing or model has ever been committed, and that remains true — but commercially it is
arguably more sensitive than CAD: it is **what SDI charged, to whom, at what margin.** In
the hands of a competitor or a client it is directly damaging, and the client-side of it may
engage the same confidentiality clauses as design data.

It also sits, unavoidably, in every place the repository has been: the hosting provider, the
managed development container, and any working copy.

An extract of the historical quotation corpus was present in the repository from **16 July
2026 until 10 August 2026**. It has been removed from the tracked tree. **Recovery from
history is still possible for anyone with read access to the commits in that window; a
history rewrite is a separate decision.**

Nothing in the engine read it — it was an intermediate staging file between the internal
spreadsheets and the database — so its removal broke nothing, and the working copies
remain on the internal machine where the system of record already lives. Until the history
question is settled, treat repository access as equivalent to access to the quotation
archive and restrict it accordingly.

**Recommended actions.** (1) Decide whether the history must be rewritten as well. (2) If not, it must be removed from the working tree **and from
history** — removing it from the current commit leaves it fully readable in the history.
(3) In the meantime, treat repository access as equivalent to access to the quotation
archive, and restrict it accordingly. (4) The `prepared_by` names make this personal data
as well as commercial data.

### 7.2 HIGH — Live credentials tracked in source control

**Estimating Intelligence only.** A backend configuration file has been tracked since
16 July 2026 and contains:

- the **production SQL Server password** for the live database, and
- the **BrightHR client secret**.

The repository's ignore rules *do* name this file — but ignore rules have no effect on a
file that is already tracked, which is exactly what happened here.

**Anyone with read access to the repository, at any point since that date, has had both
credentials.** That includes the hosting provider, the managed development container, and
every working copy. The database account reaches live company data; the HR secret reaches
staff personal data.

**Recommended actions, in this order.** (1) **Rotate both secrets now** — this is the only
item in this document that is a live exposure rather than a documentation gap, and rotation
is what actually closes it. (2) Then remove the file from tracking. Note that removing it
deletes it from other working copies on merge, so back it up locally first. (3) Removing it
going forward does **not** remove it from history; treat the historical exposure as having
happened and let rotation, not deletion, be the remedy. (4) Take advice on whether the HR
secret's exposure requires any notification.

**This has been outstanding and flagged repeatedly for several weeks and is still not
done.** It should not be presented to the solicitors as resolved.

### 7.3 HIGH — The portal is network-reachable with its access gate off

**Estimating Intelligence only.** The service binds to **all network interfaces**, not
loopback. Its API-key gate is implemented correctly, but is **skipped entirely when the key
is blank** — and in the tracked configuration file the key **is** blank. The code itself
prints a warning to that effect at start-up.

On that configuration, any machine on the network can call the API, and the API reads
customer drawing folders. The two other tools are materially safer here: one is loopback-only
and unreachable from the network; the other is loopback by default and designed to sit
behind Windows Authentication.

**Recommended actions.** Set a key and confirm the gate is active wherever the service runs;
or bind to loopback and put authentication in front of it, as the Document Manager tool
does. Confirm which is in force on the live machine.

### 7.4 HIGH — Client-confidential data reaching AI vendors

This is Yogesh's top risk for both his tools, and it applies to all three — but it takes two
different forms, and the distinction is worth making carefully to the solicitors.

**For the SOLIDWORKS COM and Document Manager tools it is *ad hoc*.** The applications send
nothing. The exposure is that the developer tooling runs on the same machine with the same
access, and transmits whatever is opened or pasted — named client jobs, internal share
paths, a client roster inferable from folder listings, and, for the Document Manager tool,
live client CAD sitting in the same working folder. It is controllable by policy.

**For Estimating Intelligence it is *by design*.** Sending customer drawing content to an
external AI provider is not a lapse; it is the product working as built. No policy change
removes it. The only levers are the commercial terms it happens under, and whether the
content can be reduced.

**Position across the AI vendors, with tiers now confirmed:**

- **OpenAI (Business)** — best covered. Not used for training by default; a DPA is
  available. Confirm it has been accepted.
- **Cursor (Pro)** — Privacy Mode enabled, so code is not stored or trained on. Only
  enforced organisation-wide on Business, so re-check periodically.
- **Anthropic (Pro, consumer)** — model-training setting off, retention 30 days. Materially
  improved. **Residual gap: the consumer tier carries no DPA even with training off.**
- **xAI** — the runtime integration. This is the one with **no negotiated terms at all**,
  and it is the one receiving customer drawing images.

**Why this is a legal question, not hygiene.** SDI's contracts with retail clients of this
profile commonly restrict disclosure of client designs and project information to third
parties, sometimes with express sub-processor-approval requirements. Routing
client-identifying design data through an AI vendor may engage those clauses — most acutely
where the terms are weakest, which is precisely where the largest disclosure sits.

**Recommended actions.** (1) Keep the Anthropic training setting off and Cursor Privacy Mode
on; re-check both periodically. (2) Confirm the OpenAI Business DPA. (3) Move Anthropic to a
commercial agreement with zero-retention terms to close the residual gap. (4) **Establish
what commercial terms are available from xAI**, and whether an enterprise tier with
no-training and retention commitments exists — this is the biggest single gap on the list.
(5) Have the solicitors review the client contracts for confidentiality and sub-processor
clauses. (6) Take advice on whether historic sessions, before the settings were changed,
require client notification. (7) Adopt a policy of never pointing a general AI coding tool
at live client job folders; work from anonymised fixtures. Note this policy **cannot** apply
to Estimating Intelligence itself, which must read live packs to do its job.

### 7.5 MEDIUM — Repository and account control

For the SOLIDWORKS COM and Document Manager tools the position is good: the hosting account
is registered to an SDI company email and commits are authored under it. The remaining point
is to confirm the account is structured as an **SDI-owned organisation with more than one
administrator**, rather than a single individual account under a company address.

**For Estimating Intelligence it is weaker.** The repository sits under a **personal
account**, and a substantial share of commits are authored under a **personal, non-company
email address**. The large majority of commits are authored by an AI assistant identity
under an AI vendor's address, reflecting AI-assisted development.

Consequences to put to the solicitors: ownership of the work product should be confirmed as
SDI's; continuity depends on an individual's personal account; and there is a single-person
dependency on all three tools. **Actions:** transfer to an SDI-owned organisation, enforce
two-factor authentication and branch protection, and ensure a second SDI administrator has
access to each.

### 7.6 MEDIUM — No provider register or data-processing terms in place

The solicitors' request implies none of this was documented. Under UK GDPR a controller must
keep records of processing (Article 30) and hold Article 28 terms with its processors. Two
categories of personal data are in scope here: **client personal data** (contact names on
drawings and in correspondence), and — specific to Estimating Intelligence — **SDI staff
personal data**, both through the BrightHR integration and through the estimator names in
the quotation corpus. This document is intended to serve as the technical half of the
Article 30 record; the commercial half still needs gathering.

### 7.7 MEDIUM — Concentration of client data on workstations and drives

All three tools read client CAD across the network drives, and all three leave generated
output locally. The Document Manager tool's working folder physically contains entire client
job folders. Anyone obtaining a machine, the shares or the backups can reach that material.
**Mitigations:** full-disk encryption, tight share permissions, separating code repositories
from live client job folders, and confirming backups are covered by an agreement with
appropriate terms.

### 7.8 UNQUANTIFIED *[to confirm]* — External IT support access

Whether an outsourced IT provider holds administrative access to the workstations, servers,
network drives or backups cannot be established from a code review. If one does, it can
reach all client CAD and all three tools' data, and requires a written agreement with
confidentiality and data-processing terms. To be answered by whoever manages IT.

### 7.9 LOW — Open-source supply chain

Dependencies are installed from PyPI, and from npm for one tool. A compromised package could
run code on a machine with access to client data. No SDI data flows outward, so there is no
disclosure obligation, but pinning and reviewing dependency versions is prudent — the npm
tree in particular is large and transitive.

---

## 8. What SDI can safely state

**On the SOLIDWORKS COM tool and the Document Manager tool** — a strong position, and it
should be stated plainly:

> Both applications process client CAD data entirely on SDI infrastructure. Neither makes
> outbound network calls, neither contains an AI or cloud SDK, and neither transmits data to
> any external provider at runtime — verified by source review. No client CAD file, design
> file, export or licence key has ever been committed to source control, verified against
> the complete history of both repositories. Client names that were once present in one
> tool's committed documentation have been removed and verified absent. The external-provider
> exposure for these two tools arises not from the applications but from the code-hosting
> provider and the AI coding assistants used to build them — all now on improved data terms.

**On Estimating Intelligence** — the defensible statement is narrower, and should not be
stretched:

> The engine runs on SDI infrastructure and reads customer drawings from SDI drives. No
> customer CAD model, drawing export or PDF has ever been committed to source control,
> verified against the complete history. However, the system transmits customer drawing
> content — including full drawing page images — to an external AI provider at runtime as
> part of its normal operation, and its repository additionally holds SDI's historical
> quotation corpus and, at present, a live-credentials file. These are matters of
> configuration and commercial terms, and are being addressed.

Do not extend the first statement to cover all three tools. The difference is real, it is
checkable, and a statement that blurred it would not survive scrutiny.

---

## 9. Basis and confirmation

The technical findings in sections 2 to 6 were established by reading source code,
configuration, dependency manifests, documentation and complete version-control history for
all three tools. Every count, date and "none found" in this document is the output of a
check that can be re-run and will produce the same answer.

Items marked *[to confirm]* are outside what a code review can establish — subscription
tiers, signed agreements, repository visibility settings, IT access arrangements and licence
terms — and must be sourced from commercial and IT records before being presented to the
solicitors as confirmed.

Two things this document deliberately does **not** contain: any credential value, and the
names or locations of the hosting accounts and repositories. Both are available separately
to whoever needs them.

Sections covering the SOLIDWORKS COM and Document Manager tools consolidate the reviews by
Yogesh Kumar dated 7 August 2026. The Estimating Intelligence sections were reviewed on the
same basis and supersede the earlier register for that tool, including the correction at
§4.1.
