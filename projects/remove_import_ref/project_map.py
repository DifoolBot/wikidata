"""Resolve a P143 project QID (e.g. Q8449) to a sitelink dbcode (e.g. eswiki).

Strategy: small hardcoded map for the common editions; otherwise read P1800
('Wikimedia database name') off the project item and cache it to a text file.
"""

from __future__ import annotations

import os
from typing import Callable, Dict, Optional

# Verified editions only -- avoids an API round-trip for frequent cases.
# Everything else resolves authoritatively via P1800 (and is then cached), so
# only add an entry here once it's confirmed against P1800. Do NOT guess: an
# earlier guessed map had Q199693 (actually cawiki) and Q177220 mislabelled.
KNOWN: Dict[str, str] = {
    "Q328": "enwiki",
    "Q8449": "eswiki",
    "Q199693": "cawiki",
    "Q206855": "ruwiki",
    "Q1551807": "plwiki",
    "Q48183": "dewiki",
    "Q8447": "frwiki",
    "Q11920": "itwiki",
    "Q10000": "nlwiki",
}


class ProjectMap:
    def __init__(self, cache_file: str, resolver: Callable[[str], Optional[str]]):
        """`resolver(qid)` reads P1800 from the project item (inject the API)."""
        self.cache_file = cache_file
        self.resolver = resolver
        self.cache: Dict[str, str] = dict(KNOWN)
        self._load_cache()

    def _load_cache(self) -> None:
        if not os.path.exists(self.cache_file):
            return
        with open(self.cache_file, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or "\t" not in line:
                    continue
                qid, dbcode = line.split("\t", 1)
                self.cache[qid] = dbcode

    def _append_cache(self, qid: str, dbcode: str) -> None:
        os.makedirs(os.path.dirname(self.cache_file) or ".", exist_ok=True)
        with open(self.cache_file, "a", encoding="utf-8") as fh:
            fh.write(f"{qid}\t{dbcode}\n")

    def dbcode(self, project_qid: str) -> Optional[str]:
        if project_qid in self.cache:
            return self.cache[project_qid]
        dbcode = self.resolver(project_qid)
        if dbcode:
            self.cache[project_qid] = dbcode
            self._append_cache(project_qid, dbcode)
        return dbcode
