# ClaudeVision — SDI Intelligence Estimating Engine

Automated pipeline for extracting data from PDF + DXF technical drawings and
producing structured, priced estimates for SDI's sheet-metal / fabrication work
(display fixtures). The engine derives estimate **inputs** from the drawings and
populates the estimators' own workbook template, which then calculates the
priced estimate.

## What it does

- Extracts text and geometry from engineering drawings (PDFs + flat DXFs)
- Identifies parts, materials, thickness, dimensions, holes, folds, finishes and BOM lines
- Prices material, labour and bought-in items from the catalogue / historical DB
- **Derives genuinely or flags honestly** — never fabricates a price (see *Principles*)
- Produces structured JSON and populates the estimators' Blank Estimate Workbook
- Prepares data for pricing and RAG (historical lookup)

## Project layout

| Path | Purpose |
|------|---------|
| `src/` | **Active source** — the live `.py` pipeline (entry point `src/main.py`) |
| `corpus/` | Historical corpus (JSONL) for RAG |
| `config/` | Configuration and example env templates |
| `sql/` | SQL assets |
| `docs/` | Documentation |
| `Notes/` | Working notes / architecture drafts |

> The canonical, actively-maintained Python lives in **`src/`**. Other trees are
> historical mirrors kept only for reference.

## Setup

```bash
python -m venv venv
# Windows:  venv\Scripts\activate
# Unix:     source venv/bin/activate
pip install -r requirements.txt
```

Copy the example env template and fill in real values (never commit the populated file):

```bash
cp config/live_enquiry_collector.example.env config/.env   # example
```

## Run

```bash
python src/main.py --search-root input/drawings --drawing-pattern "*.pdf"
```

Folder-as-job (all PDFs + DXFs in a folder treated as one job):

```bash
python src/main.py --search-root "path/to/1282 - Milwaukee Wall Bay" --folder-as-job
```

## Quick health check

Verify the whole `src/` tree still parses (no DB required):

```bash
python scripts/check_compile.py
```

## Principles

The single most important rule, enforced throughout the codebase:

> **NO MOCKING.** Every output must be derived genuinely from drawing data or the
> database, or honestly flagged as a gap. A confidently-wrong number is worse than
> an honestly-absent one — it corrupts parity signals and erodes trust.

- Exact-code catalogue lookups only — never a loose `LIKE`.
- Deterministic-primary, LLM-backstop. The LLM *identifies* items in prose; it does
  not *price* known SDI part codes.
- Hold the reference-job regression (1282 — Milwaukee Wall Bay) at every step.

## Further reading

- `src/ClaudeVision_Understanding_Updated.md` — current architecture overview
- `SDI_Intelligence_HANDOFF_STATE_2.md` — accumulated engineering state
- `src/sdi_golive_roadmap.md` — go-live roadmap and open items
