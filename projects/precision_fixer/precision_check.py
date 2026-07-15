import json
import re
import time
from datetime import datetime
from pathlib import Path
from abc import ABC, abstractmethod

import pywikibot
import requests
from pywikibot import WbTime
from pywikibot.data.api import Request

import shared_lib.change_wikidata as cwd
import shared_lib.constants as wd
from shared_lib.database_handler import DatabaseHandler

API = "https://www.wikidata.org/w/api.php"


site = pywikibot.Site("wikidata", "wikidata")
repo = site.data_repository()

PAGE_TITLE = "User:Difool/precision_check"
WIKI_FILE = Path(__file__).parent / "precision_check_wiki.txt"

# --- Detection --------------------------------------------------------------

MSG = """Hi! When changing a date from year to day precision, you can't keep the same references - they only support the year.
         For example, see {your_edit} and the {bot_revert}. 
         Best practice is to add the day-date as a new value with its own references and mark it preferred, 
         or else remove the year-date entirely before adding the day-date with correct references. Thanks!"""


class FirebirdStatusTracker(DatabaseHandler):

    def __init__(self):
        file_path = Path(__file__).parent / "prec_check.json"
        create_script = Path("schemas/prec_check.sql")
        super().__init__(file_path, create_script)

    def did_revert(self, qid: str, prop: str):
        sql = "SELECT r.ID FROM QIDS r where qid=? and prop=? and bot_rev is not null"
        result = self.execute_query(
            sql,
            (
                qid,
                prop,
            ),
        )
        return len(result) > 0

    def get_not_users(self, limit: int):
        sql = """
                SELECT first ? p.USER_NAME, p.EDIT_DATE, p.QID, p.PROP, p.FAULTY_REV, p.BOT_REV, p.ACOUNT
                FROM GET_NOT_USERS  p
                order by 1
        """
        rows = self.execute_query(sql, (limit,))
        return rows

    def get_revert_qids(self, prop: str, limit: int):
        """Retrieve QIDs that need to be reverted."""

        sql = """
                SELECT FIRST ? QID 
                FROM QIDS 
                WHERE BOT_REV IS NULL AND (ERROR_MSG='' OR ERROR_MSG IS NULL) and prop = ?
        """
        rows = self.execute_query(
            sql,
            (
                limit,
                prop,
            ),
        )
        return rows

    def get_edit_date(self, qid: str, prop: str):
        """Retrieve the edit date for a given QID."""

        sql = "SELECT EDIT_DATE FROM QIDS WHERE QID=? and prop=?"
        rows = self.execute_query(
            sql,
            (
                qid,
                prop,
            ),
        )
        if not rows:
            raise RuntimeError("No record found for QID")
        return rows[0][0]

    def get_parent_rev(self, qid: str, prop: str):
        """Retrieve the parent revision ID for a given QID."""

        sql = "SELECT PARENT_REV FROM QIDS WHERE QID=? and prop=? AND BOT_REV IS NULL AND (ERROR_MSG='' OR ERROR_MSG IS NULL)"
        rows = self.execute_query(
            sql,
            (
                qid,
                prop,
            ),
        )
        if not rows:
            raise RuntimeError("No record found for QID")
        return rows[0][0]

    def get_qids(self):
        """Retrieve all QIDs with their details from the database."""

        sql = """
                SELECT r.QID, r.FAULTY_REV, r.YEAR_DATE, r.DAY_DATE, r.USER_NAME,
                    SUBSTRING(r.EDIT_DATE FROM 1 FOR 10) as EDIT_DATE, r.NR_OF_REVS, r.bot_rev,
                   case when (select first 1 t.edit_date FROM talk_msgs t where t.USER_NAME = r.USER_NAME order by t.EDIT_DATE desc) < '2026' then 'OLD'
                        when (select count(*) from users u where u.user_name = r.user_name and u.IS_IP) > 0 then 'IP'
                        when (select count(*) from users u where u.user_name = r.user_name and u.IS_BLOCKED) > 0 then 'BLOCKED'
                   else (select first 1 t.edit_date FROM talk_msgs t where t.USER_NAME = r.USER_NAME order by t.EDIT_DATE desc) end as notify
                FROM QIDS r 
                where error_msg = '' or error_msg is null
                order by cast(substring(qid from 2) as bigint) 
        """
        rows = self.execute_query(sql)
        return rows

    def set_is_ip(self, user_name):
        sql = "UPDATE users SET is_ip=True where user_name=?"
        self.execute_procedure(sql, (user_name,))

    def set_is_blocked(self, user_name):
        sql = "UPDATE users SET is_blocked=True where user_name=?"
        self.execute_procedure(sql, (user_name,))

    def has(self, qid: str, prop: str):
        """Check if a record for the given QID exists in any table."""

        tables = ["qids", "qerrors"]
        for table in tables:
            if self.has_record(
                table,
                "QID=? and prop=?",
                (
                    qid,
                    prop,
                ),
            ):
                return True
        return False

    def set_bot_edit(self, qid: str, prop: str, bot_rev):
        """Set the bot edit revision for a given QID."""

        sql = "UPDATE qids SET BOT_REV=? WHERE QID=? and prop=?"
        self.execute_procedure(
            sql,
            (
                bot_rev,
                qid,
                prop,
            ),
        )

    def add_talk_msg(self, user_name: str):
        sql = "INSERT INTO talk_msgs (user_name, edit_date) VALUES (?, ?)"

        now_cet = datetime.now()
        edit_date = now_cet.strftime("%Y-%m-%d")

        self.execute_procedure(sql, (user_name, edit_date))

    def add_error(self, qid: str, prop: str, error_msg):
        """Add an error record to the database."""

        sql = "INSERT INTO qerrors (qid, prop, error_msg) VALUES (?, ?, ?)"
        self.execute_procedure(sql, (qid, prop, error_msg))

    def add(
        self,
        qid: str,
        prop: str,
        parent_rev,
        faulty_rev,
        year_date,
        day_date,
        user,
        edit_date,
        year_refs,
        day_refs,
        nr_of_revs,
        error_msg,
    ):
        """Add a record to the database."""

        sql = "INSERT INTO qids (qid, prop, parent_rev, faulty_rev, year_date, day_date, user_name, edit_date, year_refs, day_refs, nr_of_revs, error_msg) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
        self.execute_procedure(
            sql,
            (
                qid,
                prop,
                parent_rev,
                faulty_rev,
                year_date,
                day_date,
                user,
                edit_date,
                year_refs,
                day_refs,
                nr_of_revs,
                error_msg,
            ),
        )


