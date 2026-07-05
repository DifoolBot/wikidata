#!/usr/bin/env python3
"""
viaf_score.py - pywikibot script for User:Difool/viaf_already_somewhere

Reads the wikitext of the page, computes a similarity Score for every
QID-pair row that does not yet have one (or re-scores all rows when
--rescore is given), then writes the updated wikitext back.

Scoring mirrors the Delphi TCompareWikiData logic:
  TSameBirthYearScore     +5 / -1
  TSameDeathYearScore     +5 / -1
  TOverlapLifeScore       +1 / -100
  TSameBirthCountryScore  +1 / -20
  TFloruitScore            0 / -10
  TBNFScore               +2 / -2

Special labels (shown instead of the numeric score):
  Redirect               - either QID is a redirect
  Left has conflation VIAF
  Left has VIAF
  Left external ID removed
  Different from
  VIAF filled            - both have distinct non-deprecated VIAFs
  VIAF deprecated
  SameAs
  …, Instance of         - appended when right item is not instance-of human (Q5)

Usage (on Toolforge):
  python viaf_score.py [--rescore] [--dry-run] [--limit N]

Options:
  --rescore   Remove and recompute all existing scores (default: skip rows
              that already have a score).
  --dry-run   Print the new wikitext to stdout instead of saving.
  --limit N   Process at most N rows per section (useful for testing).
"""

import re
import sys
import time
import argparse
import logging
from dataclasses import dataclass, field
from typing import Optional

import pywikibot
from pywikibot import pagegenerators  # noqa: F401 - kept for toolforge compat
from pywikibot.data import api

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PAGE_TITLE = "User:Difool/viaf_already_somewhere"
SITE = pywikibot.Site("wikidata", "wikidata")

# Wikidata API rate-limit courtesy delay between entity fetches (seconds)
API_DELAY = 0.5

# Sections with these headings are not processed (e.g. intro / actions)
IGNORE_HEADERS = {"==Actions==", "==Columns=="}

# Wikidata property IDs used during scoring
P_BIRTH_DATE = "P569"
P_DEATH_DATE = "P570"
P_FLORUIT = "P1317"
P_PLACE_OF_BIRTH = "P19"
P_PLACE_OF_DEATH = "P20"  # noqa: F841  (reserved for future use)
P_COUNTRY = "P17"
P_BNF = "P268"
P_VIAF = "P214"
P_INSTANCE_OF = "P31"
P_DIFFERENT_FROM = "P1889"
P_SAME_AS = "P460"
P_REASON_DEPRECATED = "P2241"

