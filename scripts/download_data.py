import shutil
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

import kagglehub

WANTED = [
    "movies_metadata.csv",
    "keywords.csv",
    "credits.csv",
    "ratings_small.csv",
]

cache_path = Path(kagglehub.dataset_download("rounakbanik/the-movies-dataset"))
dest = Path("data")
dest.mkdir(exist_ok=True)

for name in WANTED:
    src = cache_path / name
    if src.exists():
        shutil.copy(src, dest / name)
        print(f"copied {name} ({src.stat().st_size / 1e6:.1f} MB)")
    else:
        print(f"MISSING {name}")