class IdentifierStrategy(ABC):
    @abstractmethod
    def name(self) -> str:
        """Return the name of the identifier strategy."""
        pass

    def claim_has_strategy_ref(self, claim):
        for source in claim.sources:
            if self.property_id() in source:
                return True
            if wd.PID_STATED_IN in source:
                for c in source[wd.PID_STATED_IN]:
                    id = c.getTarget().getID()
                    if id == self.source_qid():  # Trove
                        return True
            if wd.PID_REFERENCE_URL in source:
                for c in source[wd.PID_REFERENCE_URL]:
                    ref = c.getTarget()
                    if self.is_url_strategy_ref(ref):
                        return True
        return False

    def refs_have_strategy_ref(self, refs):
        for ref in refs:
            snaks = ref.get("snaks", {})
            if self.property_id() in snaks:
                return True
            if wd.PID_STATED_IN in snaks:
                for snak in snaks[wd.PID_STATED_IN]:
                    dv = snak.get("datavalue", {})
                    val = dv.get("value", "")
                    if val == self.source_qid():  # Trove
                        return True
            if wd.PID_REFERENCE_URL in snaks:
                for snak in snaks[wd.PID_REFERENCE_URL]:
                    dv = snak.get("datavalue", {})
                    val = dv.get("value", "")
                    if self.is_url_strategy_ref(val):
                        return True
        return False

    @abstractmethod
    def property_id(self) -> str:
        """Return the Wikidata property ID for this identifier."""
        pass

    @abstractmethod
    def source_qid(self) -> str:
        """Return the Wikidata QID for the source (e.g. MUBI)."""
        pass

    @abstractmethod
    def is_url_strategy_ref(self, url: str) -> bool:
        pass


class TroveStrategy(IdentifierStrategy):
    def name(self) -> str:
        return "Trove"

    def property_id(self) -> str:
        return wd.PID_NLA_TROVE_PEOPLE_ID

    def source_qid(self) -> str:
        return wd.QID_TROVE

    def is_url_strategy_ref(self, url: str) -> bool:
        return "trove.nla.gov.au/people/" in url


class FastStrategy(IdentifierStrategy):
    def name(self) -> str:
        return "FAST"

    def property_id(self) -> str:
        return wd.PID_FAST_ID

    def source_qid(self) -> str:
        return wd.QID_FACETED_APPLICATION_OF_SUBJECT_TERMINOLOGY

    def is_url_strategy_ref(self, url: str) -> bool:
        return "worldcat.org/fast/" in url


def get_claim_with_strategy_ref(claims, strategy: IdentifierStrategy):
    res = []
    for claim in claims:
        refs = extract_refs_from_json(claim)
        if strategy.refs_have_strategy_ref(refs):
            res.append(claim)
    if len(res) > 1:
        return None
    if res:
        return res[0]
    else:
        return None


def find_faulty_edits(qid: str, prop: str, current_date_str):
    """
    Find the revision where P569 was changed to the current full date.
    Returns (faulty_rev_id, parent_rev_id) or (None, None).
    """
    revs = []
    params = {
        "action": "query",
        "prop": "revisions",
        "titles": qid,
        "rvprop": "ids|timestamp|user|comment",
        "rvlimit": "500",
    }
    req = Request(site=site, parameters=params)
    data = req.submit()
    pages = data["query"]["pages"]
    search = f"[[Property:{prop}]]: {current_date_str}"
    for pageid, page in pages.items():
        for rev in page["revisions"]:
            comment = rev.get("comment", "")
            if "wbsetclaim-update" in comment and comment.endswith(search):
                revs.append(rev)
    return revs


def resolve_claim_precision_with_strategy_ref(
    item, prop, rev, strategy: IdentifierStrategy
):
    time.sleep(5)
    res = ""
    ent = get_json_snapshot(item, rev)

    claims = ent.get("claims", {})
    if not claims:
        return ""
    p = claims.get(prop, [])
    for c in p:
        is_day = is_year = False
        ptime = c.get("mainsnak", {}).get("datavalue", {}).get("value", {})
        if ptime.get("precision") == 11:
            is_day = True
        if ptime.get("precision") == 9:
            is_year = True

        refs = []
        for ref in c.get("references", []) or []:
            refs.append(ref)

        if strategy.refs_have_strategy_ref(refs):
            if is_day:
                return "day"
            if is_year:
                res = "year"

    return res


def binary_find_faulty_edits(
    item: pywikibot.ItemPage, prop: str, strategy: IdentifierStrategy
):
    """
    Find the revision where P569 changes from year-precision (with Trove ref)
    to day-precision (with Trove ref).
    Returns (faulty_rev, parent_rev) or (None, None).
    """

    # Fetch revisions in chronological order
    params = {
        "action": "query",
        "prop": "revisions",
        "titles": item.title(),
        "rvprop": "ids|timestamp|user|comment",
        "rvlimit": "500",
        "rvdir": "newer",  # oldest → newest
    }
    req = Request(site=site, parameters=params)
    data = req.submit()
    pages = data["query"]["pages"]

    revs = []
    for pageid, page in pages.items():
        revs.extend(page["revisions"])

    if not revs:
        return None

    lo, hi = 0, len(revs) - 1
    faulty_rev, parent_rev = None, None

    while lo <= hi:
        mid = (lo + hi) // 2
        rev = revs[mid]

        print(f"Checking revision at index {mid}, lo={lo}, hi={hi}", end="\r")
        precision = resolve_claim_precision_with_strategy_ref(
            item, prop, rev["revid"], strategy
        )
        print(f"Checking revision at index {mid}, lo={lo}, hi={hi} -> {precision}")

        if precision == "day":
            # Found a 'day' → could be the transition, but check if earlier ones are also 'day'
            faulty_rev = rev
            parent_rev = revs[mid - 1] if mid > 0 else None
            hi = mid - 1  # keep searching left for the *first* 'day'
        else:
            # Still 'empty' or 'year' → transition must be to the right
            lo = mid + 1

    return [faulty_rev]


def right_binary_find_faulty_edits(
    item: pywikibot.ItemPage, prop: str, strategy: IdentifierStrategy
):
    """
    Find the *last* revision where P569 was changed from year-precision (with Trove ref)
    to day-precision (with Trove ref).
    Returns (faulty_rev, parent_rev) or (None, None),
    where each is the full revision dict.
    """

    # Fetch revisions in chronological order
    params = {
        "action": "query",
        "prop": "revisions",
        "titles": item.title(),
        "rvprop": "ids|timestamp|user|comment",
        "rvlimit": "500",
        "rvdir": "newer",  # oldest → newest
    }
    req = Request(site=site, parameters=params)
    data = req.submit()
    pages = data["query"]["pages"]

    revs = []
    for pageid, page in pages.items():
        revs.extend(page["revisions"])

    if not revs:
        return None

    lo, hi = 0, len(revs) - 1
    faulty_rev, parent_rev = None, None

    while lo <= hi:
        mid = (lo + hi) // 2
        rev = revs[mid]

        precision = resolve_claim_precision_with_strategy_ref(
            item, prop, rev["revid"], strategy
        )
        print(f"Checking revision at index {mid}, lo={lo}, hi={hi} -> {precision}")

        if precision == "day":
            # Found a candidate, but keep searching to the right for the *last* occurrence
            faulty_rev = rev
            parent_rev = revs[mid - 1] if mid > 0 else None
            lo = mid + 1
        elif precision == "year":
            # Still year precision, so the faulty change must be to the right
            lo = mid + 1
        else:
            # Not relevant, treat as "before fault" → search left
            hi = mid - 1

    return [faulty_rev]


