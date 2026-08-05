"""Parse the raw CSVs into the movies table.

    python scripts/ingest.py --limit 100   # smoke test
    python scripts/ingest.py               # full load

Reloads from scratch: the movies table is truncated first, so re-running gives a
clean load rather than primary-key conflicts.
"""
import argparse
import ast

import pandas as pd

from config import CSV_CHUNK_SIZE, DATA_DIR, MAX_CAST, CONTEXT_WINDOWS, WORDPIECE_PER_WORD
from db import connect

COLUMNS = [
    "movie_id", "title", "original_title", "overview", "tagline", "release_date",
    "runtime", "original_language", "vote_average", "vote_count", "popularity",
    "genres", "keywords", "cast_names", "directors", "search_text", "facets_text",
]


# --------------------------------------------------------------- small helpers

def parse_list(raw):
    """The source stores JSON as Python dict literals with single quotes, which
    json.loads rejects. literal_eval parses literals only - it cannot execute code."""
    if not isinstance(raw, str) or not raw.strip():
        return []
    try:
        value = ast.literal_eval(raw)
    except (ValueError, SyntaxError):
        return []
    return value if isinstance(value, list) else []


def names_of(items):
    return [d["name"] for d in items if isinstance(d, dict) and d.get("name")]


def as_int(v):
    return None if pd.isna(v) else int(v)


def as_float(v):
    return None if pd.isna(v) else float(v)


def as_text(v):
    if v is None or pd.isna(v):
        return None
    return str(v).strip() or None


# ------------------------------------------------------------------ extraction

def clean_metadata(limit):
    """Apply the cleaning rules, loudest first, reporting what each one removed."""
    md = pd.read_csv(DATA_DIR / "movies_metadata.csv", low_memory=False)
    print(f"read movies_metadata.csv: {len(md):,} rows")

    # 1. non-numeric id == the column-shifted rows. Same rows also hold the only
    #    unparseable release_dates, so this one filter clears three defects.
    md["movie_id"] = pd.to_numeric(md["id"], errors="coerce")
    bad = md["movie_id"].isna()
    if bad.any():
        print(f"  dropped {bad.sum()} column-shifted rows (non-numeric id)")
    md = md[~bad].copy()
    md["movie_id"] = md["movie_id"].astype(int)

    # 2. duplicates: keep the highest popularity. popularity is the only field
    #    that differs between duplicate scrapes, so the higher value is the more
    #    recent observation. vote_count would tie in 27 of 29 groups.
    md["_pop"] = pd.to_numeric(md["popularity"], errors="coerce").fillna(-1.0)
    before = len(md)
    md = (md.sort_values("_pop", ascending=False)
            .drop_duplicates(subset="movie_id", keep="first")
            .sort_values("movie_id"))
    if before != len(md):
        print(f"  dropped {before - len(md)} duplicate ids (kept highest popularity)")

    # 3. types. errors='coerce' turns junk into NULL instead of killing the row.
    md["release_date"] = pd.to_datetime(
        md["release_date"], errors="coerce", format="%Y-%m-%d").dt.date
    for col in ("runtime", "vote_count"):
        md[col] = pd.to_numeric(md[col], errors="coerce")
    for col in ("vote_average", "popularity"):
        md[col] = pd.to_numeric(md[col], errors="coerce")

    # 4. title, falling back to original_title.
    title = md["title"].fillna("").astype(str).str.strip()
    original = md["original_title"].fillna("").astype(str).str.strip()
    md["title"] = title.where(title != "", original)
    untitled = md["title"] == ""
    if untitled.any():
        print(f"  dropped {untitled.sum()} rows with no title and no original_title")
    md = md[~untitled]

    if limit:
        md = md.head(limit)
        print(f"  --limit {limit}: keeping {len(md):,} rows")

    print(f"  -> {len(md):,} movies")
    return md


def stream_side_file(filename, wanted, column, extract):
    """Stream a big CSV in chunks, parsing only rows we actually need.

    credits.csv is 181 MB of nested dicts; parsing all of it at once costs GBs.
    Chunking plus the `wanted` check keeps peak memory flat.
    """
    out = {}
    for chunk in pd.read_csv(DATA_DIR / filename, chunksize=CSV_CHUNK_SIZE):
        ids = pd.to_numeric(chunk["id"], errors="coerce")
        for movie_id, *raw in zip(ids, *(chunk[c] for c in column)):
            if pd.isna(movie_id):
                continue
            movie_id = int(movie_id)
            if movie_id not in wanted or movie_id in out:
                continue
            out[movie_id] = extract(*raw)
    print(f"read {filename}: matched {len(out):,} of {len(wanted):,} movies")
    return out


