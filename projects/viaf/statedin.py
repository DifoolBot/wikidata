import urllib
import json
import os.path
import re
import requests
import logging

WD = "http://www.wikidata.org/entity/"
WDQS_ENDPOINT = "https://query.wikidata.org/sparql"
READ_TIMEOUT = 60  # sec

PID_REFERENCE_URL = "P854"
PID_RETRIEVED = "P813"
PID_STATED_IN = "P248"
PID_ARCHIVE_URL = "P1065"
PID_ARCHIVE_DATE = "P2960"

PID_AKL_ONLINE_ARTIST_ID = "P4432"
PID_ARTNET_ARTIST_ID = "P3782"
PID_BENEZIT_ID = "P2843"
PID_BHCL_UUID = "P9037"
PID_BIBLIOTHEQUE_NATIONALE_DE_FRANCE_ID = "P268"
PID_BIOGRAPHIE_NATIONALE_DE_BELGIQUE_ID = "P6234"
PID_BRITISH_MUSEUM_PERSON_OR_INSTITUTION_ID = "P1711"
PID_CERL_THESAURUS_ID = "P1871"
PID_CLARA_ID = "P1615"
PID_CONOR_SI_ID = "P1280"
PID_DEUTSCHE_BIOGRAPHIE_GND_ID = "P7902"
PID_DIGITALE_BIBLIOTHEEK_VOOR_DE_NEDERLANDSE_LETTEREN_AUTHOR_ID = "P723"
PID_FIND_A_GRAVE_MEMORIAL_ID = "P535"
PID_GND_ID = "P227"
PID_HATHITRUST_ID = "P1844"
PID_HDS_ID = "P902"
PID_IDREF_ID = "P269"
PID_INTERNET_ARCHIVE_ID = "P724"
PID_INVALUABLE_COM_PERSON_ID = "P4927"
PID_ISNI = "P213"
PID_LIBRARY_OF_CONGRESS_CONTROL_NUMBER_LCCN_BIBLIOGRAPHIC = "P1144"
PID_LIBRIS_URI = "P5587"
PID_MUSEUM_OF_MODERN_ART_ARTIST_ID = "P2174"
PID_NATIONAL_GALLERY_OF_ART_ARTIST_ID = "P2252"
PID_NATIONALE_THESAURUS_VOOR_AUTEURSNAMEN_ID = "P1006"
PID_NL_CR_AUT_ID = "P691"
PID_NLA_TROVE_PEOPLE_ID = "P1315"
PID_NUKAT_ID = "P1207"
PID_OCLC_CONTROL_NUMBER = "P243"
PID_OPEN_LIBRARY_ID = "P648"
PID_PLWABN_ID = "P7293"
PID_RISM_ID = "P5504"
PID_RKDARTISTS_ID = "P650"
PID_SFMOMA_ARTIST_ID = "P4936"
PID_TRECCANI_ID = "P3365"
PID_UNION_LIST_OF_ARTIST_NAMES_ID = "P245"
PID_VIAF_ID = "P214"
PID_X_POST_ID = "P5933"
PID_X_USERNAME = "P2002"

QID_ARTNET = "Q266566"
QID_BIOGRAPHIE_NATIONALE_DE_BELGIQUE = "Q2728291"
QID_BNF_AUTHORITIES = "Q19938912"
QID_BRITISH_MUSEUM_PERSON_INSTITUTION_THESAURUS = "Q18785969"
QID_CLARA = "Q18558540"
QID_CZECH_NATIONAL_AUTHORITY_DATABASE = "Q13550863"
QID_DIGITAL_LIBRARY = "Q212805"
QID_DUTCH_NATIONAL_THESAURUS_FOR_AUTHOR_NAMES = "Q104787839"
QID_INVALUABLE = "Q50813730"
QID_KB_NATIONAL_LIBRARY_OF_THE_NETHERLANDS = "Q1526131"
QID_NATIONAL_LIBRARY_OF_SWEDEN = "Q953058"
QID_NETHERLANDS_INSTITUTE_FOR_ART_HISTORY = "Q758610"
QID_NUKAT = "Q11789729"
QID_OPEN_LIBRARY = "Q1201876"
QID_RKDARTISTS = "Q17299517"
QID_SAN_FRANCISCO_MUSEUM_OF_MODERN_ART_ONLINE_COLLECTION = "Q84575091"
QID_SUDOC = "Q2597810"
QID_TROVE = "Q18609226"
QID_UNION_LIST_OF_ARTIST_NAMES = "Q2494649"


TOOLFORGE_PATTERN = "^https?:\\/\\/wikidata-externalid-url\\.toolforge\\.org\\/\\?p=([0-9]+)&url_prefix=(.*)&id=(.*)$"

STATED_IN_FILE = "stated_in.json"

logger = logging.getLogger("splitrefs")


def query_wdqs(query: str):
    response = requests.get(
        WDQS_ENDPOINT, params={"query": query, "format": "json"}, timeout=READ_TIMEOUT
    )
    payload = response.json()
    return payload["results"]["bindings"]


def remove_start_text(input_string: str, start_text: str) -> str:
    """
    Removes the specified start_text from the input_string if it exists at the beginning.
    """
    if input_string.startswith(start_text):
        return input_string[len(start_text) :]
    else:
        return input_string