def modified_binary_find_faulty_edits(
    item: pywikibot.ItemPage, prop: str, strategy: IdentifierStrategy
):
    """
    Find the *last* revision where P569 was changed from year-precision (with Trove ref)
    to day-precision (with Trove ref).
    Returns (faulty_rev, parent_rev) or (None, None),
    where each is the full revision dict.
    """

    # Fetch revisions in chronological order
    params = {
        "action": "query",
        "prop": "revisions",
        "titles": item.title(),
        "rvprop": "ids|timestamp|user|comment",
        "rvlimit": "500",
        "rvdir": "newer",  # oldest → newest
    }
    req = Request(site=site, parameters=params)
    data = req.submit()
    pages = data["query"]["pages"]

    revs = []
    for pageid, page in pages.items():
        revs.extend(page["revisions"])

    if not revs:
        return None

    lo, hi = 0, len(revs) - 1
    faulty_rev, parent_rev = None, None

    while lo <= hi:
        mid = (lo + hi) // 2
        rev = revs[mid]

        print(f"Checking revision at index {mid}, lo={lo}, hi={hi}")
        precision = resolve_claim_precision_with_strategy_ref(
            item, prop, rev["revid"], strategy
        )
        if precision == "day":
            # candidate faulty revision, but keep searching right
            faulty_rev = rev
            parent_rev = revs[mid - 1] if mid > 0 else None
            lo = mid + 1
        elif precision == "year":
            # still year precision, move right
            lo = mid + 1
        else:
            # neither, skip forward
            lo = mid + 1

    return [faulty_rev]


def backwards_find_faulty_edits(
    item: pywikibot.ItemPage, prop: str, strategy: IdentifierStrategy
):
    """
    Find the *last* revision where P569 was changed from year-precision (with Trove ref)
    to day-precision (with Trove ref).
    Returns (faulty_rev, parent_rev) or (None, None),
    where each is the full revision dict.
    """

    # Fetch revisions in chronological order (oldest → newest)
    params = {
        "action": "query",
        "prop": "revisions",
        "titles": item.title(),
        "rvprop": "ids|timestamp|user|comment",
        "rvlimit": "500",
        "rvdir": "newer",
    }
    req = Request(site=site, parameters=params)
    data = req.submit()
    pages = data["query"]["pages"]

    revs = []
    for pageid, page in pages.items():
        revs.extend(page["revisions"])

    if not revs:
        return None

    # Scan backwards: newest → oldest
    faulty_rev, parent_rev = None, None
    prev_val = None

    for i in range(len(revs) - 1, -1, -1):
        rev = revs[i]

        print(f"Checking revision at index {i}", end="\r")
        precision = resolve_claim_precision_with_strategy_ref(
            item, prop, rev["revid"], strategy
        )
        print(f"Checking revision at index {i} -> {precision}")

        if prev_val is None:
            # initialize with last revision (guaranteed "day")
            prev_val = precision
            continue

        if prev_val == "day" and precision == "year":
            # transition found: year → day
            faulty_rev = revs[i + 1]  # the "day" revision
            parent_rev = revs[i]  # the "year" revision
            break

        prev_val = precision

    return [faulty_rev]


# --- Reference extraction ---------------------------------------------------


def extract_refs(entity_json, prop):
    """
    Extract references from entity JSON for a given property.
    Returns a list of reference dicts.
    """
    refs = []
    claims = entity_json.get("claims", {}).get(prop, [])
    for c in claims:
        for ref in c.get("references", []) or []:
            refs.append(ref)
    return refs


# --- Reference comparison ---------------------------------------------------


def refs_equal(ref1, ref2):
    """Check if two references are equal under rules: exact, same external id, same URL."""
    if ref1 == ref2:
        return True

    def extract_ids_urls(ref):
        ids, urls = [], []
        for prop, snaks in ref.get("snaks", {}).items():
            for snak in snaks:
                dv = snak.get("datavalue")
                if not dv:
                    continue
                val = dv.get("value")
                if isinstance(val, str) and val.startswith("http"):
                    urls.append(val)
                elif isinstance(val, str):
                    ids.append(val)
        return ids, urls

    ids1, urls1 = extract_ids_urls(ref1)
    ids2, urls2 = extract_ids_urls(ref2)

    if set(ids1).intersection(ids2):
        return True
    if set(urls1).intersection(urls2):
        return True
    return False


def compare_reference_lists(parent_refs, current_refs):
    """
    Compare references before faulty edit vs current references.
    Require a1=b1..an=bn and n <= m.
    If mismatch -> manual_check.
    """
    # n, m = len(parent_refs), len(current_refs)
    # if n > m:
    #     return {"status": "manual_check", "reason": "Parent refs > current refs"}

    # for i in range(n):
    #     if not refs_equal(parent_refs[i], current_refs[i]):
    #         return {"status": "manual_check", "reason": f"Mismatch at position {i}"}

    # extra_refs = current_refs[n:m]
    return {
        "status": "ok",
        "year_claim_refs": parent_refs,
        # "day_claim_refs": extra_refs,
    }


def extract_refs_from_item(item, prop):
    """Extract references from a live ItemPage object (current entity)."""
    refs = []
    if prop in item.claims:
        for claim in item.claims[prop]:
            refs.extend(claim.sources)  # sources are Reference objects
    return refs


def get_json_snapshot(item, revid):
    return json.loads(item.getOldVersion(revid))


def extract_refs_from_json(claim):
    refs = []
    for ref in claim.get("references", []) or []:
        refs.append(ref)
    return refs


