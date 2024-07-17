from collections import OrderedDict
import pywikibot as pwb
from pywikibot import pagegenerators
import requests
import re
import statedin

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
PID_ARCHIVE_URL = "P1065"
PID_ARCHIVE_DATE = "P2960"
PID_SUBJECT_NAMED_AS = "P1810"
PID_TITLE = "P1476"


PID_UNION_LIST_OF_ARTIST_NAMES_ID = "P245"
QID_UNION_LIST_OF_ARTIST_NAMES = "Q2494649"

STATED_IN_FILE = "stated_in.json"

# https://www.wikidata.org/w/index.php?title=Q17267242&diff=prev&oldid=2194531410 puinhoop
# https://www.wikidata.org/w/index.php?title=Q87186864&diff=next&oldid=2195010750 same domain; split
# https://www.wikidata.org/w/index.php?title=Q105973291&diff=next&oldid=2195247889 country of citizinship
# Q63069711 vergelijkbare nalopen; zoeken op URL?


def is_archive_url(url: str) -> bool:
    if "web.archive.org" in url.lower():
        return True
    if "archive.is" in url.lower():
        return True
    if "wayback.archive-it.org" in url.lower():
        return True

    return False


def get_qry_count(query: str) -> int:
    try:
        response = requests.get(
            WDQS_ENDPOINT,
            params={"query": query, "format": "json"},
            timeout=READ_TIMEOUT,
        )
    except:
        return None

    payload = response.json()
    data = payload["results"]["bindings"]

    for row in data:
        count = int(row.get("count", {}).get("value", ""))
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
        query = template.format(index=index, limit=limit, pid=pid)
        sub_count = get_qry_count(query)
        if sub_count == None:
            break
        count = count + sub_count
        print(f"{index}: {sub_count}; total = {count}")
        index = index + limit

    return count


