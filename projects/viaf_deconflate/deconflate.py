#!/usr/bin/env python3
"""
deconflate.py -- revisit VIAF IDs (P214) that were deprecated for conflation
(P2241 = Q14946528) and work out what should happen to them now that VIAF may
have split the cluster on their side.

By default it is a DRY RUN: it selects candidates, queries VIAF, classifies each
item into one of the outcomes below, and prints a report -- no edits. With
--apply it also performs the ADD/RELABEL edits for the actionable outcomes
(previewing unless --save is given); the review outcomes (probably-conflated,
redirect/abandoned, inconsistent) are only ever reported, never auto-edited.

Design (reviewed with Epidosis, 2026-08): for each Q5 item that carries a P214
deprecated for conflation, re-query VIAF by the item's *non-deprecated*
authority-control IDs (P244, P227, P268, ...) and also fetch the deprecated
cluster itself. Outcomes:

  ADD_AND_RELABEL  the item's IDs now resolve to one different, unused cluster
                   -> add that cluster (live) AND relabel the old statement's
                   reason Q14946528 -> Q35773207 (refers to different person),
                   then stamp retrieved=today.
  RELABEL_ONLY     same, but the new cluster is already on the item
                   -> only relabel the old statement (+ stamp).
  CORRECT_AS_OF_NOW  every id in the old cluster is now a non-deprecated id on
                   this item -> VIAF resolved the conflation -> un-deprecate
                   (normal rank, drop the P2241 qualifier) + stamp.
  STILL_CONFLATED  the IDs still resolve to the old cluster and a second party is
                   confirmed present (a source the item also has carries a
                   different value, VIAF links >=2 items, or a P1889/P4070/
                   same-VIAF partner still has one of its ids in the cluster)
                   -> keep deprecated + stamp retrieved=today.
  PROBABLY_CONFLATED  still in the old cluster but no second party confirmed
                   -> unclear -> manual review list, no edit.
  AMBIGUOUS_SHARED_ID  the item's live ids have moved out of the old cluster, but
                   the old cluster still carries an id that applies to this item
                   (a P4070 "identifier shared with" id, or an ISNI/FAST-type id
                   VIAF keeps in the cluster) AND no other Wikidata item is
                   confirmed to own the cluster -> "different person" is unsafe ->
                   manual review, no edit. (A different item counts as owner only
                   when it holds the cluster as its own non-deprecated P214; VIAF's
                   WKP link alone can be a wrong name/year guess.)
  LIST_REDIRECT    the old cluster now redirects -> manual review list.
  LIST_ABANDONED   the old cluster is abandoned / gone -> manual review list.
                   (Epidosis is fine with the bot *removing* these, but we
                   list-first until the dry-run output has been checked.)
  INCONSISTENT     the item's IDs resolve to more than one substantial cluster
                   (or some still to the old one) -> the item may mix two people,
                   or VIAF may just not have merged one person's clusters yet ->
                   manual review (the bot cannot pick which cluster to adopt).
  INSUFFICIENT     no authority ID resolved anywhere -> not enough evidence.
  ERROR            the item could not be read / evaluated.

Cross-cutting: a VIAF cluster that holds ONLY this person's records and links to
no other Wikidata item (a benign own-fragment) is always added as a live P214,
whatever the outcome above -- VIAF builds clusters bottom-up, so one person often
has several unmerged clusters, and the clean ones are safe to adopt.

Also cross-cutting: a *live* P214 the item's own ids did NOT resolve to may have
gone stale on VIAF's side. Such a value is re-queried; if VIAF now REDIRECTS it,
the live statement is deprecated (P2241 = Q45403344, redirect) and the redirect
target is added as a live P214 (unless the target is on another Wikidata item ->
review); if the record is ABANDONED/withdrawn, the live statement is deprecated
(P2241 = Q21441764, withdrawn identifier value).

Every conclusion is scoped to the subject item: the old cluster may still
conflate two *other* people, and the bot asserts nothing about that.

Reuses the sibling ``viaf`` project (AuthoritySources for per-source search
keys and matching, ViafApiClient for the lookups) and ``shared_lib.qlever`` /
``viaf.wdqs_client`` for selection and the duplicate check. Read-only against
both Wikidata and VIAF; VIAF's ~1000/day budget is respected via --max-viaf-calls.

Usage (PYTHONPATH=projects;projects/shared_lib via .env):
    python projects/viaf_deconflate/deconflate.py --out report.txt          # dry run
    python projects/viaf_deconflate/deconflate.py --max-items 30 --apply    # preview edits
    python projects/viaf_deconflate/deconflate.py --max-items 30 --apply --save  # commit
"""

import argparse
import hashlib
import io
import re
import sys
from collections import Counter, OrderedDict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pywikibot as pwb
import requests

import shared_lib.change_wikidata as cwd
import shared_lib.constants as wd
from shared_lib.wikidata_site import ensure_login, get_repo
from viaf.authority_sources import AuthorityRecord, AuthoritySource, AuthoritySources
from viaf.exceptions import SkipRecord
from viaf.viaf_api_client import (
    ViafApiClient,
    ViafLookupResult,
    ViafRateLimitExceeded,
    ViafStatus,
)
from viaf.viaf_config import load_config
from viaf.viaf_inferred_from_reference import ViafInferredFromReference
from viaf.wdqs_client import WdqsQueryError, query_wdqs

# reason-for-deprecated-rank (P2241) values. Not yet in shared_lib.constants;
# promote them there once this task is built for real.
QID_CONFLATION = "Q14946528"                  # the reason we are cleaning up
QID_REFERS_TO_DIFFERENT_PERSON = "Q35773207"  # the replacement (population is Q5)
QID_REDIRECT = "Q45403344"                    # live VIAF now redirects to another
QID_WITHDRAWN = "Q21441764"                   # live VIAF abandoned / withdrawn

# Valid VIAF cluster id: 2-9 digits, or the newer 19-22 digit form (with a gap).
VIAF_ID_RE = re.compile(r"^[1-9]\d(\d{0,7}|\d{17,20})$")

# VIAF's own authority-source code for Wikidata itself; its entries list the
# QIDs VIAF ties into a cluster.
WKP = "WKP"

# Wikidata-side signals that a deprecated VIAF is still a conflation (a second
# party is present on Wikidata): a "different from" link, an "identifier shared
# with" qualifier, or a sibling item carrying the same VIAF.
PID_DIFFERENT_FROM = "P1889"
PID_IDENTIFIER_SHARED_WITH = "P4070"

QLEVER_URL = "https://qlever.dev/api/wikidata"
HTTP_HEADERS = {
    "User-Agent": "DifoolBot/1.0 (https://www.wikidata.org/wiki/User:DifoolBot)"
}

DEFAULT_START_PID = wd.PID_GND_ID  # P227 (GND)
DEFAULT_MIN_AGE_DAYS = 365
DEFAULT_MAX_ITEMS = 1000
DEFAULT_MAX_VIAF_CALLS = 900  # stay under VIAF's ~1000/day ceiling
# Stop when VIAF reports this many daily calls left, so the shared quota keeps
# headroom for the daily add-bot cron and the manual "Add More Identifiers from
# VIAF" UI tool.
DEFAULT_MIN_DAY_REMAINING = 100
DEFAULT_APPLY_LIMIT = 5

# TEMPORARY: until the bot RfP for this task is approved, group all trial edits
# under one fixed editgroups batch so they can be linked from the request. Once
# approved, drop this and default to daily_editgroup() (see main()).
TRIAL_EDIT_GROUP = "ae99fd76fbab"


# --------------------------------------------------------------------------- #
# VIAF call budget                                                            #
# --------------------------------------------------------------------------- #


class BudgetExceeded(Exception):
    """Raised when the configured VIAF call cap is reached, to stop cleanly."""


class BudgetedViaf:
    """Thin wrapper over ViafApiClient that stops on either of two limits: a hard
    cap on calls this run (``max_calls``), or VIAF's own reported daily remaining
    dropping to ``min_day_remaining`` -- the latter keeps headroom in the shared
    quota for the add-bot cron and the manual UI tool."""

    def __init__(
        self, client: ViafApiClient, max_calls: int, min_day_remaining: int = 0
    ):
        self.client = client
        self.max_calls = max_calls
        self.min_day_remaining = min_day_remaining
        self.calls = 0

    def _guard(self) -> None:
        if self.calls >= self.max_calls:
            raise BudgetExceeded(f"reached VIAF call cap ({self.max_calls})")
        # last_remaining_day is from the previous call; stopping on it now leaves
        # roughly min_day_remaining unspent.
        rem = getattr(self.client, "last_remaining_day", None)
        if rem is not None and rem <= self.min_day_remaining:
            raise BudgetExceeded(
                f"VIAF daily budget floor reached (~{rem} left, keeping "
                f"{self.min_day_remaining} for other tools)"
            )

    def _call(self, fn, *args) -> ViafLookupResult:
        self._guard()
        result = fn(*args)
        self.calls += 1
        return result

    def sourceid(self, code: str, key: str) -> ViafLookupResult:
        return self._call(self.client.query_viaf_sourceid, code, key)

    def lccn(self, lccn: str) -> ViafLookupResult:
        return self._call(self.client.query_viaf_lccn, lccn)

    def cluster(self, viaf_id: str) -> ViafLookupResult:
        return self._call(self.client.query_viaf_id, viaf_id)


