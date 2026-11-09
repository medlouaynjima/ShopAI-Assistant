"""Grounded retrieval for store policies and the live product catalog."""
import math
import re
import hashlib
import logging
from datetime import datetime
from pathlib import Path

from src.config import settings
from src.services.database import _PostgresConnection, get_connection

logger = logging.getLogger(__name__)

KNOWLEDGE_DIRECTORY = Path(__file__).resolve().parents[2] / "knowledge"

TOKEN_PATTERN = re.compile(r"[a-z0-9]+", re.IGNORECASE)
CHUNK_SIZE = 900
STOP_WORDS = {
    "about", "and", "can", "could", "does", "for", "from", "get", "have",
    "how", "i", "in", "is", "it", "me", "my", "of", "on", "please", "tell",
    "the", "this", "to", "we", "what", "when", "where", "which", "with",
    "you", "your",
}

def _normalized_tokens(text: str) -> set[str]:
    tokens = set(TOKEN_PATTERN.findall(text.lower()))
    normalized = set()
    for token in tokens:
        if token.endswith("ies") and len(token) > 4:
            token = token[:-3] + "y"
        elif token.endswith("s") and not token.endswith("ss") and len(token) > 3:
            token = token[:-1]
        normalized.add(token)
    return normalized


def clean_document(text: str) -> str:
    """Normalize markdown into readable plain text while preserving section headings."""
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"^\s*>\s?", "", text, flags=re.M)
    text = re.sub(r"^\s*[-*_]{3,}\s*$", "", text, flags=re.M)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def chunk_document(content: str, max_chars: int = CHUNK_SIZE) -> list[str]:
    """Split cleaned markdown into section-aware chunks near paragraph boundaries."""
    if max_chars < 100:
        raise ValueError("max_chars must be at least 100")
    sections: list[str] = []
    heading = ""
    for raw in content.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            heading = line.lstrip("# ").strip()
            continue
        cleaned = clean_document(line)
        if cleaned:
            sections.append(f"{heading}: {cleaned}" if heading else cleaned)

    chunks: list[str] = []
    current = ""
    for paragraph in sections:
        # Split unusually long paragraphs at sentence boundaries, then words.
        pieces = [paragraph]
        if len(paragraph) > max_chars:
            pieces = re.split(r"(?<=[.!?])\s+", paragraph)
        for piece in pieces:
            if len(piece) > max_chars:
                words = piece.split()
                piece = ""
                for word in words:
                    candidate = f"{piece} {word}".strip()
                    if len(candidate) > max_chars and piece:
                        if current:
                            chunks.append(current)
                            current = ""
                        chunks.append(piece)
                        piece = word
                    else:
                        piece = candidate
            candidate = f"{current}\n\n{piece}".strip()
            if len(candidate) > max_chars and current:
                chunks.append(current)
                current = piece
            else:
                current = candidate
    if current:
        chunks.append(current)
    return chunks


def load_policy_documents() -> list[tuple[str, str, str, str]]:
    """Discover and load every Markdown policy file under the knowledge folder."""
    documents = []
    for path in sorted(KNOWLEDGE_DIRECTORY.rglob("*.md")):
        relative = path.relative_to(KNOWLEDGE_DIRECTORY).as_posix()
        content = path.read_text(encoding="utf-8").strip()
        if not content:
            continue
        heading = next(
            (line.lstrip("# ").strip() for line in content.splitlines() if line.startswith("#")),
            path.stem.replace("_", " ").title(),
        )
        document_id = "policy-" + relative.removesuffix(".md").replace("/", "-")
        documents.append((document_id, f"knowledge/{relative}", heading, content))
    return documents


def _paragraphs(content: str, query: str, *, limit: int = 2) -> list[str]:
    """Select short, relevant prose from a source document, omitting markdown headings."""
    query_tokens = _normalized_tokens(query) - STOP_WORDS
    scored = []
    for index, raw in enumerate(re.split(r"\n\s*\n", content)):
        paragraph = " ".join(
            line.strip() for line in raw.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        )
        if not paragraph:
            continue
        overlap = query_tokens.intersection(_normalized_tokens(paragraph))
        if not overlap:
            continue
        score = len(overlap) / max(1, len(query_tokens))
        if re.search(r"\b(window|period|deadline|how many days)\b", query, re.I) and re.search(
            r"\b\d+\s+days?\b", paragraph, re.I
        ):
            score += 1
        scored.append((score, -index, paragraph))
    scored.sort(reverse=True)
    return [paragraph for _, _, paragraph in scored[:limit]]


def _embedding_model():
    if not settings.gemini_api_key:
        return None
    from langchain_google_genai import GoogleGenerativeAIEmbeddings

    return GoogleGenerativeAIEmbeddings(
        model="models/gemini-embedding-001",
        google_api_key=settings.gemini_api_key,
        output_dimensionality=768,
    )


