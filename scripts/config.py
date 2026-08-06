"""Tunable constants, in one place so they are not scattered through the scripts."""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"

# --- ingestion -------------------------------------------------------------

# Top-N billed cast indexed per movie. `order` is TMDB's billing order, so
# order 0 is the lead. Median cast size is 10, p90 is 23: at 20 we capture the
# entire cast for 85% of the corpus.
MAX_CAST = 20

# Rows per chunk when streaming credits.csv (181 MB of nested dict literals).
CSV_CHUNK_SIZE = 5_000

# --- document length -------------------------------------------------------

# Rough stand-in for a real tokenizer: English averages ~1.3 BERT word-pieces
# per whitespace word. Measured at 1.29 across the corpus - accurate on average,
# but it understated the maximum by 35% (482 estimated vs 653 actual), because
# non-English text shatters into far more pieces per word. Fine for the
# ingestion report; use scripts/check_model.py for anything decisive.
WORDPIECE_PER_WORD = 1.3

# Context windows of the models under consideration, for the ingestion report.
CONTEXT_WINDOWS = {"all-MiniLM-L6-v2": 256, "BGE-small-en-v1.5": 512}

# --- embedding -------------------------------------------------------------

# Settled in D-010. EMBEDDING_DIM was read from the model, not from docs - the
# vector(N) column must match exactly or every insert fails.
EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
EMBEDDING_DIM = 384