# --------------------------------------------------------------------------- #
# Data types                                                                  #
# --------------------------------------------------------------------------- #


@dataclass
class Candidate:
    qid: str
    viaf_dep: str            # the deprecated VIAF cluster value
    retrieved: date | None   # P813 on the deprecated statement's reference


@dataclass
class AuthId:
    auth_src: AuthoritySource
    value: str               # the item's non-deprecated external id for that source


@dataclass
class Result:
    qid: str
    viaf_dep: str
    outcome: str
    retrieved: date | None = None
    new_cluster: str | None = None      # the primary cluster to add (ADD_AND_RELABEL)
    detail: str = ""
    viaf_calls: int = 0
    start_id: str = ""
    # Benign own-fragment clusters (only this person, no other WKP item) that are
    # not yet on the item -> always safe to add, whatever the primary outcome.
    frag_clusters: list[str] = field(default_factory=list)
    n_auth_ids: int = 0                  # authority IDs read off the item
    n_clusters: int = 0                  # distinct VIAF clusters they resolved to
    # Fixes for the item's *live* P214s that have gone stale on VIAF's side:
    live_redirects: list[tuple[str, str | None]] = field(default_factory=list)
    # (old_live_value, target-or-None) -> deprecate old (P2241=redirect), add target
    live_withdrawn: list[str] = field(default_factory=list)  # deprecate (withdrawn)
    live_review: list[str] = field(default_factory=list)     # redirect target clashes


# --------------------------------------------------------------------------- #
# Candidate selection (qlever)                                                #
# --------------------------------------------------------------------------- #


def build_candidate_query(pid: str) -> str:
    """Q5 items with a non-deprecated <pid> authority id and a P214 deprecated
    for conflation; also pull the deprecated value and its retrieved date."""
    return f"""PREFIX wikibase: <http://wikiba.se/ontology#>
PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX p: <http://www.wikidata.org/prop/>
PREFIX ps: <http://www.wikidata.org/prop/statement/>
PREFIX pq: <http://www.wikidata.org/prop/qualifier/>
PREFIX prov: <http://www.w3.org/ns/prov#>
PREFIX pr: <http://www.wikidata.org/prop/reference/>
SELECT DISTINCT ?item ?viaf_dep ?retrieved WHERE {{
  ?item wdt:P31 wd:Q5 .
  ?item wdt:{pid} ?local .
  ?item p:P214 ?st .
  ?st wikibase:rank wikibase:DeprecatedRank ;
      ps:P214 ?viaf_dep ;
      pq:P2241 wd:{QID_CONFLATION} .
  OPTIONAL {{ ?st prov:wasDerivedFrom ?ref . ?ref pr:P813 ?retrieved . }}
}}"""


def build_candidate_query_for_qids(qids: list[str]) -> str:
    """Same as build_candidate_query but scoped to a fixed set of QIDs (VALUES),
    with no authority-source requirement -- for targeted --only runs. Still only
    returns items that are Q5 and carry a P214 deprecated for conflation."""
    values = " ".join(f"wd:{q}" for q in qids)
    return f"""PREFIX wikibase: <http://wikiba.se/ontology#>
PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX p: <http://www.wikidata.org/prop/>
PREFIX ps: <http://www.wikidata.org/prop/statement/>
PREFIX pq: <http://www.wikidata.org/prop/qualifier/>
PREFIX prov: <http://www.w3.org/ns/prov#>
PREFIX pr: <http://www.wikidata.org/prop/reference/>
SELECT DISTINCT ?item ?viaf_dep ?retrieved WHERE {{
  VALUES ?item {{ {values} }}
  ?item wdt:P31 wd:Q5 .
  ?item p:P214 ?st .
  ?st wikibase:rank wikibase:DeprecatedRank ;
      ps:P214 ?viaf_dep ;
      pq:P2241 wd:{QID_CONFLATION} .
  OPTIONAL {{ ?st prov:wasDerivedFrom ?ref . ?ref pr:P813 ?retrieved . }}
}}"""


def _parse_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value[:10])
    except (ValueError, TypeError):
        return None


def _run_selection(query: str) -> list[dict]:
    """SPARQL bindings for a selection query -- from qlever when it answers, from
    WDQS otherwise.

    qlever.dev rate-limits by IP and can 429 for a while, and the shared runner
    then burns minutes in backoff. This selection is small and selective, so one
    quick qlever attempt with an immediate WDQS fallback is both faster and more
    reliable than waiting qlever out."""
    try:
        resp = requests.get(
            QLEVER_URL, params={"query": query}, headers=HTTP_HEADERS, timeout=120
        )
        if resp.status_code == 200:
            return resp.json().get("results", {}).get("bindings", [])
        pwb.warning(f"qlever selection HTTP {resp.status_code}; falling back to WDQS.")
    except (requests.RequestException, ValueError) as exc:
        pwb.warning(f"qlever selection failed ({exc}); falling back to WDQS.")
    return query_wdqs(query)


def _fold_candidates(bindings: list[dict]) -> list[Candidate]:
    """Fold selection rows to one Candidate per (qid, viaf_dep), keeping the most
    recent retrieved date when a statement has several references."""
    merged: dict[tuple[str, str], Candidate] = {}
    for row in bindings:
        qid = row.get("item", {}).get("value", "").rsplit("/", 1)[-1]
        viaf_dep = row.get("viaf_dep", {}).get("value", "")
        if not qid.startswith("Q") or not viaf_dep:
            continue
        retrieved = _parse_date(row.get("retrieved", {}).get("value", ""))
        key = (qid, viaf_dep)
        existing = merged.get(key)
        if existing is None:
            merged[key] = Candidate(qid, viaf_dep, retrieved)
        elif retrieved and (existing.retrieved is None or retrieved > existing.retrieved):
            existing.retrieved = retrieved
    return list(merged.values())


def fetch_candidates(pid: str) -> list[Candidate]:
    """Run the pid-scoped selection and fold it to Candidates."""
    return _fold_candidates(_run_selection(build_candidate_query(pid)))


def fetch_candidates_for_qids(qids: list[str]) -> list[Candidate]:
    """Fetch the conflation-deprecated P214 candidate(s) for a specific set of
    QIDs (for targeted --only runs), regardless of which authority source they
    start from. Same Q5 + deprecated-for-conflation filter as the full scan."""
    if not qids:
        return []
    return _fold_candidates(_run_selection(build_candidate_query_for_qids(qids)))


def order_and_filter(
    candidates: list[Candidate], min_age_days: int
) -> list[Candidate]:
    """Keep candidates whose conflation was flagged over ``min_age_days`` ago (so
    VIAF has had time to re-cluster), plus those with no retrieved date at all
    (never stamped -- so a first pass timestamps them). Oldest-flagged first;
    undated last."""
    cutoff = date.today().toordinal() - min_age_days
    kept = [
        c
        for c in candidates
        if c.retrieved is None or c.retrieved.toordinal() <= cutoff
    ]
    # dated oldest-first, undated after (retrieved None -> large sort key); QID
    # breaks ties so a windowed run (--max-items) processes the same set each time.
    kept.sort(
        key=lambda c: (c.retrieved.toordinal() if c.retrieved else 10**9, int(c.qid[1:]))
    )
    return kept


# --------------------------------------------------------------------------- #
# Reading the item                                                            #
# --------------------------------------------------------------------------- #


def collect_auth_ids(
    item: pwb.ItemPage, sources: AuthoritySources, ignore: set[str]
) -> list[AuthId]:
    """Every non-deprecated authority-control id on the item that maps to a known
    VIAF source and is not in *ignore* (P214 itself is never in the source table).
    Ignored sources like ISNI/FAST are skipped for *resolution* because looking
    them up in VIAF is unreliable (often not found), the same reason the add-bot's
    config drops them -- not because they cannot be matched. When such a source is
    already present in a fetched cluster it matches the item's value fine, which is
    what collect_overlap_ids relies on."""
    out: list[AuthId] = []
    for pid in sources.all_pids():
        if pid in ignore:
            continue
        src = sources.get(pid)
        for claim in item.claims.get(pid, []):
            if claim.getRank() == "deprecated" or claim.getSnakType() != "value":
                continue
            value = claim.getTarget()
            if value:
                out.append(AuthId(src, str(value)))
    return out