def is_simple_regex(pattern: str) -> bool:
    # Check for exactly one () group
    if len(re.findall(r"\([^)]*\)", pattern)) != 1:
        return False

    # Ensure no * or + outside the group
    outside_group = re.sub(r"\([^)]*\)", "", pattern)
    if re.search(r"[*+]", outside_group):
        return False

    return True


class KeepURLStrategy:
    def keep_url(self, pid: str, pattern: str) -> bool:
        pass


class CompiledPattern:
    """
    A class to represent a compiled pattern for matching URLs and extracting external IDs.

    Attributes:
        pid (str): The property ID associated with the pattern.
        pattern (str): The regex pattern to match URLs.
        compiled_pattern (Pattern): The compiled regex pattern object.
        repl (str): The replacement string used for extracting the ID.
        keep_url (bool): A flag indicating whether to keep the reference URL.

    Methods:
        match(search_url: str): Matches the URL against the compiled pattern
        and extracts the external ID if a match is found.
    """

    def __init__(self, pid: str, pattern: str, compiled_pattern, repl: str, keep_url):
        self.pid = pid
        self.pattern = pattern
        self.compiled_pattern = compiled_pattern
        self.repl = repl
        self.keep_url = keep_url

    def match(self, search_url: str):
        """
        Matches the URL against the compiled pattern and extracts the ID if a match is found.

        Args:
            search_url (str): The URL to be matched against the pattern.

        Returns:
            tuple: A tuple containing the PID and the extracted external ID if a match is found,
            or None if no match is found.
        """
        match = self.compiled_pattern.search(search_url)
        if not match:
            return None

        if self.repl:
            external_id = self.compiled_pattern.sub(self.repl, search_url)
        else:
            # for example, P7003 has 2 () groups; we don't know how to combine them into an id, so skip
            groups = match.groups()
            if len(groups) != 1:
                start, end = match.span(1)
                for i in range(2, len(groups) + 1):
                    group_start, group_end = match.span(i)

                    if (group_start == -1) and (group_end == -1):
                        continue

                    if not (start <= group_start <= end and start <= group_end <= end):
                        raise RuntimeError(
                            f"Match with {self.pid}, but multiple groups; url={search_url}"
                        )

                logger.warning(
                    f"Accepting {self.pid}, with multiple groups; url={search_url}"
                )

            external_id = match.group(1)

        return self.pid, external_id


class ToolforgePattern:

    def __init__(self):
        self.pid = None
        self.keep_url = False
        self.compiled_pattern = re.compile(
            TOOLFORGE_PATTERN,
            re.IGNORECASE,
        )

    def match(self, search_url: str) -> bool:
        match = self.compiled_pattern.search(search_url)
        if not match:
            return None

        pid = "P" + match.group(1)
        external_id = match.group(3)

        return pid, external_id


