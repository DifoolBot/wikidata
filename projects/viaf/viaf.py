import requests
import json
import pywikibot as pwb
from datetime import datetime
import os.path
import authsource
import time

# todo; 
#    Q2177740: viaf id - no value


WD = "http://www.wikidata.org/entity/"
WDQS_ENDPOINT = "https://query.wikidata.org/sparql"
# VIAF_ENDPOINT = "https://viaf.org/viaf/search"

PID_VIAF_ID = "P214"
PID_STATED_IN = "P248"
PID_RETRIEVED = "P813"
PID_REFERENCE_URL = "P854"
PID_BASED_ON_HEURISTIC = "P887"

QID_VIRTUAL_INTERNATIONAL_AUTHORITY_FILE = "Q54919"
QID_INFERRED_FROM_VIAF_ID_CONTAINING_AN_ID_ALREADY_PRESENT_IN_THE_ITEM = "Q115111315"

AUTHORITY_SOURCE_CODE_WIKIDATA = "WKP"

SITE = pwb.Site("wikidata", "wikidata")
SITE.login()
SITE.get_tokens("csrf")
REPO = SITE.data_repository()

DUPLICATES_FILE = "duplicates.json"
DONE_FILE = 'done.json'
ERRORS_FILE = "errors.json"
IGNORES_FILE = "ignores.json"
PAGE_TITLE = "User:Difool/viaf_already_somewhere"
WIKI_FILE = 'wiki.txt'

MAX_LAG_BACKOFF_SECS = 10 * 60
WDQS_SLEEP_AFTER_TIMEOUT = 30  # sec
VIAF_SLEEP_AFTER_ERROR = 10 * 60