Q_HUMAN = "Q5"
Q_CONFLATION = "Q14946528"

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Wikidata buffers  (mirror the Delphi buffers: each entity/person/place is
# loaded and examined only once, then reused across every row that needs it)
# ---------------------------------------------------------------------------

# Raw entity JSON keyed by requested QID (populated by get_entity).
_entity_cache: dict[str, dict] = {}

# Fully examined Person objects keyed by (qid, pid); see get_person.
_person_cache: dict[tuple[str, str], "Person"] = {}

# Resolved place → country (P17) QID, keyed by place QID; see _resolve_country.
_country_cache: dict[str, Optional[str]] = {}


def get_entity(qid: str) -> Optional[dict]:
    """Return the entity dict for *qid*, fetching from the API if needed.

    Fetches only claims via a single ``wbgetentities`` call.  We deliberately
    skip sitelinks/labels/descriptions: the scorer never uses them, and
    requesting sitelinks makes the response far heavier for well-connected
    items.  This also avoids the extra ``isRedirectPage`` query round-trip that
    ``pywikibot.ItemPage.get()`` triggers.

    The result is normalized to ``{"entities": {<id>: {"claims": {...}}}}``.
    ``redirects=yes`` follows a redirect and returns the *target*'s claims;
    since the target's ``id`` differs from the requested *qid*, we key the dict
    by that target id so callers can spot a redirect via
    ``next(iter(entities)) != qid``.
    """
    if qid in _entity_cache:
        return _entity_cache[qid]
    try:
        resp = api.Request(
            site=SITE,
            parameters={
                "action": "wbgetentities",
                "ids": qid,
                "props": "claims",
                "redirects": "yes",
                "format": "json",
            },
        ).submit()
        ent = resp.get("entities", {}).get(qid, {})
        actual = ent.get("id", qid)  # target id when qid is a redirect
        data = {"entities": {actual: ent}}
        _entity_cache[qid] = data
        time.sleep(API_DELAY)
        return data
    except Exception as exc:
        log.warning("Could not load %s: %s", qid, exc)
        _entity_cache[qid] = {}
        return {}


def is_redirect(qid: str) -> bool:
    """Return True if the QID redirects to a different QID."""
    data = get_entity(qid)
    if not data:
        return False
    entities = data.get("entities", {})
    if not entities:
        return False
    actual = next(iter(entities))
    return actual != qid


# ---------------------------------------------------------------------------
# Claim helpers  (mirror TClaim in Delphi)
# ---------------------------------------------------------------------------


def _claim_is_deprecated(claim: dict) -> bool:
    return claim.get("rank") == "deprecated"


def _claim_is_conflation(claim: dict) -> bool:
    """Check qualifier P2241 = Q14946528 (reason for deprecated: conflation)."""
    qualifiers = claim.get("qualifiers", {})
    for q in qualifiers.get(P_REASON_DEPRECATED, []):
        val = q.get("datavalue", {}).get("value", {})
        if isinstance(val, dict) and val.get("id") == Q_CONFLATION:
            return True
    return False


def _get_external_id(claim: dict) -> Optional[str]:
    """Return mainsnak string value, or None."""
    return claim.get("mainsnak", {}).get("datavalue", {}).get("value")


def _get_qid(claim: dict) -> Optional[str]:
    """Return mainsnak item QID value, or None."""
    val = claim.get("mainsnak", {}).get("datavalue", {}).get("value")
    if isinstance(val, dict):
        return val.get("id")
    return None


# ---------------------------------------------------------------------------
# WikiIDs  (mirror TWikiIDs)
# ---------------------------------------------------------------------------


@dataclass
class WikiID:
    external_id: str
    is_deprecated: bool
    is_conflation: bool


class WikiIDs:
    def __init__(self) -> None:
        self._ids: list[WikiID] = []

    def add(self, external_id: str, is_deprecated: bool, is_conflation: bool) -> None:
        self._ids.append(WikiID(external_id, is_deprecated, is_conflation))

    def has_id(self, external_id: str, include_deprecated: bool) -> bool:
        for id_ in self._ids:
            if include_deprecated or not id_.is_deprecated:
                if id_.external_id == external_id:
                    return True
        return False

    def has_deprecated_id(self, external_id: str) -> bool:
        """Has a deprecated entry but NO normal entry for this id."""
        return not self.has_id(external_id, False) and self.has_id(external_id, True)

    def has_any(self) -> bool:
        """Has at least one non-deprecated ID."""
        return any(not id_.is_deprecated for id_ in self._ids)

    def has_any_conflation(self) -> bool:
        """Has at least one deprecated+conflation ID."""
        return any(id_.is_deprecated and id_.is_conflation for id_ in self._ids)

    def has_shared_id(self, other: "WikiIDs") -> bool:
        """Both have the same non-deprecated external ID."""
        for id_ in self._ids:
            if not id_.is_deprecated:
                if other.has_id(id_.external_id, False):
                    return True
        return False


# ---------------------------------------------------------------------------
# WikiDate  (mirror TWikiDate - only year precision needed for scoring)
# ---------------------------------------------------------------------------


class WikiDate:
    def __init__(self) -> None:
        self._years: list[int] = []

    def add_claim(self, claim: dict) -> None:
        if _claim_is_deprecated(claim):
            return
        val = claim.get("mainsnak", {}).get("datavalue", {}).get("value")
        if not isinstance(val, dict):
            return
        time_str = val.get("time", "")
        precision = val.get("precision", 0)
        if precision < 9:  # less than year precision - ignore
            return
        # "+1797-01-01T00:00:00Z"  → year is chars 1-4
        try:
            year = int(time_str[1:5])
            self._years.append(year)
        except (ValueError, IndexError):
            pass

    def get_year(self) -> Optional[int]:
        """Return the single year if there is exactly one, else None."""
        return self._years[0] if len(self._years) == 1 else None

    def get_first(self) -> Optional[int]:
        return min(self._years) if self._years else None

    def get_last(self) -> Optional[int]:
        return max(self._years) if self._years else None


# ---------------------------------------------------------------------------
# Person  (mirror TPerson)
# ---------------------------------------------------------------------------


class Person:
    def __init__(self, qid: str, pid: str) -> None:
        self.qid = qid
        self.pid = pid  # the authority-control PID being examined
        self.birth_date = WikiDate()
        self.death_date = WikiDate()
        self.floruit = WikiDate()
        self.birth_country_qids: list[str] = []
        self.bnf_ids = WikiIDs()
        self.viaf_ids = WikiIDs()
        self.external_ids = WikiIDs()
        self.same_as = WikiIDs()
        self.has_other_instance_of = False
        self._data: dict = {}

    # ------------------------------------------------------------------ load
    def examine(self) -> None:
        self._data = get_entity(self.qid) or {}
        if self.is_redirect:
            return
        claims = self._claims()
        self._load_date(claims, P_BIRTH_DATE, self.birth_date)
        self._load_date(claims, P_DEATH_DATE, self.death_date)
        self._load_date(claims, P_FLORUIT, self.floruit)
        self._load_birth_country(claims)
        self._load_ids(claims, P_BNF, self.bnf_ids)
        self._load_ids(claims, P_VIAF, self.viaf_ids)
        self._load_ids(claims, self.pid, self.external_ids)
        self._load_same_as(claims)
        self._load_instance_of(claims)

    # --------------------------------------------------------------- helpers
    def _claims(self) -> dict:
        entities = self._data.get("entities", {})
        entity = entities.get(self.qid, {})
        return entity.get("claims", {})

    @property
    def is_redirect(self) -> bool:
        if not self._data:
            return False
        entities = self._data.get("entities", {})
        if not entities:
            return False
        return next(iter(entities)) != self.qid

    def _load_date(self, claims: dict, prop: str, dest: WikiDate) -> None:
        for c in claims.get(prop, []):
            dest.add_claim(c)

    def _load_ids(self, claims: dict, prop: str, dest: WikiIDs) -> None:
        for c in claims.get(prop, []):
            ext_id = _get_external_id(c)
            if ext_id:
                dest.add(ext_id, _claim_is_deprecated(c), _claim_is_conflation(c))

    def _load_same_as(self, claims: dict) -> None:
        for c in claims.get(P_SAME_AS, []):
            if not _claim_is_deprecated(c):
                qid = _get_qid(c)
                if qid:
                    self.same_as.add(qid, False, False)

    def _load_instance_of(self, claims: dict) -> None:
        for c in claims.get(P_INSTANCE_OF, []):
            if not _claim_is_deprecated(c):
                qid = _get_qid(c)
                if qid and qid != Q_HUMAN:
                    self.has_other_instance_of = True

    def _load_birth_country(self, claims: dict) -> None:
        """Resolve place-of-birth → country (P17), preferred rank first."""
        pob_claims = claims.get(P_PLACE_OF_BIRTH, [])
        place_qids = []
        preferred = [
            c
            for c in pob_claims
            if c.get("rank") == "preferred" and not _claim_is_deprecated(c)
        ]
        normal = [c for c in pob_claims if c.get("rank") != "deprecated"]
        for c in preferred or normal:
            qid = _get_qid(c)
            if qid:
                place_qids.append(qid)

        for place_qid in place_qids:
            country = self._resolve_country(place_qid)
            if country:
                self.birth_country_qids.append(country)

    def _resolve_country(self, place_qid: str) -> Optional[str]:
        """Return the country QID for a place (P17), preferred rank first.

        Buffered per place so a country shared by many birthplaces is resolved
        only once (mirrors the Delphi place buffer).
        """
        if place_qid in _country_cache:
            return _country_cache[place_qid]

        data = get_entity(place_qid) or {}
        entities = data.get("entities", {})
        entity = entities.get(place_qid, {})
        p17 = entity.get("claims", {}).get(P_COUNTRY, [])
        result: Optional[str] = None
        if p17:
            preferred = [
                c
                for c in p17
                if c.get("rank") == "preferred" and not _claim_is_deprecated(c)
            ]
            normal = [c for c in p17 if not _claim_is_deprecated(c)]
            for c in preferred or normal:
                qid = _get_qid(c)
                if qid:
                    result = qid
                    break

        _country_cache[place_qid] = result
        return result

    def is_different_from(self, other_qid: str) -> bool:
        claims = self._claims()
        for c in claims.get(P_DIFFERENT_FROM, []):
            if not _claim_is_deprecated(c):
                if _get_qid(c) == other_qid:
                    return True
        return False

    def get_life(self) -> tuple[Optional[int], Optional[int]]:
        return self.birth_date.get_first(), self.death_date.get_last()

    def get_floruit(self) -> tuple[Optional[int], Optional[int]]:
        return self.floruit.get_first(), self.floruit.get_last()


# ---------------------------------------------------------------------------
# Score calculators  (mirror TBaseScore subclasses)
# ---------------------------------------------------------------------------


def score_same_year(left_date: WikiDate, right_date: WikiDate) -> int:
    """TSameBirthYearScore / TSameDeathYearScore: +5 same, -1 different."""
    y1 = left_date.get_year()
    y2 = right_date.get_year()
    if y1 is None or y2 is None:
        return 0
    return 5 if y1 == y2 else -1


def score_overlap_life(left: Person, right: Person) -> int:
    """TOverlapLifeScore: +1 overlapping lifespans, -100 no overlap."""
    st1, nd1 = left.get_life()
    st2, nd2 = right.get_life()
    if st1 is None or nd1 is None or st2 is None or nd2 is None:
        return 0
    if (st1 <= nd2) and (st2 <= nd1):
        return 1
    return -100


def score_birth_country(left: Person, right: Person) -> int:
    """TSameBirthCountryScore: +1 same, -20 different (only if both have exactly one)."""
    lc = left.birth_country_qids
    rc = right.birth_country_qids
    if len(lc) == 1 and len(rc) == 1:
        return 1 if lc[0] == rc[0] else -20
    return 0


def score_floruit(left: Person, right: Person) -> int:
    """TFloruitScore: -10 when life and floruit don't overlap."""
    result = 0
    st1, nd1 = left.get_life()
    st2, nd2 = right.get_floruit()
    if st1 is not None and nd1 is not None and st2 is not None and nd2 is not None:
        if not ((st1 <= nd2) and (st2 <= nd1)):
            result = -10
    st1, nd1 = right.get_life()
    st2, nd2 = left.get_floruit()
    if st1 is not None and nd1 is not None and st2 is not None and nd2 is not None:
        if not ((st1 <= nd2) and (st2 <= nd1)):
            result = -10
    return result


def score_bnf(left: Person, right: Person) -> int:
    """TBNFScore: +2 shared BnF ID, -2 both have different BnF IDs."""
    if left.bnf_ids.has_shared_id(right.bnf_ids):
        return 2
    if left.bnf_ids.has_any() and right.bnf_ids.has_any():
        return -2
    return 0


def compute_score(left: Person, right: Person) -> int:
    total = 0
    total += score_same_year(left.birth_date, right.birth_date)
    total += score_same_year(left.death_date, right.death_date)
    total += score_overlap_life(left, right)
    total += score_birth_country(left, right)
    total += score_floruit(left, right)
    total += score_bnf(left, right)
    return total


# ---------------------------------------------------------------------------
# QIDPairScore  (mirror TQIDPairScore / GetText)
# ---------------------------------------------------------------------------


@dataclass
class QIDPairScore:
    left: str
    right: str
    score: int = 0
    is_redirect: bool = False
    is_different_from: bool = False
    has_viaf_conflation_left: bool = False
    has_viaf_left: bool = False
    external_id_removed_left: bool = False
    has_viaf: bool = False
    has_deprecated_viaf: bool = False
    has_same_as: bool = False
    has_other_instance_of_right: bool = False

    @property
    def text(self) -> str:
        if self.is_redirect:
            t = "Redirect"
        elif self.has_viaf_conflation_left:
            t = "Left has conflation VIAF"
        elif self.has_viaf_left:
            t = "Left has VIAF"
        elif self.external_id_removed_left:
            t = "Left external ID removed"
        elif self.is_different_from:
            t = "Different from"
        elif self.has_viaf:
            t = "VIAF filled"
        elif self.has_deprecated_viaf:
            t = "VIAF deprecated"
        elif self.has_same_as:
            t = "SameAs"
        else:
            t = str(self.score)
        if self.has_other_instance_of_right:
            t += ", Instance of"
        return t


def get_person(qid: str, pid: str) -> "Person":
    """Return an examined :class:`Person`, reusing a buffered one when possible.

    A QID often appears in several rows of a section (and the same section
    always uses one *pid*), so buffering avoids re-parsing the entity each time.
    Mirrors the Delphi person buffer.
    """
    key = (qid, pid)
    person = _person_cache.get(key)
    if person is None:
        person = Person(qid, pid)
        person.examine()
        _person_cache[key] = person
    return person


def create_item(
    left_qid: str, right_qid: str, viaf_id: str, pid: str, external_id: str
) -> Optional[QIDPairScore]:
    try:
        left = get_person(left_qid, pid)
        right = get_person(right_qid, pid)

        score = 0
        if not (left.is_redirect or right.is_redirect):
            score = compute_score(left, right)

        pair = QIDPairScore(left=left_qid, right=right_qid, score=score)
        pair.is_redirect = left.is_redirect or right.is_redirect
        pair.external_id_removed_left = not left.external_ids.has_id(external_id, False)
        pair.is_different_from = left.is_different_from(
            right_qid
        ) or right.is_different_from(left_qid)
        pair.has_viaf_conflation_left = left.viaf_ids.has_any_conflation()
        pair.has_viaf_left = (
            not left.viaf_ids.has_shared_id(right.viaf_ids) and left.viaf_ids.has_any()
        )
        pair.has_viaf = (
            not left.viaf_ids.has_shared_id(right.viaf_ids)
            and left.viaf_ids.has_any()
            and right.viaf_ids.has_any()
        )
        pair.has_deprecated_viaf = left.viaf_ids.has_deprecated_id(
            viaf_id
        ) or right.viaf_ids.has_deprecated_id(viaf_id)
        pair.has_other_instance_of_right = right.has_other_instance_of
        pair.has_same_as = left.same_as.has_id(
            right_qid, False
        ) and right.same_as.has_id(left_qid, False)
        return pair
    except Exception as exc:
        log.warning("create_item(%s, %s) failed: %s", left_qid, right_qid, exc)
        return None


# ---------------------------------------------------------------------------
# Wikitext parsing helpers
# ---------------------------------------------------------------------------

# Table row layout (one line each, order fixed by the bot that wrote the page):
#   |-
#   | https://viaf.org/viaf/<VIAF>
#   | {{Q|<Q1>}}
#   | <PID>|<ExternalID>          ← "ID from cluster" cell
#   | {{Q|<Q2>}}
#   | [https://... compare]
#   | <Score>                     ← may or may not be present


def _extract_qid(line: str) -> str:
    """Return the QID from a line like '| {{Q|Q12345}}'."""
    m = re.search(r"\{\{Q\|([Qq]\d+)\}\}", line)
    return m.group(1) if m else ""


def _extract_viaf(line: str) -> str:
    """Return the VIAF numeric ID from '| https://viaf.org/viaf/12345'."""
    m = re.search(r"/viaf/(\S+)", line)
    return m.group(1).strip() if m else ""


def _extract_external_id(line: str) -> str:
    """Return the part after the last '|' in the 'ID from cluster' cell."""
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:].strip()
    idx = stripped.rfind("|")
    return stripped[idx + 1 :].strip() if idx >= 0 else stripped