class StatedIn:
    """
    A class to handle operations related to 'stated in' values for PIDs.
    """

    def __init__(self):
        self.pid_dict, self.parsed_list = self.load()
        self.keep_url_strategy = None

    def get_stated_in_from_pid(self, pid: str) -> str | None:
        """Returns the applicable 'stated in' value for a given PID"""
        if pid in self.pid_dict:
            stated_in, __ = self.pid_dict[pid]
            return stated_in
        else:
            return None

    def is_id_pid(self, pid: str) -> bool:
        """Returns True if the identifier is a PID that the class recognizes"""
        return pid in self.pid_dict

    def get_stated_in_qids(self):
        """Returns a set with all applicable 'stated in' values for the PIDs that the class recognizes"""
        res = set()
        for p in self.pid_dict:
            stated_in, __ = p
            res.add(stated_in)
        return res

    def get_stated_in_from_url(self, url: str) -> str | None:
        """
        Extracts the applicable 'stated in' value from a given URL.

        This function searches for IDs within the URL and retrieves the
        'stated in' value if a single match is found. It raises an error
        if multiple matches are found.

        Args:
            url (str): The URL to search for 'stated in' values.

        Returns:
            str: The 'stated in' value if a single match is found, or
            None if no match is found.
        """
        found_list = self.extract_ids_from_url(url)
        if not found_list:
            return None

        if len(found_list) != 1:
            raise RuntimeError(f"get_stated_in_from_url: multiple results for {url}")

        pid, stated_in, external_id, keep_url = found_list[0]
        return stated_in

    def is_single_stated_in(self, pid: str, stated_in_set) -> bool:
        """
        Determines if a set of 'stated in' values can be considered as a single value for the given PID.

        This function checks if the given PID has a single valid 'stated in' value
        by adjusting the stated_in_set based on specific conditions for different PIDs.

        Args:
            pid (str): The property ID to check.
            stated_in_set (set): The set of 'stated in' values to validate.

        Returns:
            bool: True if there is only one valid 'stated in' value, False otherwise.
        """

        # remove 'stated in' values that can be ignored for specific PIDs
        if pid == PID_RKDARTISTS_ID:
            stated_in_set.remove(QID_NETHERLANDS_INSTITUTE_FOR_ART_HISTORY)
        if pid == PID_NATIONALE_THESAURUS_VOOR_AUTEURSNAMEN_ID:
            stated_in_set.remove(QID_DUTCH_NATIONAL_THESAURUS_FOR_AUTHOR_NAMES)
            stated_in_set.remove(QID_KB_NATIONAL_LIBRARY_OF_THE_NETHERLANDS)
        if pid == PID_DIGITALE_BIBLIOTHEEK_VOOR_DE_NEDERLANDSE_LETTEREN_AUTHOR_ID:
            stated_in_set.remove(QID_DIGITAL_LIBRARY)
        if pid == PID_IDREF_ID:
            stated_in_set.remove(QID_SUDOC)
        if pid == PID_LIBRIS_URI:
            stated_in_set.remove(QID_NATIONAL_LIBRARY_OF_SWEDEN)

        applicable_stated_in = self.get_stated_in_from_pid(pid)
        if applicable_stated_in:
            stated_in_set.add(applicable_stated_in)

        return len(stated_in_set) <= 1

    def get_id_from_reference_url(self, source):
        """
        Extracts the ID from a reference URL within the given source (a reference that is an ordered dictionary).

        This function attempts to find and return the ID from the reference URL
        provided in the source. It handles cases with multiple "stated in" values
        and raises errors when necessary.

        Args:
            source (dict): The source containing potential reference URLs and 'stated in' values.

        Returns:
            tuple: A tuple containing the PID, stated_in, and external ID if a valid match is found,
            or None if no match is found.
        """

        if PID_REFERENCE_URL not in source:
            return None
        if len(source[PID_REFERENCE_URL]) > 1:
            return None
        url = source[PID_REFERENCE_URL][0].getTarget()

        stated_in_set = self.get_stated_in_from_source(source)

        id = self.get_id_from_url(url=url, stated_in_set=stated_in_set)
        if id and stated_in_set and len(stated_in_set) > 1:
            # the source has multiple "stated in" values, check if we can ignore it, or raise an error
            pid, stated_in, external_id = id
            if not self.is_single_stated_in(pid, stated_in_set):
                raise RuntimeError(
                    f"id {id} has multiple stated in {stated_in_set}"
                )
        return id

    def get_pid_from_source(self, source) -> str | None:
        """
        Determines the PID from a given source (a reference that is an ordered dictionary).

        This function inspects the source to find a relevant PID.
        If multiple PIDs are found that do not fit the predefined criteria, it raises a RuntimeError.

        Args:
            source (dict): The source containing potential PIDs.

        Returns:
            str: The determined PID, or None if no valid PID is found.
        """
        pids = {prop for prop in source if prop in self.pid_dict}
        if not pids:
            return None
        if len(pids) == 1:
            return next(iter(pids))
        # handle common combinations
        if pids == {PID_NL_CR_AUT_ID, PID_BHCL_UUID}:
            return PID_BHCL_UUID
        if pids == {PID_X_POST_ID, PID_X_USERNAME}:
            return PID_X_POST_ID
        if not (
            pids
            - {
                PID_OCLC_CONTROL_NUMBER,
                PID_INTERNET_ARCHIVE_ID,
                PID_LIBRARY_OF_CONGRESS_CONTROL_NUMBER_LCCN_BIBLIOGRAPHIC,
                PID_HATHITRUST_ID,
                PID_OPEN_LIBRARY_ID,
            }
        ):
            return "BOOK"
        # probably an error in the reference that needs to be manually checked
        raise RuntimeError(f"duplicate pid in source: {pids}")

    def get_stated_in_from_source(self, source):
        """Returns a set with all 'stated in' values from a given source"""
        if PID_STATED_IN not in source:
            return None
        stated_in = set()
        for claim in source[PID_STATED_IN]:
            qid = claim.getTarget().getID()
            stated_in.add(qid)
        return stated_in

    def get_id_from_source(self, source):
        """
        Extracts the PID, stated in and external ID from a given source (a reference that is an ordered dictionary)

        This function attempts to find a PID from the source and retrieves the associated external ID.
        If no known PID is found, it tries to determine the external ID from the reference URL instead.

        Returns:
            tuple: A tuple containing the PID, stated in and external ID of the source, or
            None if an ID cannot be determined.
        """
        pid = self.get_pid_from_source(source)
        if not pid:
            # no known pid; try to determine the id from the reference URL
            return self.get_id_from_reference_url(source)
        if pid == "BOOK":
            # allowed multiple pids, to describe a book
            return None

        if len(source[pid]) > 1:
            raise RuntimeError(f"Source has multiple {pid}")

        # ignore the 'stated in' value in the source: use the applicable 'stated in' value for the PID
        stated_in = self.get_stated_in_from_pid(pid)
        if not stated_in:
            raise RuntimeError(f"no stated in for {pid}")

        external_id = source[pid][0].getTarget()
        if not external_id:
            raise RuntimeError(f"no getTarget {pid}")

        return pid, stated_in, external_id

    def get_keep_url(self, pid: str, source) -> bool:
        if PID_REFERENCE_URL not in source:
            return True
        if len(source[PID_REFERENCE_URL]) > 1:
            raise RuntimeError("get_keep_url: multiple reference URLs")

        url = source[PID_REFERENCE_URL][0].getTarget()
        found_list = self.extract_ids_from_url(url, search_pid=pid)
        if not found_list and pid:
            found_list = self.extract_ids_from_url(url)

        if not found_list:
            # if the url is not recognized, then keep it
            return True

        if len(found_list) != 1:
            raise RuntimeError(f"{pid}: get_keep_url: multiple results for {url}")

        pid, stated_in, external_id, keep_url = found_list[0]
        return keep_url

    def get_id_from_url(self, url: str, stated_in_set):
        """
        Extracts the ID from a given URL using the 'stated in' set.

        This function searches for IDs within a URL, prioritizing those that match the
        given 'stated in' set. If no matches are found, it performs a general search.
        If multiple results are found for the URL, it raises a RuntimeError.

        Args:
            url (str): The URL to search for IDs.
            stated_in_set (set): A set of 'stated in' values to filter the search.

        Returns:
            tuple: A tuple containing the PID, stated_in, and external ID if a single match is found,
            or None if no match is found.
        """
        found_list = self.extract_ids_from_url(url, search_stated_in_set=stated_in_set)
        if not found_list and stated_in_set:
            found_list = self.extract_ids_from_url(url)

        if not found_list:
            return None

        if len(found_list) != 1:
            raise RuntimeError(f"multiple results for {url}")

        # return tuple
        pid, stated_in, external_id, keep_url = found_list[0]
        return (
            pid,
            stated_in,
            external_id,
        )

    def check_external_id(self, pid: str, external_id: str, compiled_format_re) -> bool:
        if compiled_format_re:
            match = compiled_format_re.match(external_id)
            if not match:
                if pid == PID_TRECCANI_ID:
                    return False
                raise RuntimeError(
                    f"{pid}: found id {external_id} does not match format re"
                )
        elif external_id.endswith("/") or external_id.endswith("\\"):
            raise RuntimeError(f"{pid}: found id {external_id} ends with slash")

        return True

    def extract_ids_from_url(
        self, search_url: str, search_pid: str = None, search_stated_in_set=None
    ):
        """
        Extracts IDs from a given URL based on specified patterns.

        Args:
            search_url (str): The URL to search for IDs.
            search_pid (str, optional): A specific PID to filter the search. Defaults to None.
            search_stated_in_set (set, optional): A set of 'stated in' values to filter the search. Defaults to None.

        Returns:
            list: A list of tuples containing the PID, stated_in, external ID, and whether to keep the URL.
        """
        found_list = []
        if not search_url:
            return found_list

        search_url = urllib.parse.unquote(search_url)

        # Check if the URL matches any of the patterns
        for pattern_obj in self.parsed_list:
            if pattern_obj.pid:
                stated_in, compiled_format_re = self.pid_dict[pattern_obj.pid]

                if search_pid and search_pid != pattern_obj.pid:
                    continue
                if search_stated_in_set and stated_in not in search_stated_in_set:
                    continue
            else:
                # toolforge pattern has no fixed pid
                stated_in = None
                compiled_format_re = None

            res = pattern_obj.match(search_url)
            if res:
                pid, external_id = res
                if not stated_in:
                    stated_in, compiled_format_re = self.pid_dict[pid]
                if not self.check_external_id(pid, external_id, compiled_format_re):
                    continue

                # determine if we need to keep the reference URL or can drop it
                if pattern_obj.keep_url is None and self.keep_url_strategy:
                    pattern_obj.keep_url = self.keep_url_strategy.keep_url(
                        pid, pattern_obj.pattern
                    )
                if pattern_obj.keep_url is None:
                    raise RuntimeError(
                        f"{pid}: pattern {pattern_obj.pattern} keep_url is None"
                    )

                t = (pid, stated_in, external_id, pattern_obj.keep_url)
                if t not in found_list:
                    found_list.append(t)

        return found_list

    def save(self, list):
        with open(STATED_IN_FILE, "w") as outfile:
            json.dump(list, outfile)

    def ignore(self, pid: str, expr: str) -> bool:
        if pid == PID_GND_ID:
            if "deutsche-biographie" in expr:
                logger.warning(f"Ignored: {pid} {expr}")
                return True
            logger.warning(f"Accepted: {pid} {expr}")
        if pid == PID_DEUTSCHE_BIOGRAPHIE_GND_ID:
            if "deutsche-biographie" not in expr:
                logger.warning(f"Ignored: {pid} {expr}")
                return True
            logger.warning(f"Accepted: {pid} {expr}")

        return False

    def get_duplicate_stated_in(self):
        """Queries and returns a set of PIDs with multiple 'stated in' values."""

        qry = """SELECT DISTINCT ?item WHERE {
            ?item wdt:P9073 ?stated_in1, ?stated_in2.
            FILTER(?stated_in1 != ?stated_in2)
        }"""

        pids = set()
        for row in query_wdqs(qry):
            pid = row.get("item", {}).get("value", "").replace(WD, "")
            pids.add(pid)

        return pids

    def construct_list(self):

        ignore_pids = self.get_duplicate_stated_in()
        # applicable 'stated in' value (P9073)
        # URL match pattern (P8966)
        qry = """SELECT DISTINCT ?item ?stated_in ?expr ?repl ?format_re WHERE {
            ?item wdt:P9073 ?stated_in;
                wdt:P8966 ?expr.
            OPTIONAL {
                ?item p:P8966 ?statement.
                ?statement ps:P8966 ?expr;
                pq:P8967 ?repl.
            }
            OPTIONAL { ?item wdt:P1793 ?format_re. }
            FILTER((STR(?expr)) != "")
            }"""
        result_list = []
        self.stated_in = {}
        for row in query_wdqs(qry):
            pid = row.get("item", {}).get("value", "").replace(WD, "")
            if not pid.startswith("P"):
                continue
            if pid in ignore_pids:
                logger.warning(f"Ignored {pid}, it has multiple stated in")
                continue
            stated_in = row.get("stated_in", {}).get("value", "").replace(WD, "")
            if not stated_in.startswith("Q"):
                # unknown value, for example P12193
                continue
            expr = row.get("expr", {}).get("value", "")
            repl = row.get("repl", {}).get("value", "")
            format_re = row.get("format_re", {}).get("value", "")
            format_re = format_re.lstrip("^").rstrip("$")
            # '^https?:\\/\\/www\\.gutenberg\\.org\\/ebooks\\/author\\/([1-9]\\d{0,4})'
            expr = expr.lstrip("^").rstrip("$")
            expr = remove_start_text(expr, "http://")
            expr = remove_start_text(expr, "http:\/\/")
            expr = remove_start_text(expr, "http?://")  # wrong
            expr = remove_start_text(expr, "http?:\\/\\/")  # wrong
            expr = remove_start_text(expr, "http(?:s):\\/\\/")  # wrong
            expr = remove_start_text(expr, "http(?:s)?:\\/\\/")
            expr = remove_start_text(expr, "http(?:s|):\\/\\/")
            expr = remove_start_text(expr, "https://")
            expr = remove_start_text(expr, "https:\/\/")
            expr = remove_start_text(expr, "https?://")
            expr = remove_start_text(expr, "https?:\/\/")
            expr = remove_start_text(expr, "https?\\:\\/\\/")
            expr = remove_start_text(expr, "https\\:\\/\\/")
            expr = remove_start_text(expr, "https^:\\/\\/")  # wrong
            expr = remove_start_text(expr, "http\\:\\/\\/")

            expr = remove_start_text(expr, "(?:www\\.)?")
            expr = remove_start_text(expr, "www\\.")

            if self.ignore(pid, expr):
                continue

            result_list.append(
                {
                    "pid": pid,
                    "stated_in": stated_in,
                    "expr": expr,
                    "repl": repl,
                    "format_re": format_re,
                }
            )
            self.stated_in[pid] = stated_in

        return result_list

    def get_custom_list(self):
        return [
            {
                "pid": PID_RKDARTISTS_ID,
                "expr": "rkd\\.nl\\/explore\\/artists\\/(\\d+)",
            },
            {
                "pid": PID_RKDARTISTS_ID,
                "expr": "(?:explore\\.)?rkd\\.nl\\/(?:en|nl)\\/explore\\/artists\\/(\\d+)",
            },
            {
                "pid": PID_RKDARTISTS_ID,
                "expr": "research\\.rkd\\.nl\\/nl\\/detail\\/https:\\/\\/data\\.rkd\\.nl\\/artists\\/([1-9]\\d{0,5})",
            },
            {
                "pid": PID_VIAF_ID,
                "expr": r"viaf\.org\/viaf\/([1-9]\d(?:\d{0,7}|\d{17,20}))(?:\/(?:viaf\.html|#[\pLa-zA-Z0-9~˜.%,_(:)-]*))",
            },
            {
                "pid": PID_CERL_THESAURUS_ID,
                "expr": "thesaurus\\.cerl\\.org\\/record\\/(c(?:af|nc|ni|nl|np)0\\d{7})",
            },
            {
                "pid": PID_UNION_LIST_OF_ARTIST_NAMES_ID,
                "expr": "vocab\\.getty\\.edu\\/page\\/ulan\\/(\\d+)",
            },
            {
                "pid": PID_UNION_LIST_OF_ARTIST_NAMES_ID,
                "expr": "getty\\.edu\\/vow\\/ULANFullDisplay\\?find=(500\\d\{6\})&role=&nation=&prev_page=1&subjectid=\\1",
            },
            {
                "pid": PID_UNION_LIST_OF_ARTIST_NAMES_ID,
                # "expr": r"getty\.edu\/vow\/ULANFullDisplay\?find=(500\d{6})&role=&nation=&prev_page=1&subjectid=\1",
                "expr": r"getty\.edu\/vow\/ULANFullDisplay\?find=(500\d{6})&role=&nation=&prev_page=1&subjectid=\1",
            },
            {
                "pid": PID_OPEN_LIBRARY_ID,
                "expr": "openlibrary\\.org\\/works\\/(OL[1-9]\\d+A)",
            },
            {
                "pid": PID_OPEN_LIBRARY_ID,
                "expr": "openlibrary\\.org\\/authors\\/(OL[1-9]\\d+A)\\/[a-zA-Z_]+",
                "keep_url": True,
            },
            {
                "pid": PID_INVALUABLE_COM_PERSON_ID,
                "expr": "invaluable\\.com\\/features\\/viewArtist\\.cfm\\?artistRef=([\\w]+)",
            },
            {
                "pid": PID_CLARA_ID,
                "expr": "clara\\.nmwa\\.org\\/index\\.php\\?g=entity_detail&entity_id=([\\d]*)",
            },
            {
                "pid": PID_NL_CR_AUT_ID,
                "expr": "aleph\\.nkp\\.cz\\/F\\/\\?func=find-c&local_base=aut&ccl_term=ica=([a-z]{2,4}[0-9]{2,14})&CON_LNG=ENG",
            },
            {
                "pid": PID_NLA_TROVE_PEOPLE_ID,
                "expr": "trove\\.nla\\.gov\\.au\\/people\\/([\\d]*)\\?q&c=people",
            },
            {
                "pid": PID_RISM_ID,
                "expr": "opac\\.rism\\.info\\/search\\?id=pe(\\d*)",
                "repl": "people/\\1",
            },
            {
                "pid": PID_BIOGRAPHIE_NATIONALE_DE_BELGIQUE_ID,
                "stated_in": QID_BIOGRAPHIE_NATIONALE_DE_BELGIQUE,
                "expr": "academieroyale\\.be\\/fr\\/la-biographie-nationale-personnalites-detail\\/personnalites\\/([a-z-]*)\\/Vrai\\/",
            },
            {
                "pid": PID_AKL_ONLINE_ARTIST_ID,
                "expr": "degruyter\\.com\\/view\\/AKL\\/_(\\d*)",
            },
            {
                "pid": PID_PLWABN_ID,
                "expr": "mak\\.bn\\.org\\.pl\\/cgi-bin\\/KHW\\/makwww\\.exe\\?[A-Z0-9&=]*&WI=(\\d*)",
            },
            {
                "pid": PID_ARTNET_ARTIST_ID,
                "stated_in": QID_ARTNET,
                "expr": "artnet\\.com\\/artists\\/([a-zçéšäáàèëöóòüùúïí`ñoôâêîûł0-9-]*)\\/?",
            },
            {
                "pid": PID_ARTNET_ARTIST_ID,
                "stated_in": QID_ARTNET,
                "expr": "artnet\\.com\\/artists\\/([\\p{L}-]*)\\/?",
            },
            {
                "pid": PID_BENEZIT_ID,
                "expr": "oxfordartonline\\.com\\/benezit\\/view\\/10\\.1093\\/benz\\/9780199773787\\.001\\.0001\\/acref-9780199773787-e-(\\d*)",
                "repl": "B\\1",
            },
            {
                "pid": PID_BENEZIT_ID,
                "expr": "oxfordindex\\.oup\\.com\\/view\\/10\\.1093\\/benz\\/9780199773787\\.article\\.(B\\d*)",
            },
            {
                "pid": PID_MUSEUM_OF_MODERN_ART_ARTIST_ID,
                "expr": "moma\\.org\\/+collection\\/artists\\/(\\d+)",
            },
            {
                "pid": PID_SFMOMA_ARTIST_ID,
                "stated_in": QID_SAN_FRANCISCO_MUSEUM_OF_MODERN_ART_ONLINE_COLLECTION,
                "expr": "sfmoma\\.org\\/artist\\/([a-zA-Z0-9_-]*)\\/?",
            },
            {
                "pid": PID_GND_ID,
                "expr": "portal\\.dnb\\.de\\/opac\\.htm\\?method=simpleSearch&cqlMode=true&query=nid=(\\d+)",
            },
            {
                "pid": PID_GND_ID,
                "expr": r"portal\.dnb\.de\/opac\.htm\?method=simpleSearch&cqlMode=true&query=nid=(1[0123]?\d{7}[0-9X]|[47]\d{6}-\d|[1-9]\d{0,7}-[0-9X]|3\d{7}[0-9X])",
            },
            {
                "pid": PID_BIBLIOTHEQUE_NATIONALE_DE_FRANCE_ID,
                "stated_in": QID_BNF_AUTHORITIES,
                "expr": "(?:data|catalogue)\\.bnf\\.fr\\/ark:\\/12148\\/cb(\\d{8,9}[0-9bcdfghjkmnpqrstvwxz])",
            },
            {
                "pid": PID_BRITISH_MUSEUM_PERSON_OR_INSTITUTION_ID,
                "stated_in": QID_BRITISH_MUSEUM_PERSON_INSTITUTION_THESAURUS,
                "expr": "collection\\.britishmuseum\\.org\\/resource\\/\\?uri=http:\\/\\/collection\\.britishmuseum\\.org\\/id\\/person-institution\\/([1-9][0-9]{0,5})",
            },
            {
                "pid": PID_NATIONAL_GALLERY_OF_ART_ARTIST_ID,
                "expr": "nga\\.gov\\/collection\\/artist-info\\.([1-9]\\d*)\\.html",
            },
            {
                "pid": PID_CONOR_SI_ID,
                "expr": "plus\\.cobiss\\.si\\/opac7\\/conor\\/([1-9]\\d{0,8})",
            },
            {
                "pid": PID_FIND_A_GRAVE_MEMORIAL_ID,
                "expr": "(?:[a-z-]*\.)?findagrave\.com\/memorial\/([1-9]\d*)\/(?:[a-zçéšäáàèëöóòüùúïí`ñoôâêîûł_-]+)",
                "keep_url": True,
            },
            {
                "pid": PID_ISNI,
                "expr": "isni\\.org(?:\\/isni)?\\/(\\d{4})\\+?(\\d{4})\\+?(\\d{4})\\+?(\\d{3}[\\dX])",
                "repl": "\\1\\2\\3\\4",
            },
            {
                "pid": PID_HDS_ID,
                "expr": "hls-dhs-dss\\.ch\\/textes\\/d\\/D(\\d{5})\\.php",
                "repl": "0\\1",
            },
        ]

    def load(self):
        if os.path.exists(STATED_IN_FILE):
            with open(STATED_IN_FILE, "r") as infile:
                unparsed_list = json.load(infile)
        else:
            unparsed_list = self.construct_list() + self.get_custom_list()
            self.save(unparsed_list)

        pid_dict = {}
        parsed_list = []
        stated_in_dict = {}

        parsed_list.append(ToolforgePattern())

        for p in unparsed_list:
            pid = p.get("pid", "")
            pattern = p.get("expr", "")
            keep_url = p.get("keep_url", None)
            if keep_url is None:
                if is_simple_regex(pattern):
                    keep_url = False
            stated_in = p.get("stated_in", "")
            repl = p.get("repl", "")
            format_re = p.get("format_re", "")

            if pid and stated_in:
                stated_in_dict[pid] = stated_in
            if not stated_in:
                stated_in = stated_in_dict[pid]

            try:
                compiled_pattern = re.compile(
                    "^(?:https?:\\/\\/)?(?:www\\.)?" + pattern + "\\/?$", re.IGNORECASE
                )
            except:
                logger.info(f"Can't compile expr {pattern}")
                continue

            try:
                if format_re != "":
                    compiled_format_re = re.compile(
                        "^" + format_re + "$", re.IGNORECASE
                    )
                else:
                    compiled_format_re = None

            except:
                logger.info(f"Can't compile format_re {format_re}")
                continue

            if pid not in pid_dict:
                pid_dict[pid] = (
                    stated_in,
                    compiled_format_re,
                )
            parsed_list.append(
                CompiledPattern(
                    pid,
                    pattern,
                    compiled_pattern,
                    repl,
                    keep_url,
                )
            )

        return pid_dict, parsed_list


