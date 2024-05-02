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

# todo: sources bij gnd/bnf
# todo: comments below
# todo: test redirect + not found voor alle pages
# todo: redirect more simple
# todo: spatie weg bij bv. japanse naam
# todo: language bij bnf
# todo: prefix; -> family name last



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
PID_REASON_FOR_DEPRECATED_RANK = "P2241"
QID_WITHDRAWN_IDENTIFIER_VALUE = "Q21441764"


class AddLabelBot:
    def __init__(self, auth_src: authsource.AuthoritySource, language: str):
        self.auth_src = auth_src
        self.language = language
        self.test = False
        self.fix_redirect = True
        self.force_name_order = nm.NAME_ORDER_UNDETERMINED

    def run(self):
        self.iterate()

    def examine(self, qid: str):
        if not qid.startswith("Q"):  # ignore property pages and lexeme pages
            return

        self.item = pwb.ItemPage(REPO, qid)

        if not self.item.exists():
            return

        if self.item.isRedirectPage():
            return

        self.claims = self.item.get().get("claims")

        if not self.item.botMayEdit():
            print(f"Skipping {qid} because it cannot be edited by bots")
            return

        collector = authdata.Collector(force_name_order=self.force_name_order)

        # dictionary mapping authority IDs to page classes
        authority_mapping = {
            authsource.PID_LIBRARY_OF_CONGRESS_AUTHORITY_ID: loc.LocPage,
            authsource.PID_BIBLIOTHEQUE_NATIONALE_DE_FRANCE_ID: bnf.BnfPage,
            authsource.PID_IDREF_ID: idref.IdrefPage,
            authsource.PID_GND_ID: gnd.GndPage,
        }

        # Iterate through each authority ID
        for authority_pid, page_class in authority_mapping.items():
            if authority_pid in self.claims:
                for claim in self.claims[authority_pid]:
                    if claim.getRank() != "deprecated":
                        id = claim.getTarget()
                        collector.add(page_class(id))

        collector.retrieve()
        if collector.has_redirect():
            print("has redirect")
            if not self.test or self.fix_redirect:
                for page in collector.pages:
                    if page.is_redirect or page.not_found:
                        self.resolve_redirect_notfound(page)
            return

        if collector.has_duplicates():
            print("has duplicate")
            return
        
        for page in collector.pages:
            print(page)


        time.sleep(15)
        test = self.test
        if collector.name_order == nm.NAME_ORDER_EASTERN:
            print("skipping because name order is eastern")
            test = True

        # sex
        sex_info = collector.get_sex_info()
        if sex_info:
            print(f"sex: {sex_info}")
            if not test:
                self.add_qid_claim(PID_SEX_OR_GENDER, sex_info)

        # birth date
        birth_info = collector.get_date_info("birth")
        if birth_info:
            print(f"birth date: {birth_info}")
            if not test:
                self.add_date_claim(PID_DATE_OF_BIRTH, birth_info)

        # death date
        death_info = collector.get_date_info("death")
        if death_info:
            print(f"death date: {death_info}")
            if not test:
                self.add_date_claim(PID_DATE_OF_DEATH, death_info)

        # names
        labels = {}
        aliases = {}
        aliases = {}
        all_pages = []

        # skip de:
        for language in ["en", "fr", "de"]:
            # for language in ["en", "fr"]:
            if language not in self.item.labels:
                names = collector.get_names(language)
                if names:
                    is_first = True
                    for name_obj in names:
                        name = name_obj["name"]
                        pages = name_obj["pages"]
                        print(
                            f"{language} name: {name} from {self.get_short_desc(pages)}"
                        )
                        all_pages = all_pages + pages
                        if is_first:
                            labels[language] = name
                        else:
                            aliases.setdefault(language, []).append(name)

                        is_first = False

        if (
            not collector.has_hebrew_script()
            and not collector.has_cyrillic_script()
            and not test
        ):
            data = {}
            if labels:
                data["labels"] = labels
            if aliases:
                data["aliases"] = aliases
            if data:
                self.item.editEntity(
                    data, summary=f"from {self.get_short_desc(all_pages)}"
                )

    def iterate(self):
        index = 000000
        while True:
            print(f"Index = {index}")
            if not self.iterate_index(index):
                return
            index = index + 100000

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
                    }}"""

        qry = query_template.format(
            pid=self.auth_src.pid, index=index, language=self.language
        )
        r = self.query_wdqs(qry)
        if not r:
            return False
        for row in r:
            qid = row.get("item", {}).get("value", "").replace(WD, "")
            print(qid)
            authid = row.get("authid", {}).get("value", "")
            if not qid:
                continue
            if not authid:
                continue
            try:
                self.examine(qid)
            except RuntimeError as e:
                print(f"Runtime error: {e}")
        return True

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

    def add_date_claim(self, pid, date_info):
        if self.has_strong_source(pid):
            return

        date = date_info["date"]
        claim = None
        if pid in self.claims:
            for c in self.claims[pid]:
                if c.getTarget().normalize() == date.normalize():
                    if c.getRank() == "deprecated":
                        return
                    claim = c
                    break

        if not claim:
            claim = pwb.Claim(REPO, pid)
            claim.setTarget(date)
            self.item.addClaim(claim)

        claim.addSources(self.create_ref(date_info))

    def add_qid_claim(self, pid, qid_info):
        if self.has_strong_source(pid):
            return

        claim = None
        if pid in self.claims:
            for c in self.claims[pid]:
                if c.getTarget().getID() == qid_info["qid"]:
                    if c.getRank() == "deprecated":
                        return
                    claim = c
                    break

        if not claim:
            claim = pwb.Claim(REPO, pid)
            target = pwb.ItemPage(REPO, qid_info["qid"])
            claim.setTarget(target)
            self.item.addClaim(claim)

        claim.addSources(self.create_ref(qid_info))

    def has_strong_source(self, pid: str):
        if pid not in self.claims:
            return False

        for claim in self.claims[pid]:
            srcs = claim.getSources()
            for src in srcs:
                if not self.is_weak_source(src):
                    return True

        return False

    def is_weak_source(self, source):
        if PID_BASED_ON_HEURISTIC in source:
            return True
        if PID_IMPORTED_FROM_WIKIMEDIA_PROJECT in source:
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

    def resolve_redirect_notfound(self, page: authdata.AuthPage) -> None:
        for claim in self.claims[page.pid]:
            id = claim.getTarget()
            if id == page.init_id:
                if claim.getRank() == "deprecated":
                    continue
                if len(claim.qualifiers) >= 1:
                    continue
                if page.is_redirect:
                    self.set_redirect(claim, page.pid, page.id)
                elif page.not_found:
                    self.set_not_found(claim)

    def set_redirect(self, claim: pwb.Claim, pid: str, new_id: str):
        new_claim = self.get_claim(pid, new_id)
        if not new_claim:
            claim.changeTarget(new_id, summary="redirect")
            return

        if new_claim.getRank() == "deprecated":
            print("target of redirect is deprecated")
            return

        for source in claim.sources:
            sources = []
            for value_list in source.values():
                l = []
                for value in value_list:
                    c = value.copy()
                    l.append(c)
                sources.extend(l)
            # error same hash if the reference is same
            new_claim.addSources(sources, summary="copy ref")

        self.item.removeClaims(claim, summary="redirect")

    def set_not_found(self, claim: pwb.Claim) -> None:
        if claim.getRank() != "deprecated":
            claim.changeRank("deprecated", summary="not found")
        qualifier = pwb.Claim(REPO, PID_REASON_FOR_DEPRECATED_RANK)
        target = pwb.ItemPage(REPO, QID_WITHDRAWN_IDENTIFIER_VALUE)
        qualifier.setTarget(target)
        claim.addQualifier(qualifier)

    def get_claim(self, pid: str, id: str) -> pwb.Claim:
        for claim in self.claims[pid]:
            if claim.getTarget() == id:
                return claim

        return None


def do_bnf():
    authsrcs = authsource.AuthoritySources()
    bot = AddLabelBot(
        authsrcs.get(authsource.PID_BIBLIOTHEQUE_NATIONALE_DE_FRANCE_ID), "fr"
    )
    bot.test = True
    bot.run()


def do_gnd():
    authsrcs = authsource.AuthoritySources()
    bot = AddLabelBot(authsrcs.get(authsource.PID_GND_ID), "de")
    bot.test = True
    bot.run()


def do_loc():
    authsrcs = authsource.AuthoritySources()
    bot = AddLabelBot(
        authsrcs.get(authsource.PID_LIBRARY_OF_CONGRESS_AUTHORITY_ID), "en"
    )
    bot.test = True
    bot.run()


def do_idref():
    authsrcs = authsource.AuthoritySources()
    bot = AddLabelBot(authsrcs.get(authsource.PID_IDREF_ID), "fr")
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
    do_idref()
    #do_single("Q24701281")

    # ukranian; julian + gregorian: Q3920227
    # name with title: Q112080201
    # redirect: Q4263564
    # invalid chars in name: Q6070246
    # conflicting name order: Q3141116 
    # veuve d': Q111419974
    # hungary: Q24680637; Q24701318; Q24701281; Q25466541; Q25466606; Q1004670

if __name__ == "__main__":
    main()
