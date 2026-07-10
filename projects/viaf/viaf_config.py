from dataclasses import dataclass, field
from pathlib import Path

import yaml

CONFIG_FILE = Path(__file__).parent / "viaf_config.yaml"

DEFAULT_MAX_DUPLICATES = 1000
DEFAULT_COOLDOWN_DAYS = 7
DEFAULT_NOT_FOUND_CACHE_DAYS = 365


@dataclass
class ViafConfig:
    # authority source PIDs whose processing order is fixed, most important first
    order: list[str] = field(default_factory=list)
    # authority source PIDs to skip entirely
    ignore: list[str] = field(default_factory=list)
    # publish + clear the duplicates report once the DUPLICATES table reaches this many
    # rows; None disables the cap
    max_duplicates: int | None = DEFAULT_MAX_DUPLICATES
    # days to idle after a full pass through all sources before starting over
    cooldown_days: int = DEFAULT_COOLDOWN_DAYS
    # skip items VIAF returned 'not_found' for within this many days; None disables
    not_found_cache_days: int | None = DEFAULT_NOT_FOUND_CACHE_DAYS


def load_config(path: Path = CONFIG_FILE) -> ViafConfig:
    if not path.exists():
        return ViafConfig()

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return ViafConfig(
        order=list(data.get("order") or []),
        ignore=list(data.get("ignore") or []),
        max_duplicates=data.get("max_duplicates", DEFAULT_MAX_DUPLICATES),
        cooldown_days=int(data.get("cooldown_days", DEFAULT_COOLDOWN_DAYS)),
        not_found_cache_days=data.get(
            "not_found_cache_days", DEFAULT_NOT_FOUND_CACHE_DAYS
        ),
    )


def order_pids(all_pids: list[str], desired_order: list[str]) -> list[str]:
    """Return all_pids reordered so the ones in desired_order come first (in
    that order), followed by the remaining pids in their original order.

    PIDs in desired_order that don't exist in all_pids are ignored.
    """
    known = set(all_pids)
    ordered = [pid for pid in desired_order if pid in known]
    seen = set(ordered)
    ordered.extend(pid for pid in all_pids if pid not in seen)
    return ordered
