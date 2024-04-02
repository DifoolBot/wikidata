import requests
import json
import pywikibot as pwb
from datetime import datetime, timezone
import authsource
import authdata
import time
import loc
import gnd
import idref
import bnf
import name as nm
from collections import defaultdict

# * skip and save if family first
# * alle todo weg
# * test bnf redirect; zie dubbelen


WD = "http://www.wikidata.org/entity/"
WDQS_ENDPOINT = "https://query.wikidata.org/sparql"
WDQS_SLEEP_AFTER_TIMEOUT = 30  # sec

SITE = pwb.Site("wikidata", "wikidata")
SITE.login()
SITE.get_tokens("csrf")
REPO = SITE.data_repository()

PID_STATED_IN = "P248"
PID_RETRIEVED = "P813"
PID_SEX_OR_GENDER = "P21"
PID_DATE_OF_BIRTH = "P569"
PID_DATE_OF_DEATH = "P570"
PID_BASED_ON_HEURISTIC = "P887"
PID_IMPORTED_FROM_WIKIMEDIA_PROJECT = "P143"


class AddLabelBot:
    def __init__(self, auth_src: authsource.AuthoritySource, language: str):
        self.auth_src = auth_src
        self.language = language
        self.test = False

    def run(self):
        self.iterate()

    def is_weak_source(self, source):
        if PID_BASED_ON_HEURISTIC in source:
            return True
        if PID_IMPORTED_FROM_WIKIMEDIA_PROJECT in source:
            return True

        return False

    def has_strong_source(self, existing_claims, pid: str):
        if pid not in existing_claims:
            return False

        for claim in existing_claims[pid]:
            srcs = claim.getSources()
            for src in srcs:
                if not self.is_weak_source(src):
                    return True

        return False

    def create_ref(self, info):
        s_stated_in_qid = info["stated in"]
        s_id_pid = info["id_pid"]
        s_id = info["id"]

        today = datetime.now(timezone.utc)
        stated_in = pwb.Claim(REPO, PID_STATED_IN)
        stated_in.setTarget(pwb.ItemPage(REPO, s_stated_in_qid))

        id = pwb.Claim(REPO, s_id_pid)
        id.setTarget(s_id)

        retr = pwb.Claim(REPO, PID_RETRIEVED)
        dateCre = pwb.WbTime(
            year=int(today.strftime("%Y")),
            month=int(today.strftime("%m")),
            day=int(today.strftime("%d")),
        )
        retr.setTarget(dateCre)

        return [stated_in, id, retr]

    def get_short_desc(self, pages):
        descs = []
        for page in pages:
            short_desc = page.get_short_desc()
            if short_desc not in descs:
                descs.append(short_desc)
        return ", ".join(descs)

    def examine(self, qid: str):
        if not qid.startswith("Q"):  # ignore property pages and lexeme pages
            return

        item = pwb.ItemPage(REPO, qid)

        if not item.exists():
            return

        if item.isRedirectPage():
            return

        existing_claims = item.get().get("claims")

        if not item.botMayEdit():
            print(f"Skipping {qid} because it cannot be edited by bots")
            return

        collector = authdata.Collector()

        # Define a dictionary mapping authority IDs to page classes
        authority_mapping = {
            authsource.PID_LIBRARY_OF_CONGRESS_AUTHORITY_ID: loc.LocPage,
            authsource.PID_BIBLIOTHEQUE_NATIONALE_DE_FRANCE_ID: bnf.BnfPage,
            authsource.PID_IDREF_ID: idref.IdrefPage,
            authsource.PID_GND_ID: gnd.GndPage,
        }

        # Iterate through each authority ID
        for authority_pid, page_class in authority_mapping.items():
            if authority_pid in existing_claims:
                for claim in existing_claims[authority_pid]:
                    if claim.getRank() != "deprecated":
                        id = claim.getTarget()
                        collector.add(page_class(id))

        collector.retrieve()
        if collector.has_redirect():
            print("has redirect")
            collector.resolve_redirect()
            return

        if collector.has_duplicates():
            print("has duplicate")
            return

        test = self.test
        if collector.name_order == nm.NAME_ORDER_EASTERN:
            print("skipping because name order is eastern")
            test = True

        # sex
        if not self.has_strong_source(existing_claims, PID_SEX_OR_GENDER):
            sex = collector.get_sex_info()
            if sex is not None:
                print(f"sex qid: {sex}")

                if not test:
                    claim = None
                    skip = False
                    if PID_SEX_OR_GENDER in existing_claims:
                        for c in existing_claims[PID_SEX_OR_GENDER]:
                            if c.getTarget().getID() == sex["qid"]:
                                if c.getRank() == "deprecated":
                                    skip = True
                                    break
                                claim = c
                                break

                    if not skip:
                        if claim is None:
                            claim = pwb.Claim(REPO, PID_SEX_OR_GENDER)
                            target = pwb.ItemPage(REPO, sex["qid"])
                            claim.setTarget(target)
                            item.addClaim(claim)

                        claim.addSources(self.create_ref(sex))

        # birth_date
        if not self.has_strong_source(existing_claims, PID_DATE_OF_BIRTH):
            birth_date = collector.get_date_info("birth")
            if birth_date is not None:
                print(f"birth date: {birth_date}")

                if not test:
                    date = birth_date["date"]
                    claim = None
                    skip = False
                    if PID_DATE_OF_BIRTH in existing_claims:
                        for c in existing_claims[PID_DATE_OF_BIRTH]:
                            if c.getTarget().normalize() == date.normalize():
                                if c.getRank() == "deprecated":
                                    skip = True
                                    break
                                claim = c
                                break

                    if not skip:
                        if claim is None:
                            claim = pwb.Claim(REPO, PID_DATE_OF_BIRTH)
                            claim.setTarget(date)
                            item.addClaim(claim)

                        claim.addSources(self.create_ref(birth_date))

        # death_date
        if not self.has_strong_source(existing_claims, PID_DATE_OF_DEATH):
            death_date = collector.get_date_info("death")
            if death_date is not None:
                print(f"death date: {death_date}")

                if not test:
                    date = death_date["date"]
                    claim = None
                    skip = False
                    if PID_DATE_OF_DEATH in existing_claims:
                        for c in existing_claims[PID_DATE_OF_DEATH]:
                            if c.getTarget().normalize() == date.normalize():
                                if c.getRank() == "deprecated":
                                    skip = True
                                    break
                                claim = c
                                break

                    if not skip:
                        if claim is None:
                            claim = pwb.Claim(REPO, PID_DATE_OF_DEATH)
                            claim.setTarget(date)
                            item.addClaim(claim)

                        claim.addSources(self.create_ref(death_date))

        # names
        labels = {}
        aliases = {}
        aliases = defaultdict(list)
        pages = []

        for language in ["en", "fr", "de"]:
            if language not in item.labels:
                names = collector.get_names(language)
                if names:
                    is_first = True
                    for name_obj in names:
                        name = name_obj["name"]
                        p = name_obj["pages"]
                        print(f"{language} name: {name} from {self.get_short_desc(p)}")
                        pages = pages + p
                        if is_first:
                            labels[language] = name
                        else:
                            aliases[language].append(name)

                        is_first = False

        if not test:
            data = {}
            if labels != {}:
                data["labels"] = labels
            if aliases != {}:
                data["aliases"] = aliases
            if data != {}:
                item.editEntity(data, summary=f"from {self.get_short_desc(pages)}")

    def iterate(self):
        index = 250000
        while True:
            print("Index = {index}".format(index=index))
            if not self.iterate_index(index):
                return
            index = index + 100000

    def query_wdqs(self, query: str, retry_counter: int = 3):
        response = requests.get(
            WDQS_ENDPOINT, params={"query": query, "format": "json"}
        )
        try:
            payload = response.json()
        except json.JSONDecodeError as e:
            # nothing more left to slice on WDQS
            if (
                response.elapsed.total_seconds() < 3
                and "RuntimeException: offset is out of range" in response.text
            ):
                return None

            # likely timed out, try again up to three times
            retry_counter -= 1
            if (
                retry_counter > 0
                and response.elapsed.total_seconds() > 55
                and "java.util.concurrent.TimeoutException" in response.text
            ):
                time.sleep(WDQS_SLEEP_AFTER_TIMEOUT)
                return self.query_wdqs(query, retry_counter)

            raise RuntimeError(
                f"Cannot parse WDQS response as JSON; http status {response.status_code}; query time {response.elapsed.total_seconds():.2f} sec"
            ) from e

        return payload["results"]["bindings"]

    def iterate_index(self, index: int) -> bool:
        query_template = """SELECT DISTINCT ?item ?authid WHERE {{
                    SERVICE bd:slice {{
                        ?item wdt:{pid} ?authid.
                        bd:serviceParam bd:slice.offset {index} ;
                        bd:slice.limit 100000 .
                    }}
                    ?item wdt:P214 ?viaf;
                        wdt:P31 wd:Q5.
                    OPTIONAL {{
                        ?item p:{pid} ?statement0.
                        ?statement0 ps:{pid} _:anyValueP245;
                        wikibase:rank ?rank.
                    }}
                    FILTER(?rank != wikibase:DeprecatedRank)
                    FILTER(NOT EXISTS {{
                        ?item rdfs:label ?itemLabel.
                        FILTER((LANG(?itemLabel)) = "{language}")
                    }})
                    }} LIMIT 10"""

        qry = query_template.format(
            pid=self.auth_src.pid, index=index, language=self.language
        )
        r = self.query_wdqs(qry)
        if r is None:
            return False
        for row in r:
            qid = row.get("item", {}).get("value", "").replace(WD, "")
            print(qid)
            authid = row.get("authid", {}).get("value", "")
            if len(qid) == 0:
                continue
            if len(authid) == 0:
                continue
            try:
                self.examine(qid)
            except RuntimeError as e:
                print(f"Runtime error: {e}")
        return True