def _extract_pid(header: str) -> str:
    """
    Parse the section header to find the property ID.
    Accepts '=={{P|P691}}==' or plain text titles mapped in the Delphi source.
    """
    # Try {{P|Pxxx}} form first
    m = re.search(r"\{\{P\|(P\d+)\}\}", header)
    if m:
        return m.group(1)
    # Fall back to the text-to-PID map from ExtractPID in the Delphi source
    title = re.sub(r"^=+\s*|\s*=+$", "", header).strip()
    _MAP = {
        "CONOR.SI ID": "P1280",
        "National Library of Israel J9U ID": "P8189",
        "Library of Congress authority ID": "P244",
        "IdRef ID": "P269",
        "GND ID": "P227",
        "NL CR AUT ID": "P691",
        "ISNI": "P213",
        "Bibliothèque nationale de France ID": "P268",
        "NUKAT ID": "P1207",
        "Union List of Artist Names ID": "P245",
        "Nationale Thesaurus voor Auteursnamen ID": "P1006",
        "BAnQ authority ID": "P3280",
        "CANTIC ID": "P9984",
        "Libraries Australia ID": "P409",
        "NSK ID": "P1375",
        "DBC author ID": "P3846",
        "PLWABN ID": "P7293",
        "Canadiana Name Authority ID": "P8179",
        "National Library of Korea ID": "P5034",
        "CiNii Books author ID": "P271",
        "Vatican Library VcBA ID": "P8034",
        "RERO ID (obsolete),": "P3065",
        "RISM ID": "P5504",
        "Portuguese National Library author ID": "P1005",
        "BNMM authority ID": "P3788",
        "EGAXA ID": "P1309",
        "NDL Authority ID": "P349",
        "Libris-URI": "P5587",
        "National Library of Latvia ID": "P1368",
        "NORAF ID": "P1015",
    }
    return _MAP.get(title, "")


