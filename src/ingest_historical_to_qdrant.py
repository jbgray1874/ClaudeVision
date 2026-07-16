#!/usr/bin/env python3
"""
ingest_historical_to_qdrant.py — Embed corpus JSONL records into Qdrant vector DB
for semantic RAG pricing lookups.

Complements ingest_historical_to_db.py — both read the same corpus JSONL.
Qdrant stores the embedding vectors; SQL stores the full structured data.
At query time: vector search in Qdrant -> get SQL IDs -> join SQL for prices.

Collections created:
    sdi_parts    — one point per steel fabricated part (description + material + ops)
    sdi_jobs     — one point per job (description + customer + materials used)
    sdi_bought_in — one per bought-in line (description + part code)

Usage:
    # Start Qdrant first:
    docker run -p 6333:6333 -v C:/SDIIntelligence/qdrant_storage:/qdrant/storage qdrant/qdrant

    # Run ingest:
    python ingest_historical_to_qdrant.py --jsonl corpus.jsonl
    python ingest_historical_to_qdrant.py --jsonl corpus.jsonl --batch-size 256 --dry-run

    # Query test:
    python ingest_historical_to_qdrant.py --query "mild steel laser cut 2mm bracket"
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

LOG = logging.getLogger("ingest_historical_to_qdrant")

QDRANT_HOST = "localhost"
QDRANT_PORT = 6333
EMBED_MODEL  = "sentence-transformers/all-MiniLM-L6-v2"  # 384-dim, fast, local

COLLECTION_PARTS    = "sdi_parts"
COLLECTION_JOBS     = "sdi_jobs"
COLLECTION_BOUGHT_IN = "sdi_bought_in"
VECTOR_SIZE = 384


# ── Embedding ──────────────────────────────────────────────────────────────────
_encoder = None

def get_encoder():
    global _encoder
    if _encoder is None:
        from sentence_transformers import SentenceTransformer
        LOG.info("Loading embedding model %s ...", EMBED_MODEL)
        _encoder = SentenceTransformer(EMBED_MODEL)
        LOG.info("Embedding model loaded")
    return _encoder


def embed_batch(texts: List[str]) -> List[List[float]]:
    enc = get_encoder()
    vecs = enc.encode(texts, batch_size=64, show_progress_bar=False, normalize_embeddings=True)
    return vecs.tolist()


# ── Qdrant helpers ─────────────────────────────────────────────────────────────
def get_qdrant_client():
    from qdrant_client import QdrantClient
    return QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT, timeout=30)


def ensure_collections(client) -> None:
    from qdrant_client.models import Distance, VectorParams
    existing = {c.name for c in client.get_collections().collections}
    for name in [COLLECTION_PARTS, COLLECTION_JOBS, COLLECTION_BOUGHT_IN]:
        if name not in existing:
            client.create_collection(
                collection_name=name,
                vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
            )
            LOG.info("Created collection: %s", name)
        else:
            LOG.info("Collection exists: %s", name)


def upsert_points(client, collection: str, points: List[Dict]) -> None:
    from qdrant_client.models import PointStruct
    structs = [
        PointStruct(id=p["id"], vector=p["vector"], payload=p["payload"])
        for p in points
    ]
    client.upsert(collection_name=collection, points=structs, wait=True)


# ── Payload builders ───────────────────────────────────────────────────────────
def _s(v) -> Optional[str]:
    return str(v).strip()[:300] if v not in (None, "") else None

def _f(v) -> Optional[float]:
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None

def _i(v) -> Optional[int]:
    try:
        return int(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def build_part_payload(rec: Dict, sql_summary_id: Optional[int] = None) -> Dict:
    return {
        "record_type": "part",
        "source_workbook": _s(rec.get("source", {}).get("workbook")),
        "job_no": _s(rec.get("job_no")),
        "year": _i(rec.get("year")),
        "part_number": _s(rec.get("part_number")),
        "description": _s(rec.get("description")),
        "material": _s(rec.get("material")),
        "thickness_mm": _f(rec.get("thickness_mm")),
        "length_mm": _f(rec.get("length_mm")),
        "width_mm": _f(rec.get("width_mm")),
        "quantity": _i(rec.get("quantity")),
        "material_cost_gbp": _f(rec.get("material_cost_gbp")),
        "labour_cost_per_part_gbp": _f(rec.get("labour_cost_per_part_gbp")),
        "operations": [_s(o.get("operation")) for o in (rec.get("operations") or []) if o.get("operation")],
        "sql_summary_id": sql_summary_id,
        "embedding_text": _s(rec.get("embedding_text")),
    }


def build_job_payload(rec: Dict, sql_summary_id: Optional[int] = None) -> Dict:
    return {
        "record_type": "job",
        "source_workbook": _s(rec.get("source", {}).get("workbook")),
        "job_no": _s(rec.get("job_no")),
        "description": _s(rec.get("description")),
        "customer": _s(rec.get("customer")),
        "year": _i(rec.get("year")),
        "quantity": _i(rec.get("quantity")),
        "unit_cost_gbp": _f(rec.get("unit_cost_gbp")),
        "raw_manufacturing_cost_gbp": _f(rec.get("raw_manufacturing_cost_gbp")),
        "materials_used": _s(", ".join(rec.get("materials_used") or [])),
        "departments_used": _s(", ".join(rec.get("departments_used") or [])),
        "part_count": _i(rec.get("part_count")),
        "sql_summary_id": sql_summary_id,
        "embedding_text": _s(rec.get("embedding_text")),
    }


def build_bought_in_payload(rec: Dict, sql_summary_id: Optional[int] = None) -> Dict:
    desc = _s(rec.get("description") or rec.get("part_code") or "")
    return {
        "record_type": "bought_in",
        "source_workbook": _s(rec.get("source", {}).get("workbook")),
        "job_no": _s(rec.get("job_no")),
        "year": _i(rec.get("year")),
        "part_code": _s(rec.get("part_code")),
        "description": desc,
        "supplier": _s(rec.get("supplier")),
        "unit_price_gbp": _f(rec.get("unit_price_gbp")),
        "qty_per_unit": _f(rec.get("qty_per_unit") or rec.get("quantity")),
        "sql_summary_id": sql_summary_id,
        "embedding_text": desc,
    }


# ── SQL ID lookup (optional — links Qdrant points to SQL rows) ─────────────────
def _get_sql_id_map(workbooks: List[str]) -> Dict[str, int]:
    """Fetch existing SQL summary IDs for faster linkage."""
    try:
        import pyodbc
        conn = pyodbc.connect(
            "DRIVER={ODBC Driver 18 for SQL Server};"
            "SERVER=10.0.0.200;DATABASE=SDILive;"
            "UID=AIBot;PWD=AIAgentPW2026;"
            "Encrypt=yes;TrustServerCertificate=yes;"
        )
        cur = conn.cursor()
        placeholders = ",".join("?" * len(workbooks))
        cur.execute(
            f"SELECT source_workbook, id FROM AIEstimating.historical_quote_summary "
            f"WHERE source_workbook IN ({placeholders})", workbooks
        )
        result = {row[0]: row[1] for row in cur.fetchall()}
        conn.close()
        return result
    except Exception as e:
        LOG.warning("Could not fetch SQL IDs (continuing without): %s", e)
        return {}


# ── Main ingest ────────────────────────────────────────────────────────────────
def ingest_jsonl(jsonl_path: Path, batch_size: int = 128, dry_run: bool = False) -> None:
    # Load all records
    records: List[Dict] = []
    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass

    LOG.info("Loaded %d records from %s", len(records), jsonl_path)

    # Separate by type
    job_recs = [r for r in records if r.get("record_type") == "job"]
    part_recs = [r for r in records if r.get("record_type") == "part"]
    bi_recs   = [r for r in records if r.get("record_type") == "bought_in"]

    LOG.info("Jobs: %d  Parts: %d  Bought-in: %d", len(job_recs), len(part_recs), len(bi_recs))

    if dry_run:
        LOG.info("[DRY RUN] Would embed and upsert %d points across 3 collections",
                 len(job_recs) + len(part_recs) + len(bi_recs))
        LOG.info("[DRY RUN] Sample part embedding_text: %s",
                 part_recs[0].get("embedding_text") if part_recs else "N/A")
        return

    # Get SQL ID map for linkage
    all_workbooks = list({r.get("source", {}).get("workbook", "") for r in records if r.get("source")})
    sql_id_map = _get_sql_id_map(all_workbooks[:500])  # batch limit

    # Connect to Qdrant
    client = get_qdrant_client()
    ensure_collections(client)

    # Helper: upsert in batches
    def _ingest_collection(recs: List[Dict], collection: str, payload_fn) -> int:
        total = 0
        batch_texts = []
        batch_recs  = []

        def _flush():
            nonlocal total
            if not batch_recs:
                return
            vecs = embed_batch(batch_texts)
            points = []
            for i, (rec, vec) in enumerate(zip(batch_recs, vecs)):
                src = rec.get("source", {}).get("workbook", "")
                sql_id = sql_id_map.get(src)
                payload = payload_fn(rec, sql_id)
                # Use a stable integer ID: hash of workbook+job_no+index
                point_id = abs(hash(f"{src}|{rec.get('job_no','')}|{collection}|{total+i}")) % (2**53)
                points.append({"id": point_id, "vector": vec, "payload": payload})
            upsert_points(client, collection, points)
            total += len(points)
            LOG.info("  %s: %d upserted", collection, total)

        for rec in recs:
            text = rec.get("embedding_text") or ""
            if not text.strip():
                continue
            batch_texts.append(text)
            batch_recs.append(rec)
            if len(batch_recs) >= batch_size:
                _flush()
                batch_texts = []
                batch_recs  = []

        _flush()
        return total

    n_parts = _ingest_collection(part_recs,  COLLECTION_PARTS,    build_part_payload)
    n_jobs  = _ingest_collection(job_recs,   COLLECTION_JOBS,     build_job_payload)
    n_bi    = _ingest_collection(bi_recs,    COLLECTION_BOUGHT_IN, build_bought_in_payload)

    LOG.info("Qdrant ingest complete: %d parts, %d jobs, %d bought-in", n_parts, n_jobs, n_bi)


# ── Query test ─────────────────────────────────────────────────────────────────
def query_parts(query_text: str, top_k: int = 5) -> None:
    client = get_qdrant_client()
    vec = embed_batch([query_text])[0]
    results = client.search(
        collection_name=COLLECTION_PARTS,
        query_vector=vec,
        limit=top_k,
        with_payload=True,
    )
    print(f"\nTop {top_k} similar parts for: '{query_text}'\n{'─'*60}")
    for r in results:
        p = r.payload
        print(f"  Score: {r.score:.3f} | {p.get('part_number','?')} — {p.get('description','?')}")
        print(f"    Material: {p.get('material','?')} | Thickness: {p.get('thickness_mm','?')}mm")
        print(f"    Mat cost: £{p.get('material_cost_gbp','?')} | "
              f"Lab cost: £{p.get('labour_cost_per_part_gbp','?')}")
        print(f"    Job: {p.get('job_no','?')} ({p.get('year','?')}) | "
              f"Source: {p.get('source_workbook','?')}")
        print()


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s"
    )

    parser = argparse.ArgumentParser(description="Embed corpus JSONL into Qdrant vector DB")
    parser.add_argument("--jsonl", help="Path to corpus JSONL from corpus_ingest.py")
    parser.add_argument("--batch-size", type=int, default=128, help="Embedding batch size")
    parser.add_argument("--dry-run", action="store_true", help="Count records only, no writes")
    parser.add_argument("--query", help="Test query against sdi_parts collection")
    parser.add_argument("--top-k", type=int, default=5, help="Number of results for --query")
    args = parser.parse_args()

    if args.query:
        query_parts(args.query, args.top_k)
        return

    if not args.jsonl:
        parser.error("--jsonl required unless using --query")

    jsonl_path = Path(args.jsonl)
    if not jsonl_path.exists():
        LOG.error("JSONL file not found: %s", jsonl_path)
        sys.exit(1)

    LOG.info("Starting Qdrant ingest from %s (dry_run=%s)", jsonl_path, args.dry_run)
    ingest_jsonl(jsonl_path, batch_size=args.batch_size, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