def check_is_simple_regex_func(pattern: str):
    print(f"{pattern}: is_simple_regex={is_simple_regex(pattern)}")


def check_stated_in():
    s = StatedIn()
    print(s.extract_ids_from_url("https://arthistorians.info/warburga"))
    print(s.extract_ids_from_url("https://d-nb.info/gnd/1231643-X"))
    print(s.extract_ids_from_url("https://www.deutsche-biographie.de/129070807.html"))
    print(
        s.extract_ids_from_url(
            "https://fr.findagrave.com/memorial/194627825/michael-cooper"
        )
    )
    print(s.extract_ids_from_url("https://fr.findagrave.com/memorial/194627825/"))
    print(s.extract_ids_from_url("http://www.hls-dhs-dss.ch/textes/d/D41767.php"))
    print(s.extract_ids_from_url("http://www.isni.org/0000000080772828"))
    print(s.extract_ids_from_url("http://www.isni.org/isni/0000000080772828"))
    print(s.extract_ids_from_url("http://www.isni.org/0000%2B0000%2B7969%2B8579"))
    print(
        s.extract_ids_from_url("https://www.cairn.info/publications-de-wd--462.htm")
    )  # P4369 + P4700
    print(
        s.extract_ids_from_url(
            "https://www.pc.gc.ca/apps/dfhd/page_nhs_eng.aspx?id=15832"
        )
    )  # P2526 + P9054

    print(is_simple_regex("vocab\\.getty\\.edu\\/page\\/ulan\\/(\\d+)"))
    print(is_simple_regex("vocab\\.getty\\.edu\\/page\\/ulan\\/([1-9]\d*)"))

    p = s.extract_ids_from_url("http://vocab.getty.edu/page/ulan/500011051")
    print(p[0][0].keep_url)


