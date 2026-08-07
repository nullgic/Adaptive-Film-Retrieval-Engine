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

**Answered — why a databases course teaches the join table, and why this schema
does not need it.**

Measured shape of the problem: **20** distinct genres, **2.00** per film on
average (max 8), **2,442** films with none, **91,015** genre cells in total.
The normalised form would be a `genres` table of 20 rows plus a `movie_genres`
join table of 91,015 rows.

A course teaches the join table for four reasons, and they are all real:

1. **Update anomaly.** Renaming *Science Fiction* to *Sci-Fi* touches one row in
   a `genres` table. With arrays it means rewriting the array in every affected
   row. The same fact is stored 20,244 times for *Drama* alone, and anything
   stored many times can disagree with itself.
2. **Referential integrity.** A foreign key makes `'Dramaa'` impossible to
   insert. `text[]` accepts any string at all.
3. **The vocabulary becomes data.** The `genres` table *is* the list of valid
   genres. With arrays you have to derive it — `SELECT DISTINCT g FROM movies,
   unnest(genres) g` — and that only tells you what exists, not what is allowed.
4. **Somewhere to put attributes.** If a genre later needs a description, a
   parent genre, or a display order, a row can hold them. An array element is a
   bare string with nowhere to hang anything.

Why none of that bites here:

- **The table is write-once.** `ingest.py` truncates and reloads. There is no
  `UPDATE` path against `genres` anywhere in the codebase, so the update anomaly
  in (1) cannot occur — not "is unlikely", cannot. A rename upstream is handled
  by re-ingesting, which was going to be cheaper than an `UPDATE` regardless.
- **The vocabulary is closed and not ours.** All 20 values come from TMDB and
  are parsed, never typed. The typo a foreign key protects against in (2) is one
  this pipeline has no way to introduce.
- **A genre is only a name.** Nothing in this project needs (4), and adding a
  join table on the chance that something might is speculative.
- **Reads stay join-free.** `genres @> ARRAY['Comedy']` against a GIN index,
  versus a two-table join, on the hot path of every filtered search.

**The honest caveat on 1NF:** a purist would say a repeating group in one column
violates first normal form. That objection was written about comma-separated
strings in a `varchar`. A Postgres `text[]` is a typed, constrained, indexable
column with real operators, which is a materially different thing — but "it's
fine, it's an array" is not an argument, and the four points above are what
actually carry the decision.

**What would flip it:** genres becoming editable in the product, or needing any
attribute of their own. Either one makes the array wrong, and migrating means
rewriting all 45,433 rows.

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

## D-011: Encode every document, including the content-free ones

**Chose:** all 45,433 documents get an embedding. No minimum content threshold.

**The problem:** `search_text` quality is a gradient, not a binary.

| tier | count | what the embedder reads |
|---|---|---|
| has overview | 44,474 | real prose |
| no overview, has keywords | 205 | title + concept words (the D-005 rescue) |
| no overview, no keywords, has genres/tagline | 519 | title + "Drama" |
| title only | 235 | "Bix" |

The 235 thinnest documents are 3–30 characters. Their vectors encode essentially
nothing, and cosine similarity does not force an uninformative document to score
low — it will sit at some arbitrary angle to every query.

**Alternatives:**
- Skip thin documents, leave `embedding` NULL — requires choosing a threshold of
  235, 754, or 959, all defensible
- Encode all, plus a `thin_document` boolean column to filter on later
- Delete the 235 rows from the corpus

**Why:** two reasons, and the second is the stronger one.

1. Skipping them *asserts* that thin documents degrade retrieval. That is a
   plausible belief and it is currently untested — there is no Judge layer yet,
   so there is no number behind it. This project's claim is that improvement is
   measured, not asserted; that has to apply to my own instincts too.

2. **Encoding everything is the reversible choice.** With vectors present, the
   thin documents can be excluded at *query* time with a `WHERE` clause, costing
   nothing. Skipping them cannot be undone without a re-encode. Given the two
   options are near-identical in cost, take the one that keeps the door open.

Deleting the rows was rejected outright: they are real films, and trimming the
corpus to look clean would falsify the 45,433 figure that D-003 and D-010 both
depend on.

**Cost / what this gives up:** 235 arbitrary vectors sit in the semantic index
and may surface on queries they have no business matching. Nothing flags them,
so isolating their effect later means re-deriving the tier query in this entry
rather than reading a column.

**How I'd settle it:** once precision@k and NDCG exist, run the held-out query
set twice — once over the full corpus, once with the 235 excluded at query time.
If the thin documents measurably pollute results, this entry gets revisited with
a number attached instead of an instinct.

---

## D-012: No ANN index — exact search over the vectors

**Chose:** no index on `movies.embedding`. Every semantic query sequentially
scans all 45,433 vectors and returns the true nearest neighbours.

**Alternatives:**
- HNSW — a navigable graph, sub-millisecond queries, ~95–99% recall
- IVFFlat — partitions vectors into lists, searches only the nearest few

**Why:** an **ANN** (approximate nearest neighbour) index buys speed by
*sometimes returning something other than the true nearest neighbours*. This
project's entire claim is that a learned reranker measurably improves on a
baseline. A baseline built on approximate retrieval carries an unknown recall
loss baked in, so any later measurement could not separate the reranker's effect
from the index's error. Exact search is cheap at this corpus size, so the speed
an index would buy is currently worth nothing.

**Cost / what this gives up:** query latency grows linearly with the corpus.
Fine at 45,433 rows; not fine at 1M.

**Measured:** median **128 ms** per semantic query over all 45,433 vectors
(min 109, max 141; six queries, warm cache). The lexical arm runs 15–47 ms.