def collect_overlap_ids(
    item: pwb.ItemPage, sources: AuthoritySources
) -> list[AuthId]:
    """Every authority id that still *applies to this item*, for the old-cluster
    overlap safety check -- broader than collect_auth_ids:

    * all non-deprecated authority ids, INCLUDING sources normally ignored for
      resolution (ISNI/FAST/...): those are only unreliable to *look up* in VIAF,
      but when one is already present in a fetched cluster it matches the item's
      value fine -- so containment against a cluster we already have is safe;
    * deprecated authority ids that carry an "identifier shared with" (P4070)
      qualifier -- a shared id is deprecated because it also belongs to another
      person, but it still applies to THIS item too.

    Used only to detect that a de-conflated old cluster still overlaps this
    person (-> ambiguous, route to review); never for VIAF resolution."""
    out: list[AuthId] = []
    for pid in sources.all_pids():
        src = sources.get(pid)
        for claim in item.claims.get(pid, []):
            if claim.getSnakType() != "value":
                continue
            if claim.getRank() == "deprecated" and not claim.qualifiers.get(
                PID_IDENTIFIER_SHARED_WITH
            ):
                continue  # deprecated for some other reason -> no longer applies
            value = claim.getTarget()
            if value:
                out.append(AuthId(src, str(value)))
    return out


def _cluster_shared_id(
    qid: str, cluster: ViafLookupResult, overlap_ids: list[AuthId]
) -> AuthId | None:
    """The first item id (from collect_overlap_ids) that ``cluster`` still lists,
    or None -- i.e. an identifier the old cluster and the item both carry."""
    for a in overlap_ids:
        if cluster_covers(qid, cluster, a):
            return a
    return None


def _cluster_owned_by_other_item(qid: str, v_dep: str, cluster: ViafLookupResult) -> bool:
    """True if the old cluster's WKP names a *different* Wikidata item that
    actually holds this cluster as its own non-deprecated P214 -- a confirmed,
    bidirectional owner.

    VIAF's WKP link alone is not proof: VIAF often adds it on a name/year match
    when the Wikidata item has no VIAF id yet, and such a guess can be wrong until
    Wikidata carries the matching VIAF id. So we read the pointed-at item and only
    count it when it genuinely claims this cluster (any non-deprecated rank)."""
    partners = {n for n, _ in cluster.source_mapping.get(WKP, []) if n} - {qid}
    for pqid in partners:
        try:
            partner = pwb.ItemPage(get_repo(), pqid)
            partner.get()
        except Exception:
            continue
        for c in partner.claims.get(wd.PID_VIAF_ID, []):
            if (
                c.getRank() != "deprecated"
                and c.getSnakType() == "value"
                and str(c.getTarget()) == v_dep
            ):
                return True
    return False


def _claim_has_reason(claim: pwb.Claim, reason_qid: str) -> bool:
    for q in claim.qualifiers.get(wd.PID_REASON_FOR_DEPRECATED_RANK, []):
        if q.getSnakType() == "value" and q.getTarget().getID() == reason_qid:
            return True
    return False


def _item_value_qids(item: pwb.ItemPage, pid: str) -> set[str]:
    """QIDs the item's value-snak statements for *pid* point to."""
    out: set[str] = set()
    for c in item.claims.get(pid, []):
        if c.getSnakType() == "value" and c.getTarget() is not None:
            out.add(c.getTarget().getID())
    return out


def _qualifier_value_qids(claim: pwb.Claim, pid: str) -> set[str]:
    """QIDs a claim's *pid* value-snak qualifiers point to."""
    out: set[str] = set()
    for q in claim.qualifiers.get(pid, []):
        if q.getSnakType() == "value" and q.getTarget() is not None:
            out.add(q.getTarget().getID())
    return out


def _items_with_viaf(viaf_id: str, exclude_qid: str) -> set[str]:
    """QIDs (other than *exclude_qid*) carrying this VIAF at any rank. Raises
    WdqsQueryError on failure -- callers must NOT read a failure as "none", which
    would let a real duplicate slip through."""
    query = (
        'SELECT DISTINCT ?item WHERE { ?item p:P214 ?s. '
        f'?s ps:P214 "{viaf_id}". FILTER(?item != wd:{exclude_qid}) }} LIMIT 10'
    )
    out: set[str] = set()
    for row in query_wdqs(query):
        q = row.get("item", {}).get("value", "").rsplit("/", 1)[-1]
        if q.startswith("Q") and q != exclude_qid:
            out.add(q)
    return out


def _wdqs_items_with_viaf(viaf_id: str, exclude_qid: str) -> set[str]:
    """As _items_with_viaf but empty on a WDQS failure -- ONLY for the
    still-conflated confirmation, where failing to find a sibling merely routes
    the item to review (safe). Never use it for the duplicate check before an ADD."""
    try:
        return _items_with_viaf(viaf_id, exclude_qid)
    except WdqsQueryError:
        return set()


def retrieved_of(claim: pwb.Claim) -> date | None:
    """Most recent retrieved (P813) date across the claim's references."""
    best: date | None = None
    for source in claim.sources:
        for ref in source.get(wd.PID_RETRIEVED, []):
            t = ref.getTarget()
            if t:
                d = date(t.year, t.month or 1, t.day or 1)
                if best is None or d > best:
                    best = d
    return best


# --------------------------------------------------------------------------- #
# VIAF resolution                                                             #
# --------------------------------------------------------------------------- #


def _record_for(qid: str, auth_id: AuthId) -> AuthorityRecord | None:
    """An AuthorityRecord with its VIAF search key computed, or None if the
    source cannot build one (e.g. a Libris control-number fetch that 404s)."""
    record = AuthorityRecord(qid, auth_id.value)
    try:
        auth_id.auth_src.compute_viaf_search_key(record)
    except SkipRecord:
        return None
    return record if record.viaf_search_key else None


def query_auth(viaf: BudgetedViaf, qid: str, auth_id: AuthId) -> ViafLookupResult | None:
    """Look this authority id up in VIAF (LC via lccn, everything else via
    sourceID), mirroring the add-bot. None when no search key is available."""
    record = _record_for(qid, auth_id)
    if record is None or not record.viaf_search_key:
        return None
    key = record.viaf_search_key
    if auth_id.auth_src.viaf_code == "LC":
        return viaf.lccn(key)
    return viaf.sourceid(auth_id.auth_src.viaf_code, key)


def cluster_covers(qid: str, cluster: ViafLookupResult, auth_id: AuthId) -> bool:
    """True if ``cluster`` already lists this authority id under its own source
    code -- so we need not spend a separate VIAF call to resolve it."""
    record = _record_for(qid, auth_id)
    if record is None:
        return False
    for nsid, content_id in cluster.source_mapping.get(auth_id.auth_src.viaf_code, []):
        try:
            if auth_id.auth_src.matches_viaf_external_id(nsid, content_id, record):
                return True
        except SkipRecord:
            continue
    return False


def _item_has_matching_id(
    qid: str, code: str, nsid: str, content_id: str, auth_ids: list[AuthId]
) -> bool:
    """True if one of the item's authority ids for VIAF source ``code`` matches
    this cluster record."""
    for a in auth_ids:
        if a.auth_src.viaf_code != code:
            continue
        record = _record_for(qid, a)
        if record is None:
            continue
        try:
            if a.auth_src.matches_viaf_external_id(nsid, content_id, record):
                return True
        except SkipRecord:
            continue
    return False


def _is_own_fragment(
    qid: str, cluster: ViafLookupResult, auth_ids: list[AuthId]
) -> bool:
    """True if ``cluster`` holds nothing but this person's own records -- every
    authority record matches an id on the item and no WKP entry points at a
    different Wikidata item.

    VIAF often leaves a stray record (e.g. a lone RERO id) in its own singleton
    cluster before merging it into the person's main cluster. Such a fragment is
    this person, not a rival cluster, so it must not trigger INCONSISTENT when
    the item already has its main VIAF live."""
    for code, records in cluster.source_mapping.items():
        if code == WKP:
            if any(nsid and nsid != qid for nsid, _ in records):
                return False
            continue
        for nsid, content_id in records:
            if not _item_has_matching_id(qid, code, nsid, content_id, auth_ids):
                return False
    return True