def analyze_item(item, parent_rev, prop, strategy: IdentifierStrategy):

    # Get JSON snapshot for parent and current (latest) revisions
    parent_ent = get_json_snapshot(item, parent_rev)
    current_ent = get_json_snapshot(item, item.latest_revision_id)

    # parent
    parent_claims = parent_ent.get("claims", {}).get(prop, [])
    if len(parent_claims) == 0:
        raise RuntimeError("No claims in parent revision")
    parent_claim = get_claim_with_strategy_ref(parent_claims, strategy)
    if not parent_claim:
        raise RuntimeError(f"No {strategy.name()} claim found in parent revision")
    parent_time = parent_claim.get("mainsnak", {}).get("datavalue", {}).get("value", {})
    if parent_time.get("precision") != 9:
        raise RuntimeError("Parent claim does not have year precision")
    # current
    current_claims = current_ent.get("claims", {}).get(prop, [])
    if len(current_claims) == 0:
        raise RuntimeError("No claims in current revision")
    current_claim = get_claim_with_strategy_ref(current_claims, strategy)
    if not current_claim:
        raise RuntimeError(f"No {strategy.name()} claim found in current revision")
    current_time = (
        current_claim.get("mainsnak", {}).get("datavalue", {}).get("value", {})
    )
    if current_time.get("precision") != 11:
        raise RuntimeError("Current claim does not have day precision")

    parent_refs = extract_refs_from_json(parent_claim)
    current_refs = extract_refs_from_json(current_claim)
    if not strategy.refs_have_strategy_ref(parent_refs):
        raise RuntimeError(f"No {strategy.name()} reference in parent refs")
    if not strategy.refs_have_strategy_ref(current_refs):
        raise RuntimeError(f"No {strategy.name()} reference in current refs")

    result = compare_reference_lists(
        parent_refs, current_refs
    )  # your existing function
    result["ptime"] = parent_time
    result["ctime"] = current_time
    # if result["status"] == "ok":
    #     print(f"{qid}: safe to fix")
    #     print("Year refs:", len(result["year_claim_refs"]))
    #     print("Day refs:", len(result["day_claim_refs"]))
    # else:
    #     raise RuntimeError(f"Manual check needed ({result['reason']})")
    return result


MONTHS = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]


#  wd:Q52155494	Jean Brissaud
#  wd:Q55910518	Léon Mazeaud
#  wd:Q97066773	Walter Charles Alan Ker
#  wd:Q109854556	Alfred Sutro
#  wd:Q52150746	Joseph Gajard
#  wd:Q55944154	Jean-Mar

# Q21539253: -> multiple changes to the date
# Q7794437 -> en wikipedia ref removed
# Q4011595 -> en wikipedia ref removed


def WbTime_to_str(s):
    t = WbTime.fromWikibase(s)
    if t.precision == 9:
        # Year only
        dt = f"{t.year:04d}"
    elif t.precision == 11:
        # Full date with zero-padded month/day
        dt = f"{t.year:04d}-{t.month:02d}-{t.day:02d}"
    else:
        raise RuntimeError("Unexpected precision")
    if t.calendarmodel == "http://www.wikidata.org/entity/Q1985786":
        dt += "J"
    return dt


def determine_precision_rev(
    qid: str, prop: str, strategy: IdentifierStrategy, tracker: FirebirdStatusTracker
):
    """
    Test the precision fixing logic for a given Wikidata item.
    """
    item = pywikibot.ItemPage(repo, qid)
    item.get()  # populate latest revision metadata

    claims = item.claims.get(prop, [])
    if not claims:
        raise RuntimeError(f"No {prop} claims found")

    # if len(claims) > 1:
    #     raise RuntimeError("Multiple claims for P569")

    # claim = claims[0]
    # current_date = claim.getTarget()

    # if not current_date:
    #     raise RuntimeError("No target date for claim")

    # current_date_str = (
    #     f"{current_date.day} {MONTHS[current_date.month-1]} {current_date.year}"
    # )
    # day_precision_date = cwd.Date.create_from_WbTime(current_date)
    # year_precision_date = cwd.Date.create_from_WbTime(current_date)
    # year_precision_date.change_to_year()

    # revs = binary_find_faulty_edits(item, prop)
    revs = backwards_find_faulty_edits(item, prop, strategy)
    # revs = binary_find_faulty_edits(item, prop, strategy)
    if not revs:
        raise RuntimeError("No faulty edits found")
    # take the last one
    rev = revs[-1]
    if not rev:
        raise RuntimeError("No faulty edits found")
    faulty_rev = rev["revid"]
    parent_rev = rev["parentid"]
    user = rev["user"]
    timestamp = rev["timestamp"]
    error_msg = ""
    year_refs = 0
    day_refs = 0

    try:
        analysis_result = analyze_item(item, parent_rev, prop, strategy)
        if "year_claim_refs" in analysis_result:
            year_refs = len(analysis_result["year_claim_refs"])
        else:
            year_refs = 0
        if "day_claim_refs" in analysis_result:
            day_refs = len(analysis_result["day_claim_refs"])
        else:
            day_refs = 0
        year_date = WbTime_to_str(analysis_result["ptime"])
        day_date = WbTime_to_str(analysis_result["ctime"])
    except Exception as e:
        analysis_result = {}
        error_msg = str(e)
        year_date = ""
        day_date = ""

    if error_msg:
        print(error_msg)
    else:
        print("found")

    tracker.add(
        qid,
        prop,
        parent_rev,
        faulty_rev,
        year_date,
        day_date,
        user,
        timestamp,
        year_refs,
        day_refs,
        len(revs),
        error_msg,
    )


def get_retrieved_date(source):
    if wd.PID_RETRIEVED not in source:
        return None
    for claim in source[wd.PID_RETRIEVED]:
        dt = claim.getTarget()
        return dt


def get_reference_urls(source):
    urls = []
    if wd.PID_REFERENCE_URL in source:
        for claim in source[wd.PID_REFERENCE_URL]:
            url = claim.getTarget()
            urls.append(url)
    if wd.PID_WIKIMEDIA_IMPORT_URL in source:
        for claim in source[wd.PID_WIKIMEDIA_IMPORT_URL]:
            url = claim.getTarget()
            urls.append(url)
    return urls


def get_stated_in_ids(source):
    ids = []
    if wd.PID_STATED_IN in source:
        for claim in source[wd.PID_STATED_IN]:
            qid = claim.getTarget().id
            ids.append(qid)
    return ids


def get_wikimedia_ids(source):
    ids = []
    if wd.PID_IMPORTED_FROM_WIKIMEDIA_PROJECT in source:
        for claim in source[wd.PID_IMPORTED_FROM_WIKIMEDIA_PROJECT]:
            qid = claim.getTarget().id
            ids.append(qid)
    return ids


def get_inferred_from(source):
    ids = []
    if wd.PID_INFERRED_FROM in source:
        for claim in source[wd.PID_INFERRED_FROM]:
            qid = claim.getTarget().id
            ids.append(qid)
    return ids


def get_external_ids(source):
    for prop, data in source.items():
        for item in data:
            if item.type != "external-id":
                continue
            value = item.getTarget()
            if not value:
                continue
            yield (prop, value)


def compare_dates(date1, date2):
    # date1 is a WdTime; date2 is a string "YYYY-MM-DDTHH:MM:SSZ"
    d1_str = f"{date1.year:04d}-{date1.month:02d}-{date1.day:02d}T00:00:00Z"
    if d1_str < date2:
        return -1
    elif d1_str > date2:
        return 1
    else:
        return 0