class SplitRefBot:
    def __init__(self, stated_in_list: statedin.StatedIn, generator: str):
        self.stated_in_list = stated_in_list
        self.generator = pagegenerators.PreloadingEntityGenerator(generator)
        self.split_getty = False

    def run(self):
        for item in self.generator:
            self.item = item
            self.examine_item()

    def examine_item(self):
        if not self.item.exists():
            return

        if self.item.isRedirectPage():
            return

        claims = self.item.get().get("claims")

        if not self.item.botMayEdit():
            raise RuntimeError(
                f"Skipping {self.item.title()} because it cannot be edited by bots"
            )

        for prop in ["P21", "P569", "P570", "P213", "P106"]:
            if prop in claims:
                for claim in claims[prop]:
                    new_sources = []
                    self.has_archive = False
                    claim_changed = False
                    for s in claim.sources:
                        if self.can_split_source(s):
                            source_changed, source_list = self.split_source(s)
                            claim_changed = claim_changed or source_changed
                            new_sources.extend(source_list)
                        else:
                            new_sources.append(s)
                    if claim_changed:
                        claim.sources = new_sources
                        if self.has_archive:
                            summary = "split reference with multiple reference urls + archive url"
                        else:
                            summary = "split reference with multiple reference urls"
                        self.save_claim(claim, summary)

    def get_single_claim(self, src, pid: str):
        if pid not in src:
            return None

        if len(src[pid]) > 1:
            return None

        return src[pid][0]

    def can_split_source(self, src) -> bool:
        if PID_REFERENCE_URL not in src:
            return False

        count = len(src[PID_REFERENCE_URL])
        if count <= 1:
            return False

        for prop in src:
            if self.split_getty and prop == PID_UNION_LIST_OF_ARTIST_NAMES_ID:
                continue
            if self.split_getty and prop == PID_STATED_IN:
                if len(src[prop]) != 1:
                    return False
                qid = src[prop][0].getTarget().getID()
                if qid == QID_UNION_LIST_OF_ARTIST_NAMES:
                    continue
                else:
                    return False

            if prop not in (
                PID_REFERENCE_URL,
                PID_RETRIEVED,
                PID_ARCHIVE_DATE,
                PID_ARCHIVE_URL,
            ):
                if PID_REFERENCE_URL in src and len(src[PID_REFERENCE_URL]) > 1:
                    print(f"{self.item.title()}: multiple Reference url, with {prop}")
                return False

        # do not accept multiple PID_ARCHIVE_URL
        if PID_ARCHIVE_URL in src and len(src[PID_ARCHIVE_URL]) > 1:
            print(f"{self.item.title()}: multiple Archive URL")
            return False

        # do not accept multiple PID_ARCHIVE_DATE
        if PID_ARCHIVE_DATE in src and len(src[PID_ARCHIVE_DATE]) > 1:
            print(f"{self.item.title()}: multiple Archive date")
            return False

        # do not accept multiple PID_RETRIEVED
        if PID_RETRIEVED in src and len(src[PID_RETRIEVED]) > 1:
            print(f"{self.item.title()}: multiple Retrieved")
            return False

        if PID_ARCHIVE_URL in src or PID_ARCHIVE_DATE in src:
            self.has_archive = True

        if PID_ARCHIVE_URL in src:
            archive_url = src[PID_ARCHIVE_URL][0].getTarget()
            found = False
            for value in src[PID_REFERENCE_URL]:
                url = value.getTarget()
                if url in archive_url:
                    found = True
                    break
            if not found:
                print(f"{self.item.title()}: unrecognized archive url: {archive_url}")
                return False

        domains = set()
        for value in src[PID_REFERENCE_URL]:
            url = value.getTarget()
            if is_archive_url(url):
                print(f"{self.item.title()}: found achive url {url}")
                return False

            stated_in_qid = self.stated_in_list.get_stated_in_from_url(url)
            if not stated_in_qid:
                # prevent splitting reference urls with the same domain but different langage, for example:
                # https://www.zaowouki.org/en/the-artist/biography/
                # https://www.zaowouki.org/fr/artiste/biographie/
                match = re.search(r"^https?:\/\/([a-z0-9._-]*)\/", url, re.IGNORECASE)
                if match:
                    domain = match.group(1)
                    if (
                        domain != "cantic.bnc.cat"
                        and domain != "arcade.nyarc.org"
                        and domain != "openlibrary.org"
                        and domain != "wikidata-externalid-url.toolforge.org"
                        and domain != "mak.bn.org.pl"
                        and domain != "www.degruyter.com"
                        and domain != "www.alvin-portal.org"
                        and domain != "www.artnet.com"
                        and domain != "resources.huygens.knaw.nl"
                        and domain != "librarycatalog.usj.edu.lb"
                        and domain != "ccbibliotecas.azores.gov.pt"
                        and domain != "www.invaluable.com"
                        and domain != "opac.rism.info"
                        and domain != "www.oxfordartonline.com"
                        and domain != "nl.go.kr"
                    ):
                        if domain in domains:
                            print(
                                f"{self.item.title()}: found duplicate domain {domain}"
                            )
                            return False
                        domains.add(domain)

        return True

    def save_claim(self, claim, summary: str):
        if not claim.on_item:
            claim.on_item = self.item
        try:
            REPO.save_claim(claim, summary=summary)
        except:
            print(self.item.title())
            pass

    def split_source(self, src):
        """
        Splits source with multiple reference urls into multiple sources with one reference url.

        Returns:
            tuple: A tuple containing a boolean flag indicating if any changes were made (changed) and a list of sources.
        """
        sources = []
        retrieved_claim = self.get_single_claim(src, PID_RETRIEVED)
        archive_date_claim = self.get_single_claim(src, PID_ARCHIVE_DATE)
        archive_url_claim = self.get_single_claim(src, PID_ARCHIVE_URL)
        if archive_url_claim:
            archive_url = archive_url_claim.getTarget()
        else:
            archive_url = None
        changed = len(src[PID_REFERENCE_URL]) > 1
        for value in src[PID_REFERENCE_URL]:
            source = OrderedDict()

            url = value.getTarget()
            stated_in_qid = self.stated_in_list.get_stated_in_from_url(url)
            if stated_in_qid:
                stated_in = pwb.Claim(REPO, PID_STATED_IN)
                stated_in.isReference = True
                stated_in.setTarget(pwb.ItemPage(REPO, stated_in_qid))
                stated_in.on_item = self.item
                source[PID_STATED_IN] = [stated_in]
                changed = True

            ref = pwb.Claim(REPO, PID_REFERENCE_URL)
            ref.isReference = True
            ref.setTarget(url)
            ref.on_item = self.item
            source[PID_REFERENCE_URL] = [ref]

            if retrieved_claim is not None:
                retr = pwb.Claim(REPO, PID_RETRIEVED)
                retr.isReference = True
                dt = retrieved_claim.getTarget()
                retr.setTarget(dt)
                retr.on_item = self.item
                source[PID_RETRIEVED] = [retr]

            if archive_url and url in archive_url:
                arch_url = pwb.Claim(REPO, PID_ARCHIVE_URL)
                arch_url.isReference = True
                arch_url.setTarget(archive_url)
                arch_url.on_item = self.item
                source[PID_ARCHIVE_URL] = [arch_url]

                if archive_date_claim is not None:
                    arch_date = pwb.Claim(REPO, PID_ARCHIVE_DATE)
                    arch_date.isReference = True
                    dt = archive_date_claim.getTarget()
                    arch_date.setTarget(dt)
                    arch_date.on_item = self.item
                    source[PID_ARCHIVE_DATE] = [arch_date]

                archive_url = None

            sources.append(source)

        return changed, sources