def _cluster_has_conflicting_id(
    qid: str, cluster: ViafLookupResult, auth_ids: list[AuthId]
) -> bool:
    """True if ``cluster`` carries a record for an authority source the item ALSO
    has, but with a value none of the item's ids for that source match -- e.g. the
    item's GND is G1 and the cluster holds GND G2 (G2 != G1).

    Authority ids are single-valued per person, so a *different* value for a
    source already on the item is a second person's id sitting in the cluster: a
    query-free, staleness-proof confirmation that the deprecated cluster is still
    a conflation (reads the live cluster, needs no VIAF call and no WDQS)."""
    item_codes = {a.auth_src.viaf_code for a in auth_ids}
    for code, records in cluster.source_mapping.items():
        if code == WKP or code not in item_codes:
            continue
        for nsid, content_id in records:
            if not _item_has_matching_id(qid, code, nsid, content_id, auth_ids):
                return True
    return False


def _partner_id_in_cluster(
    partner_qid: str,
    cluster: ViafLookupResult,
    sources: AuthoritySources,
    ignore: set[str],
) -> bool:
    """True if candidate partner item *partner_qid* has any authority id present
    in *cluster* -- i.e. the cluster currently holds a second person's records.

    This is the staleness-proof confirmation: a "different from" / "identifier
    shared with" / same-VIAF sibling only POINTS at the partner (those markers
    linger after VIAF resolves the conflation, so alone they only show it was
    ONCE conflated); the partner's id actually still being in the live cluster is
    what proves it is still conflated."""
    try:
        partner = pwb.ItemPage(get_repo(), partner_qid)
        partner.get()
    except Exception:
        return False
    for a in collect_auth_ids(partner, sources, ignore):
        if cluster_covers(partner_qid, cluster, a):
            return True
    return False


def forward_resolve(
    viaf: BudgetedViaf, qid: str, auth_ids: list[AuthId], start_pid: str
) -> tuple[set[str], dict[str, ViafLookupResult]]:
    """Resolve the item's authority ids to VIAF clusters, starting with
    ``start_pid`` and skipping any id a fetched cluster already contains.

    Returns (clusters_hit, fetched) where clusters_hit is the set of cluster ids
    the ids landed in and fetched maps cluster id -> its lookup result."""
    ordered = sorted(auth_ids, key=lambda a: 0 if a.auth_src.pid == start_pid else 1)
    fetched: dict[str, ViafLookupResult] = {}
    covered: set[tuple[str, str]] = set()

    for a in ordered:
        key = (a.auth_src.pid, a.value)
        if key in covered:
            continue
        covered.add(key)
        result = query_auth(viaf, qid, a)
        if result is None or result.status != ViafStatus.FOUND or not result.viaf_cluster_id:
            continue
        cid = result.viaf_cluster_id
        fetched.setdefault(cid, result)
        # Free coverage: any other id already inside this cluster needs no call.
        for b in ordered:
            bkey = (b.auth_src.pid, b.value)
            if bkey not in covered and cluster_covers(qid, result, b):
                covered.add(bkey)

    return set(fetched.keys()), fetched


def used_on_other_item(
    cluster_id: str, qid: str, cluster: ViafLookupResult | None, do_wdqs: bool
) -> str | None:
    """Return a QID (other than ``qid``) that already carries ``cluster_id``, or
    None. Checks VIAF's own WKP siblings first (already in hand), then WDQS.
    Raises WdqsQueryError if the WDQS check fails -- the caller must decline to
    add rather than treat a failed check as 'unused'."""
    if cluster is not None:
        for nsid, _ in cluster.source_mapping.get(WKP, []):
            if nsid and nsid != qid:
                return nsid
    if do_wdqs:
        for other in _items_with_viaf(cluster_id, qid):
            return other
    return None


def _redirect_target(res: ViafLookupResult) -> str:
    """The VIAF id a redirect points to (``directto``), or "" if missing/invalid.
    VIAF's client hands ``redirect_to`` back as a string or a small dict, so
    coerce and validate it against the VIAF id shape."""
    target = res.redirect_to
    if isinstance(target, dict):
        target = target.get("#text", "")
    target = str(target or "").strip()
    return target if VIAF_ID_RE.match(target) else ""


def resolve_live_status(
    viaf: "BudgetedViaf", qid: str, unconfirmed_live: list[str],
    v_all: set[str], do_wdqs: bool,
) -> tuple[list[tuple[str, str | None]], list[str], list[str]]:
    """For each live P214 the item's own ids did NOT resolve to, query VIAF and
    work out whether it has gone stale. Returns (redirects, withdrawn, review):

      redirects  (old, target-or-None): VIAF redirects old -> target. target is
                 None when the target is already on this item (just deprecate old);
                 otherwise the target is unused elsewhere and safe to add.
      withdrawn  old values whose VIAF record is abandoned/withdrawn.
      review     old values whose redirect target is already on another Wikidata
                 item (a human should decide) -- left untouched.

    Only the unconfirmed live values are queried (the resolved ones are known
    FOUND), so the extra VIAF calls are spent only on genuinely suspect ids."""
    redirects: list[tuple[str, str | None]] = []
    withdrawn: list[str] = []
    review: list[str] = []
    for live in sorted(unconfirmed_live):
        st = viaf.cluster(live)
        if st.status == ViafStatus.REDIRECT:
            target = _redirect_target(st)
            if not target:
                continue  # malformed redirect -> leave the statement alone
            if target in v_all:
                redirects.append((live, None))  # target already on the item
                continue
            try:
                dup = used_on_other_item(target, qid, None, do_wdqs)
            except WdqsQueryError:
                review.append(live)  # cannot verify unused -> human
                continue
            if dup:
                review.append(live)
            else:
                redirects.append((live, target))
        elif st.status in (ViafStatus.ABANDONED, ViafStatus.NOT_FOUND, ViafStatus.EMPTY):
            withdrawn.append(live)
        # FOUND: a valid live cluster the ids just did not resolve to -> leave it.
    return redirects, withdrawn, review


# --------------------------------------------------------------------------- #
# Classification                                                              #
# --------------------------------------------------------------------------- #


