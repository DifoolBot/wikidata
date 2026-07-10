from pathlib import Path

# Runtime data files (db config, lookup caches, ignore lists) live here, out
# of the way of the source. The directory is gitignored.
DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)