def has_ref_url(year_refs, url):
    for ref in year_refs:
        snaks = ref.get("snaks", {})
        for prop, data in snaks.items():
            if prop != wd.PID_REFERENCE_URL and prop != wd.PID_WIKIMEDIA_IMPORT_URL:
                continue
            for snak in data:
                dv = snak.get("datavalue", {})
                val = dv.get("value", "")
                if val == url:
                    return True
    return False


def has_stated_in_id(year_refs, stated_in):
    for ref in year_refs:
        snaks = ref.get("snaks", {})
        for prop, data in snaks.items():
            if prop != wd.PID_STATED_IN:
                continue
            for snak in data:
                dv = snak.get("datavalue", {})
                val = dv.get("value", "")
                id = val.get("id", "")
                if id == stated_in:
                    return True
    return False


def has_wikimedia_id(year_refs, wikimedia_id):
    for ref in year_refs:
        snaks = ref.get("snaks", {})
        for prop, data in snaks.items():
            if prop != wd.PID_IMPORTED_FROM_WIKIMEDIA_PROJECT:
                continue
            for snak in data:
                dv = snak.get("datavalue", {})
                val = dv.get("value", "")
                id = val.get("id", "")
                if id == wikimedia_id:
                    return True
    return False


def has_inferred_from(year_refs, inf_from):
    for ref in year_refs:
        snaks = ref.get("snaks", {})
        for prop, data in snaks.items():
            if prop != wd.PID_INFERRED_FROM:
                continue
            for snak in data:
                dv = snak.get("datavalue", {})
                val = dv.get("value", "")
                id = val.get("id", "")
                if id == inf_from:
                    return True
    return False


def has_external_id(year_refs, prop: str, ext_id):
    for ref in year_refs:
        snaks = ref.get("snaks", {})
        if prop not in snaks:
            continue
        for snak in snaks[prop]:
            dv = snak.get("datavalue", {})
            val = dv.get("value", "")
            if val == ext_id:
                return True
    return False


def has_ref_url_matching_external_id(year_refs, ext_id):
    for ref in year_refs:
        snaks = ref.get("snaks", {})
        if wd.PID_REFERENCE_URL not in snaks:
            continue
        for snak in snaks[wd.PID_REFERENCE_URL]:
            dv = snak.get("datavalue", {})
            val = dv.get("value", "")
            if ext_id in val:
                return True, val
    return False, None


