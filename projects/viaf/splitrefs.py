import json
from collections import OrderedDict
import os.path
import pywikibot as pwb
from pywikibot import pagegenerators
import requests
import re

SITE = pwb.Site("wikidata", "wikidata")
SITE.login()
SITE.get_tokens("csrf")
REPO = SITE.data_repository()

WD = "http://www.wikidata.org/entity/"
WDQS_ENDPOINT = "https://query.wikidata.org/sparql"
READ_TIMEOUT = 60  # sec

PID_REFERENCE_URL = "P854"
PID_RETRIEVED = "P813"
PID_STATED_IN = "P248"

STATED_IN_FILE = "stated_in.json"


def remove_start_text(input_string, start_text):
    """
    Removes the specified start_text from the input_string if it exists at the beginning.
    """
    if input_string.startswith(start_text):
        return input_string[len(start_text) :]
    else:
        return input_string


def query_wdqs(query: str):
    response = requests.get(
        WDQS_ENDPOINT, params={"query": query, "format": "json"}, timeout=READ_TIMEOUT
    )
    payload = response.json()
    return payload["results"]["bindings"]

def get_qry_count(query: str) -> int:
    try:
        response = requests.get(
            WDQS_ENDPOINT, params={"query": query, "format": "json"}, timeout=READ_TIMEOUT
        )
    except:
        return None

    payload = response.json()
    data = payload["results"]["bindings"]

    for row in data:
        count = int(row.get('count', {}).get('value', ''))
        return count
    
    return None

def get_count(pid: str):
    count = 0
    index = 0
    limit = 300_000
    while True:
        template = """SELECT (COUNT(DISTINCT ?item) AS ?count) WHERE {{
                    SERVICE bd:slice {{
                        ?item p:{pid} ?statement.
                        bd:serviceParam bd:slice.offset {index} . # Start at item number (not to be confused with QID)
                        bd:serviceParam bd:slice.limit {limit}  . # List this many items
                    }}
                    ?statement prov:wasDerivedFrom ?ref.
                    ?ref pr:P854 ?some_ref, ?some_ref2.
                    FILTER(?some_ref != ?some_ref2)
                    FILTER(NOT EXISTS {{ ?ref pr:P248 ?s. }})
                    }}
                    """
        query = template.format(index=index,limit=limit,pid=pid)
        sub_count = get_qry_count(query)
        if sub_count == None:
            break
        count = count + sub_count
        print(f"{index}: {sub_count}; total = {count}")
        index = index + limit

    return count


class StatedIn:
    def __init__(self):
        self.parsed_list = self.load()

    def get_stated_in_qid(self, url):
        # Check if the URL matches any of the patterns
        for p in self.parsed_list:
            pattern = p["exp"]
            stated_in = p["stated_in"]

            if pattern.match(url):
                return stated_in

        # no match found
        return None

    def save(self, list):
        with open(STATED_IN_FILE, "w") as outfile:
            json.dump(list, outfile)

    def construct_list(self):
        qry = """SELECT * WHERE {
                    {
                        SELECT DISTINCT ?stated_in ?type ?exp WHERE {
                        ?item wdt:P9073 ?stated_in;
                            wdt:P8966 ?exp.
                        BIND("pattern" AS ?type)
                        }
                    }
                    UNION
                    {
                        SELECT DISTINCT ?stated_in ?type ?exp WHERE {
                        ?item wdt:P9073 ?stated_in;
                            wdt:P1921 ?exp.
                        BIND("formatter" AS ?type)
                        }
                    }
                    }"""
        result_list = []
        for row in query_wdqs(qry):
            stated_in = row.get("stated_in", {}).get("value", "").replace(WD, "")
            if not stated_in.startswith("Q"):
                # unknown value, for example P12193
                continue
            type = row.get("type", {}).get("value", "")
            exp = row.get("exp", {}).get("value", "")
            if type == "formatter":
                # 'http://www.gutenberg.org/ebooks/author/$1'
                exp = remove_start_text(exp, "http://")
                exp = remove_start_text(exp, "https://")
                exp = exp.replace("/", "\\/")
                exp = exp.replace("$1", ".*")
            elif type == "pattern":
                # '^https?:\\/\\/www\\.gutenberg\\.org\\/ebooks\\/author\\/([1-9]\\d{0,4})'
                exp = exp.lstrip("^").rstrip("$")
                exp = remove_start_text(exp, "http://")
                exp = remove_start_text(exp, "http:\/\/")
                exp = remove_start_text(exp, "http?://")  # wrong
                exp = remove_start_text(exp, "http?:\\/\\/")  # wrong
                exp = remove_start_text(exp, "http(?:s):\\/\\/")  # wrong
                exp = remove_start_text(exp, "http(?:s)?:\\/\\/")
                exp = remove_start_text(exp, "http(?:s|):\\/\\/")
                exp = remove_start_text(exp, "https://")
                exp = remove_start_text(exp, "https:\/\/")
                exp = remove_start_text(exp, "https?://")
                exp = remove_start_text(exp, "https?:\/\/")
                exp = remove_start_text(exp, "https?\\:\\/\\/")
                exp = remove_start_text(exp, "https\\:\\/\\/")
                exp = remove_start_text(exp, "https^:\\/\\/")  # wrong
                exp = remove_start_text(exp, "http\\:\\/\\/")

            result_list.append({"stated_in": stated_in, "exp": exp})
        return result_list

    def load(self):
        if os.path.exists(STATED_IN_FILE):
            with open(STATED_IN_FILE, "r") as infile:
                unparsed_list = json.load(infile)
        else:
            unparsed_list = self.construct_list()
            self.save(unparsed_list)

        parsed_list = []
        for p in unparsed_list:
            pattern = p["exp"]
            stated_in = p["stated_in"]

            try:
                compiled = re.compile("https?:\\/\\/" + pattern, re.IGNORECASE)
                parsed_list.append({"exp": compiled, "stated_in": stated_in})
            except:
                print(f"Can't compile pattern {pattern}")
                pass

        return parsed_list