def check_is_simple_regex():
    check_is_simple_regex_func("ab([0-9]*)")
    check_is_simple_regex_func("ab[a-z]+([0-9]*)")

    check_is_simple_regex_func("rkd\\.nl\\/explore\\/artists\\/(\\d+)")

    check_is_simple_regex_func(
        "(?:[a-z-]*\.)?findagrave\.com\/memorial\/([1-9]\d*)\/(?:[a-zçéšäáàèëöóòüùúïí`ñoôâêîûł_-]+)"
    )
    check_is_simple_regex_func(
        "(?:data|catalogue)\\.bnf\\.fr\\/ark:\\/12148\\/cb(\\d{8,9}[0-9bcdfghjkmnpqrstvwxz])"
    )
    check_is_simple_regex_func(
        "(?:explore\\.)?rkd\\.nl\\/(?:en|nl)\\/explore\\/artists\\/(\\d+)"
    )
    check_is_simple_regex_func(
        "academieroyale\\.be\\/fr\\/la-biographie-nationale-personnalites-detail\\/personnalites\\/([a-z-]*)\\/Vrai\\/"
    )
    check_is_simple_regex_func(
        "aleph\\.nkp\\.cz\\/F\\/\\?func=find-c&local_base=aut&ccl_term=ica=([a-z]{2,4}[0-9]{2,14})&CON_LNG=ENG"
    )
    check_is_simple_regex_func("artnet\\.com\\/artists\\/([\\p{L}-]*)\\/?")
    check_is_simple_regex_func(
        "artnet\\.com\\/artists\\/([a-zçéšäáàèëöóòüùúïí`ñoôâêîûł0-9-]*)\\/?"
    )
    check_is_simple_regex_func(
        "clara\\.nmwa\\.org\\/index\\.php\\?g=entity_detail&entity_id=([\\d]*)"
    )
    check_is_simple_regex_func(
        "collection\\.britishmuseum\\.org\\/resource\\/\\?uri=http:\\/\\/collection\\.britishmuseum\\.org\\/id\\/person-institution\\/([1-9][0-9]{0,5})"
    )
    check_is_simple_regex_func("degruyter\\.com\\/view\\/AKL\\/_(\\d*)")
    check_is_simple_regex_func(
        "getty\\.edu\\/vow\\/ULANFullDisplay\\?find=(500\\d\{6\})&role=&nation=&prev_page=1&subjectid=\\1"
    )
    check_is_simple_regex_func("hls-dhs-dss\\.ch\\/textes\\/d\\/D(\\d{5})\\.php")
    check_is_simple_regex_func(
        "invaluable\\.com\\/features\\/viewArtist\\.cfm\\?artistRef=([\\w]+)"
    )
    check_is_simple_regex_func(
        "isni\\.org(?:\\/isni)?\\/(\\d{4})\\+?(\\d{4})\\+?(\\d{4})\\+?(\\d{3}[\\dX])"
    )
    check_is_simple_regex_func(
        "mak\\.bn\\.org\\.pl\\/cgi-bin\\/KHW\\/makwww\\.exe\\?[A-Z0-9&=]*&WI=(\\d*)"
    )
    check_is_simple_regex_func("moma\\.org\\/+collection\\/artists\\/(\\d+)")
    check_is_simple_regex_func(
        "nga\\.gov\\/collection\\/artist-info\\.([1-9]\\d*)\\.html"
    )
    check_is_simple_regex_func("opac\\.rism\\.info\\/search\\?id=pe(\\d*)")
    check_is_simple_regex_func(
        "openlibrary\\.org\\/authors\\/(OL[1-9]\\d+A)\\/[a-zA-Z_]+"
    )
    check_is_simple_regex_func("openlibrary\\.org\\/works\\/(OL[1-9]\\d+A)")
    check_is_simple_regex_func(
        "oxfordartonline\\.com\\/benezit\\/view\\/10\\.1093\\/benz\\/9780199773787\\.001\\.0001\\/acref-9780199773787-e-(\\d*)"
    )
    check_is_simple_regex_func(
        "oxfordindex\\.oup\\.com\\/view\\/10\\.1093\\/benz\\/9780199773787\\.article\\.(B\\d*)"
    )
    check_is_simple_regex_func("plus\\.cobiss\\.si\\/opac7\\/conor\\/([1-9]\\d{0,8})")
    check_is_simple_regex_func(
        "portal\\.dnb\\.de\\/opac\\.htm\\?method=simpleSearch&cqlMode=true&query=nid=(\\d+)"
    )
    check_is_simple_regex_func(
        "research\\.rkd\\.nl\\/nl\\/detail\\/https:\\/\\/data\\.rkd\\.nl\\/artists\\/([1-9]\\d{0,5})"
    )
    check_is_simple_regex_func("sfmoma\\.org\\/artist\\/([a-zA-Z0-9_-]*)\\/?")
    check_is_simple_regex_func(
        "thesaurus\\.cerl\\.org\\/record\\/(c(?:af|nc|ni|nl|np)0\\d{7})"
    )
    check_is_simple_regex_func(
        "trove\\.nla\\.gov\\.au\\/people\\/([\\d]*)\\?q&c=people"
    )
    check_is_simple_regex_func("vocab\\.getty\\.edu\\/page\\/ulan\\/(\\d+)")
    check_is_simple_regex_func(
        r"getty\.edu\/vow\/ULANFullDisplay\?find=(500\d{6})&role=&nation=&prev_page=1&subjectid=\1"
    )
    check_is_simple_regex_func(
        r"portal\.dnb\.de\/opac\.htm\?method=simpleSearch&cqlMode=true&query=nid=(1[0123]?\d{7}[0-9X]|[47]\d{6}-\d|[1-9]\d{0,7}-[0-9X]|3\d{7}[0-9X])"
    )
    check_is_simple_regex_func(
        r"viaf\.org\/viaf\/([1-9]\d(?:\d{0,7}|\d{17,20}))(?:\/(?:viaf\.html|#[\pLa-zA-Z0-9~˜.%,_(:)-]*))"
    )


def main() -> None:
    # check_stated_in()
    check_is_simple_regex()


if __name__ == "__main__":
    main()
