# SDI Intelligence — Go-Live Roadmap
## Target: 30 June 2026

---

## THIS WEEKEND (14–15 June) — James

### Saturday 14 June
- [ ] Run Replen Trolley (12479-02) through engine → xlsx to Tim
- [ ] Run Milwaukee Wall Bay (1282) through engine → xlsx to James Ryan
- [ ] Seed BoughtInCatalogue from Tony's historical workbooks (target 50+ new rows)
  - `python migrate_bought_in_catalogue.py --source "K:\Estimating\Completed\AI Estimating\AISheets\"`
- [ ] Confirm SSH-M6-8-35-A2 shoulder screw price with Tim → update BoughtInCatalogue
- [ ] Add RAL9007 powder coat to catalogue (Trestle uses it, currently only RAL7016)
- [ ] Add tube sizes: 60×30×2mm, 50×50×2mm per-length prices from Tony

### Sunday 15 June
- [ ] Build `ingest_historical_to_db.py` — reads corpus JSONL → upserts into:
  - `dbo.historical_quote_material_line`
  - `dbo.historical_quote_operation`
  - `dbo.historical_quote_summary`
  - `dbo.historical_quote_part`
- [ ] Run first batch ingest: target 50 jobs from `K:\Estimating\Completed\`
- [ ] Verify RAG improvements on re-run of Trestle and Replen Trolley

---

## WEEK 1 (16–20 June) — Parallel Run + Engine Hardening

### Monday 16 June
- [ ] Collect Tim and Tony feedback on xlsx outputs
- [ ] Tony: Trestle parity session — line by line vs his manual workbook
  - Run full parity command against Tony's AISheets workbook
  - Document every gap > 10% in parity tracker
- [ ] Tim: Replen Trolley review — Decision Report walkthrough
- [ ] Fix any P1 issues from Tony/Tim feedback

### Tuesday 17 June
- [ ] Run 3 more jobs with known manual estimates (from AISheets folder)
  - Select mix: pure steel, mixed, timber/board
  - Record engine vs manual variance for each
- [ ] PET/PETG material misroute fix (`json_normaliser.py`) — P1
- [ ] Powder coat throughput model wiring into `estimator.py` — P1
- [ ] `Led` material detection fix — tubes being misread as LED

### Wednesday 18 June
- [ ] Historical ingest second batch: target 150 total jobs in DB
- [ ] Wire `wire_costing.py` into `estimator.py` — P2
- [ ] Add packing SKUs rules table (PALLET1, BOX per job size)
- [ ] Run parity on 2 more jobs — build confidence matrix

### Thursday 19 June
- [ ] Parallel run review meeting: James, Tim, Tony, Simon
  - Present: variance distribution across all jobs run so far
  - Identify remaining systematic gaps
  - Agree go-live acceptance criteria (e.g. within 15% on 80% of jobs)
- [ ] Address any blockers from review

### Friday 20 June
- [ ] Historical ingest third batch: target 300 total jobs
- [ ] Fix any remaining P1/P2 issues from parallel run
- [ ] Update BoughtInCatalogue: target 200+ rows total
- [ ] Tier 2 dead code removal: `_get_bought_in_part` from `pricing_service.py`

---

## WEEK 2 (23–27 June) — Pre-Go-Live Hardening

### Monday 23 June
- [ ] Run full parallel suite: 10+ jobs, all with known manual estimates
- [ ] Generate parity HTML report for each — share with Tim and Tony
- [ ] Begin intranet portal integration planning (post-go-live feature)
  - Define API endpoints: `/estimate`, `/parity`, `/status`
  - Design job submission UI (PDF + DXF upload)

### Tuesday 24 June
- [ ] Address all remaining parity gaps identified from full suite
- [ ] Set `SDI_API_KEY` in `.env` — required before wider access
- [ ] Portal: connect existing FastAPI (port 8071) to estimate trigger
- [ ] Test end-to-end: upload PDF → engine runs → xlsx appears in portal

### Wednesday 25 June
- [ ] Director access: Simon, MD, FD can view job results in portal
  - Read-only dashboard: jobs run, variance distribution, flags
- [ ] Dry run go-live: James Ryan submits Milwaukee Wall Bay via portal
- [ ] Document any remaining issues

### Thursday 26 June
- [ ] Final parallel run sign-off: Tony and Tim confirm acceptance
- [ ] Engine freeze: no new code changes after this date
- [ ] Final BoughtInCatalogue seeding from remaining Tony workbooks
- [ ] User guide: 1-page "how to submit a job" for Tim, Tony, Howard

### Friday 27 June
- [ ] Go-live preparation:
  - Verify all services running (FastAPI, DB connections)
  - Backup current state of DB and src/
  - Final smoke test on 3 jobs
  - Brief Simon on what goes live Monday

---

## GO-LIVE: Monday 30 June 2026

### Week of 30 June — Post Go-Live Monitoring
- [ ] Monitor first 5 live jobs through engine
- [ ] Daily parity check: engine vs estimator, flag any surprises
- [ ] Begin portal enhancements (job queue, email notifications)
- [ ] Plan TruTops Boost integration for real nesting yield data

---

## REMAINING OPEN ITEMS BY PRIORITY

### P1 — Must fix before go-live
| Item | Owner | ETA |
|---|---|---|
| PET/PETG material misroute | James | 17 Jun |
| Powder coat throughput wiring | James | 17 Jun |
| SSH-M6-8-35-A2 price confirmation | Tim | 14 Jun |
| Historical ingest (300 jobs) | James | 20 Jun |
| `SDI_API_KEY` set in .env | James | 24 Jun |

### P2 — Should fix before go-live
| Item | Owner | ETA |
|---|---|---|
| Wire goods costing model | James | 18 Jun |
| Packing SKUs rules table | James | 18 Jun |
| `Led` tube material fix | James | 17 Jun |
| RAL9007 in catalogue | James | 14 Jun |
| BoughtInCatalogue 200+ rows | James | 20 Jun |

### P3 — Post go-live
| Item | Owner | ETA |
|---|---|---|
| TruTops Boost integration | James | Jul |
| Portal job submission UI | James | Jul |
| Director dashboard | James | Jul |
| Dead code removal (tier 2) | James | Jul |
| Shapely net area geometry fix | James | Jul |

---

## PARALLEL RUN JOB TRACKER

| Job | Drawing | Reviewer | Engine | Manual | Variance | Status |
|---|---|---|---|---|---|---|
| Flat Pack Trestle | 11087-17-GA Rev J | Tony | £295.29 (cell) / £352.58 (prov) | £335.00 | -12% / +5% | ✅ In review |
| Replen Trolley | 12479-02-GA Rev A | Tim | TBD | TBD | TBD | 🔄 Running |
| Milwaukee Wall Bay | 1282 | James Ryan | TBD | ~£168.68 | TBD | ⏳ Pending |
| Job 4 | TBD | Tony | TBD | TBD | TBD | ⏳ Weekend |
| Job 5 | TBD | Tim | TBD | TBD | TBD | ⏳ Week 1 |

---

## SUCCESS CRITERIA FOR GO-LIVE
1. Engine within **15%** of manual estimate on **≥80%** of jobs run
2. No INSUFFICIENT DATA on jobs with full DXF coverage
3. All P1 items resolved
4. Tony and Tim sign off on parallel run
5. Simon briefed and portal accessible to directors

---

## VECTOR DB — QDRANT (Added 11 June)

### Why Qdrant over Chroma
- Persistent storage, production-grade, REST API
- Payload filtering (filter by material/gauge before vector search)
- Runs alongside existing FastAPI stack, same machine

### Setup (run once this weekend)
```powershell
# Install dependencies
pip install qdrant-client sentence-transformers --break-system-packages