# ---------------------------------------------------------------------------
# Score label classification
# ---------------------------------------------------------------------------

_DONE_PREFIXES = (
    "Redirect",
    "Left has VIAF",
    "Left external ID removed",
    "Left has conflation VIAF",
)

_SKIP_PREFIXES = _DONE_PREFIXES + (
    "Different from",
    "VIAF filled",
    "VIAF deprecated",
    "SameAs",
    "?",
)


def _score_cell_is_computed(cell: str) -> bool:
    """True if the cell already contains a computed score (any value)."""
    c = cell.strip()
    for p in _SKIP_PREFIXES:
        if c.startswith(p):
            return True
    # numeric (possibly with ", Instance of" appended)
    return bool(re.match(r"^-?\d+", c))


def _row_is_done(score_cell: str) -> bool:
    """True if the row should be removed (action already taken)."""
    c = score_cell.strip()
    return any(c.startswith(p) for p in _DONE_PREFIXES)


# ---------------------------------------------------------------------------
# Section processor
# ---------------------------------------------------------------------------


# A section score map: {(q1, q2): QIDPairScore} for the rows of one section.
ScoreMap = dict[tuple[str, str], QIDPairScore]


def score_section(lines: list[str], pid: str, limit: Optional[int]) -> ScoreMap:
    """Compute a :class:`QIDPairScore` for every eligible row in one section.

    This is the network-bound half of the pipeline (it calls the API via
    ``create_item``).  It returns a map keyed by the ``(q1, q2)`` pair rather
    than by line position, so the result can later be applied to a *different*
    revision of the page (see :func:`apply_section`).  Rows beyond *limit* are
    left out of the map (they render as "?" when applied).
    """
    score_map: ScoreMap = {}
    i = 0
    processed = 0
    while i < len(lines):
        if lines[i].strip() == "|-" and i + 5 < len(lines):
            # Expected structure:
            #   i+0  |-
            #   i+1  | https://viaf.org/viaf/...
            #   i+2  | {{Q|Q1}}
            #   i+3  | PID|ExternalID
            #   i+4  | {{Q|Q2}}
            #   i+5  | [... compare]
            viaf = _extract_viaf(lines[i + 1])
            q1 = _extract_qid(lines[i + 2])
            ext_id = _extract_external_id(lines[i + 3])
            q2 = _extract_qid(lines[i + 4])
            if q1 and q2 and viaf and ext_id:
                if limit is None or processed < limit:
                    log.info("Scoring %s ↔ %s (VIAF %s)", q1, q2, viaf)
                    pair = create_item(q1, q2, viaf, pid, ext_id)
                    processed += 1
                    if pair is not None:
                        score_map[(q1, q2)] = pair
        i += 1
    return score_map


