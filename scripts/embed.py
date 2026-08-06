"""Encode search_text into vectors and write them to movies.embedding.

    python scripts/embed.py --limit 200   # smoke test
    python scripts/embed.py               # full run, ~38 min on CPU

Resumable by construction: only rows where embedding IS NULL are selected, and
each chunk is committed before the next is fetched. A crash costs one chunk
rather than the whole run, and re-running after a completed run does nothing.
"""
import argparse
import time

from pgvector.psycopg import register_vector
from sentence_transformers import SentenceTransformer

from config import EMBEDDING_DIM, EMBEDDING_MODEL
from db import connect

# Rows per fetch/encode/write round trip. Large enough that
# sentence-transformers can sort by length and fill its batches without wasting
# padding; small enough that a crash loses ~2 minutes rather than 38.
CHUNK = 2048


def pending_count(cur):
    cur.execute("SELECT count(*) FROM movies WHERE embedding IS NULL")
    return cur.fetchone()[0]


def fetch_chunk(cur, size):
    """The next unencoded rows. No OFFSET is needed: the previous chunk is
    already committed, so those rows no longer match embedding IS NULL."""
    cur.execute(
        "SELECT movie_id, search_text FROM movies WHERE embedding IS NULL "
        "ORDER BY movie_id LIMIT %s",
        (size,),
    )
    return cur.fetchall()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, help="stop after N documents")
    args = parser.parse_args()

    model = SentenceTransformer(EMBEDDING_MODEL)

    # Fail on row 0 rather than row 45,433. The vector(N) column width is fixed
    # at declaration, so a model/schema mismatch rejects every single insert.
    actual = model.get_embedding_dimension()
    if actual != EMBEDDING_DIM:
        raise SystemExit(
            f"{EMBEDDING_MODEL} returns {actual} dims, schema expects {EMBEDDING_DIM}"
        )

    done = 0
    started = time.perf_counter()

    with connect() as conn:
        # Teaches psycopg to send numpy arrays as the pgvector 'vector' type,
        # instead of us hand-formatting '[0.1,0.2,...]' strings.
        register_vector(conn)

        with conn.cursor() as cur:
            remaining = pending_count(cur)
            target = min(remaining, args.limit) if args.limit else remaining
            print(f"{remaining:,} rows unencoded; encoding {target:,}")

            while done < target:
                rows = fetch_chunk(cur, min(CHUNK, target - done))
                if not rows:
                    break

                movie_ids = [row[0] for row in rows]
                texts = [row[1] for row in rows]

                # No instruction prefix: BGE is asymmetric, and the prefix
                # belongs on queries only. normalize_embeddings gives unit
                # vectors, which is what pgvector's cosine operator <=> expects.
                vectors = model.encode(
                    texts,
                    batch_size=64,
                    normalize_embeddings=True,
                    show_progress_bar=False,
                )

                cur.executemany(
                    "UPDATE movies SET embedding = %s WHERE movie_id = %s",
                    list(zip(vectors, movie_ids)),
                )
                conn.commit()

                done += len(rows)
                rate = done / (time.perf_counter() - started)
                left = (target - done) / rate
                print(f"  {done:,}/{target:,}   {rate:.1f} docs/s   ~{left / 60:.1f} min left",
                      flush=True)

    print(f"\nencoded {done:,} documents in {(time.perf_counter() - started) / 60:.1f} min")


if __name__ == "__main__":
    main()