class AddIDBot:
    def __init__(self, stated_in_list: statedin.StatedIn, generator):
        self.stated_in_list = stated_in_list
        self.generator = pagegenerators.PreloadingEntityGenerator(generator)
        self.item = None
        self.test = True
        self.summary_list = []

    def examine(self, qid: str):
        if not qid.startswith("Q"):  # ignore property pages and lexeme pages
            return

        self.item = pwb.ItemPage(REPO, qid)

        self.examine_item()

    def run(self):
        for item in self.generator:
            self.item = item
            self.examine_item()

    def examine_item(self):
        if not self.item.exists():
            return

        if self.item.isRedirectPage():
            return

        claims = self.item.get().get("claims")

        if not self.item.botMayEdit():
            raise RuntimeError(
                f"Skipping {self.item.title()} because it cannot be edited by bots"
            )

        print(f"item = {self.item.title()}")
        for prop in claims:
            for claim in claims[prop]:
                if not claim.sources:
                    continue

                self.summary_list = []
                sources = claim.sources
                claim_changed, new_sources = self.change_sources(prop, claim, sources)

                if claim_changed:
                    summary = ", ".join(self.summary_list)
                    claim.sources = new_sources
                    if not self.test:
                        self.save_claim(claim, summary)

    def change_sources(self, prop, claim, sources):
        added, sources = self.add_id_sources(prop, claim, sources)
        archived, sources = self.set_archive_url_sources(prop, claim, sources)
        merged, sources = self.merge_sources(prop, claim, sources)
        return added or archived or merged, sources

    def add_id_sources(self, prop, claim, sources):
        new_sources = []
        claim_changed = False
        self.changes = set()
        for src in sources:
            new_src = self.add_id(src, prop)
            if new_src:
                claim_changed = True
                new_sources.append(new_src)
            else:
                # nothing changed, add original source
                new_sources.append(src)

        if claim_changed:
            change_list = list(self.changes)
            self.summary_list.append("changed reference url into " + ", ".join(change_list))

        return claim_changed, new_sources

    def set_archive_url_sources(self, prop, claim, sources):
        new_sources = []
        claim_changed = False
        for src in sources:
            new_src = self.set_archive_url(src)
            if new_src:
                claim_changed = True
                new_sources.append(new_src)
            else:
                # nothing changed, add original source
                new_sources.append(src)

        if claim_changed:
            self.summary_list.append("changed reference url into archive url")

        return claim_changed, new_sources

    def merge_sources(self, prop, claim, sources):
        if len(sources) <= 1:
            return False, sources

        new_sources = []
        claim_changed = False
        # Dictionary to store unique source identifiers
        mergeable = {}
        error_dict = {}
        self.changes = set()
        for src in sources:
            src_id = self.stated_in_list.get_id_from_source(src)
            if src_id:
                error = self.can_merge(src, src_id[0])
                if error:
                    # collect the errors, we only show the errors if we have duplicate src ids
                    error_dict.setdefault(src_id, []).append(error)
                elif src_id in mergeable: 
                    # If the source identifier already exists, merge the sources
                    index = mergeable[src_id]
                    new_sources[index] = self.merge(src_id, new_sources[index], src)
                    claim_changed = True
                    continue
                else:
                    # Otherwise, add the source identifier to the mergeable dictionary
                    mergeable[src_id] = len(new_sources)

            # Add the source, unless the source was merged above
            new_sources.append(src)

        if claim_changed:
            change_list = list(self.changes)
            self.summary_list.append("merged " + ", ".join(change_list))

        # show the errors for duplicate src ids
        for src_id in error_dict:
            if len(error_dict[src_id]) > 1:
                for error in error_dict[src_id]:
                    print(f"{prop} - {src_id[0]} {src_id[2]}: {error}")

        return claim_changed, new_sources

    def get_newest_date(self, pid: str, src):
        latest = None
        if pid in src:
            for value in src[pid]:
                d = value.getTarget()
                if d and not latest:
                    latest = d
                elif d and latest and (latest.normalize() < d.normalize()):
                    latest = d
        return latest

    def get_old_new_src(self, src1, src2):
        d1 = self.get_newest_date(PID_RETRIEVED, src1)
        d2 = self.get_newest_date(PID_RETRIEVED, src2)
        if d1 and d2:
            is_src1_oldest = d1.normalize() <= d2.normalize()
        else:
            is_src1_oldest = not d1
        if is_src1_oldest:
            return src1, src2
        else:
            return src2, src1

    def set_pid(self, pid: str, t, new_source):
        oldest_src, newest_src = t
        if pid in newest_src:
            new_source[pid] = newest_src[pid]
        elif pid in oldest_src:
            new_source[pid] = oldest_src[pid]

    def can_merge(self, src, pid: str):
        # Don't merge sources with multiple reference URLs;
        # these sources should probably be cleaned up first
        if PID_REFERENCE_URL in src:
            if len(src[PID_REFERENCE_URL]) > 1:
                return "source contains multiple reference urls"

        for prop in src:
            # Don't merge if the source contains other properties than these
            if prop not in [
                PID_STATED_IN,
                PID_REFERENCE_URL,
                PID_RETRIEVED,
                PID_SUBJECT_NAMED_AS,
                PID_TITLE,
                pid,
            ]:
                    
                return f"Source cannot be merged because it contains prop {prop}"

        return None

    def merge(self, src_id, src1, src2):
        pid, stated_in_qid, id = src_id

        new_source = OrderedDict()

        if stated_in_qid:
            stated_in = pwb.Claim(REPO, PID_STATED_IN)
            stated_in.isReference = True
            stated_in.setTarget(pwb.ItemPage(REPO, stated_in_qid))
            stated_in.on_item = self.item
            new_source[PID_STATED_IN] = [stated_in]

        if pid and id:
            self.changes.add(pid)
            pid_claim = pwb.Claim(REPO, pid)
            pid_claim.isReference = True
            pid_claim.setTarget(id)
            pid_claim.on_item = self.item
            new_source[pid] = [pid_claim]

        # remove reference urls;
        # skip stated in, retrieved and pid; these are already done above
        props = []
        for prop in src1:
            if prop not in props:
                props.append(prop)
        for prop in src2:
            if prop not in props:
                props.append(prop)
        skip = set([PID_STATED_IN, PID_REFERENCE_URL, PID_RETRIEVED, pid])

        props = [x for x in props if x not in skip]

        t = self.get_old_new_src(src1, src2)
        for prop in props:
            self.set_pid(prop, t, new_source)
        self.set_pid(PID_RETRIEVED, t, new_source)

        return new_source

    def add_id(self, src, skip_prop: str):
        if PID_REFERENCE_URL not in src:
            return None

        count = len(src[PID_REFERENCE_URL])
        if count > 1:
            return None

        for prop in src:
            if self.stated_in_list.is_id_pid(prop):
                return None

        ref = src[PID_REFERENCE_URL][0]
        url = ref.getTarget()
        res = self.stated_in_list.get_id_from_url(url)
        if res is None:
            print(f"unknown url {url}")
            return None

        pid, stated_in_qid, id = res
        if pid == skip_prop:
            return None

        # if self.test:
        #    print(f"{skip_prop} url: {url} => {pid} {id}")

        new_source = OrderedDict()

        if stated_in_qid:
            stated_in = pwb.Claim(REPO, PID_STATED_IN)
            stated_in.isReference = True
            stated_in.setTarget(pwb.ItemPage(REPO, stated_in_qid))
            stated_in.on_item = self.item
            new_source[PID_STATED_IN] = [stated_in]

        if pid and id:
            self.changes.add(pid)
            pid_claim = pwb.Claim(REPO, pid)
            pid_claim.isReference = True
            pid_claim.setTarget(id)
            pid_claim.on_item = self.item
            new_source[pid] = [pid_claim]

        for prop in src:
            if prop == PID_STATED_IN:
                continue
            if prop == PID_REFERENCE_URL:
                continue
            new_source[prop] = src[prop]

        return new_source

    def set_archive_url(self, src):
        if PID_REFERENCE_URL not in src:
            return None

        has_archive_url = False
        for value in src[PID_REFERENCE_URL]:
            url = value.getTarget()
            if is_archive_url(url):
                has_archive_url = True
                break

        if not has_archive_url:
            return None

        new_source = OrderedDict()
        for prop in src:
            if prop == PID_REFERENCE_URL:
                for value in src[prop]:
                    url = value.getTarget()
                    if is_archive_url(url):
                        arch_url = pwb.Claim(REPO, PID_ARCHIVE_URL)
                        arch_url.isReference = True
                        arch_url.setTarget(url)
                        arch_url.on_item = self.item

                        new_source.setdefault(PID_ARCHIVE_URL, []).append(arch_url)
                    else:
                        new_source.setdefault(prop, []).append(value)
            elif prop == PID_ARCHIVE_URL:
                for value in src[prop]:
                    new_source.setdefault(prop, []).append(value)
            else:
                new_source[prop] = src[prop]

        return new_source

    def save_claim(self, claim, summary: str):
        if not claim.on_item:
            claim.on_item = self.item
        REPO.save_claim(claim, summary=summary)


