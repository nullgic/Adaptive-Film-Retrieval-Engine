"""Measure each candidate embedding model against the real corpus, for D-010.

    python scripts/check_model.py                # both candidates, full corpus
    python scripts/check_model.py --limit 2000   # smoke test

Reads only. Nothing is written to the database and no vectors are produced --
this exists to turn two numbers from documentation into two numbers from the
model itself:

  * the embedding dimension, which fixes the vector(N) column width forever
  * the context window, measured with the model's OWN tokenizer rather than
    the WORDPIECE_PER_WORD estimate in config.py

Truncation is silent: a document over the window is cut with no error and no
warning, and the missing half is simply never searchable. The only way to know
it happened is to count first.
"""
import argparse

import numpy as np
from sentence_transformers import SentenceTransformer

from config import WORDPIECE_PER_WORD
from db import connect

# The two 384-dimension candidates from D-010. The 768-dim mpnet models can be
# appended here; nothing else in this script needs to change.
CANDIDATES = [
    "BAAI/bge-small-en-v1.5",
    "sentence-transformers/all-MiniLM-L6-v2",
]

# Tokenizing 45k documents in one call builds one huge list; 1000 at a time
# keeps memory flat and costs nothing in speed.
BATCH = 1000


def fetch_documents(limit):
    """Return (title, search_text) for every non-empty embedding document.

    search_text is the semantic half of the corpus per D-004 -- title, tagline,
    overview, genres and keywords, but deliberately no cast names.
    """
    sql = "SELECT title, search_text FROM movies WHERE search_text <> ''"
    if limit:
        sql += f" LIMIT {limit}"

    with connect() as conn, conn.cursor() as cur:
        cur.execute(sql)
        rows = cur.fetchall()

    titles = [row[0] for row in rows]
    documents = [row[1] for row in rows]
    return titles, documents


def token_lengths(model, documents):
    """True token count per document, including the model's special tokens.

    truncation=False is the entire point. The tokenizer's default is to cut at
    the model's limit, which would cap every result at exactly the window size
    and make the measurement report zero truncation no matter what the corpus
    contains -- the bug would hide itself.

    add_special_tokens=True counts the [CLS] and [SEP] markers the model wraps
    around every input. They occupy real slots in the window, so leaving them
    out would undercount by two and understate truncation.
    """
    lengths = []
    for start in range(0, len(documents), BATCH):
        batch = documents[start:start + BATCH]
        encoded = model.tokenizer(
            batch,
            add_special_tokens=True,
            truncation=False,
            padding=False,
        )
        lengths.extend(len(ids) for ids in encoded["input_ids"])
    return np.array(lengths)


def report(name, model, titles, documents):
    # D-010 names get_sentence_embedding_dimension(); sentence-transformers 5.x
    # renamed it to get_embedding_dimension() and warns on the old name.
    dimension = model.get_embedding_dimension()
    window = model.max_seq_length

    lengths = token_lengths(model, documents)
    over = lengths > window
    longest = int(np.argmax(lengths))

    # Words per document, to check the 1.3 multiplier config.py currently assumes.
    words = np.array([len(doc.split()) for doc in documents])
    observed_ratio = lengths.sum() / words.sum()

    print(f"\n{'=' * 70}\n{name}\n{'=' * 70}")
    print(f"  embedding dimension  {dimension}    <- this is the vector(N) width")
    print(f"  context window       {window} tokens")

    print(f"\n  {len(lengths):,} documents measured with the model's own tokenizer")
    print(f"    max observed   {lengths.max()} tokens")
    print(f"    p99            {int(np.percentile(lengths, 99))}")
    print(f"    p95            {int(np.percentile(lengths, 95))}")
    print(f"    median         {int(np.percentile(lengths, 50))}")
    print(f"    longest doc    {titles[longest]!r}")

    count = int(over.sum())
    share = 100 * count / len(lengths)
    verdict = "FITS" if count == 0 else "TRUNCATION"
    print(f"\n  over {window} tokens: {count:,} of {len(lengths):,} ({share:.2f}%)  <- {verdict}")

    print(f"\n  tokens per word: {observed_ratio:.2f} measured "
          f"vs {WORDPIECE_PER_WORD} assumed in config.py")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, help="measure only the first N documents")
    args = parser.parse_args()

    titles, documents = fetch_documents(args.limit)
    print(f"loaded {len(documents):,} documents from movies.search_text")

    for name in CANDIDATES:
        print(f"\nloading {name} ...")
        model = SentenceTransformer(name)
        report(name, model, titles, documents)

    print(f"\n{'=' * 70}")
    print("Nothing was written. Record the choice as D-010, then set")
    print("EMBEDDING_MODEL and EMBEDDING_DIM in config.py.")


if __name__ == "__main__":
    main()