def top_billed_and_directors(raw_cast, raw_crew):
    cast = parse_list(raw_cast)
    # order is TMDB billing order; entries missing it sort to the back.
    cast.sort(key=lambda d: d.get("order", 10**6) if isinstance(d, dict) else 10**6)
    directors = [d for d in parse_list(raw_crew)
                 if isinstance(d, dict) and d.get("job") == "Director"]
    return names_of(cast[:MAX_CAST]), names_of(directors)


# -------------------------------------------------------------------- documents

def build_documents(row, genres, keywords, cast_names, directors):
    """search_text feeds the embedding model; facets_text feeds the lexical index.

    search_text is ordered by descending value, so if a model's context window
    truncates it, the cheapest material is what gets dropped.
    """
    search_parts = [
        row["title"],
        as_text(row["overview"]) or "",
        " ".join(keywords),
        " ".join(genres),
        as_text(row["tagline"]) or "",
    ]
    search_text = "\n".join(p for p in search_parts if p)
    facets_text = " ".join(keywords + cast_names + directors)
    return search_text, facets_text


def report_document_lengths(search_texts):
    """Estimated word-pieces per document. A real tokenizer replaces this on
    embedding day; this only answers 'are we anywhere near the window?'."""
    words = pd.Series([len(t.split()) for t in search_texts])
    pieces = words * WORDPIECE_PER_WORD

    print(f"\nsearch_text length (estimated word-pieces, {WORDPIECE_PER_WORD}x words):")
    for label, value in [("min", pieces.min()), ("median", pieces.median()),
                         ("p90", pieces.quantile(.90)), ("p95", pieces.quantile(.95)),
                         ("p99", pieces.quantile(.99)), ("max", pieces.max())]:
        print(f"  {label:<7} {value:>7.0f}")
    for model, window in CONTEXT_WINDOWS.items():
        over = (pieces > window).sum()
        print(f"  over {window:>3} ({model}): {over:,} docs ({100 * over / len(pieces):.1f}%)")


# ------------------------------------------------------------------------- load

def load(rows):
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM movies")
        existing = cur.fetchone()[0]
        print(f"\ntruncating movies ({existing:,} existing rows)")
        cur.execute("TRUNCATE movies")

        with cur.copy(f"COPY movies ({', '.join(COLUMNS)}) FROM STDIN") as copy:
            for row in rows:
                copy.write_row(row)

        cur.execute("SELECT count(*) FROM movies")
        loaded = cur.fetchone()[0]
        conn.commit()
    return loaded


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, help="load only the first N movies")
    args = parser.parse_args()

    md = clean_metadata(args.limit)
    wanted = set(md["movie_id"])

    credits = stream_side_file("credits.csv", wanted, ["cast", "crew"],
                               top_billed_and_directors)
    keywords = stream_side_file("keywords.csv", wanted, ["keywords"],
                                lambda raw: names_of(parse_list(raw)))

    rows, search_texts = [], []
    for row in md.to_dict("records"):
        movie_id = row["movie_id"]
        genres = names_of(parse_list(row["genres"]))
        kws = keywords.get(movie_id, [])
        cast_names, directors = credits.get(movie_id, ([], []))

        search_text, facets_text = build_documents(row, genres, kws, cast_names, directors)
        search_texts.append(search_text)

        rows.append((
            movie_id,
            row["title"],
            as_text(row["original_title"]),
            as_text(row["overview"]),
            as_text(row["tagline"]),
            None if pd.isna(row["release_date"]) else row["release_date"],
            as_int(row["runtime"]),
            as_text(row["original_language"]),
            as_float(row["vote_average"]),
            as_int(row["vote_count"]),
            as_float(row["popularity"]),
            genres, kws, cast_names, directors,
            search_text, facets_text,
        ))

    report_document_lengths(search_texts)
    loaded = load(rows)
    print(f"loaded {loaded:,} movies")


if __name__ == "__main__":
    main()