def split_slice(stated_in_list, prop, offset, limit):
    template = """SELECT DISTINCT ?item WHERE {{
            SERVICE bd:slice {{
                ?item p:{prop} ?statement.
                bd:serviceParam bd:slice.offset {offset} ;
                bd:slice.limit {limit} .
            }}
            ?statement prov:wasDerivedFrom ?ref.
            ?ref pr:P854 ?some_ref, ?some_ref2.
            FILTER(?some_ref != ?some_ref2)
            FILTER(NOT EXISTS {{ ?ref pr:P248 ?s. }})
            }}
            """
    query = template.format(prop=prop, offset=offset, limit=limit)

    generator = pagegenerators.PreloadingEntityGenerator(
        pagegenerators.WikidataSPARQLPageGenerator(query, site=REPO)
    )

    splitBot = SplitRefBot(stated_in_list, generator)
    splitBot.run()


def split(prop: str):
    stated_in_list = statedin.StatedIn()

    index = 0
    limit = 150_000
    while True:
        print(f"Index = {index}")
        split_slice(stated_in_list, prop, index, limit)

        index = index + limit


def split_getty():
    query = """SELECT distinct ?item WHERE {
        ?item ?some_prop ?statement.
        ?statement prov:wasDerivedFrom ?ref.
        ?ref pr:P248 wd:Q2494649.
        ?ref pr:P854 ?some_ref, ?some_ref2.
        ?ref pr:P245 ?some_id.
        FILTER(?some_ref != ?some_ref2)
        }"""

    stated_in_list = statedin.StatedIn()

    generator = pagegenerators.PreloadingEntityGenerator(
        pagegenerators.WikidataSPARQLPageGenerator(query, site=REPO)
    )

    splitBot = SplitRefBot(stated_in_list, generator)
    splitBot.split_getty = True
    splitBot.run()