def apply_section(
    lines: list[str], score_map: ScoreMap, remove_done: bool = True
) -> list[str]:
    """Apply a precomputed *score_map* to one section's *lines* (no network).

    Steps (matching Delphi ProcessText → RemoveDone → InsertData):
      1. Strip the existing score column header and values.
      2. Remove rows whose score marks a done action (unless *remove_done*
         is False, in which case they are kept and labelled like any other).
      3. Re-insert the score column header and per-row score cells (original
         row order preserved; the table stays browser-sortable via "sortable").

    Rows not present in *score_map* (e.g. added to the page after scoring, or
    beyond the scoring limit) keep the placeholder "?".
    """
    lines = _remove_score_column(lines)
    if remove_done:
        lines = _remove_done_rows(lines, score_map)
    lines = _insert_score_column(lines, score_map)
    return lines


def _remove_done_rows(lines: list[str], score_map: ScoreMap) -> list[str]:
    """Drop each row whose ``(q1, q2)`` scored to a done-action label."""
    done_starts = set()
    i = 0
    while i < len(lines):
        if lines[i].strip() == "|-" and i + 5 < len(lines):
            q1 = _extract_qid(lines[i + 2])
            q2 = _extract_qid(lines[i + 4])
            pair = score_map.get((q1, q2))
            if pair is not None and _row_is_done(pair.text):
                done_starts.add(i)
        i += 1

    if not done_starts:
        return lines

    new_lines: list[str] = []
    skip_until = -1
    i = 0
    while i < len(lines):
        if i in done_starts:
            # Find end of this row block (next "|-" or "|}")
            j = i + 1
            while j < len(lines) and lines[j].strip() not in ("|-", "|}"):
                j += 1
            skip_until = j - 1
        if i > skip_until:
            new_lines.append(lines[i])
        i += 1
    return new_lines