def classify(
    qid: str,
    v_dep: str,
    retrieved: date | None,
    clusters_hit: set[str],
    fetched: dict[str, ViafLookupResult],
    old: ViafLookupResult,
    v_live: set[str],
    v_all: set[str],
    benign: set[str],
    old_is_clean: bool,
    confirmed: bool,
    old_shared: str | None,
    old_owner_confirmed: bool,
    do_wdqs: bool,
) -> tuple[str, str | None, str]:
    """Decide the outcome from the deprecated cluster's status, where the item's
    live authority ids resolve, and which clusters are already on the item.

    ``old_is_clean`` means every id in the deprecated cluster is now a
    non-deprecated id on this item -- VIAF resolved the conflation, so the cluster
    is correct for this person now (CORRECT_AS_OF_NOW). ``confirmed`` means a
    second party's id is still in the cluster -- either the cluster carries a
    source the item also has but with a different value (item GND != cluster GND),
    or a candidate partner item (pointed at by P1889 / P4070 / a same-VIAF
    sibling) has one of its own ids in the cluster -- proof a second party remains
    (STILL_CONFLATED). Both read the live cluster, so neither goes stale.

    ``v_live`` is the item's non-deprecated P214 values; ``v_all`` is every P214
    value on the item at any rank (a cluster already on the item is never a "new"
    one to add). ``benign`` are unmerged own-fragments of this same person (VIAF
    lagging behind Wikidata) -- not rival clusters, so they never make an item
    INCONSISTENT. A live id still resolving to ``v_dep`` means the old cluster
    still holds this person, so forward resolution subsumes the reverse check.

    ``old_shared`` (a short "CODE value" label, or None) means the old cluster
    still carries an identifier that applies to this item -- a shared id
    (deprecated with P4070) or an ignored-source id like ISNI that VIAF has in the
    cluster. When the item's live ids have otherwise moved out of the old cluster,
    that leftover overlap makes the "refers to different person" reading unsafe --
    so the item goes to review (AMBIGUOUS_SHARED_ID) UNLESS ``old_owner_confirmed``:
    a different Wikidata item actually owns the old cluster (holds it as its own
    non-deprecated P214). Then the cluster is that other person's and the overlap
    is just common shared-id noise, so the relabel stands. VIAF's WKP link alone
    is not proof of ownership -- VIAF often adds it on a name/year match, so it can
    be wrong until Wikidata carries the matching VIAF id."""
    if old.status == ViafStatus.REDIRECT:
        return "LIST_REDIRECT", None, f"old cluster redirects to {old.redirect_to}"
    if old.status in (ViafStatus.ABANDONED, ViafStatus.NOT_FOUND, ViafStatus.EMPTY):
        return "LIST_ABANDONED", None, f"old cluster status={old.status}"

    # Clusters the ids land in that aren't already on the item; "rival" also drops
    # the benign own-fragments (still this person, just not merged in VIAF yet).
    new_clusters = clusters_hit - v_all
    rival = new_clusters - benign

    if v_dep in clusters_hit:
        # A live authority id still resolves to the deprecated cluster: it still
        # holds this person.
        if rival:
            return ("INCONSISTENT", None,
                    f"still in old cluster, but ids also moved to {sorted(rival)}")
        # Confidently still a conflation only when a second party is visible for
        # free: the item has a separate live clean VIAF, or the old cluster links
        # >=2 Wikidata items. Absence is NOT proof of clean -- older conflations
        # often never got the sibling item created -- so those go to review.
        if old_is_clean:
            # every id in the old cluster is now a non-deprecated id on this item
            # -> VIAF resolved the conflation; the cluster is correct for this
            # person now (un-deprecate + stamp).
            return ("CORRECT_AS_OF_NOW", None,
                    "old cluster now holds only this item's ids -> VIAF resolved it")
        # The old cluster still holds a foreign id. Is it tied to a second item?
        wkp_other = {nsid for nsid, _ in old.source_mapping.get(WKP, []) if nsid} - {qid}
        if wkp_other or confirmed:
            return "STILL_CONFLATED", None, "still conflated (a second party is in the cluster)"
        return ("PROBABLY_CONFLATED", None,
                "old cluster holds an id not on this item and not tied to another "
                "item -> unclear, needs a human")

    # No live id resolves to the deprecated cluster: it no longer holds this
    # person. If a *different* Wikidata item is confirmed to own the old cluster
    # (``old_owner_confirmed`` -- it holds the cluster as its own non-deprecated
    # P214), the cluster is that other person's, so "refers to different person"
    # is well founded even when a common shared id (e.g. ISNI) overlaps -- relabel.
    # But if the old cluster still carries an id that applies to this item (a
    # P4070-shared id, or an ISNI/FAST-type id VIAF keeps in it) and no other item
    # is confirmed to own it, the leftover overlap makes "different person" unsafe
    # -> route to review. (VIAF's own WKP link is not enough: VIAF often adds it on
    # name/year alone, so it can be wrong until Wikidata carries the matching id.)
    if old_shared is not None and not old_owner_confirmed:
        return ("AMBIGUOUS_SHARED_ID", None,
                f"old cluster still carries an id that applies to this item "
                f"({old_shared}) and no other item is confirmed to own it -> "
                f"ambiguous, needs a human")
    if not clusters_hit:
        return "INSUFFICIENT", None, "no authority id resolved to any cluster"

    if v_live:
        # The item already has its main cluster live; only a substantial rival
        # cluster (not a stray own-fragment) is a real disagreement.
        if len(rival) > 1:
            return "INCONSISTENT", None, f"ids resolve to multiple new clusters: {sorted(rival)}"
        if rival:
            r = next(iter(rival))
            return ("INCONSISTENT", r,
                    f"item already has live VIAF {sorted(v_live)}; ids also -> {r}")
        return ("RELABEL_ONLY", None,
                "old cluster no longer holds the person; clean cluster already live")

    # No live VIAF: the person's records are now in a cluster to adopt. Only the
    # *rival* (non-benign) clusters decide the outcome here -- benign own-fragments
    # are added separately (they are provably this person), so several of them, or
    # a mix of fragments and a cluster already on the item, is not INCONSISTENT.
    if len(rival) > 1:
        return "INCONSISTENT", None, f"ids resolve to multiple clusters: {sorted(rival)}"
    if not rival:
        return ("RELABEL_ONLY", None,
                "old cluster no longer holds the person; its ids resolve to a "
                "cluster already on the item or to its own fragment(s)")
    new_cluster = next(iter(rival))
    try:
        dup = used_on_other_item(new_cluster, qid, fetched.get(new_cluster), do_wdqs)
    except WdqsQueryError:
        # A failed duplicate check must never read as "unused" -> don't add;
        # relabel the old statement (independent and safe) and leave the add.
        return ("RELABEL_ONLY", new_cluster,
                f"could not verify {new_cluster} is unused (WDQS error); not adding")
    if dup:
        return "RELABEL_ONLY", new_cluster, f"new cluster {new_cluster} also on {dup}"
    return "ADD_AND_RELABEL", new_cluster, f"new cluster {new_cluster}"


def evaluate(
    candidate: Candidate,
    sources: AuthoritySources,
    viaf: BudgetedViaf,
    start_pid: str,
    do_wdqs: bool,
    ignore: set[str],
) -> Result:
    """Read the item, resolve its ids, fetch the old cluster, classify."""
    before = viaf.calls
    qid = candidate.qid
    try:
        item = pwb.ItemPage(get_repo(), qid)
        if not item.exists():
            return Result(qid, candidate.viaf_dep, "ERROR", detail="item does not exist")
        if item.isRedirectPage():
            return Result(qid, candidate.viaf_dep, "ERROR", detail="item is a redirect")
        item.get()

        # One pass over the item's P214 statements: pin down the retrieved date of
        # the deprecated-conflation statement (authoritative, over the query's),
        # and gather the clusters already live on the item.
        retrieved = candidate.retrieved
        v_live: set[str] = set()
        v_all: set[str] = set()
        dep_claim: pwb.Claim | None = None
        for claim in item.claims.get(wd.PID_VIAF_ID, []):
            if claim.getSnakType() != "value":
                continue
            value = str(claim.getTarget())
            v_all.add(value)
            if claim.getRank() == "deprecated":
                if value == candidate.viaf_dep and _claim_has_reason(claim, QID_CONFLATION):
                    retrieved = retrieved_of(claim)
                    dep_claim = claim
            else:
                v_live.add(value)

        auth_ids = collect_auth_ids(item, sources, ignore)
        start_id = next(
            (a.value for a in auth_ids if a.auth_src.pid == start_pid), ""
        )
        if not auth_ids:
            return Result(
                qid, candidate.viaf_dep, "INSUFFICIENT",
                retrieved=retrieved, detail="no known authority ids on item",
                viaf_calls=viaf.calls - before, start_id=start_id,
            )

        clusters_hit, fetched = forward_resolve(viaf, qid, auth_ids, start_pid)
        old = viaf.cluster(candidate.viaf_dep)
        # Clusters that are just unmerged fragments of this same person (VIAF
        # lagging behind Wikidata) -- not rival clusters.
        benign = {
            cid for cid, res in fetched.items() if _is_own_fragment(qid, res, auth_ids)
        }
        # Confirm the old cluster is STILL a conflation: find candidate partner
        # items via pointers -- "different from" (P1889), "identifier shared with"
        # (P4070) on the deprecated statement, a sibling carrying the same VIAF --
        # then verify a partner's own id is STILL in the live cluster. The markers
        # linger after VIAF resolves a conflation (they only point), but the
        # partner's id being in the cluster right now cannot go stale. Worth the
        # work only when we would otherwise be unsure. VIAF-free (old is already
        # fetched; partners read from Wikidata).
        # Read the deprecated cluster's CURRENT contents (staleness-proof):
        # old_is_clean = every id in it is a non-deprecated id on this item (VIAF
        # resolved it -> correct now); confirmed = a foreign id is tied to another
        # item (a second party remains -> still conflated). Both VIAF-free.
        old_is_clean = old.status == ViafStatus.FOUND and _is_own_fragment(
            qid, old, auth_ids
        )
        # Does the old cluster still carry an id that applies to this item -- a
        # shared id (deprecated with P4070) or an ignored-source id like ISNI that
        # VIAF keeps in the cluster? If the live ids have otherwise moved out, that
        # leftover overlap makes "refers to different person" unsafe (-> review).
        old_shared: str | None = None
        old_owner_confirmed = False
        if old.status == ViafStatus.FOUND:
            hit = _cluster_shared_id(qid, old, collect_overlap_ids(item, sources))
            if hit is not None:
                old_shared = f"{hit.auth_src.viaf_code} {hit.value}"
                # Only matters when the live ids have moved out (the relabel case)
                # -- is a different item confirmed to own the old cluster? (a WD
                # read; VIAF's WKP link alone is not trusted -- see the helper.)
                if candidate.viaf_dep not in clusters_hit:
                    old_owner_confirmed = _cluster_owned_by_other_item(
                        qid, candidate.viaf_dep, old
                    )
        confirmed = False
        if (
            candidate.viaf_dep in clusters_hit
            and old.status == ViafStatus.FOUND
            and not old_is_clean
        ):
            # Cheapest confirmation first: the cluster carries a source the item
            # also has, but with a different value (item GND != cluster GND) -> a
            # second person's id is in the cluster. Query-free, staleness-proof.
            confirmed = _cluster_has_conflicting_id(qid, old, auth_ids)
            wkp_other = {n for n, _ in old.source_mapping.get(WKP, []) if n} - {qid}
            if not confirmed and not wkp_other:  # else try the Wikidata pointers
                partners = _item_value_qids(item, PID_DIFFERENT_FROM)
                if dep_claim is not None:
                    partners |= _qualifier_value_qids(dep_claim, PID_IDENTIFIER_SHARED_WITH)
                if do_wdqs:
                    partners |= _wdqs_items_with_viaf(candidate.viaf_dep, qid)
                partners.discard(qid)
                confirmed = any(
                    _partner_id_in_cluster(pqid, old, sources, ignore) for pqid in partners
                )
        outcome, new_cluster, detail = classify(
            qid, candidate.viaf_dep, retrieved, clusters_hit, fetched, old,
            v_live, v_all, benign, old_is_clean, confirmed, old_shared,
            old_owner_confirmed, do_wdqs,
        )
        # Benign own-fragments (only this person, no other WKP item) not already
        # on the item are always safe to add, whatever the primary outcome says
        # about the deprecated statement -- the apply step re-checks each is unused.
        frag_clusters = sorted(benign - v_all - ({new_cluster} if new_cluster else set()))
        # Stale live P214s: a live VIAF the item's own ids did NOT resolve to may
        # have been redirected or withdrawn on VIAF's side. Check only those.
        live_redirects, live_withdrawn, live_review = resolve_live_status(
            viaf, qid, sorted(v_live - clusters_hit), v_all, do_wdqs,
        )
        return Result(
            qid, candidate.viaf_dep, outcome,
            retrieved=retrieved, new_cluster=new_cluster, detail=detail,
            viaf_calls=viaf.calls - before, start_id=start_id,
            frag_clusters=frag_clusters, n_auth_ids=len(auth_ids),
            n_clusters=len(clusters_hit), live_redirects=live_redirects,
            live_withdrawn=live_withdrawn, live_review=live_review,
        )
    except (BudgetExceeded, ViafRateLimitExceeded):
        raise
    except Exception as exc:  # keep the run going; one bad item is not fatal
        return Result(
            qid, candidate.viaf_dep, "ERROR",
            detail=f"{type(exc).__name__}: {exc}",
            viaf_calls=viaf.calls - before,
        )