def iter_P269():
    query = """SELECT DISTINCT ?item ?prop ?statement ?url WHERE {
            ?item ?prop ?statement.
            ?statement prov:wasDerivedFrom ?ref.
            ?ref pr:P854 ?url.
            FILTER(CONTAINS(LCASE(STR(?url)), "idref.fr"))
            FILTER(NOT EXISTS { ?ref pr:P269 ?s. })
            FILTER(?prop != p:P269)
            }
            LIMIT 50"""

    query = """SELECT DISTINCT ?item ?prop ?statement ?url WHERE {
            ?item ?prop ?statement.
            ?statement prov:wasDerivedFrom ?ref.
            ?ref pr:P854 ?url.
            FILTER(CONTAINS(LCASE(STR(?url)), "rkd.nl"))
            FILTER(NOT EXISTS { ?ref pr:P650 ?s. })
            FILTER(?prop != p:P650)
            }
            LIMIT 250"""

    query = """SELECT DISTINCT ?item ?prop ?statement ?url WHERE {
            SERVICE bd:slice {
                ?ref pr:P854 ?url.
                bd:serviceParam bd:slice.offset 2000000;
                bd:slice.limit 1000000 .
            }
            ?item ?prop ?statement.
            ?statement prov:wasDerivedFrom ?ref.
            FILTER(CONTAINS(LCASE(STR(?url)), "musicalics"))
            FILTER(NOT EXISTS { ?ref pr:P6925 ?s. })
            FILTER(?prop != p:P6925)
            }"""

    query = """SELECT distinct ?item ?statement  WHERE {
            ?item ?some_prop ?statement.
            ?statement prov:wasDerivedFrom ?ref1, ?ref2.
            ?ref1 pr:P248 wd:Q17299517.
            ?ref2 pr:P248 wd:Q17299517.
            FILTER(?ref1 != ?ref2)
            } LIMIT 100"""

    stated_in_list = statedin.StatedIn()

    generator = pagegenerators.PreloadingEntityGenerator(
        pagegenerators.WikidataSPARQLPageGenerator(query, site=REPO)
    )

    addBot = AddIDBot(stated_in_list, generator)
    addBot.run()