The estimate when this decision was taken was 40–120 ms, so the real cost sits
just above the range that was guessed. The decision stands — 128 ms is fine for
a CLI — but the guess was optimistic and is recorded as such rather than quietly
corrected.

**How I'd settle it:** revisit when a query is slow enough to be annoying. At
that point measure HNSW's actual recall *against these exact results* rather
than trusting a published benchmark — the exact answers are available precisely
because this decision was made first.

---

## D-013: Reciprocal Rank Fusion, K=60, 50 candidates per arm

**Chose:** fuse the lexical and semantic lists with RRF. Each document scores
`Σ 1/(K + rank)` summed over the arms that returned it, with K=60 and each arm
contributing its top 50.

**Alternatives:**
- Weighted sum of normalised scores — `α·lexical + (1−α)·semantic`
- Interleaving — alternate one result from each arm
- Use one arm only and ignore the other

**Why:** `ts_rank` values and cosine similarities are not comparable numbers.
`ts_rank` runs from ~0.99 for a title hit down to ~0.06 for a plot-only match
(D-008); cosine similarity sits in a narrow band and shifts with query length.
A weighted sum requires normalising both onto a common scale, and there is no
principled way to do it — min-max normalisation makes a document's score depend
on whatever else happened to land in the same result list. RRF reads **rank
position only**, so the two scales never have to be reconciled at all.

**Cost / what this gives up:** discarding the scores throws away real
information. A document that won its arm by a mile scores identically to one
that barely won. RRF cannot express confidence.

**Observed instance of that cost — the `Tom Hanks` query.** The lexical arm
alone returns his films correctly: *The Man with One Red Shoe*, *Bachelor
Party*, *From the Earth to the Moon*, *That Thing You Do!*. The semantic arm
returns noise, exactly as D-004 predicts for proper nouns — *Blue Sky*,
*Hank: 5 Years from the Brink*, *The Power and the Glory*.

Fusing them promotes *Tom Sawyer* to rank 3, above genuine Hanks films, because
both arms weakly agree on the token "Tom" (lexical rank 7, semantic rank 30).
Two mediocre ranks outscore one strong one: `1/67 + 1/90 = 0.0260` against
`1/62 = 0.0161`.

So RRF actively **degrades** this query relative to the lexical arm alone. That
is not an implementation bug — it is the cost above, appearing on the very first
real query set. It is also precisely what the Judge layer exists to quantify and
a strong candidate for what the learned reranker should learn to fix.

**K=60 is not tuned.** It is the constant from Cormack, Clarke & Buettcher
(2009), which is where nearly every RRF implementation takes it from. Larger K
flattens the advantage of top ranks; smaller K lets rank 1 dominate. The
50-candidate depth per arm is likewise a round number, not a result.

**How I'd settle it:** K and the candidate depth are exactly the knobs the Judge
layer exists to tune. Once NDCG against a held-out query set works, sweep K over
{10, 30, 60, 100} and depth over {25, 50, 100}. Until then these are documented
defaults, not findings.

---

## D-014: Candidate depth — OPEN, but the measurement is in

**Leading candidate:** raise `CANDIDATE_DEPTH` from 50 to **100**.

**The question:** how many candidates each arm contributes before fusion. D-013
set it to 50 as a round number and said so.

**What was measured** (see `QUERIES.md` for the full analysis): recall@k against
two ground-truth sets derived from columns the retriever never sees as queries —
68 films with `Tom Hanks` in `cast_names`, 33 with `Steven Spielberg` in
`directors`.

| k | `Tom Hanks` lexical recall | `Spielberg` lexical recall |
|---|---|---|
| 50 | 0.69 | 0.91 |
| **100** | **1.00** | **1.00** |
| 200–1000 | 1.00 | 1.00 |

At depth 50, **21 of 68 Tom Hanks films are outside the candidate pool** — a
reranker could never surface them, because it never sees them. At 100 the pool
is complete for both sets, and nothing beyond 100 adds anything.

**Why not deeper than 100:** measured, not assumed. Fused top-10s were compared
at depth 50 against depth 500 across all ten queries in `QUERIES.md`. Six were
identical; the four that changed reordered the same titles without admitting new
ones. `1/(K + rank)` decays fast enough that a rank-500 document contributes 11%
of a rank-1 document — enough to nudge, never enough to upset.

**The cost is close to zero.** The exact scan already compares all 45,433
vectors regardless of `LIMIT` (D-012), so the semantic arm's cost is unchanged;
only the fusion arithmetic grows, and it is a dictionary update per candidate.

**What raising depth does NOT do:** it does not change what the user sees today.
*WALL·E* sits at semantic rank 115 for `lonely robot in space`, and at depth 500
it still does not enter the visible top 10, because a single-arm rank-115
document scores below the cut. Depth widens what a *reranker* can promote from.
It is an investment in the ceiling, not a fix for the present ranking.

**Prediction that was wrong, recorded rather than deleted:** I expected a deeper
pool to worsen the `Tom Hanks` / `Tom Sawyer` regression in D-013, on the theory
that more candidates means more weak two-arm agreements. Measured, the opposite
happened — *Tom Sawyer* held rank 3 at both depths, and *Bachelor Party*, a real
Hanks film, moved up from 5 to 4.

**Deliberately still open:** the number is a design decision and this entry
records the evidence, not the choice. Same pattern D-010 used before the model
was settled.

**What this does not fix:** depth is irrelevant to two of the four failures.
`Speilberg` scores recall 0.00 at every k in both arms — a misspelling is a
different token, and that needs `pg_trgm`. `film about grief` has all eleven
targets outside the top 50 with the best at rank 70 and the worst at 18,057 —
that is the embedding failing to encode theme, and no depth reaches it.

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