# --------------------------------------------------------------------------- #
# Reporting                                                                   #
# --------------------------------------------------------------------------- #

_ORDER = [
    "ADD_AND_RELABEL", "RELABEL_ONLY", "CORRECT_AS_OF_NOW", "STILL_CONFLATED",
    "PROBABLY_CONFLATED", "AMBIGUOUS_SHARED_ID", "LIST_REDIRECT", "LIST_ABANDONED",
    "INCONSISTENT", "INSUFFICIENT", "ERROR",
]


def _line(r: Result) -> str:
    retr = r.retrieved.isoformat() if r.retrieved else "-"
    new = f" new={r.new_cluster}" if r.new_cluster else ""
    return (
        f"{r.qid:<12} dep={r.viaf_dep:<12} start={r.start_id or '-':<14} "
        f"retr={retr:<11} ids={r.n_auth_ids} cl={r.n_clusters} "
        f"{r.outcome:<16}{new}{_live_summary(r)}  {r.detail}"
    )


def write_report(results: list[Result], viaf_calls: int, stopped: str | None, out) -> None:
    counts = Counter(r.outcome for r in results)
    print("", file=out)
    print("=" * 78, file=out)
    print(
        f"Processed {len(results)} candidate(s); {viaf_calls} VIAF call(s) used."
        + (f"  [stopped: {stopped}]" if stopped else ""),
        file=out,
    )
    print("=" * 78, file=out)
    for outcome in _ORDER:
        if counts.get(outcome):
            print(f"  {outcome:<16} {counts[outcome]}", file=out)
    frag_items = sum(1 for r in results if r.frag_clusters)
    if frag_items:
        frag_total = sum(len(r.frag_clusters) for r in results)
        print(f"  (+ {frag_total} benign fragment cluster(s) added on {frag_items} "
              f"item(s), across the outcomes above)", file=out)
    red = sum(len(r.live_redirects) for r in results)
    wdn = sum(len(r.live_withdrawn) for r in results)
    rev = sum(len(r.live_review) for r in results)
    if red or wdn or rev:
        print(f"  (live-P214 fixes: {red} redirect, {wdn} withdrawn; {rev} redirect "
              f"target(s) clash -> review)", file=out)
    print("", file=out)
    # Per-item detail, grouped by outcome in the order above.
    by_outcome: dict[str, list[Result]] = {}
    for r in results:
        by_outcome.setdefault(r.outcome, []).append(r)
    for outcome in _ORDER:
        rows = by_outcome.get(outcome)
        if not rows:
            continue
        print(f"--- {outcome} ({len(rows)}) ---", file=out)
        for r in rows:
            print(_line(r), file=out)
        print("", file=out)


# --------------------------------------------------------------------------- #
# Apply (add / relabel / un-deprecate / stamp)                                #
# --------------------------------------------------------------------------- #

# Outcomes that translate into an edit; everything else is "leave alone" or
# "route to a human", never auto-edited.
_EDIT_OUTCOMES = {
    "ADD_AND_RELABEL", "RELABEL_ONLY", "CORRECT_AS_OF_NOW", "STILL_CONFLATED",
}

# Outcomes that need a human / carry no bot edit -- fully settled by a classify
# pass, so they are recorded (and then skipped) even on a dry run.
_REVIEW_OUTCOMES = {
    "PROBABLY_CONFLATED", "AMBIGUOUS_SHARED_ID", "INCONSISTENT",
    "LIST_REDIRECT", "LIST_ABANDONED", "INSUFFICIENT",
}


# --------------------------------------------------------------------------- #
# Processed-item state (text files, like the sibling bots)                     #
# --------------------------------------------------------------------------- #

OUTPUT_DIR = Path(__file__).resolve().parent / "output"
DONE_FILE = OUTPUT_DIR / "done.txt"        # statements actually edited (--save)
REVIEW_FILE = OUTPUT_DIR / "review.txt"    # routed to a human, no bot edit
ERROR_FILE = OUTPUT_DIR / "error.txt"      # transient failures -- NOT skipped


def _load_state_keys(path: Path) -> set[tuple[str, str]]:
    """(qid, viaf_dep) keys recorded in a state file."""
    keys: set[tuple[str, str]] = set()
    if path.exists():
        with open(path, encoding="utf-8") as f:
            for line in f:
                parts = line.split("\t")
                if len(parts) >= 2 and parts[0].startswith("Q"):
                    keys.add((parts[0].strip(), parts[1].strip()))
    return keys


def load_skip_set(include_review: bool = True) -> set[tuple[str, str]]:
    """(qid, viaf_dep) statements to skip re-processing: everything already
    edited, plus (unless recheck-review) everything already routed to review.
    Errors are never skipped -- they retry."""
    keys = _load_state_keys(DONE_FILE)
    if include_review:
        keys |= _load_state_keys(REVIEW_FILE)
    return keys


def _live_summary(r: "Result") -> str:
    """Compact tail describing the extra fragment/redirect/withdrawn actions."""
    parts = []
    if r.frag_clusters:
        parts.append(f"+frag={r.frag_clusters}")
    if r.live_redirects:
        parts.append(f"redirect={r.live_redirects}")
    if r.live_withdrawn:
        parts.append(f"withdrawn={r.live_withdrawn}")
    if r.live_review:
        parts.append(f"live_review={r.live_review}")
    return (" " + " ".join(parts)) if parts else ""


def _append_state(path: Path, r: "Result") -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"{r.qid}\t{r.viaf_dep}\t{r.outcome}\t{date.today().isoformat()}\t"
                f"{r.detail}{_live_summary(r)}\n")


def record_state(results: list["Result"], edited_qids: set[str]) -> dict[str, int]:
    """Append newly-settled statements to the state files, de-duplicating against
    what is already there. ``edited_qids`` are the QIDs an --save apply actually
    wrote (empty on a dry run). A statement is settled when it needs no (further)
    bot edit: a review outcome with no pending fragment add is settled by the
    classify pass alone; an edit outcome or a fragment add is settled only once
    saved. Errors go to error.txt and are never skipped."""
    done, review, errors = (_load_state_keys(DONE_FILE),
                            _load_state_keys(REVIEW_FILE),
                            _load_state_keys(ERROR_FILE))
    added = {"done": 0, "review": 0, "error": 0}
    for r in results:
        key = (r.qid, r.viaf_dep)
        if r.outcome == "ERROR":
            if key not in errors:
                _append_state(ERROR_FILE, r); errors.add(key); added["error"] += 1
            continue
        pending_edit = (r.outcome in _EDIT_OUTCOMES or bool(r.frag_clusters)
                        or bool(r.live_redirects) or bool(r.live_withdrawn))
        review_primary = r.outcome in _REVIEW_OUTCOMES or bool(r.live_review)
        if pending_edit:
            if r.qid in edited_qids:              # actually written this run
                if key not in done:
                    _append_state(DONE_FILE, r); done.add(key); added["done"] += 1
                # a review statement that also gained a fragment add still needs a
                # human -> keep it on the worklist too.
                if review_primary and key not in review:
                    _append_state(REVIEW_FILE, r); review.add(key); added["review"] += 1
            # else: still pending, do not record
        elif review_primary and key not in review:
            _append_state(REVIEW_FILE, r); review.add(key); added["review"] += 1
    return added