def add_id(qid: str, test: bool = True):
    stated_in_list = statedin.StatedIn()
    addIDBot = AddIDBot(stated_in_list, None)
    addIDBot.test = test
    addIDBot.examine(qid)


def zandbak():
    add_id("Q15397819", test=False)


def main() -> None:
    # zandbak()
    add_id("Q62127980", test = True)

    #iter_P269()
    # split("P106")
    # ["P21", "P569", "P570", "P213", "P106"]:
    # get_count("P569")
    # splitBot = SplitRefBot(stated_in_list, None)
    # splitBot.item = pwb.ItemPage(REPO, "Q100076969")
    # splitBot.examine_item()

    # unknown url http://www.artnet.com/artists/katsushika-hokusai/
    # unknown url https://opac.sbn.it/risultati-ricerca-avanzata?item:5032:BID=BVEV002335
    # unknown url https://openlibrary.org/authors/OL7598341A/Nick_Cave
    # unknown url http://www.moma.org/collection/artists/34
    # unknown url https://frankfurter-personenlexikon.de/node/498
    # unknown url https://www.deutsche-biographie.de/gnd121651363.html#ndbcontent
    # unknown url https://www.fine-arts-museum.be/nl/de-collectie/artist/claus-hugo-1
    # unknown url https://rkd.nl/en/explore/images/122771
    # unknown url https://www.musik-sammler.de/artist/luciano-pavarotti-gianni-morandi
    # unknown url https://www.tekstowo.pl/wykonawca,luciano_pavarotti.html
    # unknown url https://www.naxos.com/person/17308.htm
    # unknown url https://opac.sbn.it/opacsbn/opac/iccu/scheda_authority.jsp?bid=IT\ICCU\CUBV\103982
    # unknown url https://www.digitalarchivioricordi.com/it/people/display/9961

    # Q99234328; Q124344625; Q108634101; Q118118614
    # merge: Q86376351; Q62523359; Q63165263; Q97573321; Q62127980


if __name__ == "__main__":
    main()