def sync_knowledge_base() -> int:
    """Upsert current policy and product documents; preserve the source databases."""
    conn = get_connection()
    try:
        documents = load_policy_documents()
        products = conn.execute(
            """SELECT sku, name, category, description, price, inventory
               FROM products WHERE active = 1"""
        ).fetchall()
        documents.extend(
            (
                f"product-{product['sku']}",
                f"products/{product['sku']}",
                product["name"],
                f"{product['name']} ({product['sku']}) is in {product['category']}. "
                f"{product['description']} Price: ${product['price']:.2f}. "
                f"Inventory: {product['inventory']} units.",
            )
            for product in products
        )

        updated_at = datetime.now().isoformat()
        for document_id, source, title, content in documents:
            existing = conn.execute(
                "SELECT source, title, content FROM knowledge_documents WHERE document_id = ?",
                (document_id,),
            ).fetchone()
            if existing is None:
                conn.execute(
                    """INSERT INTO knowledge_documents
                       (document_id, source, title, content, updated_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (document_id, source, title, content, updated_at),
                )
            elif (
                existing["source"] != source
                or existing["title"] != title
                or existing["content"] != content
            ):
                conn.execute(
                    """UPDATE knowledge_documents
                       SET source = ?, title = ?, content = ?, updated_at = ?
                       WHERE document_id = ?""",
                    (source, title, content, updated_at, document_id),
                )
                if isinstance(conn, _PostgresConnection):
                    conn.execute(
                        "UPDATE knowledge_documents SET embedding = NULL WHERE document_id = ?",
                        (document_id,),
                    )

        desired_ids = {item[0] for item in documents}
        for row in conn.execute(
            """SELECT document_id FROM knowledge_documents
               WHERE source LIKE 'knowledge/%%' OR source LIKE 'products/%%'"""
        ).fetchall():
            if row["document_id"] not in desired_ids:
                conn.execute(
                    "DELETE FROM knowledge_chunks WHERE document_id = ?",
                    (row["document_id"],),
                )
                conn.execute(
                    "DELETE FROM knowledge_documents WHERE document_id = ?",
                    (row["document_id"],),
                )

        stored_documents = conn.execute(
            "SELECT document_id, content FROM knowledge_documents ORDER BY document_id"
        ).fetchall()
        for document in stored_documents:
            chunks = chunk_document(document["content"])
            existing_chunks = conn.execute(
                "SELECT ordinal, content FROM knowledge_chunks WHERE document_id = ? ORDER BY ordinal",
                (document["document_id"],),
            ).fetchall()
            if [(row["ordinal"], row["content"]) for row in existing_chunks] == list(enumerate(chunks)):
                continue
            conn.execute(
                "DELETE FROM knowledge_chunks WHERE document_id = ?",
                (document["document_id"],),
            )
            for ordinal, chunk in enumerate(chunks):
                chunk_id = hashlib.sha256(
                    f"{document['document_id']}:{ordinal}:{chunk}".encode("utf-8")
                ).hexdigest()
                conn.execute(
                    """INSERT INTO knowledge_chunks
                       (chunk_id, document_id, ordinal, content, updated_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (chunk_id, document["document_id"], ordinal, chunk, updated_at),
                )

        conn.commit()
        return len(documents)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _lexical_search(query: str, limit: int) -> list[dict]:
    tokens = {
        token for token in _normalized_tokens(query)
        if len(token) > 2 and token not in STOP_WORDS
    }
    if not tokens:
        return []

    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT d.source, d.title, c.content
               FROM knowledge_chunks c
               JOIN knowledge_documents d USING (document_id)"""
        ).fetchall()
    finally:
        conn.close()

    matches = []
    for row in rows:
        content_tokens = _normalized_tokens(f"{row['title']} {row['content']}")
        overlap = tokens & content_tokens
        if not overlap:
            continue
        coverage = len(overlap) / len(tokens)
        precision = len(overlap) / max(1, len(content_tokens))
        score = (0.8 * coverage) + (0.2 * precision)
        if score >= 0.08:
            matches.append({
                "source": row["source"],
                "title": row["title"],
                "content": row["content"],
                "score": score,
            })
    return sorted(matches, key=lambda match: match["score"], reverse=True)[:limit]


def _vector_search(query: str, limit: int) -> list[dict] | None:
    if not settings.database_url or not settings.gemini_api_key:
        return None

    conn = None
    try:
        model = _embedding_model()
        if model is None:
            return None
        conn = get_connection()
        unindexed = conn.execute(
            "SELECT COUNT(*) FROM knowledge_chunks WHERE embedding IS NULL"
        ).fetchone()[0]
        if unindexed:
            return None
        query_vector = model.embed_query(query)
        vector_literal = "[" + ",".join(str(value) for value in query_vector) + "]"
        rows = conn.execute(
            """SELECT d.source, d.title, c.content,
                      1 - (c.embedding <=> ?::vector) AS score
               FROM knowledge_chunks c
               JOIN knowledge_documents d USING (document_id)
               ORDER BY c.embedding <=> ?::vector
               LIMIT ?""",
            (vector_literal, vector_literal, limit),
        ).fetchall()
        return [
            {
                "source": row["source"],
                "title": row["title"],
                "content": row["content"],
                "score": float(row["score"]),
            }
            for row in rows
            if float(row["score"]) >= 0.35
        ]
    except Exception as error:
        logger.warning("Vector retrieval failed; using keyword retrieval (%s).", type(error).__name__)
        return None
    finally:
        if conn is not None:
            conn.close()


def search_knowledge(query: str, limit: int = 4) -> list[dict]:
    """Hybrid retrieve cited evidence and rerank the combined candidate set."""
    clean_query = query.strip()
    if not clean_query:
        return []
    lexical = _lexical_search(clean_query, max(limit * 3, 8))
    vector = _vector_search(clean_query, max(limit * 3, 8)) or []
    # Reciprocal rank fusion combines lexical and cosine rankings without
    # assuming that their score scales are comparable.
    fused: dict[tuple[str, str], dict] = {}
    for ranking in (lexical, vector):
        for rank, item in enumerate(ranking, start=1):
            key = (item["source"], item["content"])
            candidate = fused.setdefault(key, {**item, "score": 0.0, "lexical_score": 0.0})
            candidate["score"] += 1.0 / (60 + rank)
            if ranking is lexical:
                candidate["lexical_score"] = item["score"]
    query_tokens = _normalized_tokens(clean_query) - STOP_WORDS
    matches = list(fused.values())
    for item in matches:
        item_tokens = _normalized_tokens(f"{item['title']} {item['content']}")
        coverage = len(query_tokens & item_tokens) / max(1, len(query_tokens))
        title_hits = len(query_tokens & _normalized_tokens(item["title"]))
        # Lightweight deterministic reranker: reward question term coverage
        # and title relevance after hybrid candidate generation.
        item["score"] += (0.02 * coverage) + (0.01 * title_hits)
    matches.sort(key=lambda item: item["score"], reverse=True)
    if matches:
        # Avoid returning weakly related policy chunks just because they share a
        # broad term (for example, a payments document mentioning a return).
        relevance_floor = matches[0]["score"] * 0.7
        matches = [item for item in matches if item["score"] >= relevance_floor]
    matches = matches[:max(limit, 1)]
    return matches


def format_evidence(query: str) -> str:
    """Return concise, relevant grounded excerpts with citations."""
    results = search_knowledge(query)
    if not results:
        return (
            "I couldn't find a matching answer in the ShopAssist policy or product "
            "documents. Please contact support for confirmation."
        )
    evidence = []
    for item in results[:2]:
        excerpts = _paragraphs(item["content"], query, limit=1)
        if excerpts:
            evidence.append(
                f"{item['title']}: {excerpts[0]}\nSource: `{item['source']}`"
            )
    if not evidence:
        return (
            "I couldn't find a matching answer in the ShopAssist policy or product "
            "documents. Please contact support for confirmation."
        )
    return "\n\n".join(evidence)


def index_embeddings() -> int:
    """Embed pending chunks in PostgreSQL/pgvector in bounded batches."""
    if not settings.database_url.lower().startswith(("postgresql://", "postgres://")):
        raise RuntimeError("Set DATABASE_URL to a PostgreSQL database before indexing.")
    if not settings.gemini_api_key:
        raise RuntimeError("Set GEMINI_API_KEY before generating document embeddings.")

    from src.services.database import init_db

    init_db()
    sync_knowledge_base()
    model = _embedding_model()
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT chunk_id, content FROM knowledge_chunks
               WHERE embedding IS NULL ORDER BY document_id, ordinal"""
        ).fetchall()
        if not rows:
            return 0
        indexed = 0
        for offset in range(0, len(rows), 32):
            batch = rows[offset:offset + 32]
            embeddings = model.embed_documents([row["content"] for row in batch])
            if len(embeddings) != len(batch):
                raise RuntimeError("Embedding provider returned an incomplete batch.")
            for row, vector in zip(batch, embeddings):
                if len(vector) != 768:
                    raise RuntimeError(
                        f"Embedding dimension mismatch for chunk {row['chunk_id']}: "
                        f"expected 768, got {len(vector)}."
                    )
                if not all(math.isfinite(float(value)) for value in vector):
                    raise RuntimeError("Embedding provider returned a non-finite value.")
                vector_literal = "[" + ",".join(str(float(value)) for value in vector) + "]"
                conn.execute(
                    "UPDATE knowledge_chunks SET embedding = ?::vector WHERE chunk_id = ?",
                    (vector_literal, row["chunk_id"]),
                )
            conn.commit()
            indexed += len(batch)
        return indexed
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    indexed = index_embeddings()
    print(f"Generated and stored embeddings for {indexed} knowledge chunks.")