def _find_dep_conflation_claim(item: pwb.ItemPage, v_dep: str) -> pwb.Claim | None:
    """The item's deprecated-for-conflation P214 claim whose value is ``v_dep``."""
    for claim in item.claims.get(wd.PID_VIAF_ID, []):
        if (
            claim.getRank() == "deprecated"
            and claim.getSnakType() == "value"
            and str(claim.getTarget()) == v_dep
            and _claim_has_reason(claim, QID_CONFLATION)
        ):
            return claim
    return None


def _stamp_retrieved(claim: pwb.Claim) -> None:
    """Remove any retrieved-only reference on the claim, then add a fresh
    retrieved (P813) = today. So "update, or add if absent" falls out, and old
    bare-retrieved references do not accumulate.

    Also drop any stray retrieved (P813) *qualifier*: some editors put retrieved
    in the qualifiers (so it sits visually under the reason-for-deprecated-rank),
    but as a qualifier its target is ambiguous -- the value, the rank, or the
    reason -- and it is invisible to reference queries. We record retrieved as a
    reference instead, so the qualifier is consolidated away."""
    claim.qualifiers.pop(wd.PID_RETRIEVED, None)
    kept = [src for src in claim.sources if set(src.keys()) != {wd.PID_RETRIEVED}]
    today = date.today()
    ref = pwb.Claim(get_repo(), wd.PID_RETRIEVED, is_reference=True)
    ref.setTarget(pwb.WbTime(year=today.year, month=today.month, day=today.day))
    kept.append(OrderedDict([(wd.PID_RETRIEVED, [ref])]))
    claim.sources = kept


def _relabel_reason(claim: pwb.Claim) -> None:
    """Change reason for deprecated rank (P2241) from conflation (Q14946528) to
    'refers to different person' (Q35773207); leave every other qualifier."""
    reasons = claim.qualifiers.get(wd.PID_REASON_FOR_DEPRECATED_RANK, [])
    kept = [
        q for q in reasons
        if not (q.getSnakType() == "value" and q.getTarget().getID() == QID_CONFLATION)
    ]
    if not any(
        q.getSnakType() == "value"
        and q.getTarget().getID() == QID_REFERS_TO_DIFFERENT_PERSON
        for q in kept
    ):
        q = pwb.Claim(get_repo(), wd.PID_REASON_FOR_DEPRECATED_RANK, is_qualifier=True)
        q.setTarget(pwb.ItemPage(get_repo(), QID_REFERS_TO_DIFFERENT_PERSON))
        kept.append(q)
    claim.qualifiers[wd.PID_REASON_FOR_DEPRECATED_RANK] = kept


def _undeprecate(claim: pwb.Claim) -> None:
    """Un-deprecate: rank -> normal and drop the reason-for-deprecated-rank
    (P2241) qualifier (a normal-rank statement must not carry one)."""
    claim.rank = "normal"
    claim.qualifiers.pop(wd.PID_REASON_FOR_DEPRECATED_RANK, None)


def _find_live_claim(item: pwb.ItemPage, value: str) -> pwb.Claim | None:
    """The item's non-deprecated P214 claim whose value is ``value``."""
    for claim in item.claims.get(wd.PID_VIAF_ID, []):
        if (
            claim.getRank() != "deprecated"
            and claim.getSnakType() == "value"
            and str(claim.getTarget()) == value
        ):
            return claim
    return None


def _deprecate_with_reason(claim: pwb.Claim, reason_qid: str) -> None:
    """Deprecate a (currently live) claim: rank -> deprecated with a single
    reason-for-deprecated-rank (P2241) qualifier."""
    claim.rank = "deprecated"
    q = pwb.Claim(get_repo(), wd.PID_REASON_FOR_DEPRECATED_RANK, is_qualifier=True)
    q.setTarget(pwb.ItemPage(get_repo(), reason_qid))
    claim.qualifiers[wd.PID_REASON_FOR_DEPRECATED_RANK] = [q]


class RetrievedReference(cwd.Reference):
    """A bare reference carrying only retrieved (P813) = today, for a value the bot
    took from VIAF today with no other citable source -- e.g. a redirect target,
    whose provenance is simply 'VIAF redirected here, as retrieved today'."""

    def is_equal_reference(self, src) -> bool:
        return set(src.keys()) == {wd.PID_RETRIEVED}

    def create_source(self):
        today = date.today()
        ref = pwb.Claim(get_repo(), wd.PID_RETRIEVED, is_reference=True)
        ref.setTarget(pwb.WbTime(year=today.year, month=today.month, day=today.day))
        return OrderedDict([(wd.PID_RETRIEVED, [ref])])

    def is_strong_reference(self) -> bool:
        return False


def daily_editgroup(tag: str = "viaf_deconflate") -> str:
    """A stable per-day editgroups batch id, so all of a day's edits group under
    one https://editgroups.toolforge.org/b/CB/<id>/ batch (reviewable/revertable
    together). Same tag+day -> same id; --editgroup overrides it."""
    return hashlib.sha1(f"{tag}:{date.today().isoformat()}".encode()).hexdigest()[:12]


def apply_edits(
    results: list[Result], limit: int, save: bool, edit_group: str = ""
) -> set[str]:
    """Perform the edits, grouped per item so one item with several deprecated
    statements (or the same new cluster reached twice) is a single edit.
    ``save=False`` builds the edit in WikiDataPage test mode (prints a summary,
    writes nothing). ``edit_group`` (a batch id) tags every edit summary so the
    run's edits are grouped on editgroups.toolforge.org and can be reviewed or
    rolled back together. Returns the number of items (would be) edited.

    Per outcome: ADD_AND_RELABEL adds the new cluster (full VIAF reference) and
    relabels the old one; RELABEL_ONLY relabels; CORRECT_AS_OF_NOW un-deprecates;
    STILL_CONFLATED just re-stamps. Every touched deprecated statement is stamped
    with retrieved=today. Independently of the outcome, any benign own-fragment
    clusters (r.frag_clusters) are also added -- they are provably this person, so
    even a review-only item (e.g. INCONSISTENT) can still gain a clean live VIAF.
    Every add is re-checked as unused right before it is written.

    Returns the set of QIDs that were (or, in test mode, would be) edited."""
    # An item is edited if it has an edit outcome OR a benign own-fragment to add
    # (those ride along with any outcome, including the review ones).
    by_qid: dict[str, list[Result]] = {}
    for r in results:
        if (r.outcome in _EDIT_OUTCOMES or r.frag_clusters
                or r.live_redirects or r.live_withdrawn):
            by_qid.setdefault(r.qid, []).append(r)

    edited: set[str] = set()
    for qid, rows in by_qid.items():
        if len(edited) >= limit:
            break
        adds = {r.new_cluster for r in rows
                if r.outcome == "ADD_AND_RELABEL" and r.new_cluster}
        for r in rows:  # benign own-fragments, added regardless of outcome
            adds.update(r.frag_clusters)
        relabels = {r.viaf_dep for r in rows
                    if r.outcome in ("ADD_AND_RELABEL", "RELABEL_ONLY")}
        undeprecates = {r.viaf_dep for r in rows if r.outcome == "CORRECT_AS_OF_NOW"}
        stamps = {r.viaf_dep for r in rows if r.outcome == "STILL_CONFLATED"}
        live_redirects: dict[str, str | None] = {}
        for r in rows:
            for old, tgt in r.live_redirects:
                live_redirects.setdefault(old, tgt)
        live_withdrawn = {v for r in rows for v in r.live_withdrawn}
        try:
            item = pwb.ItemPage(get_repo(), qid)
            item.get(force=True)  # fresh, so ranks/refs and add-dedup see reality
            on_item = {
                str(c.getTarget())
                for c in item.claims.get(wd.PID_VIAF_ID, [])
                if c.getSnakType() == "value"
            }
            wdpage = cwd.WikiDataPage(item, test=not save)
            wdpage.edit_group = edit_group
            for cluster in sorted(adds):
                if cluster in on_item:  # already present at some rank -> never re-add
                    continue
                try:  # re-check right before adding; WD may have changed since scan
                    others = _items_with_viaf(cluster, qid)
                except WdqsQueryError:
                    pwb.warning(f"{qid}: cannot verify {cluster} is unused; skipping add")
                    continue
                if others:
                    pwb.warning(f"{qid}: {cluster} now on {sorted(others)}; skipping add")
                    continue
                wdpage.add_statement(
                    cwd.ExternalIDStatement(prop=wd.PID_VIAF_ID, external_id=cluster),
                    reference=ViafInferredFromReference(wd.PID_VIAF_ID, cluster),
                )
            for v_dep in sorted(relabels):
                claim = _find_dep_conflation_claim(item, v_dep)
                if claim is not None:
                    _relabel_reason(claim)
                    _stamp_retrieved(claim)
                    wdpage.claim_changed(claim)
            for v_dep in sorted(undeprecates):
                claim = _find_dep_conflation_claim(item, v_dep)
                if claim is not None:
                    _undeprecate(claim)
                    _stamp_retrieved(claim)
                    wdpage.claim_changed(claim)
            for v_dep in sorted(stamps):
                claim = _find_dep_conflation_claim(item, v_dep)
                if claim is not None:
                    _stamp_retrieved(claim)
                    wdpage.claim_changed(claim)
            # Stale live P214s: redirect (deprecate old + add target) or withdrawn.
            # Only deprecate the old redirect if its target can actually be added
            # (or is already on the item), so we never orphan the statement.
            for old, tgt in sorted(live_redirects.items()):
                claim = _find_live_claim(item, old)
                if claim is None:
                    continue
                if tgt and tgt not in on_item:
                    try:
                        others = _items_with_viaf(tgt, qid)
                    except WdqsQueryError:
                        pwb.warning(f"{qid}: cannot verify redirect target {tgt}; skipping")
                        continue
                    if others:
                        pwb.warning(f"{qid}: redirect target {tgt} now on {sorted(others)}; skipping")
                        continue
                    wdpage.add_statement(
                        cwd.ExternalIDStatement(prop=wd.PID_VIAF_ID, external_id=tgt),
                        reference=RetrievedReference(),
                    )
                _deprecate_with_reason(claim, QID_REDIRECT)
                wdpage.claim_changed(claim)
            for old in sorted(live_withdrawn):
                claim = _find_live_claim(item, old)
                if claim is not None:
                    _deprecate_with_reason(claim, QID_WITHDRAWN)
                    wdpage.claim_changed(claim)
            wdpage.summary = "VIAF de-conflation"
            if wdpage.apply():
                edited.add(qid)
                verb = "edited" if save else "would edit"
                extra = ""
                if live_redirects:
                    extra += f" redirect={sorted(live_redirects)}"
                if live_withdrawn:
                    extra += f" withdrawn={sorted(live_withdrawn)}"
                pwb.output(
                    f"{verb} {qid}: add={sorted(adds)} relabel={sorted(relabels)} "
                    f"undeprecate={sorted(undeprecates)} stamp={sorted(stamps)}{extra}"
                )
        except Exception as e:  # one bad item must not abort the batch
            pwb.error(f"apply failed for {qid}: {e}")
    return edited