def is_new_source(year_refs, edit_date, source):
    # source is an ordered dict
    retrieved = get_retrieved_date(source)
    if retrieved and compare_dates(retrieved, edit_date) >= 0:
        return True
    for ref_url in get_reference_urls(source):
        if has_ref_url(year_refs, ref_url):
            return False
    for wiki in get_wikimedia_ids(source):
        if has_wikimedia_id(year_refs, wiki):
            return False
    for stated_in in get_stated_in_ids(source):
        if has_stated_in_id(year_refs, stated_in):
            return False
    for prop, ext_id in get_external_ids(source):
        if has_external_id(year_refs, prop, ext_id):
            return False
        if prop == wd.PID_FAST_ID:
            ref_url = f"http://id.worldcat.org/fast/{ext_id}"
            if has_ref_url(year_refs, ref_url):
                return False
            ref_url = f"https://experimental.worldcat.org/fast/{ext_id}"
            if has_ref_url(year_refs, ref_url):
                return False
        elif prop == wd.PID_VIAF_CLUSTER_ID:
            ref_url = f"https://viaf.org/viaf/{ext_id}/"
            if has_ref_url(year_refs, ref_url):
                return False
        elif prop == wd.PID_DEUTSCHE_BIOGRAPHIE_GND_ID:
            ref_url = f"http://www.deutsche-biographie.de/pnd{ext_id}.html"
            if has_ref_url(year_refs, ref_url):
                return False
        elif prop == wd.PID_BIBLIOTHEQUE_NATIONALE_DE_FRANCE_ID:
            ref_url = f"http://data.bnf.fr/ark:/12148/cb{ext_id}"
            if has_ref_url(year_refs, ref_url):
                return False
            ref_url = f"https://catalogue.bnf.fr/ark:/12148/cb{ext_id}"
            if has_ref_url(year_refs, ref_url):
                return False
            ref_url = f"http://catalogue.bnf.fr/ark:/12148/cb{ext_id}"
            if has_ref_url(year_refs, ref_url):
                return False
        elif prop == wd.PID_CERL_THESAURUS_ID:
            ref_url = f"http://thesaurus.cerl.org/record/{ext_id}"
            if has_ref_url(year_refs, ref_url):
                return False
        elif prop == wd.PID_MUTUALART_ARTIST_ID:
            ref_url = f"https://www.mutualart.com/Artist/Wang-Xuetao/{ext_id}"
            if has_ref_url(year_refs, ref_url):
                return False
            ref_url = f"https://www.mutualart.com/Artist/Albert-Unseld/{ext_id}"
            if has_ref_url(year_refs, ref_url):
                return False
            ref_url = f"https://www.mutualart.com/Artist/Miklos-Farkashazy/{ext_id}"
            if has_ref_url(year_refs, ref_url):
                return False
            ref_url = f"https://www.mutualart.com/Artist/Edith-Lawrence/{ext_id}"
            if has_ref_url(year_refs, ref_url):
                return False

        elif prop == "P5597":
            ref_url = f"http://www.artcyclopedia.com/artists/{ext_id}.html"
            if has_ref_url(year_refs, ref_url):
                return False
        elif prop == "P7128":
            ref_url = f"https://research.frick.org/directory/detail/{ext_id}"
            if has_ref_url(year_refs, ref_url):
                return False
        elif prop == wd.PID_NATIONAL_LIBRARY_OF_SPAIN_ID:
            ref_url = f"http://datos.bne.es/persona/{ext_id}.html"
            if has_ref_url(year_refs, ref_url):
                return False
        elif prop == wd.PID_RKDARTISTS_ID:
            ref_url = f"https://rkd.nl/explore/artists/{ext_id}"
            if has_ref_url(year_refs, ref_url):
                return False
            ref_url = f"https://research.rkd.nl/nl/detail/https%3A%2f%2fdata.rkd.nl%2fartists%2f{ext_id}"
            if has_ref_url(year_refs, ref_url):
                return False
        elif prop == wd.PID_PERSEE_AUTHOR_ID:
            ref_url = f"http://www.persee.fr/authority/{ext_id}"
            if has_ref_url(year_refs, ref_url):
                return False
        elif prop == wd.PID_NL_CR_AUT_ID:
            ref_url = f"https://aleph.nkp.cz/F/?func=find-c&local_base=aut&ccl_term=ica={ext_id}&CON_LNG=ENG"
            if has_ref_url(year_refs, ref_url):
                return False
        elif prop == wd.PID_SELIBR_ID:
            ref_url = f"https://libris.kb.se/auth/{ext_id}"
            if has_ref_url(year_refs, ref_url):
                return False
        elif prop == wd.PID_NLA_TROVE_PEOPLE_ID:
            ref_url = f"http://trove.nla.gov.au/people/{ext_id}?q&c=people"
            if has_ref_url(year_refs, ref_url):
                return False
            ref_url = f"https://trove.nla.gov.au/people/{ext_id}"
            if has_ref_url(year_refs, ref_url):
                return False
        elif prop == wd.PID_BVMC_PERSON_ID:
            ref_url = f"http://data.cervantesvirtual.com/person/{ext_id}"
            if has_ref_url(year_refs, ref_url):
                return False
        elif prop == wd.PID_NUKAT_ID:
            ref_url = f"https://wikidata-externalid-url.toolforge.org/?p=1207&url_prefix=http://nukat.edu.pl/aut/&id={ext_id}"
            if has_ref_url(year_refs, ref_url):
                return False
        elif prop == wd.PID_OPEN_LIBRARY_ID:
            ref_url = f"https://openlibrary.org/works/{ext_id}"
            if has_ref_url(year_refs, ref_url):
                return False
            ref_url = f"https://openlibrary.org/authors/{ext_id}/John_Edmunds"
            if has_ref_url(year_refs, ref_url):
                return False
            ref_url = f"https://openlibrary.org/authors/{ext_id}/Daniel_March"
            if has_ref_url(year_refs, ref_url):
                return False
            ref_url = f"https://openlibrary.org/authors/{ext_id}/Bruno_Weil"
            if has_ref_url(year_refs, ref_url):
                return False

        elif prop == "P5882":
            ref_url = f"https://www.muziekweb.nl/Link/{ext_id}/"
            if has_ref_url(year_refs, ref_url):
                return False
        elif prop == wd.PID_DESIGN__ART_AUSTRALIA_ONLINE_ID:
            ref_url = f"https://www.daao.org.au/bio/{ext_id}"
            if has_ref_url(year_refs, ref_url):
                return False
        elif prop == wd.PID_ANGELICUM_ID:
            ref_url = f"https://pust.urbe.it/cgi-bin/koha/opac-authoritiesdetail.pl?authid={ext_id}"
            if has_ref_url(year_refs, ref_url):
                return False
            ref_url = f"https://pust.urbe.it/cgi-bin/koha/opac-authoritiesdetail.pl?marc=1&authid={ext_id}"
            if has_ref_url(year_refs, ref_url):
                return False
        elif prop == wd.PID_AUSTRALIAN_WOMENS_REGISTER_ID:
            ref_url = f"http://www.womenaustralia.info/biogs/{ext_id}.htm"
            if has_ref_url(year_refs, ref_url):
                return False
        elif prop == wd.PID_PROJECT_GUTENBERG_AUTHOR_ID:
            ref_url = f"https://www.gutenberg.org/ebooks/author/{ext_id}"
            if has_ref_url(year_refs, ref_url):
                return False
        elif prop == wd.PID_LIEDERNET_COMPOSER_ID:
            ref_url = (
                f"https://www.lieder.net/lieder/get_settings.html?ComposerId={ext_id}"
            )
            if has_ref_url(year_refs, ref_url):
                return False
        elif prop == wd.PID_AMERICAN_ACADEMY_IN_ROME_ID:
            ref_url = f"https://library.aarome.org/cgi-bin/koha/opac-authoritiesdetail.pl?marc=1&authid={ext_id}"
            if has_ref_url(year_refs, ref_url):
                return False
        elif prop == wd.PID_UNION_LIST_OF_ARTIST_NAMES_ID:
            ref_url = f"http://www.getty.edu/vow/ULANFullDisplay?find=&role=&nation=&subjectid={ext_id}"
            if has_ref_url(year_refs, ref_url):
                return False
        elif prop == wd.PID_THE_PEERAGE_PERSON_ID:
            ref_url = f"http://www.thepeerage.com/{ext_id}"
            if has_ref_url(year_refs, ref_url):
                return False
        elif prop == wd.PID_UNIVERSITY_OF_BARCELONA_AUTHORITY_ID_FORMER_SCHEME:
            ref_url = (
                f"https://crai.ub.edu/sites/default/files/autoritats/permanent/{ext_id}"
            )
            if has_ref_url(year_refs, ref_url):
                return False
        elif prop == wd.PID_PLWABN_ID:
            ref_url = f"http://mak.bn.org.pl/cgi-bin/KHW/makwww.exe?BM=1&NU=1&IM=4&WI={ext_id}"
            if has_ref_url(year_refs, ref_url):
                return False
        elif prop == wd.PID_AKL_ONLINE_ARTIST_ID:
            ref_url = f"https://www.degruyter.com/view/AKL/_{ext_id}"
            if has_ref_url(year_refs, ref_url):
                return False
        elif prop == wd.PID_AGORHA_PERSONINSTITUTION_ID:
            ref_url = f"http://www.purl.org/inha/agorha/002/{ext_id}"
            if has_ref_url(year_refs, ref_url):
                return False
        elif prop == wd.PID_ARTNET_ARTIST_ID:
            ref_url = f"http://www.artnet.com/artists/{ext_id}"
            if has_ref_url(year_refs, ref_url):
                return False
        elif prop == wd.PID_BHL_CREATOR_ID:
            ref_url = f"https://www.biodiversitylibrary.org/creator/{ext_id}"
            if has_ref_url(year_refs, ref_url):
                return False
        elif prop == wd.PID_INVALUABLECOM_PERSON_ID:
            ref_url = (
                f"https://www.invaluable.com/features/viewArtist.cfm?artistRef={ext_id}"
            )
            if has_ref_url(year_refs, ref_url):
                return False
        elif prop == wd.PID_KUNSTINDEKS_DANMARK_ARTIST_ID:
            ref_url = f"https://www.kulturarv.dk/kid/VisKunstner.do?kunstnerId={ext_id}"
            if has_ref_url(year_refs, ref_url):
                return False
        elif prop == wd.PID_HYMNARY_AUTHOR_ID:
            ref_url = f"https://hymnary.org/person/{ext_id}"
            if has_ref_url(year_refs, ref_url):
                return False
        elif prop == wd.PID_HISTORY_OF_PARLIAMENT_ID:
            ref_url = f"http://www.historyofparliamentonline.org/volume/{ext_id}"
            if has_ref_url(year_refs, ref_url):
                return False
        elif prop == wd.PID_MUSEE_DORSAY_ARTIST_OR_PERSONALITY_ID:
            ref_url = f"http://www.musee-orsay.fr/fr/espace-professionnels/professionnels/chercheurs/rech-rec-art-home/notice-artiste.html?nnumid={ext_id}"
            if has_ref_url(year_refs, ref_url):
                return False
        elif prop == wd.PID_RIJKSMUSEUM_RESEARCH_LIBRARY_AUTHORITY_ID:
            ref_url = f"https://library.rijksmuseum.nl/cgi-bin/koha/opac-authoritiesdetail.pl?marc=1&authid={ext_id}"
            if has_ref_url(year_refs, ref_url):
                return False
        elif prop == wd.PID_PONTIFICIA_UNIVERSITA_DELLA_SANTA_CROCE_ID:
            ref_url = f"http://catalogo.pusc.it/auth/{ext_id}"
            if has_ref_url(year_refs, ref_url):
                return False
        elif prop == "P723":
            ref_url = f"http://www.dbnl.org/auteurs/auteur.php?id={ext_id}"
            if has_ref_url(year_refs, ref_url):
                return False
        elif prop == wd.PID_AUSTRIAN_BIOGRAPHICAL_ENCYCLOPEDIA_ID:
            ref_url = f"https://www.biographien.ac.at/oebl/oebl_{ext_id}.xml"
            if has_ref_url(year_refs, ref_url):
                return False
        elif prop == wd.PID_BENEZIT_ID:
            ref_url = f"http://oxfordindex.oup.com/view/10.1093/benz/9780199773787.article.{ext_id}"
            if has_ref_url(year_refs, ref_url):
                return False
        elif prop == "P2977":
            ref_url = f"http://www.lordbyron.org/persRec.php?&selectPerson={ext_id}"
            if has_ref_url(year_refs, ref_url):
                return False
        elif prop == wd.PID_MINNEAPOLIS_INSTITUTE_OF_ART_CONSTITUENT_ID:
            ref_url = f"https://collections.artsmia.org/people/{ext_id}"
            if has_ref_url(year_refs, ref_url):
                return False
        elif prop == wd.PID_BNB_PERSON_ID_OBSOLETE:
            ref_url = f"http://bnb.data.bl.uk/id/person/{ext_id}"
            if has_ref_url(year_refs, ref_url):
                return False
        elif prop == wd.PID_ENTOMOLOGISTS_OF_THE_WORLD_ID:
            ref_url = (
                f"http://sdei.senckenberg.de/biographies/information.php?id={ext_id}"
            )
            if has_ref_url(year_refs, ref_url):
                return False

    for prop, ext_id in get_external_ids(source):
        is_match, ref_url = has_ref_url_matching_external_id(year_refs, ext_id)
        if is_match:
            raise RuntimeError(
                f"Possible match via external id in URL: {prop} {ext_id} <-> {ref_url}"
            )
    for inf_from in get_inferred_from(source):
        if has_inferred_from(year_refs, inf_from):
            return False

    # no matches found; apparently a new source
    return True


