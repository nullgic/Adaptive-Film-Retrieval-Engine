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

**Chose:** top 20 billed cast members. "Top" means the `cast` entry's `order`
field — TMDB's billing order, so `order: 0` is the lead. Checked on a 200-movie
sample: 0 entries missing the key, 192/199 starting at 0.

**Alternatives:** 5, 10, or all.

**Why:** the cutoff was judgement, but it was informed by the distribution:

| median | mean | p90 | p95 | max |
|---|---|---|---|---|
| 10 | 12.4 | 23 | 32 | 313 |

| cutoff | movies that reach it | names indexed |
|---|---|---|
| 5 | 37,207 (81.8%) | 202,490 |
| 10 | 23,724 (52.2%) | 347,954 |
| 20 | 6,608 (14.5%) | 474,165 |
| all | — | 562,474 |

Only 14.5% of films have 20+ cast, so 20 captures the *entire* cast for 85% of
the corpus while costing 36% more names than 10. The dilution argument for a
tighter cutoff was really an argument about embeddings, and per D-004 cast is
lexical-only — in an inverted index, a query for a minor actor returning a film
they appeared in is correct behaviour, not noise.

**Cost:** larger `facets_text`, and the C-weight band carries more names that
nobody will search for.

**How I'd settle it:** vary across 5 / 10 / 20 / all and measure recall on a set
of cast-name queries. The distribution is measured; the cutoff still isn't tuned.

---

## D-007: Deduplicate by highest popularity

**Chose:** sort by popularity descending, then `drop_duplicates(keep="first")`.

**Alternatives:** keep whichever row appears first in the file; keep the row with
the highest `vote_count`; inspect all the duplicate pairs manually.

**Verified — the pairs were inspected.** 29 distinct ids appear more than once
(30 excess rows; one id appears three times). Of those:

- **16 pairs are byte-identical** — the same row captured twice.
- **13 pairs differ in exactly one field: `popularity`.**

```
id 132641:  popularity  ['0.096079', '0.619388']
id  22649:  popularity  ['1.914697', '2.411191']
id  84198:  popularity  ['0.501046', '1.673307']
```

Title, overview, vote_count and everything else are identical throughout. These
are not different movies — `popularity` is a time-varying TMDB metric, and the
dataset was scraped over a period, so the same film was captured at two moments.

**Why:** popularity is the *only* field that moves, so the higher value is the
more recent observation. Sorting descending before `keep="first"` makes "first"
mean "most recent scrape" rather than "whatever order the CSV happened to be in",
which is both deterministic and justifiable.

**Why not `vote_count`:** it looks more principled and isn't. `vote_count` is
**tied in 27 of the 29 groups**, so the rule would fall back to arbitrary 93% of
the time while appearing to have a reason. Worse than admitting arbitrariness.

**Cost:** for the 16 identical pairs the rule is a coin flip, which is fine —
the rows are the same.

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

**Corrected (measured with the real tokenizer, `scripts/check_model.py`):** the
numbers above came from the `WORDPIECE_PER_WORD = 1.3` estimate in config.py and
the tail was wrong.

| | estimated | measured |
|---|---|---|
| median | 81 | 80 |
| p95 | 181 | 180 |
| p99 | 222 | 225 |
| **max** | **482** | **653** |
| truncated at 256 | 30 (0.1%) | 74 (0.16%) |
| truncated at 512 | 0 | 4 (0.01%) |

The average ratio was fine — 1.29 measured against 1.3 assumed. The tail was not.
A flat multiplier assumes every word costs the same number of word-pieces, and
the document that blew the estimate is not even the longest one:

| | chars | words | tokens |
|---|---|---|---|
| Werckmeister Harmonies | 2,480 | 368 | fits in 512 |
| **Shadowboxing** | 806 | 133 | **653** |

Shadowboxing's overview is written in Russian. An English-vocabulary tokenizer
has no word-pieces for Cyrillic and falls back to near-per-character splitting —
4.9 tokens per word against a corpus average of 1.29. No word-count estimate can
see that coming.

This is an outlier rather than a pattern: 20 overviews contain Cyrillic and 5
contain CJK out of 45,433. Foreign-language *films* are common (2,436 French,
1,347 Japanese, 826 Russian) but their overviews are written in English.

**The lesson stands and gets sharper:** the estimate was good enough to make the
right shortlist and not good enough to make the decision. "Against 512, zero"
was false.

---

## D-010: Embedding model — `BAAI/bge-small-en-v1.5`

**Chose:** `BAAI/bge-small-en-v1.5`. 384 dimensions, 512-token window, both read
off the model itself via `scripts/check_model.py`, not from documentation.

**Alternatives:**
- `all-MiniLM-L6-v2` — 384 dims, 256-token window, the common default
- `all-mpnet-base-v2` — 768 dims, slower, better benchmark scores
- `multi-qa-mpnet-base-dot-v1` — 768 dims, tuned for query-to-passage matching
- API embeddings (OpenAI, Cohere) — likely better, cost money, add latency

**Why:** measured against the real corpus, both 384-dim candidates were checked
with their own tokenizers over all 45,433 documents:

| model | window | documents truncated |
|---|---|---|
| BGE-small-en-v1.5 | 512 | 4 (0.01%) |
| all-MiniLM-L6-v2 | 256 | 74 (0.16%) |

Same column width, same storage cost, 18× fewer truncated documents. MiniLM's
narrower window buys nothing back. The two mpnet models were not measured —
they would double the column to 768 dims, and that tradeoff was not worth
testing before a baseline exists to measure any gain against.

**Cost / what this gives up:** benchmark scores favour the 768-dim mpnet models.
This picks the cheaper column without evidence that the more expensive one would
retrieve better *on this corpus* — that comparison needs the Judge layer, which
does not exist yet.

**Not zero:** 4 documents still exceed 512 tokens and will be silently cut. The
longest document in the corpus is 653 tokens (`Shadowboxing`, see D-009). No
384-dim option avoids this. Accepted at 0.01%, and the affected films keep their
full lexical index either way, so they remain findable.

**How I'd settle the mpnet question:** once precision@k and NDCG exist against
the held-out query set, re-embed with `all-mpnet-base-v2` and compare.

**Note:** re-embedding later is not catastrophic here. Because users are
simulated, a model change means regenerating sessions and recomputing the
baseline — an evening's work, not a lost project.

**API note:** this entry originally specified `m.get_sentence_embedding_dimension()`.
sentence-transformers 5.x renamed it to `get_embedding_dimension()`; the old name
still works but emits a FutureWarning.

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