def do_bnf():
    authsrcs = authsource.AuthoritySources()
    bot = AddLabelBot(
        authsrcs.get(authsource.PID_BIBLIOTHEQUE_NATIONALE_DE_FRANCE_ID), "fr"
    )
    bot.test = True
    bot.run()

def do_gnd():
    authsrcs = authsource.AuthoritySources()
    bot = AddLabelBot(
        authsrcs.get(authsource.PID_GND_ID), "de"
    )
    bot.test = True
    bot.run()

def do_loc():
    authsrcs = authsource.AuthoritySources()
    bot = AddLabelBot(
        authsrcs.get(authsource.PID_LIBRARY_OF_CONGRESS_AUTHORITY_ID), "en"
    )
    bot.test = True
    bot.run()


def do_single(qid: str):
    authsrcs = authsource.AuthoritySources()
    bot = AddLabelBot(
        authsrcs.get(authsource.PID_LIBRARY_OF_CONGRESS_AUTHORITY_ID), "en"
    )
    bot.test = True
    bot.examine(qid)


def main() -> None:
    do_gnd()


#     #bot.examine('Q3920227')
#     #bot.examine('Q112080201')
#     bot.examine('Q115781041')
# do_single('Q4069848')

# test: Q4093861; idref
# test: Q4069848; name error
# test: Q3825797; wrong name:
# test: Q111419974; veuve d'

if __name__ == "__main__":
    main()
