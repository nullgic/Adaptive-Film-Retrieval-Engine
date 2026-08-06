"""Query the corpus. Two retrieval arms, fused into one ranked list.

    python scripts/search.py "space opera with rebels"
    python scripts/search.py "Tom Hanks" --k 10 --explain

The lexical arm ranks by ts_rank over the weighted tsvector (D-008). The
semantic arm ranks by cosine distance over the embedding column, exact rather
than approximate (D-012). Neither arm sees the other; they are combined by
Reciprocal Rank Fusion on rank position alone (D-013).
"""
import argparse
import time
from typing import NamedTuple

from pgvector.psycopg import register_vector
from sentence_transformers import SentenceTransformer

from config import CANDIDATE_DEPTH, EMBEDDING_MODEL, QUERY_PREFIX, RRF_K
from db import connect

# websearch_to_tsquery rather than plainto_tsquery: it accepts quoted phrases
# and OR, and it never raises on stray user punctuation. The A/B/C weights are
# already baked into the stored search_tsv column, so nothing is re-weighted here.
LEXICAL_SQL = """
SELECT movie_id, title, release_date, ts_rank(search_tsv, q) AS score
FROM movies, websearch_to_tsquery('english', %s) AS q
WHERE search_tsv @@ q
ORDER BY score DESC, movie_id
LIMIT %s
"""

# <=> is pgvector's cosine distance, so 1 - distance is cosine similarity.
# Ordering by the distance ascending is the same as similarity descending, and
# it is the form an index would use if one were ever added.
SEMANTIC_SQL = """
SELECT movie_id, title, release_date, 1 - (embedding <=> %s) AS score
FROM movies
WHERE embedding IS NOT NULL
ORDER BY embedding <=> %s
LIMIT %s
"""


def run_arm(cur, sql, params):
    """Execute one arm, returning [(movie_id, title, year, score)] in rank order."""
    cur.execute(sql, params)
    return [
        (movie_id, title, date.year if date else None, float(score))
        for movie_id, title, date, score in cur.fetchall()
    ]


def rrf(arms):
    """Reciprocal Rank Fusion.

    arms: {arm_name: [(movie_id, title, year, score)]}, each already in rank order.

    A document's fused score is the sum of 1 / (RRF_K + rank) over every arm
    that returned it, with rank counted from 1. Only the position is used - the
    arms' own scores are never compared, because ts_rank and cosine similarity
    live on scales with no common unit (D-013).

    A document found by both arms accumulates two terms and so outranks a
    document found by one, which is the whole reason to fuse rather than pick.
    """
    fused = {}
    for arm_name, results in arms.items():
        for position, (movie_id, title, year, _score) in enumerate(results, start=1):
            entry = fused.setdefault(
                movie_id, {"title": title, "year": year, "score": 0.0, "ranks": {}}
            )
            entry["score"] += 1 / (RRF_K + position)
            entry["ranks"][arm_name] = position

    return sorted(fused.values(), key=lambda entry: -entry["score"])


class Results(NamedTuple):
    """One search, with both arms kept alongside the fused list.

    A NamedTuple is a tuple whose positions have names, so callers read
    `results.fused` instead of `results[1]`. The arms are returned unfused as
    well because the interesting question is usually not what the ranking is,
    but which arm produced it.
    """
    query: str
    fused: list
    lexical: list
    semantic: list
    lexical_ms: float
    semantic_ms: float


def search(query, conn, model, k=10, depth=CANDIDATE_DEPTH):
    """Run both arms and fuse them. Returns Results.

    `conn` and `model` are passed in rather than built here, because both are
    expensive and reusable: loading the model costs seconds, and a caller
    running a query set wants one model and one connection for all of them.

    The connection must already have pgvector's register_vector applied, or
    passing the query vector as a parameter fails. open_connection() below
    does that.
    """
    # The instruction prefix goes on the query and never on the documents.
    # embed.py deliberately does not apply it - see QUERY_PREFIX in config.py.
    query_vector = model.encode(QUERY_PREFIX + query, normalize_embeddings=True)

    with conn.cursor() as cur:
        started = time.perf_counter()
        lexical = run_arm(cur, LEXICAL_SQL, (query, depth))
        lexical_ms = (time.perf_counter() - started) * 1000

        started = time.perf_counter()
        semantic = run_arm(cur, SEMANTIC_SQL, (query_vector, query_vector, depth))
        semantic_ms = (time.perf_counter() - started) * 1000

    return Results(
        query=query,
        fused=rrf({"lexical": lexical, "semantic": semantic})[:k],
        lexical=lexical,
        semantic=semantic,
        lexical_ms=lexical_ms,
        semantic_ms=semantic_ms,
    )


def open_connection():
    """connect() plus the pgvector type adapter, which search() requires."""
    conn = connect()
    register_vector(conn)
    return conn


def show_arm(label, results, limit):
    print(f"\n{label} - {len(results)} candidates")
    if not results:
        print("  (nothing)")
    for position, (_id, title, year, score) in enumerate(results[:limit], start=1):
        print(f"  {position:>2}. {score:.4f}  {title} ({year or '----'})")


def show_fused(results, limit):
    print(f"\n{'':<4}{'rrf':>8}  {'lex':>4} {'sem':>4}  title")
    for position, entry in enumerate(results[:limit], start=1):
        lex = entry["ranks"].get("lexical", "-")
        sem = entry["ranks"].get("semantic", "-")
        year = entry["year"] or "----"
        print(f"{position:>2}. {entry['score']:>8.5f}  {lex:>4} {sem:>4}  "
              f"{entry['title']} ({year})")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query")
    parser.add_argument("--k", type=int, default=10, help="results to show")
    parser.add_argument("--depth", type=int, default=CANDIDATE_DEPTH,
                        help="candidates taken from each arm before fusion")
    parser.add_argument("--explain", action="store_true",
                        help="also print each arm's list before fusion")
    args = parser.parse_args()

    model = SentenceTransformer(EMBEDDING_MODEL)

    with open_connection() as conn:
        results = search(args.query, conn, model, k=args.k, depth=args.depth)

    if args.explain:
        show_arm("lexical (ts_rank)", results.lexical, args.k)
        show_arm("semantic (cosine)", results.semantic, args.k)

    print(f"\nquery: {results.query!r}")
    show_fused(results.fused, args.k)
    print(f"\nlexical {results.lexical_ms:.0f}ms   "
          f"semantic {results.semantic_ms:.0f}ms (exact scan, no index - D-012)")


if __name__ == "__main__":
    main()
