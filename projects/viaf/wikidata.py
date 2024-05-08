import requests
import name as nm
import authdata
import languagecodes as lc
import pywikibot as pwb

PID_COUNTRY_OF_CITIZENSHIP = "P27"
PID_LANGUAGES_SPOKEN_WRITTEN_OR_SIGNED = "P1412"
PID_NAME_IN_NATIVE_LANGUAGE = "P1559"

SITE = pwb.Site("wikidata", "wikidata")
SITE.login()
SITE.get_tokens("csrf")
REPO = SITE.data_repository()

skip_labels = {
    "be": "BLR",
    "he": "ISR",
    "ja": "JPN",
    "ko": "KOR",
    "ru": "RUS",
    "uk": "UKR",
    "vi": "VNM",
    "zh": "CHN",
}

class WikidataPage(authdata.AuthPage):
    def __init__(self, wikidata_id: str):
        super().__init__(
            id=wikidata_id,
            page_language="",
        )

    def __str__(self):
        output = f"""
                init_id: {self.init_id}
                wikidata: {self.id}
                not found: {self.not_found}
                redirect: {self.is_redirect}
                countries: {self.countries}
                languages: {self.languages}
                hebrew: {self.has_hebrew_script()}
                cyrillic: {self.has_cyrillic_script()}
                non latin: {self.has_non_latin_script()}"""
        return output

    def run(self):
        if not self.id.startswith("Q"):  # ignore property pages and lexeme pages
            return

        self.item = pwb.ItemPage(REPO, self.id)

        if not self.item.exists():
            return

        if self.item.isRedirectPage():
            return

        self.claims = self.item.get().get("claims")

        self.process()

    def get_short_desc(self) -> str:
        return "wikidata"


    def process(self):
        if PID_COUNTRY_OF_CITIZENSHIP in self.claims:
            for claim in self.claims[PID_COUNTRY_OF_CITIZENSHIP]:
                if claim.getRank() == "deprecated":
                    continue
                qid = claim.getTarget().getID()
                if qid not in lc.qid_country:
                    raise RuntimeError(f"Unknown country qid {qid}")
                country = lc.qid_country[qid]
                self.add_country(country)

        if PID_LANGUAGES_SPOKEN_WRITTEN_OR_SIGNED in self.claims:
            for claim in self.claims[PID_LANGUAGES_SPOKEN_WRITTEN_OR_SIGNED]:
                if claim.getRank() == "deprecated":
                    continue
                qid = claim.getTarget().getID()
                if qid not in lc.qid_language:
                    raise RuntimeError(f"Unknown language qid {qid}")
                lang = lc.qid_language[qid]
                self.add_language(lang)

        if PID_NAME_IN_NATIVE_LANGUAGE in self.claims:
            for claim in self.claims[PID_NAME_IN_NATIVE_LANGUAGE]:
                if claim.getRank() == "deprecated":
                    continue
                lan = claim.getTarget().language
                if lan not in lc.wikidata_language:
                    raise RuntimeError(f"Unknown wikidata language {lan}")
                lang = lc.wikidata_language[lan]
                self.add_language(lang)

        # if nothing found, look at the sitelinks
        if not self.countries and not self.languages:
            for sitelink in self.item.sitelinks:
                if sitelink not in lc.wikidata_sitelink:
                    raise RuntimeError(f"Unknown sitelink {sitelink}")
                country = lc.wikidata_sitelink[sitelink]
                self.add_country(country)
            
            if "HUN" in self.countries and len(self.countries) > 1:
                raise RuntimeError("Check hungarian in sitelinks") 

        # for now, always add country (resulting in skip changing the label) for these countries
        for lbl in skip_labels:
            if lbl in self.item.labels:
                self.add_country(skip_labels[lbl])

        self.set_name_order(self.get_name_order())


def main() -> None:
    # no language info: Q4526465; Q112415186; Q112437251
    # hebrew label: Q100989556; Q105548138
    # rembrandt: Q5598

    try:
        p = WikidataPage("Q107103494")
        p.run()
        print(p)
    except RuntimeError as e:
        print(f"Runtime error: {e}")


if __name__ == "__main__":
    main()