def _remove_score_column(lines: list[str]) -> list[str]:
    """
    Remove the '! Score' header line and any score data cells that follow
    '| [compare link]' lines (the last data cell before '|-' or '|}').
    Mirrors Delphi RemoveScore.
    """
    result = []
    # Remove header
    for ln in lines:
        if ln.strip() == "! Score":
            continue
        result.append(ln)

    # Remove trailing data cell before each row separator
    cleaned: list[str] = []
    i = 0
    while i < len(result):
        if i + 1 < len(result) and result[i].strip().startswith("|"):
            nxt = result[i + 1].strip()
            if nxt in ("|-", "|}"):
                # Check if this looks like a score cell (not a data cell)
                # A score cell starts with "| " then a label or number
                cell = result[i].strip()[1:].strip()  # strip leading '|'
                # If it's not a link/QID/viaf-url line, it's a score
                if not (
                    cell.startswith("{{")
                    or cell.startswith("http")
                    or cell.startswith("[http")
                ):
                    i += 1
                    continue
        cleaned.append(result[i])
        i += 1

    return cleaned


def _insert_score_column(lines: list[str], score_map: ScoreMap) -> list[str]:
    """
    Add '! Score' after the last '!' header line and insert a per-row score
    cell, keeping the original row order.  Mirrors Delphi InsertHeader +
    InsertData.  Rows missing from *score_map* get the placeholder "?".
    """

    # --- Insert '! Score' header after last '!' header line
    last_header_idx = -1
    for i, ln in enumerate(lines):
        if ln.strip().startswith("!"):
            last_header_idx = i
    if last_header_idx >= 0:
        lines = (
            lines[: last_header_idx + 1] + ["! Score"] + lines[last_header_idx + 1 :]
        )

    # --- Insert score cells and collect sortable rows
    # We'll rebuild the table body with score cells inserted, then sort.

    # Split into: pre-table, table header, table body, post-table
    # "table body" = everything between the last header line and '|}'
    header_end = -1
    for i, ln in enumerate(lines):
        if ln.strip().startswith("!"):
            header_end = i

    table_end = -1
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].strip() == "|}":
            table_end = i
            break

    if header_end < 0 or table_end < 0:
        return lines  # malformed, leave as-is

    pre = lines[: header_end + 1]
    body = lines[header_end + 1 : table_end]
    post = lines[table_end:]

    # Parse body into individual row blocks  [[line, line, …], …]
    row_blocks: list[list[str]] = []
    cur: list[str] = []
    for ln in body:
        if ln.strip() == "|-":
            if cur:
                row_blocks.append(cur)
            cur = [ln]
        else:
            cur.append(ln)
    if cur:
        row_blocks.append(cur)

    # Add score cell to each block, keeping the original row order so a diff
    # against the previous revision is easy to eyeball.  (The table is
    # "sortable", so readers can still sort by Score in the browser.)
    new_body: list[str] = []
    for block in row_blocks:
        q1 = ""
        q2 = ""
        for ln in block:
            if not q1:
                q1 = _extract_qid(ln)
            elif not q2:
                q2 = _extract_qid(ln)
        pair = score_map.get((q1, q2)) if q1 and q2 else None
        label = pair.text if pair is not None else "?"
        new_body.extend(block + [f"| {label}"])

    return pre + new_body + post


