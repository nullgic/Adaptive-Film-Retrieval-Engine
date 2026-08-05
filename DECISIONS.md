# Decisions

Architecture decision records for the Adaptive Film Retrieval Engine.

Written at decision time, not after. Each entry: what was chosen, what the
alternatives were, why, and — where the choice is arbitrary — what evidence
would settle it.

A decision with "picked it, didn't tune it" as the honest answer is fine.
A decision where I can't name the alternatives is a signal to go find them.

---

## D-001: Postgres + pgvector over a separate vector store

**Chose:** one Postgres instance holding documents and vectors together.

**Alternatives:**
- FAISS — a standalone index file, faster at scale, lives outside the database
- Pinecone / Weaviate — managed vector databases, network calls, cost money
- Elasticsearch — strong lexical search, vector support bolted on later

**Why:** metadata filters and vector similarity can happen in a single query.
With FAISS, filtering by year or genre means retrieving from the index, then
joining against a separate database by hand. At 45k documents the performance
gap doesn't bite.

**Cost:** slower than FAISS at large scale. Would revisit above ~1M documents.

---

## D-002: `genres` as `text[]` rather than a join table

**Chose:** array column with a GIN index.

**Alternatives:**
- A `genres` table plus a `movie_genres` join table (textbook normalized form)
- A single comma-separated `text` column (denormalized, no index support)

**Why:** reads stay join-free, and `WHERE genres @> ARRAY['Comedy']` is fast
with a GIN index at 45k rows.

**Cost:** genre names are duplicated across rows rather than stored once, and
renaming a genre would mean updating every row. A normalized schema would be
the right call if genres were edited frequently or carried their own metadata.

**TODO:** be able to explain why a databases course would teach the join table
version, and why this project doesn't need it.

---

## D-003: Load the full corpus, not a subset

**Chose:** all ~45,433 movies.

**Alternatives:** a 5k or 10k subset for faster iteration during week 1.

**Why:** ingestion is fast enough with COPY that the full load isn't a
bottleneck. A subset would have to be swapped out before evaluation anyway.

---

## D-004: Cast and directors in the lexical document, not the embedding

**Chose:** cast and director names go into `facets_text` (feeding `search_tsv`)
but not into `search_text` (feeding the embedder).

**Alternatives:** both, or neither.

**Why:** lexical search handles proper nouns precisely — searching "Tom Hanks"
should return exactly his films, and it does (96 of them). Dense embedding
models handle rare proper nouns poorly; a name is an arbitrary token with
little semantic structure, so adding them mostly adds noise.

---

## D-005: Keywords in BOTH documents

**Chose:** keywords go into `facets_text` and `search_text`.

**Alternatives:** lexical only, matching the treatment of cast.

**Why:** keywords are concepts (`jealousy`, `toy comes to life`), not proper
nouns, so the argument for excluding cast doesn't transfer — concept words are
exactly what embeddings encode well. Decisive factor: 954 movies have no
overview at all, and without keywords their embedding input would be title plus
genres, which is nearly content-free.

---

## D-006: `MAX_CAST = 20`

**Chose:** top 20 billed cast members.

**Alternatives:** 5, 10, or all (~50 average).

**Why:** picked on judgement, not measured. More names help queries like "that
movie with the guy from X"; fewer names keep the lexical document tighter.

**How I'd settle it:** vary it across 5 / 10 / 20 / all, and measure recall on
a set of cast-name queries. Currently untuned and I should say so.

---

## D-007: Deduplicate by highest popularity

**Chose:** sort by popularity descending, then `drop_duplicates(keep="first")`.

**Alternatives:** keep whichever row appears first in the file; keep the most
complete row; inspect all 30 duplicate pairs manually.

**Why:** 30 duplicate ids out of 45,466. Sorting first makes "first" mean
"highest popularity" rather than "whatever order the CSV happened to be in",
which makes the result deterministic and picks the more canonical row.

**TODO:** nobody checked whether the duplicate pairs actually differ in content.
Worth one look.

---

## D-008: Weighted `ts_rank` (A / B / C), not BM25

**Chose:** Postgres full-text search with `setweight` — title A, tagline and
overview B, facets C.

**Alternatives:**
- Unweighted `ts_rank`
- Real BM25 via the `pg_search` extension
- Elasticsearch, which uses BM25 by default

**Why:** already in the database, no extra service. The weights produce a real
quality difference: title matches score ~0.99, plot-only matches ~0.54.

**Important:** `ts_rank` is NOT BM25. It's a simpler tf-idf-style scheme without
BM25's term-frequency saturation or document-length normalization. Say
"weighted `ts_rank`", never "BM25".

**Note:** the A/B/C weights are a hardcoded relevance prior — a hand-tuned belief
about what matters. That's exactly what the learned reranker will be measured
against later.

---

## D-009: Measure token lengths before choosing an embedding model

**Chose:** measure the distribution of document token lengths during ingestion
rather than assuming documents fit.

**Result:** median 81, p95 181, p99 222, max 482. Against a 256-token window,
30 of 45,433 documents (0.1%) would be truncated. Against 512, zero.

**Why it mattered:** truncation is silent — no error, no warning, content just
disappears. This measurement is what makes the model choice evidence-based
rather than a guess.

---

## D-010: Embedding model — OPEN

**Leading candidate:** `BAAI/bge-small-en-v1.5` — 384 dimensions, 512-token
window.

**Alternatives:**
- `all-MiniLM-L6-v2` — 384 dims, 256-token window, the common default
- `all-mpnet-base-v2` — 768 dims, slower, better benchmark scores
- `multi-qa-mpnet-base-dot-v1` — 768 dims, tuned for query-to-passage matching
- API embeddings (OpenAI, Cohere) — likely better, cost money, add latency

**Reasoning so far:** BGE-small gives the same column width as MiniLM with twice
the context window and better retrieval benchmarks. At 45k documents the speed
difference between 384 and 768 dimensions barely matters, so this should be
decided on quality rather than speed.

**Before committing:** confirm the dimension count directly from the model —
`m.get_sentence_embedding_dimension()` — rather than trusting a number from
documentation. The `vector(N)` column must match exactly or every insert fails.

**Note:** re-embedding later is not catastrophic here. Because users are
simulated, a model change means regenerating sessions and recomputing the
baseline — an evening's work, not a lost project.

---

## Template

```markdown
## D-0NN: Short title

**Chose:**

**Alternatives:**

**Why:**

**Cost / what this gives up:**

**How I'd settle it:** (for arbitrary knobs — what evidence would decide it)
```
