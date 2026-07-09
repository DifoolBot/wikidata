"""Central access to repo paths and secrets.

All secrets (API keys, database credentials) live in the repo-root ``.env``
file, which is gitignored and also loaded by VS Code via ``python.envFile``.
Document new keys in ``.env.example``.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).parents[2]
SCHEMAS_DIR = ROOT_DIR / "schemas"

_loaded = False


def load_env() -> None:
    """Load the repo-root .env once; safe to call from every entry point."""
    global _loaded
    if not _loaded:
        load_dotenv(ROOT_DIR / ".env")
        _loaded = True


def get_env(name: str, required: bool = True) -> str | None:
    load_env()
    value = os.getenv(name)
    if required and not value:
        raise KeyError(
            f"Environment variable '{name}' is not set; add it to {ROOT_DIR / '.env'}"
        )
    return value