# ---------------------------------------------------------------------------
# Main page processing
# ---------------------------------------------------------------------------


def split_into_sections(wikitext: str) -> list[dict]:
    """
    Split the wikitext into a list of {'header': str, 'lines': [str]} dicts.
    The first dict has header='' for content before the first == heading ==.
    """
    sections: list[dict] = []
    current_header = ""
    current_lines: list[str] = []

    for raw_line in wikitext.splitlines():
        if raw_line.startswith("==") and not raw_line.startswith("==="):
            sections.append({"header": current_header, "lines": current_lines})
            current_header = raw_line
            current_lines = []
        else:
            current_lines.append(raw_line)

    sections.append({"header": current_header, "lines": current_lines})
    return sections


def rebuild_wikitext(sections: list[dict]) -> str:
    parts: list[str] = []
    for sec in sections:
        if sec["header"]:
            parts.append(sec["header"])
        parts.extend(sec["lines"])
    return "\n".join(parts)


# A full-page score map is keyed by (pid, q1, q2) so that the same QID pair
# appearing under two different property sections doesn't collide.
PageScoreMap = dict[tuple[str, str, str], QIDPairScore]


def _scorable_sections(
    sections: list[dict], rescore: bool, log_details: bool = False
):
    """Yield ``(sec, pid)`` for each section that should be (re)scored.

    The same gating is used by both the compute pass (:func:`score_wikitext`)
    and the apply pass (:func:`apply_wikitext`) so they always agree on which
    sections to touch.  Set *log_details* only on the compute pass to avoid
    duplicate log lines.
    """
    for sec in sections:
        header = sec["header"]

        # Skip non-property sections
        if not header or header in IGNORE_HEADERS:
            continue
        if not re.search(r"\{\{P\|P\d+\}\}|==\s*\w", header):
            continue

        pid = _extract_pid(header)
        if not pid:
            if log_details:
                log.warning("Could not determine PID for section: %s", header)
            continue

        # A section that already has a Score column is left alone unless the
        # caller asked to rescore everything.
        has_score_col = any(ln.strip() == "! Score" for ln in sec["lines"])
        if has_score_col and not rescore:
            if log_details:
                log.info("Skipping %s (already scored; use rescore to recompute)", header)
            continue

        if log_details:
            log.info("Processing section %s (PID=%s)", header, pid)
        yield sec, pid


def score_wikitext(
    original_text: str, rescore: bool = False, limit: Optional[int] = None
) -> PageScoreMap:
    """Compute scores for every scorable row (network-bound).

    Returns a map keyed by ``(pid, q1, q2)`` so it can be applied to a *later*
    revision of the page — see :func:`apply_wikitext`.
    """
    sections = split_into_sections(original_text)
    page_map: PageScoreMap = {}
    for sec, pid in _scorable_sections(sections, rescore, log_details=True):
        for (q1, q2), pair in score_section(list(sec["lines"]), pid, limit).items():
            page_map[(pid, q1, q2)] = pair
    return page_map


