import urllib
import json
import os.path
import re
import requests


WD = "http://www.wikidata.org/entity/"
WDQS_ENDPOINT = "https://query.wikidata.org/sparql"
READ_TIMEOUT = 60  # sec

PID_REFERENCE_URL = "P854"
PID_RETRIEVED = "P813"
PID_STATED_IN = "P248"
PID_ARCHIVE_URL = "P1065"
PID_ARCHIVE_DATE = "P2960"

PID_OPEN_LIBRARY_ID = "P648"
PID_RKDARTISTS_ID = "P650"
QID_OPEN_LIBRARY = "Q1201876"
QID_RKDARTISTS = "Q17299517"
PID_INVALUABLE_COM_PERSON_ID = "P4927"
QID_INVALUABLE = "Q50813730"
PID_CLARA_ID = "P1615"
QID_CLARA = "Q18558540"
QID_CZECH_NATIONAL_AUTHORITY_DATABASE = "Q13550863"
PID_NL_CR_AUT_ID = "P691"
PID_NLA_TROVE_PEOPLE_ID = "P1315"
QID_TROVE = "Q18609226"
PID_RISM_ID = "P5504"
PID_BIOGRAPHIE_NATIONALE_DE_BELGIQUE_ID = "P6234"
QID_BIOGRAPHIE_NATIONALE_DE_BELGIQUE = "Q2728291"
PID_PLWABN_ID = "P7293"
PID_AKL_ONLINE_ARTIST_ID = "P4432"
PID_ARTNET_ARTIST_ID = "P3782"
PID_BENEZIT_ID = "P2843"
QID_ARTNET = "Q266566"
PID_UNION_LIST_OF_ARTIST_NAMES_ID = "P245"
QID_UNION_LIST_OF_ARTIST_NAMES = "Q2494649"
PID_MUSEUM_OF_MODERN_ART_ARTIST_ID = "P2174"
QID_SAN_FRANCISCO_MUSEUM_OF_MODERN_ART_ONLINE_COLLECTION = "Q84575091"
PID_SFMOMA_ARTIST_ID = "P4936"

STATED_IN_FILE = "stated_in.json"


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


