"""Measure whether known-answer questions retrieve their expected sources."""
from datetime import datetime, timezone
import argparse
import json
from pathlib import Path
import tempfile
import uuid

from src.config import settings
import src.services.database as database
from src.services.database import get_connection
from src.services.knowledge_service import search_knowledge

RESULT_PATH = Path(__file__).with_name("live_results") / "rag-retrieval.json"

CASES = [
    ("return_window", "How long do I have to return an item?", "knowledge/returns_policy.md", "14 days"),
    ("return_condition", "What condition must a returned item be in?", "knowledge/returns_policy.md", "original packaging"),
    ("defective_return_shipping", "Who pays shipping if an item arrived defective?", "knowledge/returns_policy.md", "free"),
    ("refund_timing", "How long after you receive a return is a refund processed?", "knowledge/returns_policy.md", "3–5 business days"),
    ("return_exclusions", "Can I return clearance items or earbud tips?", "knowledge/returns_policy.md", "cannot be returned"),
    ("cancel_confirmation", "When does an order cancellation become final?", "knowledge/cancellations_policy.md", "confirms"),
    ("payment_simulation", "Does ShopAssist actually charge my payment method?", "knowledge/payments_policy.md", "does not charge"),
    ("shipping_demo", "Are the tracking events from a live carrier?", "knowledge/shipping_policy.md", "demonstration data"),
    ("support_timing", "Does a ticket guarantee a response time?", "knowledge/support_policy.md", "do not guarantee"),
    ("product_keyboard", "How much is the Mechanical Keyboard and how many are in stock?", "products/SKU-201", "149.99"),
]


def evaluate(use_postgres: bool = False) -> dict:
    if use_postgres:
        if not settings.database_url.lower().startswith(("postgresql://", "postgres://")):
            raise RuntimeError("DATABASE_URL must point to PostgreSQL for vector evaluation.")
        if not settings.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY is required for vector evaluation.")
        conn = get_connection()
        try:
            counts = conn.execute(
                """SELECT COUNT(*) AS total,
                          COUNT(*) FILTER (WHERE embedding IS NULL) AS missing
                   FROM knowledge_chunks"""
            ).fetchone()
            if not counts["total"] or counts["missing"]:
                raise RuntimeError(
                    f"PostgreSQL index is incomplete ({counts['missing']} of "
                    f"{counts['total']} chunks have no embedding). Run the indexer first."
                )
        finally:
            conn.close()
        result_path = RESULT_PATH.with_name("rag-retrieval-postgres.json")
        retrieval_mode = "hybrid keyword + Gemini embedding + pgvector (configured PostgreSQL)"
    else:
        settings.database_url = ""
        settings.redis_url = ""
        database.DB_PATH = Path(tempfile.gettempdir()) / f"shopassist-rag-eval-{uuid.uuid4().hex}.db"
        database.init_db()
        result_path = RESULT_PATH
        retrieval_mode = "keyword-only fallback (temporary seeded SQLite)"

    cases = []
    reciprocal_rank = 0.0
    recalls = {1: 0, 3: 0, 5: 0}
    for case_id, query, expected_source, expected_fact in CASES:
        results = search_knowledge(query, limit=5)
        sources = [item["source"] for item in results]
        rank = next((index for index, source in enumerate(sources, 1) if source == expected_source), None)
        reciprocal_rank += (1 / rank) if rank else 0
        for k in recalls:
            recalls[k] += int(expected_source in sources[:k])
        relevant = next((item for item in results if item["source"] == expected_source), None)
        fact_found = bool(relevant and expected_fact.casefold() in relevant["content"].casefold())
        cases.append({
            "case_id": case_id,
            "expected_source": expected_source,
            "retrieved_sources": sources,
            "rank": rank,
            "expected_fact_in_retrieved_chunk": fact_found,
        })

    count = len(CASES)
    report = {
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "retrieval_mode": retrieval_mode,
        "question_count": count,
        "metrics": {
            "recall_at_1": recalls[1] / count,
            "recall_at_3": recalls[3] / count,
            "recall_at_5": recalls[5] / count,
            "mean_reciprocal_rank": reciprocal_rank / count,
            "expected_fact_in_retrieved_chunk": sum(c["expected_fact_in_retrieved_chunk"] for c in cases) / count,
        },
        "cases": cases,
        "limitations": [
            "No embeddings or vector search are exercised by this local benchmark.",
            "Questions and expected sources are hand-authored from this repository's demo policies and catalog.",
        ],
    }
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--postgres", action="store_true", help="Use the configured PostgreSQL pgvector index (read-only).")
    args = parser.parse_args()
    result = evaluate(use_postgres=args.postgres)
    path = RESULT_PATH.with_name("rag-retrieval-postgres.json") if args.postgres else RESULT_PATH
    print(json.dumps({"metrics": result["metrics"], "saved_to": str(path)}, indent=2))