def apply_wikitext(
    current_text: str,
    page_map: PageScoreMap,
    rescore: bool = False,
    remove_done: bool = True,
) -> Optional[str]:
    """Apply a precomputed *page_map* to *current_text* (no network).

    Returns the rebuilt wikitext, or ``None`` when nothing changed.  Because
    the map is keyed by QID pair, this can safely run against a revision read
    *after* scoring: a row deleted meanwhile is simply skipped.

    A section that has no computed scores is left untouched.  This matters when
    a *new* section appears in the fresh revision (the section-adding bot ran
    during scoring): we must not stamp it with a Score column full of "?", or
    later daily runs would treat it as already scored and never fill it in.  It
    is picked up whole on the next run instead.
    """
    # Group the flat map by pid so each section gets its own local map, and so
    # a pid absent here marks a section we did not score (and must skip).
    by_pid: dict[str, ScoreMap] = {}
    for (p, q1, q2), pair in page_map.items():
        by_pid.setdefault(p, {})[(q1, q2)] = pair

    sections = split_into_sections(current_text)
    changed = False
    for sec, pid in _scorable_sections(sections, rescore):
        local = by_pid.get(pid)
        if local is None:
            log.info("Skipping section for %s (not scored this run)", pid)
            continue
        new_lines = apply_section(list(sec["lines"]), local, remove_done)
        if new_lines != sec["lines"]:
            sec["lines"] = new_lines
            changed = True

    if not changed:
        return None
    return rebuild_wikitext(sections)


def process_wikitext(
    original_text: str,
    rescore: bool = False,
    limit: Optional[int] = None,
    remove_done: bool = True,
) -> Optional[str]:
    """Compute + apply against the *same* text and return the rebuilt wikitext
    (or ``None`` when nothing changed).

    This is the offline convenience used by the file-based tests.  The live
    bot instead scores one revision and applies to a freshly re-read revision;
    see :func:`process_page`.
    """
    page_map = score_wikitext(original_text, rescore=rescore, limit=limit)
    return apply_wikitext(
        original_text, page_map, rescore=rescore, remove_done=remove_done
    )


def process_page(
    rescore: bool = False,
    dry_run: bool = False,
    limit: Optional[int] = None,
    remove_done: bool = True,
) -> None:
    """Score the live page, then apply the scores to a freshly re-read copy.

    Scoring can take many minutes (one API round-trip per entity), during which
    the page may be edited.  To avoid discarding a whole run on a concurrent
    edit — or clobbering it — we split the work:

      1. Read a snapshot and compute the score map from it.
      2. Re-read the page (resetting the edit-conflict base to the latest
         revision) and apply the precomputed scores to *that* text.
      3. Save, with pywikibot's edit-conflict detection as a final backstop for
         the small window between the re-read and the write.
    """
    page = pywikibot.Page(SITE, PAGE_TITLE)

    # 1. Snapshot + compute (slow).
    page.get(force=True)
    base_revid = page.latest_revision_id
    page_map = score_wikitext(page.text, rescore=rescore, limit=limit)

    # 2. Re-read so we apply onto (and conflict-check against) the latest rev.
    page.get(force=True)
    if page.latest_revision_id != base_revid:
        log.info(
            "Page changed during scoring (rev %s → %s); applying to the new revision.",
            base_revid,
            page.latest_revision_id,
        )

    new_text = apply_wikitext(
        page.text, page_map, rescore=rescore, remove_done=remove_done
    )
    if new_text is None:
        log.info("No changes needed.")
        return

    if dry_run:
        print(new_text)
        return

    summary = "add/update Score column" + (" (rescored)" if rescore else "")
    page.text = new_text
    try:
        # minor for the non-destructive daily add-only run; major when rescoring.
        page.save(summary=summary, minor=not rescore)
        log.info("Page saved.")
    except pywikibot.exceptions.EditConflictError:
        log.warning(
            "Edit conflict on save; page was edited in the final window. "
            "Skipping this run — the next scheduled run will retry."
        )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--rescore",
        action="store_true",
        help="Recompute all scores, even existing ones",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Print result to stdout, do not save"
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="Process at most N rows per section"
    )
    parser.add_argument(
        "--keep-done",
        action="store_true",
        help="Keep rows whose score marks a done action instead of removing them",
    )
    args = parser.parse_args()

    process_page(
        rescore=args.rescore,
        dry_run=args.dry_run,
        limit=args.limit,
        remove_done=not args.keep_done,
    )


if __name__ == "__main__":
    main()
