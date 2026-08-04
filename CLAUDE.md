# Project: Adaptive Search with Implicit Feedback

## What this is

A search system over a movie corpus that learns from user behavior and
measurably improves its own ranking over time. It is NOT a recommender.
The point of the project is the measurement, not the search.

Five layers:
1. **Index** — documents stored twice: a Postgres full-text index (lexical)
   and a pgvector index of embeddings (semantic).
2. **Retriever** — query hits both indexes; results fused with Reciprocal
   Rank Fusion into one ranked list.
3. **Observer** — logs every search and every subsequent interaction
   (clicks, position, dwell time, reformulation, abandonment).
4. **Judge** — evaluation harness computing precision@k, recall@k, NDCG
   against a held-out query set. Produces the baseline everything is
   measured against.
5. **Learner** — converts behavioral logs into relevance labels, trains a
   reranker (LightGBM) that reorders retriever output. Improvement is
   measured against the baseline, not asserted.

Users are simulated: personas with hidden preference vectors and a click
model. Because the preferences are known, ground truth for evaluation is
known.

## Stack

- Python 3.11+, virtualenv in `venv/`
- Postgres 16 + pgvector, via Docker Compose
- psycopg (v3), pandas
- sentence-transformers for embeddings
- LightGBM for the reranker
- FastAPI for the API layer (later)

## Layout

- `data/` — raw datasets (gitignored, never commit)
- `.env` — secrets (gitignored). `.env.example` documents the variables.

## Current status

Week 1 (Aug 4–10). Goal: query in, ranked list out. No web UI, no
learning loop, no metrics yet. Those come in weeks 2 and 3.

## How to work with me

I'm a student learning this — I have not taken data structures yet and
I'm new to building real projects. The code existing is worth nothing to
me if I can't explain it in an interview.

- Explain what you're going to do before writing it, and why you chose
  that approach over alternatives.
- Prefer plan mode for anything touching more than one file.
- Don't write code I didn't ask for. Don't scaffold ahead of where I am.
- Small commits, one logical change each.
- If I ask for something that's a bad idea, say so instead of building it.
- When you use a term I might not know, define it inline once.

## Constraints

- Never commit `.env`, `data/`, or model files.
- Keep the corpus subset small during week 1 — fast iteration beats scale.