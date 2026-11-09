# ShopAssist RAG implementation and evaluation

**Date:** 9 November 2026 (reviewed)

## Implemented

1. Policy markdown and active product rows are synchronized into PostgreSQL's knowledge tables.
2. Markdown links, inline code, quote markers, and repeated whitespace are cleaned. Content is split into section-aware chunks near paragraph boundaries (900 characters by default).
3. Each chunk has a stable ID and its own 768-dimensional embedding column. Gemini embeddings are generated in batches of 32; incomplete, malformed, and non-finite vectors are rejected.
4. Retrieval ranks chunks lexically and by pgvector cosine similarity. Reciprocal-rank fusion combines the rankings, followed by a deterministic term-coverage/title relevance reranker.
5. Existing answer formatting selects concise excerpts and attaches the originating policy path or product SKU. If vector retrieval is not available, the request falls back to keyword retrieval.
6. The index contains published policies and catalog products only; it does not index conversation or private order data.

## Retrieval evaluation

Ten hand-authored questions with known policy/product sources were evaluated first on temporary SQLite keyword fallback and then on the configured PostgreSQL/pgvector index using Gemini query embeddings.

| Metric | Keyword fallback | Hybrid pgvector |
|---|---:|---:|
| Recall@1 | 90% (9/10) | 90% (9/10) |
| Recall@3 | 100% (10/10) | 100% (10/10) |
| Recall@5 | 100% (10/10) | 100% (10/10) |
| Mean reciprocal rank | 0.95 | 0.95 |
| Expected fact present in retrieved results | 100% (10/10) | 100% (10/10) |

The lowest-ranked question was “Who pays shipping if an item arrived defective?” Both modes ranked the shipping policy first and the returns policy second; the expected fact was still present in the results. The hybrid run exercised query embedding, pgvector cosine search, fusion, and reranking. Detailed outputs are in [`live_results/rag-retrieval.json`](live_results/rag-retrieval.json) and [`live_results/rag-retrieval-postgres.json`](live_results/rag-retrieval-postgres.json). Re-run with `python -m evaluation.rag_quality` or `python -m evaluation.rag_quality --postgres`.

## Remaining acceptance work

The last recorded PostgreSQL/pgvector evaluation found 21 embedded chunks. The measured hybrid results matched the keyword baseline on this small test set, so the benchmark confirms the vector path worked at evaluation time but does not show a quality lift. The current environment cannot reach the Docker engine, so the live database index was not revalidated during this review. Expand the question set and include paraphrases/ambiguous queries before making a broader quality claim.