class ViafBot:
    def __init__(self, auth_src: authsource.AuthoritySource):
        self.auth_src = auth_src
        self.test = False
        self.duplicates = self.load_duplicates()
        self.errors = self.load_errors()
        self.ignores = self.load_ignores()

    def run(self):
        self.iterate()
        if not self.test:
            self.write_to_wiki(self.make_wikitext())
            if os.path.exists(DUPLICATES_FILE):
                os.remove(DUPLICATES_FILE)
            if os.path.exists(ERRORS_FILE):
                os.remove(ERRORS_FILE)
            self.update_done(self.auth_src.pid)

    def query_wdqs(self, query: str,  retry_counter: int = 3):
        response = requests.get(
            WDQS_ENDPOINT, params={"query": query, "format": "json"}
        )
        try:
            payload = response.json()
        except json.JSONDecodeError as e:
            # nothing more left to slice on WDQS
            if response.elapsed.total_seconds() < 3 and 'RuntimeException: offset is out of range' in response.text:
                return []

            # likely timed out, try again up to three times
            retry_counter -= 1
            if retry_counter > 0 and response.elapsed.total_seconds() > 55 and 'java.util.concurrent.TimeoutException' in response.text:
                time.sleep(WDQS_SLEEP_AFTER_TIMEOUT)
                return self.query_wdqs(query, retry_counter)

            raise RuntimeError(
                f'Cannot parse WDQS response as JSON; http status {response.status_code}; query time {response.elapsed.total_seconds():.2f} sec') from e

        return payload["results"]["bindings"]

    def query_viaf(self, aid: authsource.AuthorityID):
        try:
            self.auth_src.determine_search_code(aid)
            if aid.search_code == None:
                time.sleep(1)
                self.add_error(aid.qid,
                            "{qid}: {desc} {local_auth_id} no search code found".format(
                                qid=aid.qid, desc=self.auth_src.description, local_auth_id=aid.id_from_wikidata
                            )
                            )
                return []
        except Exception as e:
            print('*** determine_search_code error ***')
            print('Error: {error}'.format(error=e))
            time.sleep(10)
            self.add_error(aid.qid,
                           "{qid}: {desc} {local_auth_id} no search code found".format(
                               qid=aid.qid, desc=self.auth_src.description, local_auth_id=aid.id_from_wikidata
                           )
                           )
            return []

        url = "https://viaf.org/viaf/sourceID/{code}|{local_auth_id}/justlinks.json".format(
            code=self.auth_src.codes[0], local_auth_id=aid.search_code
        )
        try:
            response = requests.get(url)
        except requests.exceptions.ConnectionError as e:
            print('*** ConnectionError ***')
            print('Error: {error}'.format(error=e))
            time.sleep(VIAF_SLEEP_AFTER_ERROR)
            return []
        except Exception as e:
            print('*** Generic VIAF error ***')
            print('Error: {error}'.format(error=e))
            time.sleep(VIAF_SLEEP_AFTER_ERROR)
            return []

        if response.status_code == 404:
            time.sleep(1)
            self.add_error(aid.qid,
                           "{qid}: {desc} {local_auth_id} not found".format(
                               qid=aid.qid, desc=self.auth_src.description, local_auth_id=aid.id_from_wikidata
                           )
                           )
            return []
        try:
            data = response.json()
        except json.JSONDecodeError as e:
            self.add_error(aid.qid,
                           "{desc} {local_auth_id} returns an error: {error}".format(
                               desc=self.auth_src.description, local_auth_id=aid.id_from_wikidata, error=e
                           )
                           )
            return []

        return data

    def check_viaf_justlinks(self, data, aid: authsource.AuthorityID):
        res = {}

        if "viafID" not in data:
            return None

        viaf_id = data["viafID"]
        res["viaf_id"] = viaf_id
        res["has_local_auth_id"] = False
        res["has_wikidata"] = False
        res["has_error"] = False

        for code in self.auth_src.codes:
            if code in data:
                for id in data[code]:
                    if self.auth_src.is_same_id(id, aid):
                        res["has_local_auth_id"] = True
                    else:
                        self.add_error(aid.qid,
                                       "viaf id {viaf_id} of {qid} has another {desc} link".format(
                                           viaf_id=viaf_id, qid=aid.qid, desc=self.auth_src.description
                                       )
                                       )
                        res["has_error"] = True

        if AUTHORITY_SOURCE_CODE_WIKIDATA in data:
            for other_qid in data[AUTHORITY_SOURCE_CODE_WIKIDATA]:
                if other_qid == aid.qid:
                    res["has_wikidata"] = True
                else:
                    self.add_duplicate(aid.qid, other_qid, aid.id_from_wikidata, viaf_id)
                    self.add_error(aid.qid,
                                   "viaf id {viaf_id} of {qid} has another wikidata link".format(
                                       viaf_id=viaf_id, qid=aid.qid
                                   )
                                   )
                    res["has_error"] = True

        return res

    def create_viaf_ref(self, viaf_id: str):
        today = datetime.today()

        stated_in = pwb.Claim(REPO, PID_STATED_IN)
        stated_in.setTarget(
            pwb.ItemPage(REPO, QID_VIRTUAL_INTERNATIONAL_AUTHORITY_FILE)
        )

        id = pwb.Claim(REPO, PID_VIAF_ID)
        id.setTarget(viaf_id)

        retr = pwb.Claim(REPO, PID_RETRIEVED)
        dateCre = pwb.WbTime(
            year=int(today.strftime("%Y")),
            month=int(today.strftime("%m")),
            day=int(today.strftime("%d")),
        )
        retr.setTarget(dateCre)

        ref = pwb.Claim(REPO, PID_BASED_ON_HEURISTIC)
        ref.setTarget(
            pwb.ItemPage(
                REPO,
                QID_INFERRED_FROM_VIAF_ID_CONTAINING_AN_ID_ALREADY_PRESENT_IN_THE_ITEM,
            )
        )

        return [stated_in, id, retr, ref]

    def change_wikidata(self, aid: authsource.AuthorityID) -> None:
        if not aid.qid.startswith("Q"):  # ignore property pages and lexeme pages
            return

        item = pwb.ItemPage(REPO, aid.qid)

        try:
            if not item.exists():
                return
        except pwb.exceptions.MaxlagTimeoutError as ex:
            print(
                "max lag timeout. sleeping. failed to add claim for qid {qid}".format(qid=aid.qid))
            time.sleep(MAX_LAG_BACKOFF_SECS)
            return
        

        if item.isRedirectPage():
            return

        existing_claims = item.get().get("claims")

        if not item.botMayEdit():
            self.add_error(
                aid.qid, "Skipping %s because it cannot be edited by bots" % aid.qid)
            return

        if PID_VIAF_ID in existing_claims:
            self.add_error(
                aid.qid, "Skipping %s because it already has a VIAF ID" % aid.qid)
            return

        if self.auth_src.pid not in existing_claims:
            self.add_error(aid.qid, "Skipping {qid} because it has no {code} PID".format(
                qid=aid.qid, code=self.auth_src.pid))
            return

        found = False
        for claim in existing_claims[self.auth_src.pid]:
            id = claim.getTarget()
            if id == aid.id_from_wikidata:
                if claim.getRank() == "deprecated":
                    self.add_error(aid.qid, "Skipping {qid} because the {code} {local_auth_id} is deprecated".format(
                        qid=aid.qid, code=self.auth_src.pid, local_auth_id=aid.id_from_wikidata))
                    return
                found = True
                break

        if not found:
            self.add_error(aid.qid, "Skipping {qid} because it has no {code} {local_auth_id}".format(
                qid=aid.qid, code=self.auth_src.pid, local_auth_id=aid.id_from_wikidata))
            return

        if self.test:
            return

        print("Adding VIAF ID {viaf_id} to {qid}".format(
            viaf_id=aid.viaf_id, qid=aid.qid))
        try:
            claim = pwb.Claim(REPO, PID_VIAF_ID)
            claim.setTarget(aid.viaf_id)
            item.addClaim(
                claim,
                summary="Adding VIAF ID based on {desc}".format(
                    desc=self.auth_src.description
                ),
            )

            claim.addSources(
                self.create_viaf_ref(aid.viaf_id), summary="Adding VIAF reference"
            )

        except Exception as e:
            self.add_error(aid.qid, "Error adding claims: %s" % e)

    def get_duplicates_qids(self, aid: authsource.AuthorityID):
        res = []
        query = 'SELECT DISTINCT ?item WHERE {{ ?item p:P214 ?statement0. ?statement0 (ps:P214) "{viaf_id}". FILTER (?item != wd:{qid})}} LIMIT 5'.format(
            viaf_id=aid.viaf_id, qid=aid.qid
        )

        for row in self.query_wdqs(query):
            other_qid = row.get("item", {}).get("value", "").replace(WD, "")
            res.append(other_qid)
        return res

    def iterate_viaf(self, aid: authsource.AuthorityID) -> None:
        if aid.qid in self.duplicates:
            return
        if aid.qid in self.errors:
            return
        if aid.qid in self.ignores:
            return

        res = self.check_viaf_justlinks(
            self.query_viaf(aid), aid
        )
        if res is None:
            return

        aid.viaf_id = res["viaf_id"]
        has_local_auth_id = res["has_local_auth_id"]
        has_error = res["has_error"]

        if not has_local_auth_id:
            self.add_error(aid.qid,
                           "{viaf_id} has no {desc} link".format(
                               viaf_id=aid.viaf_id, desc=self.auth_src.description
                           )
                           )
            return

        duplicate_qids = self.get_duplicates_qids(aid)
        if duplicate_qids != []:
            self.add_error(aid.qid, "{qid} has duplicates: {dupl}".format(
                qid=aid.qid, dupl=duplicate_qids))
            for duplicate_qid in duplicate_qids:
                self.add_duplicate(aid.qid, duplicate_qid, aid.id_from_wikidata, aid.viaf_id)
        elif has_error:
            self.add_error(
                aid.qid, "{qid} has errors, but no duplicates".format(qid=aid.qid))
        else:
            print(
                "{qid} -> {viaf_id}; {desc} {local_auth_id}".format(
                    qid=aid.qid,
                    viaf_id=aid.viaf_id,
                    desc=self.auth_src.description,
                    local_auth_id=aid.id_from_wikidata,
                )
            )
            self.change_wikidata(aid)

    def make_wikitext(self):
        heading = '=={description}==\n'.format(description=self.auth_src.description)
        header = '{| class="wikitable sortable" style="vertical-align:bottom;"\n|-\n! VIAF\n! QID on the item\n! ID from cluster\n! 2nd QID\n! class="unsortable" | Compare'
        body = ""
        line = "\n|-\n| https://viaf.org/viaf/{viaf_id}\n| {{{{Q|{qid}}}}}\n| {auth_code}|{local_auth_id}\n| {{{{Q|{duplicate_qid}}}}}\n| {compare}"
        for qid in self.duplicates:
            # for row in self.duplicates[qid]:
            row = self.duplicates[qid][0]
            duplicate_qid = row["duplicate_qid"]
            auth_code = row["auth_code"]
            local_auth_id = row["local_auth_id"]
            viaf_id = row["viaf_id"]
            # https://dicare.toolforge.org/wikidata-diff/?qids=Q3218809+Q2920825&language=en
            compare = '[https://dicare.toolforge.org/wikidata-diff/?qids={qid1}+{qid2}&language=en compare]'.format(qid1=qid, qid2=duplicate_qid)
            body = body + line.format(
                viaf_id=viaf_id,
                qid=qid,
                auth_code=auth_code,
                local_auth_id=local_auth_id,
                duplicate_qid=duplicate_qid,
                compare=compare
            )
        footer = "\n|}"

        wikitext = f"{heading}{header}{body}{footer}"

        return wikitext

    def write_to_wiki(self, wikitext) -> None:
        #with open(WIKI_FILE, "w") as outfile:
        #    outfile.write(wikitext)
        #return
        # print(wikitext)
        # ==Union List of Artist Names ID==\n((.*)*\n)*?\|\}
        site = pwb.Site("wikidata", "wikidata")
        page = pwb.Page(site, PAGE_TITLE)
        page.text = page.text + '\n' + wikitext
        page.save(summary="upd", minor=False)

    def iterate(self):
        index = 0
        while True:
            print('Index = {index}'.format(index=index))
            if not self.iterate_index(index):
                return
            index = index + 100000

    def iterate_index(self, index: int) -> bool:
        # instance of (P31)
        # VIAF ID (P214)
        # Union List of Artist Names ID (P245)

        # humans with a Union List of Artist Names ID - not deprecated, without a VIAF ID
        # query_template = """SELECT DISTINCT ?item ?local_auth_id WHERE {{
        #                             ?item p:{pid} ?statement0.
        #                             ?statement0 ps:{pid} _:anyValueP245;
        #                                 wikibase:rank ?rank.
        #                             ?item p:P31 ?statement1.
        #                             ?statement1 ps:P31 wd:Q5.
        #                             FILTER(?rank != wikibase:DeprecatedRank)
        #                             ?item wdt:{pid} ?local_auth_id.
        #                             MINUS {{
        #                                 ?item p:P214 ?statement2.
        #                                 ?statement2 ps:P214 _:anyValueP214.
        #                             }}
        #                             }} LIMIT 3000
        #                             """
        
        query_template = """
                    SELECT DISTINCT ?item ?local_auth_id WHERE {{

                    SERVICE bd:slice {{
                        ?item wdt:{pid} ?local_auth_id .
                        bd:serviceParam bd:slice.offset {index} . # Start at item number (not to be confused with QID)
                        bd:serviceParam bd:slice.limit 100000 . # List this many items
                    }}
                    FILTER EXISTS {{?item wdt:P31 wd:Q5}}
                    MINUS {{?item p:P214  ?viaf}}
                    OPTIONAL {{?item p:{pid} ?statement0.
                                                        ?statement0 ps:{pid} _:anyValueP245;
                                                            wikibase:rank ?rank }}
                    FILTER(?rank != wikibase:DeprecatedRank)
                    }}
                    """

        qry = query_template.format(pid=self.auth_src.pid, index=index)
        r = self.query_wdqs(qry)
        if r == []:
            return False
        for row in r:
            qid = row.get("item", {}).get("value", "").replace(WD, "")
            local_auth_id = row.get("local_auth_id", {}).get("value", "")
            if len(qid) == 0:
                continue
            if len(local_auth_id) == 0:
                continue
            id = authsource.AuthorityID(qid, local_auth_id)
            self.iterate_viaf(id)
        return True

    def update_done(self, pid: str):
        if os.path.exists(DONE_FILE):
            with open(DONE_FILE, "r") as infile:
                done = json.load(infile)
        else:
            done = {}
        done[pid] = datetime.utcnow().strftime('%Y-%m-%d')
        with open(DONE_FILE, "w") as outfile:
            json.dump(done, outfile)

    def load_duplicates(self):
        if os.path.exists(DUPLICATES_FILE):
            with open(DUPLICATES_FILE, "r") as infile:
                duplicates = json.load(infile)
        else:
            duplicates = {}
        return duplicates

    def save_duplicates(self, duplicates):
        with open(DUPLICATES_FILE, "w") as outfile:
            json.dump(duplicates, outfile)

    def add_duplicate(self, qid, duplicate_qid, local_auth_id, viaf_id):
        if qid not in self.duplicates:
            self.duplicates[qid] = []
        self.duplicates[qid].append(
            {
                "duplicate_qid": duplicate_qid,
                "auth_code": self.auth_src.codes[0],
                "local_auth_id": local_auth_id,
                "viaf_id": viaf_id,
            })

        self.save_duplicates(self.duplicates)

    def add_error(self, qid, msg):
        print(msg)
        if qid not in self.errors:
            self.errors[qid] = []
        self.errors[qid].append(
            {
                "msg": msg,
            }
        )

        self.save_errors(self.errors)

    def load_errors(self):
        if os.path.exists(ERRORS_FILE):
            with open(ERRORS_FILE, "r") as infile:
                errors = json.load(infile)
        else:
            errors = {}
        return errors

    def save_errors(self, errors):
        with open(ERRORS_FILE, "w") as outfile:
            json.dump(errors, outfile)

    def load_ignores(self):
        if os.path.exists(IGNORES_FILE):
            with open(IGNORES_FILE, "r") as infile:
                ignores = json.load(infile)
        else:
            ignores = {}
        return ignores

