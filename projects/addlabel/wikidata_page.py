"""Fallback source: country/language information from the Wikidata item
itself. Only consulted when none of the authority sources provide language
info (see AddLabelBot.examine)."""

import pywikibot as pwb

import shared_lib.constants as wd
from shared_lib.wikidata_site import REPO

import addlabel.countries as countries
import addlabel.languages as languages
from addlabel.authority_page import AuthorityPage
from addlabel.countries import Countries
from addlabel.languages import Languages

# Items that already have a label in one of these languages are treated as
# associated with the corresponding country, so their labels are left alone
# (transliteration is risky there).
SKIP_LABEL_LANGUAGES = {
    "be": countries.QID_BELARUS,
    "he": countries.QID_ISRAEL,
    "ja": countries.QID_JAPAN,
    "ko": countries.QID_SOUTH_KOREA,
    "ru": countries.QID_RUSSIA,
    "uk": countries.QID_UKRAINE,
    "vi": countries.QID_VIETNAM,
    "zh": countries.QID_CHINA,
}


class WikidataPage(AuthorityPage):
    def __init__(
        self,
        qid: str,
        language_lookup: Languages,
        country_lookup: Countries,
    ):
        super().__init__(
            external_id=qid,
            page_language="",
            language_lookup=language_lookup,
            country_lookup=country_lookup,
        )

    def __str__(self):
        return f"""
                init_id: {self.initial_external_id}
                wikidata: {self.external_id}
                not found: {self.not_found}
                redirect: {self.is_redirect}
                countries: {self.country_codes()}
                languages: {self.language_codes()}
                hebrew: {self.has_hebrew_script()}
                cyrillic: {self.has_cyrillic_script()}
                non latin: {self.has_non_latin_script()}"""

    def get_short_desc(self) -> str:
        return "wikidata"

    def run(self):
        if not self.external_id.startswith("Q"):
            # ignore property pages and lexeme pages
            return

        self.item = pwb.ItemPage(REPO, self.external_id)

        if not self.item.exists():
            return

        if self.item.isRedirectPage():
            return

        self.claims = self.item.get().get("claims", {})

        self.process()

    def process(self):
        if wd.PID_COUNTRY_OF_CITIZENSHIP in self.claims:
            for claim in self.claims[wd.PID_COUNTRY_OF_CITIZENSHIP]:
                if claim.getRank() == "deprecated":
                    continue
                target = claim.getTarget()
                if target:
                    self.add_country(target.getID())

        if wd.PID_LANGUAGES_SPOKEN_WRITTEN_OR_SIGNED in self.claims:
            for claim in self.claims[wd.PID_LANGUAGES_SPOKEN_WRITTEN_OR_SIGNED]:
                if claim.getRank() == "deprecated":
                    continue
                self.add_language(claim.getTarget().getID())

        if wd.PID_NAME_IN_NATIVE_LANGUAGE in self.claims:
            for claim in self.claims[wd.PID_NAME_IN_NATIVE_LANGUAGE]:
                if claim.getRank() == "deprecated":
                    continue
                wiki_lang = claim.getTarget().language
                self.add_language(self.language_lookup.get_language_from_wiki(wiki_lang))

        # if nothing found, look at the sitelinks
        if not self.countries and not self.languages:
            for sitelink in self.item.sitelinks:
                self.add_language(self.language_lookup.get_language_from_wiki(sitelink))

            if languages.QID_HUNGARIAN in self.languages and len(self.languages) > 1:
                raise RuntimeError("Check hungarian in sitelinks")

        # for now, always add the country (resulting in skipping the label
        # change) for these languages
        for label_language, country_qid in SKIP_LABEL_LANGUAGES.items():
            if label_language in self.item.labels:
                self.add_country(country_qid)

        self.set_name_order(self.determine_name_order())


def main() -> None:
    try:
        p = WikidataPage(
            "Q107103494",
            language_lookup=Languages(),
            country_lookup=Countries(),
        )
        p.run()
        print(p)
    except RuntimeError as e:
        print(f"Runtime error: {e}")


if __name__ == "__main__":
    main()