def revert_edit(
    qid: str,
    prop: str,
    parent_rev,
    edit_date,
    strategy: IdentifierStrategy,
    tracker: FirebirdStatusTracker,
    test: bool = True,
):
    if tracker.did_revert(qid, prop):
        raise RuntimeError("already done")
    item = pywikibot.ItemPage(repo, qid)
    item.get()  # populate latest revision metadata

    claims = item.claims.get(prop, [])
    if not claims:
        raise RuntimeError(f"No {prop} claims found")

    found_claims = []
    for claim in claims:
        if strategy.claim_has_strategy_ref(claim):
            found_claims.append(claim)
    if len(found_claims) != 1:
        raise RuntimeError(f"Multiple {prop} claims found")

    claim = found_claims[0]

    analysis_result = analyze_item(item, parent_rev, prop, strategy)
    if not analysis_result:
        raise RuntimeError("Analysis failed")

    # year_refs = len(analysis_result["year_claim_refs"])
    # day_refs = len(analysis_result["day_claim_refs"])

    s = analysis_result["ptime"]
    if not s or type(s) != dict:
        raise RuntimeError("No ptime in analysis result")
    year_date = WbTime.fromWikibase(s)
    s = analysis_result["ctime"]
    if not s or type(s) != dict:
        raise RuntimeError("No ctime in analysis result")
    day_date = WbTime.fromWikibase(s)

    page = cwd.WikiDataPage(item, test=test)
    page.summary = "Reverted: user set day precision on referenced claim"

    if prop == wd.PID_DATE_OF_BIRTH:
        date_class = cwd.DateOfBirth
    elif prop == wd.PID_DATE_OF_DEATH:
        date_class = cwd.DateOfDeath
    else:
        raise RuntimeError("Unsupported property")

    config = cwd.StatementConfig()
    config.only_add = True
    day_st = date_class(cwd.Date.create_from_WbTime(day_date), config=config)
    page.add_statement(day_st)

    config = cwd.StatementConfig()
    config.claim = claim
    config.remove_preferred = True
    year_st = date_class(cwd.Date.create_from_WbTime(year_date), config=config)
    page.add_statement(year_st)

    count = 0

    def move_day_refs(source, idx):
        nonlocal count
        b = is_new_source(analysis_result["year_claim_refs"], edit_date, source)
        if b:
            count = count + 1
        return b

    page.move_references(year_st, day_st, move_day_refs)
    page.check_date_statements()
    page.apply()
    print(f"Applied changes for {qid}")

    if not test:
        tracker.set_bot_edit(qid, prop, item.latest_revision_id)

    return count


def revert_qid(
    qid: str,
    prop: str,
    strategy: IdentifierStrategy,
    tracker: FirebirdStatusTracker,
    test: bool = True,
):
    parent_rev = tracker.get_parent_rev(qid, prop)
    edit_date = tracker.get_edit_date(qid, prop)
    revert_edit(qid, prop, parent_rev, edit_date, strategy, tracker, test=test)


def ask_revert_qid(
    qid: str, prop: str, strategy: IdentifierStrategy, tracker: FirebirdStatusTracker
):
    revert_qid(qid, prop, strategy, tracker, test=True)
    if input(f"Revert {qid}? (y/n): ").lower() == "y":
        revert_qid(qid, prop, strategy, tracker, test=False)


def ask_revert_iterate(
    prop: str,
    limit,
    ask: bool,
    strategy: IdentifierStrategy,
    tracker: FirebirdStatusTracker,
):
    rows = tracker.get_revert_qids(prop, limit)
    for row in rows:
        qid = row[0]
        parent_rev = tracker.get_parent_rev(qid, prop)
        edit_date = tracker.get_edit_date(qid, prop)
        try:
            if ask:
                count = revert_edit(
                    qid, prop, parent_rev, edit_date, strategy, tracker, test=True
                )
                print(f"Proposed revert for {qid}, {count} sources moved")
                if (count == 0) or (input(f"Revert {qid}? (y/n): ").lower() == "y"):
                    revert_edit(
                        qid, prop, parent_rev, edit_date, strategy, tracker, test=False
                    )
            else:
                revert_edit(
                    qid, prop, parent_rev, edit_date, strategy, tracker, test=False
                )
        except Exception as e:
            print(f"Error reverting {qid}: {e}")


