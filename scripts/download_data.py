"""Download the source CSVs from Kaggle into data/.

    python scripts/download_data.py

Run once. kagglehub caches the dataset elsewhere on disk, so re-running copies
from that cache rather than downloading again.
"""
import shutil
from pathlib import Path

from dotenv import load_dotenv

from config import DATA_DIR, PROJECT_ROOT

# Point at the project root explicitly rather than letting load_dotenv search
# upward from the working directory, so this works when run from anywhere -
# the same reason db.py does it.
load_dotenv(PROJECT_ROOT / ".env")

# Imported after load_dotenv on purpose: kagglehub reads credentials from the
# environment at import time, so importing it first would find nothing.
import kagglehub  # noqa: E402

WANTED = [
    "movies_metadata.csv",
    "keywords.csv",
    "credits.csv",
    "ratings_small.csv",
]

cache_path = Path(kagglehub.dataset_download("rounakbanik/the-movies-dataset"))
DATA_DIR.mkdir(exist_ok=True)

for name in WANTED:
    src = cache_path / name
    if src.exists():
        shutil.copy(src, DATA_DIR / name)
        print(f"copied {name} ({src.stat().st_size / 1e6:.1f} MB)")
    else:
        print(f"MISSING {name}")
