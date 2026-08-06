-- Runs after 01-extensions.sql on first boot of an empty data volume.
-- Also applied on demand by scripts/apply_schema.py, so it must be idempotent.

CREATE TABLE IF NOT EXISTS movies (
    movie_id          integer PRIMARY KEY,
    title             text NOT NULL,
    original_title    text,
    overview          text,
    tagline           text,
    release_date      date,
    runtime           integer,
    original_language text,
    vote_average      real,
    vote_count        integer,
    popularity        real,

    -- Typed facets. These are for filtering: genres @> ARRAY['Comedy'].
    genres            text[] NOT NULL DEFAULT '{}',
    keywords          text[] NOT NULL DEFAULT '{}',
    cast_names        text[] NOT NULL DEFAULT '{}',
    directors         text[] NOT NULL DEFAULT '{}',

    -- Two derived documents, deliberately different.
    -- search_text is what the embedding model will read (semantic half).
    -- facets_text feeds the lexical index only: names are what an inverted
    -- index is good at and what a fixed-width vector is bad at.
    search_text       text NOT NULL DEFAULT '',
    facets_text       text NOT NULL DEFAULT '',

    -- Recomputed by Postgres on every write, so it can never drift from the row.
    -- The 'english' config is written out as a literal on purpose: the
    -- one-argument to_tsvector() reads a session setting, which makes it
    -- STABLE rather than IMMUTABLE, and a generated column requires IMMUTABLE.
    -- Weights: title beats plot beats cast/keywords.
    search_tsv tsvector GENERATED ALWAYS AS (
        setweight(to_tsvector('english', coalesce(title, '')), 'A') ||
        setweight(to_tsvector('english',
            coalesce(tagline, '') || ' ' || coalesce(overview, '')), 'B') ||
        setweight(to_tsvector('english', coalesce(facets_text, '')), 'C')
    ) STORED,

    ingested_at       timestamptz NOT NULL DEFAULT now()
);

-- The semantic half of the index. 384 is fixed by D-010 (BAAI/bge-small-en-v1.5)
-- and confirmed from the model itself, not from documentation -- pgvector fixes
-- the width at declaration, and a mismatch fails every insert.
--
-- ALTER rather than a column in CREATE TABLE above: CREATE TABLE IF NOT EXISTS
-- skips entirely when the table exists, so it would never reach an existing
-- volume. No ANN index yet -- the column is NULL until embeddings are written.
ALTER TABLE movies ADD COLUMN IF NOT EXISTS embedding vector(384);

-- GIN is the inverted-index access method: it maps each lexeme to the rows
-- containing it, which is the whole point of full-text search.
CREATE INDEX IF NOT EXISTS movies_search_tsv_idx ON movies USING GIN (search_tsv);
CREATE INDEX IF NOT EXISTS movies_genres_idx     ON movies USING GIN (genres);
