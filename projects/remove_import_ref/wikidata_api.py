"""Thin read-only Wikidata API client built on pywikibot's low-level
``api.Request``.

We use the *low-level* request (not ItemPage) deliberately: the project needs
the entity JSON at a specific old revision, filtered to one user's edits --
which the high-level objects don't expose. Routing through pywikibot means we
inherit its maxlag handling, retries, throttling and User-Agent, and share a
single Site/session with the edit path (remover.py). No hand-rolled rate
limiting, no second HTTP stack.

Methods return plain dicts, so the matching logic (reference_checker) stays
unit-testable against fixtures without any network.
"""

from __future__ import annotations

import json
from typing import Dict, List, Optional

import pywikibot
from pywikibot.data import api
from pywikibot.site import BaseSite


class WikidataAPI:
    def __init__(self, site: Optional[BaseSite] = None):
        self.site = site or pywikibot.Site("wikidata", "wikidata")

    def _query(self, **params) -> Dict:
        """One API call through pywikibot (maxlag/retry/throttle/UA handled)."""
        params.setdefault("formatversion", "2")
        req = api.Request(site=self.site, parameters=params)
        return req.submit()

    def user_revisions(self, qid: str, user: str) -> List[Dict]:
        """All revisions of `qid` made by `user`, newest first.

        The per-page rvuser filter means we never touch the user's global
        contributions -- cost scales with the item list, not their edit count.
        """
        out: List[Dict] = []
        cont: Dict = {}
        while True:
            data = self._query(
                action="query",
                prop="revisions",
                titles=qid,
                rvuser=user,
                rvprop="ids|timestamp|comment",
                rvlimit="max",
                **cont,
            )
            for page in data.get("query", {}).get("pages", []):
                out.extend(page.get("revisions", []))
            if "continue" in data:
                cont = data["continue"]
            else:
                break
        return out

    def entities_at_revisions(self, revids: List[int]) -> Dict[int, Dict]:
        """Fetch several revisions' entity JSON in one request. A revision and
        its parent share a page, so this halves the heavy content fetches."""
        out: Dict[int, Dict] = {}
        data = self._query(
            action="query",
            prop="revisions",
            revids="|".join(str(r) for r in revids),
            rvprop="ids|content",
            rvslots="main",
        )
        for page in data.get("query", {}).get("pages", []):
            for rev in page.get("revisions", []):
                content = rev.get("slots", {}).get("main", {}).get("content")
                if content:
                    out[rev["revid"]] = json.loads(content)
        return out

    def current_entity(self, qid: str) -> Optional[Dict]:
        data = self._query(
            action="wbgetentities",
            ids=qid,
            props="claims|sitelinks",
        )
        return data.get("entities", {}).get(qid)

    def entity_claim_p1800(self, qid: str) -> Optional[str]:
        """Read the 'Wikimedia database name' (e.g. 'eswiki') off a project item."""
        ent = self._query(
            action="wbgetentities",
            ids=qid,
            props="claims",
        ).get("entities", {}).get(qid)
        if not ent:
            return None
        for claim in ent.get("claims", {}).get("P1800", []):
            dv = claim.get("mainsnak", {}).get("datavalue", {})
            if dv.get("type") == "string":
                return dv.get("value")
        return None