# Start Qdrant (keep running as a service)
docker run -d --name qdrant -p 6333:6333 `
  -v C:\SDIIntelligence\qdrant_storage:/qdrant/storage `
  --restart always qdrant/qdrant
```

### Weekend ingest sequence (do in order)
```powershell
# Step 1: Generate corpus JSONL from all historical sheets
python corpus_ingest.py `
  --glob "K:\Estimating\Completed\**\*.xls" `
  --out "C:\ClaudeVision\output\corpus\historical_corpus.jsonl"

# Step 2: Ingest into SQL (RAG structured data)
python ingest_historical_to_db.py `
  --jsonl "C:\ClaudeVision\output\corpus\historical_corpus.jsonl"

# Step 3: Embed into Qdrant (semantic search)
python ingest_historical_to_qdrant.py `
  --jsonl "C:\ClaudeVision\output\corpus\historical_corpus.jsonl" `
  --batch-size 256

# Step 4: Test a query
python ingest_historical_to_qdrant.py `
  --query "mild steel laser cut 2mm bracket powder coat RAL9007"
```

### Collections created in Qdrant
| Collection | Content | Use |
|---|---|---|
| sdi_parts | One point per fabricated part | Price similar parts |
| sdi_jobs | One point per job | Find similar jobs |
| sdi_bought_in | One per bought-in line | Price similar bought-in items |

### Integration into pricing_service.py (Week 2)
- Add `_qdrant_lookup()` function after existing Jaccard RAG
- Embed incoming part description → vector search → top 5 matches → median price
- Falls back gracefully if Qdrant is not running
- Wire in alongside existing `dbo.historical_quote_material_line` Jaccard lookup

### Scripts delivered
- `ingest_historical_to_db.py` — SQL ingest ✅
- `ingest_historical_to_qdrant.py` — Qdrant ingest + query test ✅