class StatedIn:
    def __init__(self):
        self.pids, self.parsed_list = self.load()

    def get_stated_in_from_pid(self, search_pid: str):
        # todo: create dict
        for p in self.parsed_list:
            pid = p["pid"]
            stated_in = p["stated_in"]
            if search_pid == pid:
                return stated_in
        return None

    def get_stated_in_from_url(self, url: str):
        url = urllib.parse.unquote(url)
        # Check if the URL matches any of the patterns
        for p in self.parsed_list:
            pattern = p["expr"]
            stated_in = p["stated_in"]

            if pattern.match(url):
                return stated_in

        # no match found
        return None

    def is_id_pid(self, pid: str):
        res = pid in self.pids
        return res

    def get_id_from_reference_url(self, source):
        if PID_REFERENCE_URL not in source:
            return None
        if len(source[PID_REFERENCE_URL]) > 1:
            return None
        url = source[PID_REFERENCE_URL][0].getTarget()
        return self.get_id_from_url(url)

    def get_id_from_source(self, source):
        found_pid = None
        for prop in source:
            if prop in self.pids:
                if found_pid:
                    # todo: print
                    return None
                found_pid = prop

        if not found_pid:
            return self.get_id_from_reference_url(source)
        if len(source[found_pid]) > 1:
            return None

        stated_in = self.get_stated_in_from_pid(found_pid)
        if not stated_in:
            # todo: print
            return None

        id = source[found_pid][0].getTarget()
        if not id:
            # todo: print
            return None

        return found_pid, stated_in, id

    def get_id_from_url(self, url: str):
        url = urllib.parse.unquote(url)
        # Check if the URL matches any of the patterns
        for p in self.parsed_list:
            pid = p["pid"]
            pattern = p["expr"]
            stated_in = p["stated_in"]
            repl = p["repl"]

            match = pattern.search(url)
            if match:
                if repl:
                    id = pattern.sub(repl, url)
                else:
                    # for example, P7003 has 2 () groups; we don't know how to combine them into an id, so skip
                    if len(match.groups()) != 1:
                        print(f"Match with {pid}, but multiple groups; url={url}")
                        continue
                    id = match.group(1)

                return pid, stated_in, id

        # no match found
        return None

    def save(self, list):
        with open(STATED_IN_FILE, "w") as outfile:
            json.dump(list, outfile)

    def construct_list(self):
        qry = """SELECT DISTINCT ?item ?stated_in ?expr ?repl WHERE {
                ?item wdt:P9073 ?stated_in.
                OPTIONAL {
                    ?item p:P8966 ?statement.
                    ?statement ps:P8966 ?expr;
                    pq:P8967 ?repl.
                }
                OPTIONAL { ?item wdt:P8966 ?expr. }
                FILTER((STR(?expr)) != "")
                }"""
        result_list = []
        self.stated_in = {}
        for row in query_wdqs(qry):
            pid = row.get("item", {}).get("value", "").replace(WD, "")
            stated_in = row.get("stated_in", {}).get("value", "").replace(WD, "")
            if not stated_in.startswith("Q"):
                # unknown value, for example P12193
                continue
            expr = row.get("expr", {}).get("value", "")
            repl = row.get("repl", {}).get("value", "")
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

            result_list.append(
                {"pid": pid, "stated_in": stated_in, "expr": expr, "repl": repl}
            )
            self.stated_in[pid] = stated_in

        return result_list

    def get_custom_list(self):
        return [
            {
                "pid": PID_RKDARTISTS_ID,
                "expr": "rkd.nl\\/explore\\/artists\\/(\\d+)",
            },
            {
                "pid": PID_RKDARTISTS_ID,
                "expr": "rkd.nl\\/(?:en|nl)\\/explore\\/artists\\/(\\d+)",
            },
            {
                "pid": "P1871",
                "expr": "thesaurus.cerl.org\\/record\\/(c(?:af|nc|ni|nl|np)0\\d{7})",
            },
            {
                "pid": PID_UNION_LIST_OF_ARTIST_NAMES_ID,
                "expr": "vocab.getty.edu\\/page\\/ulan\\/(\\d+)",
            },
            {
                "pid": PID_OPEN_LIBRARY_ID,
                "expr": "openlibrary\\.org\\/works\\/(OL[1-9]\\d+A)",
            },
            {
                "pid": PID_INVALUABLE_COM_PERSON_ID,
                "expr": "invaluable.com\\/features\\/viewArtist.cfm\\?artistRef=([\\w]+)",
            },
            {
                "pid": PID_CLARA_ID,
                "expr": "clara.nmwa.org\\/index.php\\?g=entity_detail&entity_id=([\\d]*)",
            },
            {
                "pid": PID_NL_CR_AUT_ID,
                "expr": "aleph.nkp.cz\\/F\\/\\?func=find-c&local_base=aut&ccl_term=ica=([a-z]{2,4}[0-9]{2,14})&CON_LNG=ENG",
            },
            {
                "pid": PID_NLA_TROVE_PEOPLE_ID,
                "expr": "trove.nla.gov.au\\/people\\/([\\d]*)\\?q&c=people",
            },
            {
                "pid": PID_RISM_ID,
                "expr": "opac.rism.info\\/search\\?id=pe(\\d*)",
                "repl": "people/\\1",
            },
            {
                "pid": PID_BIOGRAPHIE_NATIONALE_DE_BELGIQUE_ID,
                "stated_in": QID_BIOGRAPHIE_NATIONALE_DE_BELGIQUE,
                "expr": "academieroyale.be\\/fr\\/la-biographie-nationale-personnalites-detail\\/personnalites\\/([a-z-]*)\\/Vrai\\/",
            },
            {
                "pid": PID_AKL_ONLINE_ARTIST_ID,
                "expr": "degruyter.com\\/view\\/AKL\\/_(\\d*)",
            },
            {
                "pid": PID_PLWABN_ID,
                "expr": "mak.bn.org.pl\\/cgi-bin\\/KHW\\/makwww.exe\\?[A-Z0-9&=]*&WI=(\\d*)",
            },
            {
                "pid": PID_ARTNET_ARTIST_ID,
                "stated_in": QID_ARTNET,
                "expr": "artnet.com\\/artists\\/([a-zç-]*)\\/?",
            },
            {
                "pid": PID_ARTNET_ARTIST_ID,
                "stated_in": QID_ARTNET,
                "expr": "artnet.com\\/artists\\/([\\p{L}-]*)\\/?",
            },
            {
                "pid": PID_BENEZIT_ID,
                "expr": "oxfordartonline.com\\/benezit\\/view\\/10.1093\\/benz\\/9780199773787.001.0001\\/acref-9780199773787-e-(\\d*)",
                "repl": "B\\1",
            },
            {
                "pid": PID_BENEZIT_ID,
                "expr": "oxfordindex.oup.com\\/view\\/10.1093\\/benz\\/9780199773787.article.(B\\d*)",
            },
            {
                "pid": PID_MUSEUM_OF_MODERN_ART_ARTIST_ID,
                "expr": "moma.org\\/+collection\\/artists\\/(\\d+)",
            },
            {
                "pid": PID_SFMOMA_ARTIST_ID,
                "stated_in": QID_SAN_FRANCISCO_MUSEUM_OF_MODERN_ART_ONLINE_COLLECTION,
                "expr": "sfmoma.org\/artist\/([a-zA-Z0-9_-]*)\/?",
            },
        ]

    def load(self):
        if os.path.exists(STATED_IN_FILE):
            with open(STATED_IN_FILE, "r") as infile:
                unparsed_list = json.load(infile)
        else:
            unparsed_list = self.construct_list() + self.get_custom_list()
            self.save(unparsed_list)

        pids = set()
        parsed_list = []
        stated_in_dict = {}
        for p in unparsed_list:
            pid = p.get("pid", "")
            pattern = p.get("expr", "")
            stated_in = p.get("stated_in", "")
            repl = p.get("repl", "")

            pids.add(pid)
            if pid and stated_in:
                stated_in_dict[pid] = stated_in
            if not stated_in:
                stated_in = stated_in_dict[pid]

            try:
                compiled = re.compile(
                    "^(?:https?:\\/\\/)?(?:www\\.)?" + pattern + "\\/?$", re.IGNORECASE
                )
                parsed_list.append(
                    {"pid": pid, "expr": compiled, "stated_in": stated_in, "repl": repl}
                )
            except:
                print(f"Can't compile pattern {pattern}")
                pass

        return pids, parsed_list