class SplitRefBot:
    def __init__(self, stated_in_list: StatedIn, generator, prop: str):
        self.stated_in_list = stated_in_list
        self.generator = pagegenerators.PreloadingEntityGenerator(generator)
        self.prop = prop

    def run(self):
        for item in self.generator:
            if not item.exists():
                continue

            if item.isRedirectPage():
                continue

            claims = item.get().get("claims")

            if not item.botMayEdit():
                raise RuntimeError(
                    f"Skipping {item.title()} because it cannot be edited by bots"
                )

            if self.prop in claims:
                for claim in claims[self.prop]:
                    new_sources = []
                    claim_changed = False
                    for s in claim.sources:
                        if self.can_split_source(s):
                            source_changed, source_list = self.split_source(s, item)
                            claim_changed = claim_changed or source_changed
                            new_sources.extend(source_list)
                        else:
                            new_sources.append(s)
                    if claim_changed:
                        claim.sources = new_sources
                        summary = "split reference with multiple reference urls"
                        self.save_claim(claim, item, summary)

    def get_retrieved_claim(self, src):
        if PID_RETRIEVED not in src:
            return None

        if len(src[PID_RETRIEVED]) > 1:
            return None

        return src[PID_RETRIEVED][0]

    def can_split_source(self, src) -> bool:
        if PID_REFERENCE_URL not in src:
            return False

        # count = len(src[PID_REFERENCE_URL])
        # if count <= 1:
        #     return False

        for prop in src:
            if prop not in (PID_REFERENCE_URL, PID_RETRIEVED):
                return False

        # do not accept multiple PID_RETRIEVED
        if PID_RETRIEVED in src and len(src[PID_RETRIEVED]) > 1:
            return False

        domains = set()
        for value in src[PID_REFERENCE_URL]:
            url = value.getTarget()
            if "web.archive.org" in url.lower():
                return False
            if "archive.is" in url.lower():
                return False

            stated_in_qid = self.stated_in_list.get_stated_in_qid(url)
            if not stated_in_qid:
                # prevent splitting reference urls with the same domain but different langage, for example:
                # https://www.zaowouki.org/en/the-artist/biography/
                # https://www.zaowouki.org/fr/artiste/biographie/
                match = re.search(r"^https?:\/\/([a-z0-9._-]*)\/", url, re.IGNORECASE)
                if match:
                    domain = match.group(1)
                    if domain in domains:
                        return False
                    domains.add(domain)

        return True

    def save_claim(self, claim, item: pwb.ItemPage, summary: str):
        if not claim.on_item:
            claim.on_item = item
        REPO.save_claim(claim, summary=summary)

    def split_source(self, src, item: pwb.ItemPage):
        """
        Splits source with multiple reference urls into individual sources.

        Returns:
            tuple: A tuple containing a boolean flag indicating if any changes were made (changed) and a list of sources.
        """
        sources = []
        retrieved_claim = self.get_retrieved_claim(src)
        changed = len(src[PID_REFERENCE_URL]) > 1
        for value in src[PID_REFERENCE_URL]:
            source = OrderedDict()

            url = value.getTarget()
            stated_in_qid = self.stated_in_list.get_stated_in_qid(url)
            if stated_in_qid:
                stated_in = pwb.Claim(REPO, PID_STATED_IN)
                stated_in.isReference = True
                stated_in.setTarget(pwb.ItemPage(REPO, stated_in_qid))
                stated_in.on_item = item
                source[PID_STATED_IN] = [stated_in]
                changed = True

            ref = pwb.Claim(REPO, PID_REFERENCE_URL)
            ref.isReference = True
            ref.setTarget(url)
            ref.on_item = item
            source[PID_REFERENCE_URL] = [ref]

            if retrieved_claim is not None:
                retr = pwb.Claim(REPO, PID_RETRIEVED)
                retr.isReference = True
                dt = retrieved_claim.getTarget()
                retr.setTarget(dt)
                retr.on_item = item
                source[PID_RETRIEVED] = [retr]

            sources.append(source)

        return changed, sources


def main() -> None:
    # count = get_count("P569")
    # print(count)
    # return

    query = """SELECT distinct ?item WHERE {
            ?item p:P569 ?statement.
            ?statement prov:wasDerivedFrom ?ref.
            ?ref pr:P854 ?some_ref, ?some_ref2.
            FILTER(?some_ref != ?some_ref2)
            FILTER(NOT EXISTS { ?ref pr:P248 ?s. })
            }
            LIMIT 10"""

    stated_in_list = StatedIn()

    generator = pagegenerators.PreloadingEntityGenerator(
        pagegenerators.WikidataSPARQLPageGenerator(query, site=REPO)
    )

    splitBot = SplitRefBot(stated_in_list, generator, "P569")
    splitBot.run()


if __name__ == "__main__":
    main()
