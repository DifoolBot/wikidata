from pathlib import Path

# Runtime data files (db config, progress, qlever work files, wiki output) live
# here, out of the way of the source. The directory is gitignored.
DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)