def main() -> None:

    authsrc = authsource.AuthoritySources()
    # nothing found: 
    #              : PID_FAST_ID
    #              : PID_CONOR_SI_ID
    #              : PID_PERSEUS_AUTHOR_ID
    # lots of not found: PID_BIBLIOTECA_NACIONAL_DE_ESPANA_ID; PID_ISNI
    # niets gevonden: PID_EGAXA_ID; PID_BNRM_ID
    # done; PID_IDREF_ID; PID_GND_ID; PID_SBN_AUTHOR_ID; PID_NL_CR_AUT_ID; PID_VATICAN_LIBRARY_VCBA_ID; PID_NATIONAL_LIBRARY_OF_KOREA_ID
    #       PID_BNMM_AUTHORITY_ID; PID_NSK_ID; PID_LIBRARIES_AUSTRALIA_ID; PID_NATIONAL_LIBRARY_OF_BRAZIL_ID
    #       PID_CANADIANA_NAME_AUTHORITY_ID; PID_RISM_ID; PID_NORAF_ID; PID_NATIONAL_LIBRARY_OF_IRELAND_ID
    #       PID_LEBANESE_NATIONAL_LIBRARY_ID; PID_NATIONAL_LIBRARY_OF_ICELAND_ID
    #       PID_NATIONALE_THESAURUS_VOOR_AUTEURSNAMEN_ID; PID_NDL_AUTHORITY_ID; PID_RERO_ID_OBSOLETE
    #       PID_PORTUGUESE_NATIONAL_LIBRARY_AUTHOR_ID; PID_PLWABN_ID; PID_CANTIC_ID; PID_BANQ_AUTHORITY_ID; PID_RILM_ID
    #       PID_ELNET_ID; PID_DBC_AUTHOR_ID; PID_CINII_BOOKS_AUTHOR_ID; PID_NATIONAL_LIBRARY_OF_RUSSIA_ID
    #       PID_CYT_CCS; PID_NATIONAL_LIBRARY_OF_LATVIA_ID; PID_LIBRIS_URI; PID_BIBLIOTHEQUE_NATIONALE_DE_FRANCE_ID
    #       PID_SYRIAC_BIOGRAPHICAL_DICTIONARY_ID; PID_NUKAT_ID; PID_NATIONAL_LIBRARY_OF_CHILE_ID
    bot = ViafBot(authsrc.get(authsource.PID_CONOR_SI_ID))
    bot.test = False
    bot.run()


if __name__ == "__main__":
    main()
