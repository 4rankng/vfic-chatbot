# Files

- [Knowledge ingestion pipeline and category worker](ingestion.md) - From upload to pgvector — parse → canonicalize → digest (LLM) → embed → write — plus the version-ingest path, the category worker that reconciles project taxonomy, and the recovery semantics introduced by migration 0050.
- [Knowledge base, RAG retrieval, and pgvector layout](rag.md) - Per-project knowledge documents, the EMBEDDING_DIM schema pin, pgvector halfvec HNSW + exact rerank, the retrieval flow with chunk visibility rules, and the direct-context capacity invariants.
- [Single page sync](single-page-sync.md)
