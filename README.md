# Adaptive Film Retrieval Engine

A search system over ~45,000 films that logs how people interact with its
results, turns that behaviour into relevance labels, and trains a reranker to
reorder its own output. The improvement is then measured against the original
baseline rather than asserted.

**It is not a recommender.** Nothing here suggests films you might like. It
answers queries, watches what happens next, and tries to get better at answering
them. The point of the project is the measurement, not the search.

<!-- image: screenshot of scripts/search.py output for a sample query -->

---

## Status

Five layers, built in order. Two exist.

| layer | what it does | state |
|---|---|---|
| **Index** | every film stored twice — a weighted Postgres full-text index, and a pgvector index of embeddings | done |
| **Retriever** | a query hits both indexes; the two ranked lists are fused with Reciprocal Rank Fusion | done |
| **Observer** | logs every search and what follows it — clicks, position, dwell time, reformulation, abandonment | not started |
| **Judge** | precision@k, recall@k and NDCG against a held-out query set; produces the baseline | not started |
| **Learner** | converts behavioural logs into relevance labels, trains a LightGBM reranker | not started |

Users will be simulated — personas with hidden preference vectors and a click
model. Because the preferences are known in advance, ground truth for evaluation
is known too, which is the only reason any of the measurement works.

Right now you can type a query and get a ranked list. There is no web UI, no
logging, and no metrics yet.

---

## What's actually been measured

Numbers from the current corpus, not from documentation:

| | |
|---|---|
| documents indexed | 45,433 |
| embedding model | `BAAI/bge-small-en-v1.5` — 384 dimensions, 512-token window |
| documents truncated at 512 tokens | 4 (0.01%) |
| longest document | 653 tokens |
| encode time, full corpus | 31.2 min on CPU (24.2 docs/sec) |
| semantic query, exact scan | 128 ms median over all 45,433 vectors |
| lexical query | 15–47 ms |

There is deliberately **no approximate-nearest-neighbour index** on the vectors.
An ANN index trades recall for speed, and a baseline carrying an unknown recall
loss would make any later improvement impossible to attribute. At this corpus
size exact search is affordable, so it stays exact. See D-012.

---

## Try it

Prerequisites: Docker, Python 3.11+, and a Kaggle account for the dataset.

```bash
cp .env.example .env          # then fill in the values
docker compose up -d          # Postgres 16 + pgvector

python -m venv venv
venv/Scripts/activate         # Windows; use source venv/bin/activate elsewhere
pip install -r requirements.txt
```

Then the pipeline, in order:

```bash
python scripts/download_data.py   # ~250 MB of CSVs from Kaggle
python scripts/apply_schema.py    # create the table and indexes
python scripts/ingest.py          # parse CSVs into Postgres
python scripts/embed.py           # encode 45,433 documents -- takes ~30 min
python scripts/search.py "space opera with rebels"
```

`embed.py` is the slow one. It is resumable — it only encodes rows where
`embedding IS NULL` and commits every 2,048, so if it dies you just run it again
and it picks up where it stopped.

`--explain` shows both arms separately before they are fused, which is usually
the interesting part:

```bash
python scripts/search.py "Tom Hanks" --explain
```

<!-- image: --explain output showing the two arms diverging -->

---

## How it works

Every film is turned into **two different documents**, on purpose.

`search_text` feeds the embedding model: title, overview, keywords, genres,
tagline. `facets_text` feeds the full-text index and additionally carries cast
and director names.

Names are in one and not the other because the two methods are good at different
things. An inverted index matches "Tom Hanks" exactly and cheaply. A dense
embedding model handles rare proper nouns badly — a name is an arbitrary token
with little semantic structure — so putting cast into the vector mostly adds
noise. Keywords go in both, because they are concepts rather than names, and
because 959 films have no overview at all and would otherwise embed almost
nothing.

At query time both indexes are searched independently and the two ranked lists
are combined with **Reciprocal Rank Fusion**: each document scores
`1 / (60 + rank)` summed over the arms that returned it. Only rank position is
used. The two arms produce scores on scales with no common unit — `ts_rank`
runs about 0.99 down to 0.06, cosine similarity sits in a narrow band — and
there is no principled way to normalise one onto the other, so RRF refuses to
try.

---

## How improvement will be reported

Not as one number.

The held-out query set is deliberately **mixed** — concrete queries (proper
nouns, plot elements) alongside abstract ones (themes, moods) — and the
reranker's lift is reported **split by category**: concrete +X%, abstract +Y%.
Never pooled into a single headline figure.

Pooling would make the result depend on the query mix rather than on the
reranker. Shift the proportion of abstract queries and the "improvement" moves
while the model stays identical, which makes the number unreproducible by anyone
who samples queries differently. It would also hide the more interesting result.

Because the ceiling has already been measured per query type, the **gap between
the two categories is the finding**, and it is attributable: abstract queries
lag because their correct answers were never in the candidate pool for the
reranker to reorder. That is a retrieval failure, not a ranking one. A single
averaged number would state that the reranker underperformed and leave the
reason invisible. See D-015.

---

## Honest limitations

Ten queries are recorded in [QUERIES.md](QUERIES.md), including the four that
fail. Briefly:

- **Fusion sometimes makes things worse.** For `Tom Hanks`, the lexical arm alone
  returns his films correctly. Fused, *Tom Sawyer* — which he is not in — lands
  at rank 3, because both arms weakly agree on the token "Tom" and RRF rewards
  agreement over strength.
- **Misspellings fail completely.** Postgres full-text search does stemming, not
  fuzzy matching, so `Speilberg` and `Spielberg` are unrelated tokens. Would need
  `pg_trgm`.
- **Non-English queries cluster by language, not meaning.** A Russian query
  returns Russian films generally rather than the relevant one. Expected from an
  English-only model, but worth knowing.
- **The vector arm cannot return nothing.** Every query has a nearest neighbour,
  so a meaningless query still gets five confident results.
- **Abstract queries fail — and the cause is the embedding, not the corpus.**
  *A Monster Calls* ranks 18,057 of 45,433 for `film about grief`. It carries the
  keyword `death of mother`, that string sits verbatim in the document the
  embedder read, and the film still ranks **6,273rd for that exact query**. Its
  similarity holds inside a 0.07 band for every thematic phrasing but reaches
  0.746 for a plot-literal one. The thematic metadata is present and reached the
  vector; mean pooling dilutes it. See D-016.

None of these are fixed yet, and fixing them before the Judge layer exists would
mean claiming an improvement with nothing to measure it against.

That last one is the clearest case. The keyword-vector fix — encode `keywords`
into their own column and fuse a third arm — is the best-evidenced idea in the
project right now, which is exactly why it is scheduled for week 5 rather than
built today. Doing it now would make week 4 report "abstract queries improved"
with no way to separate the new arm's contribution from the reranker's. Deferred
with a stated reason and a date, not left undone.

---

## Decisions

[DECISIONS.md](DECISIONS.md) records every architectural choice — what was
picked, what the alternatives were, why, and for the arbitrary knobs, what
evidence would settle them. Written at decision time, and corrected in place
when a measurement later proved a guess wrong.

Worth reading if you want to know why documents are stored twice, why genres are
a `text[]` instead of a join table, or why the token-length estimate that chose
the embedding model turned out to be wrong in the tail.

---

## Stack

Python 3.11, Postgres 16 with pgvector, psycopg 3, sentence-transformers,
pandas. LightGBM and FastAPI arrive with the Learner and the API layer.