# --------------------------------------------------------------------------- #
# CLI                                                                         #
# --------------------------------------------------------------------------- #


def main() -> None:
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--pid", default=DEFAULT_START_PID,
                    help=f"authority property to start from (default {DEFAULT_START_PID} = GND)")
    ap.add_argument("--max-items", type=int, default=DEFAULT_MAX_ITEMS,
                    help="stop after this many candidate items")
    ap.add_argument("--max-viaf-calls", type=int, default=DEFAULT_MAX_VIAF_CALLS,
                    help="stop before exceeding this many VIAF API calls")
    ap.add_argument("--min-day-remaining", type=int, default=DEFAULT_MIN_DAY_REMAINING,
                    help="stop when VIAF reports this many daily calls left, so the "
                         "shared quota keeps headroom (e.g. for the manual UI tool)")
    ap.add_argument("--min-age-days", type=int, default=DEFAULT_MIN_AGE_DAYS,
                    help="only items flagged as conflation at least this long ago "
                         "(plus any with no retrieved date)")
    ap.add_argument("--no-dup-check", action="store_true",
                    help="skip the WDQS 'is the new cluster on another item?' check")
    ap.add_argument("--out", default=None, help="also write the report to this file")
    ap.add_argument("--apply", action="store_true",
                    help="after classifying, perform ADD/RELABEL edits (previews "
                         "unless --save is given)")
    ap.add_argument("--save", action="store_true",
                    help="with --apply, actually save the edits (default: preview only)")
    ap.add_argument("--apply-limit", type=int, default=DEFAULT_APPLY_LIMIT,
                    help="with --apply, edit at most this many items")
    ap.add_argument("--only", default=None,
                    help="comma-separated QIDs to process instead of the full "
                         "selection (targeted verification; bypasses the age "
                         "filter and --max-items)")
    ap.add_argument("--editgroup", metavar="ID", default=None,
                    help="editgroups batch id for the edit summaries (default: a "
                         "fixed trial batch until the RfP is approved; then a "
                         "stable per-day id via daily_editgroup())")
    ap.add_argument("--recheck-review", action="store_true",
                    help="re-process items previously routed to review (VIAF may "
                         "have split a cluster since); still skips edited items")
    ap.add_argument("--recheck", action="store_true",
                    help="ignore the processed-item state entirely (re-do all)")
    ap.add_argument("--no-state", action="store_true",
                    help="do not read or write the output/ state files")
    args = ap.parse_args()

    ensure_login()
    sources = AuthoritySources()
    if args.pid not in sources.all_pids():
        print(f"{args.pid} is not a known VIAF authority source.")
        return
    ignore = set(load_config().ignore)

    if args.only:
        only_qids = [q.strip().upper() for q in args.only.split(",") if q.strip()]
        raw = fetch_candidates_for_qids(only_qids)
        found = {c.qid for c in raw}
        missing = [q for q in only_qids if q not in found]
        if missing:
            print(f"warning: --only QIDs not conflation candidates / not found: {missing}")
        candidates = order_and_filter(raw, 0)  # hand-picked: no age filter
        print(
            f"--only: {len(candidates)} candidate statement(s) for "
            f"{len(found)}/{len(only_qids)} requested item(s)."
        )
    else:
        raw = fetch_candidates(args.pid)
        candidates = order_and_filter(raw, args.min_age_days)
        print(
            f"selection returned {len(raw)} candidate(s); {len(candidates)} remain after "
            f"the {args.min_age_days}-day age filter (start source {args.pid})."
        )
        # Skip statements already handled in a previous run (saves VIAF calls);
        # --only always bypasses this.
        if not args.no_state and not args.recheck:
            skip = load_skip_set(include_review=not args.recheck_review)
            before = len(candidates)
            candidates = [c for c in candidates if (c.qid, c.viaf_dep) not in skip]
            if before != len(candidates):
                print(f"skipped {before - len(candidates)} already-processed "
                      f"candidate(s) from output/ state.")
        candidates = candidates[: args.max_items]

    viaf = BudgetedViaf(ViafApiClient(), args.max_viaf_calls, args.min_day_remaining)
    results: list[Result] = []
    stopped: str | None = None
    for i, candidate in enumerate(candidates, 1):
        try:
            result = evaluate(
                candidate, sources, viaf, args.pid, not args.no_dup_check, ignore
            )
        except (BudgetExceeded, ViafRateLimitExceeded) as exc:
            stopped = str(exc)
            break
        results.append(result)
        if i % 25 == 0:
            print(f"  ...{i}/{len(candidates)} items, {viaf.calls} VIAF calls")

    write_report(results, viaf.calls, stopped, sys.stdout)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            write_report(results, viaf.calls, stopped, fh)
        print(f"Report written to {args.out}")

    edited_qids: set[str] = set()
    if args.apply:
        # TEMPORARY: fixed trial batch until the RfP is approved; then switch to
        # daily_editgroup(). --editgroup still overrides.
        edit_group = args.editgroup or TRIAL_EDIT_GROUP
        mode = "SAVING edits" if args.save else "previewing edits (no save)"
        print(f"\n--- apply: {mode}, up to {args.apply_limit} item(s) ---")
        print(f"editgroup https://editgroups.toolforge.org/b/CB/{edit_group}/")
        edited = apply_edits(results, args.apply_limit, args.save, edit_group)
        print(f"{'edited' if args.save else 'previewed'} {len(edited)} item(s).")
        if args.save:
            edited_qids = edited

    # Record settled statements so later runs skip them (review outcomes are
    # settled by classification; edits only once actually saved).
    if not args.no_state:
        added = record_state(results, edited_qids)
        if any(added.values()):
            print(f"state: +{added['done']} done, +{added['review']} review, "
                  f"+{added['error']} error  (in {OUTPUT_DIR})")


if __name__ == "__main__":
    main()