def is_blocked(user):
    headers = {"User-Agent": "DifoolBot (https://www.wikidata.org/wiki/User:DifoolBot)"}
    r = requests.get(
        API,
        params={"action": "query", "list": "blocks", "bkusers": user, "format": "json"},
        headers=headers,
    )
    r.raise_for_status()
    j = r.json()
    return bool(j["query"]["blocks"])


def is_ip(user):
    return re.match(r"^\d{1,3}(\.\d{1,3}){3}$", user) or re.match(
        r"^([0-9a-fA-F]{0,4}:){2,7}[0-9a-fA-F]{0,4}$", user
    )


def is_masked_ip(user):
    return user.startswith("~") and re.match(r"^~\d{4}-\d+-\d+$", user)


def notify_user(user_name, qid, faulty_rev, bot_rev, tracker: FirebirdStatusTracker):
    # user_name = "Difool"
    user = pywikibot.User(site, user_name)
    talk_page = user.getUserTalkPage()

    faulty_url = (
        f"https://www.wikidata.org/w/index.php?title={qid}&diff=prev&oldid={faulty_rev}"
    )
    faulty_link = f"[{faulty_url} your edit]"
    bot_url = (
        f"https://www.wikidata.org/w/index.php?title={qid}&diff=prev&oldid={bot_rev}"
    )
    bot_link = f"[{bot_url} bot's correction]"
    message = (
        "\n\n== Date precision changes with references ==\n\n"
        + MSG.format(your_edit=faulty_link, bot_revert=bot_link)
        + "\n\n(This is an automatic message generated by a bot to explain the correction.) ~~~~"
    )
    message = message.replace("    ", " ")
    message = message.replace("   ", " ")
    message = message.replace("  ", " ")
    message = message.replace("  ", " ")
    message = message.replace("\n ", "\n")

    talk_page.text += message
    talk_page.save(summary="Posting guidance about date precision and references")

    tracker.add_talk_msg(user_name)


def notify_users(limit, tracker: FirebirdStatusTracker):
    rows = tracker.get_not_users(limit)
    for row in rows:
        user_name, edit_date, qid, prop, faulty_rev, bot_rev, acount = row
        if is_ip(user_name) or is_masked_ip(user_name):
            tracker.set_is_ip(user_name)
        elif is_blocked(user_name):
            tracker.set_is_blocked(user_name)
        else:
            notify_user(user_name, qid, faulty_rev, bot_rev, tracker)


def iterate_text_file(
    prop: str, strategy: IdentifierStrategy, tracker: FirebirdStatusTracker
):
    # load the file items.txt and process each QID
    # with open("projects\\precision_fixer\\items.txt", "r") as f:

    # subdirectory = "precision_fixer"
    # file_name = "items.txt"
    # file_path = os.path.join(subdirectory, file_name)

    with open(
        "D:\\python\\wikidata\\projects\\precision_fixer\\items.txt",
        "r",
        encoding="utf-8",
    ) as f:
        for line in f:
            qid = line.strip()
            if qid:
                if tracker.has(qid, prop):
                    continue
                try:
                    determine_precision_rev(qid, prop, strategy, tracker)
                except Exception as e:
                    tracker.add_error(qid, prop, str(e))
                    print(f"Error processing {qid}: {e}")


def make_wikitext():
    tracker = FirebirdStatusTracker()

    heading = ""
    header = '\n{| class="wikitable sortable" style="vertical-align:bottom;"\n|-\n! QID\n! Year-date\n! Day date\n! Edit\n! User\n! Date of edit\n! Revert\n! Notification'
    body = ""
    # item, year-date, edit performing the change to day-date, day-date, user performing the edit, date of the edit, date of the revert, notification to the user [if not already notified])
    line = "\n|-\n| {{{{Q|{qid}}}}}\n| {year_date}\n| {day_date}\n| {edit}\n| {user}\n| {edit_date}\n| {bot_link}\n| {notification}"
    for row in tracker.get_qids():
        (
            qid,
            faulty_rev,
            year_date,
            day_date,
            user_name,
            edit_date,
            nr_of_revs,
            bot_rev,
            notify,
        ) = row
        if faulty_rev:
            faulty_url = f"https://www.wikidata.org/w/index.php?title={qid}&diff=prev&oldid={faulty_rev}"
            faulty_link = f"[{faulty_url} Edit]"
        else:
            faulty_link = ""
        if bot_rev:
            bot_url = f"https://www.wikidata.org/w/index.php?title={qid}&diff=prev&oldid={bot_rev}"
            bot_link = f"[{bot_url} Revert]"
        else:
            bot_link = ""

        userlink = f"[[User:{user_name}|{user_name}]]"
        if notify == "IP":
            notification = "IP"
        elif notify == "BLOCKED":
            notification = "Blocked"
        elif notify == "OLD":
            notification = "Already done"
        elif notify:
            notification = "Yes"
        else:
            notification = "No"

        body = body + line.format(
            qid=qid,
            year_date=year_date,
            day_date=day_date,
            edit=faulty_link,
            user=userlink,
            edit_date=edit_date,
            # nr_of_revs=nr_of_revs,
            bot_link=bot_link,
            notification=notification,
        )
    footer = "\n|}"
    wikitext = f"{heading}{header}{body}{footer}"

    return wikitext


def write_to_file(wikitext) -> None:
    with open(WIKI_FILE, "w", encoding="utf-8") as outfile:
        outfile.write(wikitext)


def write_to_wiki(wikitext):
    # with open(WIKI_FILE, "w", encoding="utf-8") as outfile:
    #     outfile.write(wikitext)
    # return
    if not wikitext:
        return
    site = pywikibot.Site("wikidata", "wikidata")
    page = pywikibot.Page(site, PAGE_TITLE)
    page.text = wikitext
    page.save(summary="upd", minor=False)


if __name__ == "__main__":
    pid = wd.PID_DATE_OF_DEATH
    strategy = FastStrategy()
    tracker = FirebirdStatusTracker()

    # iterate_text_file(pid, strategy=strategy, tracker=tracker)
    # ask_revert_qid("Q5591408", wd.PID_DATE_OF_BIRTH, FirebirdStatusTracker())
    ask_revert_iterate(pid, 2000, ask=False, strategy=strategy, tracker=tracker)
    # notify_users(300, FirebirdStatusTracker())
    # revert_iterate(FirebirdStatusTracker(), test=False)
    # precision_fix("Q25349796", wd.PID_DATE_OF_BIRTH, FirebirdStatusTracker())
    # write_to_wiki(make_wikitext())
    # write_to_file(make_wikitext())
