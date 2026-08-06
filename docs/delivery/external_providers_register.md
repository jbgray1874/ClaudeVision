# SDI Intelligence — external providers with access to data

**Prepared for:** Matthew Evans, for the solicitors' review
**Scope:** every external system that can access, receive or store SDI Intelligence data
**Basis:** read directly from the source code and configuration, not from recollection.
Every entry cites where in the system it is called from, so the list can be re-checked.

**What this document is and is not.** This is the *technical* half of what was asked for: who
receives data, what data, and from which part of the system. It does not contain agreements,
order forms or terms — those are commercial records held outside the codebase and are listed
here as gaps to be filled.

---

## A. AI and model providers

These receive SDI and customer drawing content.

### A1. xAI (Grok) — `https://api.x.ai/v1`

| | |
| --- | --- |
| **Used for** | Whole-job drawing extraction; AI market price estimates for un-catalogued bought-in parts |
| **Called from** | `src/llm_full_extract.py`, `src/web_ai_price_lookup.py` |
| **Credential** | `XAI_API_KEY` |
| **Data sent** | **Text extracted from customer drawings** — part numbers, materials, finishes, thicknesses, BOM tables, drawing notes, quantities, job number and customer name. The code describes it as "the same content a person sees flipping through the pack" (`llm_full_extract.py:295`) |
| **Images sent** | No. Text only |

This is the largest single exposure of customer intellectual property to an external party.

### A2. Anthropic — `https://api.anthropic.com`

| | |
| --- | --- |
| **Used for** | Web-search price lookup fallback |
| **Called from** | `src/web_ai_price_lookup.py` (`_call_anthropic_llm`, `_web_search_price_anthropic`) |
| **Credential** | `ANTHROPIC_API_KEY` |
| **Data sent** | Material, thickness, finish and description of the part being priced |

### A3. Anthropic — Claude Code development environment

**Separate from A2 and much broader.** The ClaudeVision repository is cloned into a
managed remote container operated by Anthropic for development work. That container has
held the complete source code, including — see D1 — a tracked configuration file
containing live database credentials.

This is a development platform holding SDI Intelligence code, which is explicitly within
the scope Matthew has asked about.

### A4. Ollama — **local, no external transmission**

`src/vision_extraction.py` can reconcile a drawing page against a vision model, but it runs
through Ollama on the local machine. Listed only so the register is complete: no data leaves
the building on this path.

---

## B. Search providers

These receive queries built from drawing data.

| Provider | Endpoint | Credential | Data sent |
| --- | --- | --- | --- |
| **SerpAPI** | `https://serpapi.com` | `SERPAPI_API_KEY` | Search strings assembled from material, thickness, part code, finish and quantity (`web_ai_price_lookup.build_web_search_query`) |
| **Google Custom Search** | `https://www.googleapis.com` | `GOOGLE_CSE_API_KEY`, `GOOGLE_CSE_CX` | The same query strings |

A query such as *"CR4 mild steel 1.5mm powder coated bracket"* discloses what SDI is pricing,
though not for whom.

---

## C. Supplier websites — outbound fetches only

`src/web_scrape_price_lookup.py` fetches catalogue pages from:

metals4u · F H Brundle · Ritemp · Panelco · Leengate Metal · Lawcris · Fastenright · Aalco

These receive an HTTP request and return a page. **No SDI data is posted to them.** They can
infer from server logs that someone looked up a given product at a given time. Included for
completeness rather than because they hold data.

---

## D. Code repository and development platforms

### D1. GitHub — `github.com/jbgray1874/ClaudeVision`

Holds the complete source code of SDI Intelligence: the estimating engine, the rate logic,
the pricing rules and the portal.

> **Requires attention before the solicitors see this list.**
>
> `sdi-intelligence-backend/.env` is **tracked in this repository**. It contains the live
> SQL Server credentials for the `SDILive` database and the BrightHR client secret. It
> entered the repository at commit `7cad363`.
>
> Anyone with read access to the repository — now or in its history — has had those
> credentials. Recommended: rotate both secrets, then remove the file from tracking. Note
> that removing it deletes it from other working copies on merge, so it must be backed up
> locally first.

---

## E. Cloud storage

**Microsoft OneDrive / SharePoint** — "OneDrive - SDI Displays".

The live enquiry drawings sit here, synchronised to individual machines. On job 12392 that
folder held thirty-nine files including SolidWorks models and customer general arrangements.
This is customer intellectual property held on a third-party platform.

---

## F. Browser-side content delivery

The portal pages load resources from `fonts.googleapis.com`, `fonts.gstatic.com` and
`cdnjs.cloudflare.com`. These receive the **viewer's** IP address and browser details when a
page is opened. They receive no SDI data. Included because they are third parties in the
request path.

---

## G. Internal only — for completeness

| System | Note |
| --- | --- |
| SQL Server `SDILive` (10.0.0.200) | On the SDI network |
| SolidWorks COM API | Runs locally against a licensed seat |
| `\\sdi-dc01\shareddata$` | Internal file share |

---

## H. What this document cannot answer

**Hatz AI** does not appear anywhere in the repository — no code, no configuration, no
credentials, no references. Whatever that engagement covers, it is not visible from the
system, so the description of work, start date, contracts and contact must come from
commercial records.

**No agreements or terms are held in the codebase.** For each provider above, the following
still need gathering from commercial records or the provider's website:

- signed agreements, order forms, proposals or statements of work
- data-processing terms
- applicable online terms of service
- where there is no formal agreement: quotations, emails, invoices or account terms

Several of these are likely to be **online terms accepted at sign-up rather than negotiated
contracts** — xAI, SerpAPI and Google Custom Search in particular are self-service APIs. That
is worth saying to the solicitors plainly rather than leaving as a gap.

---

## Suggested order of work

1. **Rotate the two credentials in D1 and remove the file from tracking.** This is the only
   item on the list that is a live exposure rather than a documentation gap.
2. Confirm the Hatz AI position from commercial records — it is the one provider the system
   cannot describe.
3. Retrieve terms of service for xAI, Anthropic, SerpAPI and Google Custom Search.
4. Confirm the Microsoft and GitHub agreements SDI already holds, which may cover E and D1.
