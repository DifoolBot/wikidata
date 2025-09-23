import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

import mwparserfromhell
import pywikibot as pwb
import wikipedia.template_date_extractor as tde
import yaml
from dateutil.parser import parse as date_parse
from mwparserfromhell.nodes import Template, Wikilink
from pywikibot.data import sparql

import shared_lib.change_wikidata as cwd
import shared_lib.constants as wd
from shared_lib.calendar_system_resolver import (
    DateCalendarService,
    load_template_config,
)
from shared_lib.locale_resolver import LocaleResolver
from shared_lib.lookups.interfaces.place_lookup_interface import (
    CountryLookupInterface,
    LanguageLookupInterface,
    PlaceLookupInterface,
)

# TODO
# - Q3290522: 'July 28, 2008 (aged 87)' -> date parse error
# - Q6097011: ''16 de November de 2002 (81 años)' -> date parser error
# - Q12441676: '20 January 1993(aged 72)' -> date parse error
# - Q4978907: alder in template with birth param
# - Q3894616: weird date parse errors
# - circa? -> raise exception
# - move wiki from error description to new column
# - Q23542792: geeft een foute datum (birth/death)
# - Q18747311: check; is Julian should be Gregorian?

# steps:
#   O1. move code to other computer
#   O2. check in code
#    3. review, clean up code
#    4. changes:
#   O     - lead text to database
#   O     - generate report of mismatches
#   O5. make request
#    6. iterate 50 items
#    7. publish request

YAML_DIR = Path(__file__).parent

SITE = pwb.Site("wikidata", "wikidata")


# Abstract base class for tracking Wikidata item processing status
class WikidataStatusTracker(ABC):
    @abstractmethod
    def is_done(self, qid: str) -> bool:
        """Return True if the item is already marked as done."""
        pass

    @abstractmethod
    def mark_done(self, qid: str, language: Optional[str], message: str):
        """Mark the item as done."""
        pass

    @abstractmethod
    def mark_error(self, qid: str, error: str):
        """Mark the item as errored, with an error message."""
        pass

    @abstractmethod
    def is_error(self, qid: str) -> bool:
        """Return True if the item is marked as errored."""
        pass

    # @abstractmethod
    # def get_country_qid(self, place_qid: str):
    #     """Return the QID of the country for a given place QID."""
    #     pass

    # @abstractmethod
    # def set_country_info(
    #     self, country_qid: str, country_code: Optional[str], country_desc: str
    # ):
    #     pass

    # @abstractmethod
    # def get_country_info(self, country_qid: str) -> Optional[Tuple]:
    #     pass

    # @abstractmethod
    # def set_country_qid(
    #     self, place_qid: str, place_label: str, country_qid: str, country_label: str
    # ):
    #     """Set the country QID for a given place QID."""
    #     pass

    # @abstractmethod
    # def get_languages_for_country(self, country_qid: str) -> List[str]:
    #     """Return a list of languages for a given country QID."""
    #     pass

    # @abstractmethod
    # def get_sorted_languages(self) -> List[str]:
    #     pass

    @abstractmethod
    def add_lead_sentence(self, qid: str, lang: str, lead_sentence: str):
        pass

    # @abstractmethod
    # def get_wikipedia_qid(self, lang: Optional[str]):
    #     pass

    @abstractmethod
    def add_mismatch(
        self, qid: str, lang: str, kind: str, wikidata_dates, wikipedia_dates, url
    ):
        pass

    # def ensure_country_info(
    #     self,
    #     qid: Optional[str] = None,
    #     code: Optional[str] = None,
    # ):
    #     if not qid:
    #         qid = get_country_qid_from_yaml(code, "countries.yaml")
    #     if not qid:
    #         info = lookup_country_info_by_code(code)
    #         if not info:
    #             raise RuntimeError(f"No country info for country code {code}")
    #         qid, code, description = info
    #         if qid:
    #             if not self.get_country_info(qid):
    #                 self.set_country_info(qid, code, description)
    #         return info

    #     # load from database
    #     info = self.get_country_info(qid)
    #     if info:
    #         qid, code, description = info
    #         if not code or not description:
    #             # reload from wikidata
    #             info = None
    #     if not info:
    #         info = lookup_country_info_by_qid(qid)
    #         if info:
    #             qid, code, description = info
    #             self.set_country_info(qid, code, description)
    #     if not info:
    #         raise RuntimeError(f"No country info for {qid}")
    #     return info


def wbtime_key(w: pwb.WbTime):
    w_norm = w.normalize()
    return (
        w_norm.year,
        w_norm.month,
        w_norm.day,
        w_norm.precision,
        w_norm.calendarmodel,
    )


def wbtime_key_flexible(w: pwb.WbTime):
    # Returns a tuple, but with calendarmodel set to None if unspecified
    w_norm = w.normalize()
    if w_norm.calendarmodel == wd.URL_UNSPECIFIED_CALENDAR:
        return (w_norm.year, w_norm.month, w_norm.day, w_norm.precision, None)
    return (
        w_norm.year,
        w_norm.month,
        w_norm.day,
        w_norm.precision,
        w_norm.calendarmodel,
    )


def wbtime_key_ignore(w: pwb.WbTime):
    # Returns a tuple, but with calendarmodel set to None if unspecified
    w_norm = w.normalize()
    return (
        w_norm.year,
        w_norm.month,
        w_norm.day,
        w_norm.precision,
        None,
    )


def wbtime_keys_match(key1, key2) -> bool:
    return key1[:4] == key2[:4] and (
        key1[4] is None or key2[4] is None or key1[4] == key2[4]
    )


@dataclass
class PersonDates:

    birth: List[pwb.WbTime] = field(default_factory=list)
    death: List[pwb.WbTime] = field(default_factory=list)

    def all_dates(self) -> List[pwb.WbTime]:
        return self.birth + self.death

    def deduplicate(self):
        def wbtime_key(w: pwb.WbTime):
            return (w.year, w.month, w.day, w.precision, w.calendarmodel)

        birth_dict = {wbtime_key(d): d for d in self.birth}
        death_dict = {wbtime_key(d): d for d in self.death}

        self.birth = list(birth_dict.values())
        self.death = list(death_dict.values())

    def to_iso(self) -> dict:
        def wb_to_iso(w: pwb.WbTime) -> str:
            y = str(w.year)
            m = f"{w.month:02}" if w.precision >= 10 and w.month else None
            d = f"{w.day:02}" if w.precision == 11 and w.day else None
            return "-".join(filter(None, [y, m, d]))

        return {
            "dob": [wb_to_iso(d) for d in self.birth],
            "dod": [wb_to_iso(d) for d in self.death],
        }

    def match_date(
        self, parsed, match_type="strict", include="both"
    ) -> list[pwb.WbTime]:
        """Return matching WbTime objects for a given parsed date.

        Args:
            parsed (date): The Python date object to compare.
            match_type (str): 'strict' compares year/month/day; 'year' compares just year.
            include (str): 'birth', 'death', or 'both'.

        Returns:
            list[WbTime]: Matching Wikidata time objects.
        """

        def matches(wb: pwb.WbTime) -> bool:
            if match_type == "strict":
                return (
                    wb.year == parsed.year
                    and wb.month == parsed.month
                    and wb.day == parsed.day
                )
            elif match_type == "year":
                return wb.year == parsed.year
            return False

        candidates = []
        if include in ("birth", "both"):
            candidates.extend([d for d in self.birth if matches(d)])
        if include in ("death", "both"):
            candidates.extend([d for d in self.death if matches(d)])
        return candidates


def print_dates(dates: List[pwb.WbTime]) -> str:
    CALENDAR_LABELS = {
        wd.URL_PROLEPTIC_JULIAN_CALENDAR: "Julian",
        wd.URL_PROLEPTIC_GREGORIAN_CALENDAR: "Gregorian",
        wd.URL_UNSPECIFIED_CALENDAR: "Unspecified",
    }

    def describe(date: pwb.WbTime) -> str:
        parts = [
            f"y={date.year}" if date.year and date.precision >= 9 else None,
            f"m={date.month}" if date.month and date.precision >= 10 else None,
            f"d={date.day}" if date.day and date.precision >= 11 else None,
            f"p={date.precision}",
            (
                CALENDAR_LABELS.get(date.calendarmodel)
                if date.calendarmodel is not None
                else None
            ),
        ]
        return ",".join(p for p in parts if p is not None)

    return ";".join(describe(d) for d in dates)


def compare_dates_asymmetric(wikipedia_dates, wikidata_dates, key_fn):
    """
    Compare Wikidata dates against Wikipedia dates.
    Returns matched Wikipedia dates and unmatched Wikidata dates.
    """
    matched_wikipedia = []
    unmatched_wikidata = []

    for wd_date in wikidata_dates:
        match_found = False
        wd_key = key_fn(wd_date)
        for wp_date in wikipedia_dates:
            wp_key = key_fn(wp_date)
            if wbtime_keys_match(wd_key, wp_key):
                matched_wikipedia.append(wp_date)
                match_found = True
                break
        if not match_found:
            unmatched_wikidata.append(wd_date)

    return matched_wikipedia, unmatched_wikidata


def fetch_page(site, title):
    page = pwb.Page(site, title)
    if not page.exists():
        return None
    return page.text  # raw wikitext


def get_country_qid_from_yaml(
    country_code: Optional[str], filename: str
) -> Optional[str]:
    if not country_code:
        return None

    path = YAML_DIR / filename
    with path.open(encoding="utf-8") as f:
        config = yaml.safe_load(f)
    for key, value in config.items():
        if value.get("code") == country_code:
            return key
    return None


class PersonLocale:
    def __init__(
        self,
        item: pwb.ItemPage,
        country_lookup: CountryLookupInterface,
        place_lookup: PlaceLookupInterface,
        language_lookup: LanguageLookupInterface,
        tracker: WikidataStatusTracker,
    ):
        self.item = item
        self.tracker = tracker
        self.birth_country_qids = set()
        self.death_country_qids = set()
        self.country_qids = set()
        self.country: Optional[str] = None
        self.language: Optional[str] = None
        self.wikipedia_qid: Optional[str] = None
        self.url: Optional[str] = None
        self.sitelink = None
        self.locale = LocaleResolver(place_lookup, language_lookup)
        self.country_lookup = country_lookup
        # self.place_lookup = place_lookup
        self.language_lookup = language_lookup

    def load(self):
        cwd.ensure_loaded(self.item)

        self.locale.load_from_claims(self.item.claims)
        # # Helper to filter claims by rank
        # def filter_claims_by_rank(claims):
        #     preferred_claims = [
        #         c for c in claims if getattr(c, "rank", "").lower() == "preferred"
        #     ]
        #     if preferred_claims:
        #         return preferred_claims
        #     # If no preferred, use normal (or any non-deprecated)
        #     return [
        #         c
        #         for c in claims
        #         if getattr(c, "rank", "").lower() not in ("deprecated",)
        #     ]

        # # Place of birth
        # if self.item.claims.get("P19"):
        #     claims = filter_claims_by_rank(self.item.claims["P19"])
        #     for claim in claims:
        #         target = claim.getTarget()
        #         if not target:
        #             continue
        #         place_qid = target.id
        #         country_qid = self.tracker.get_country_qid(place_qid)
        #         if not country_qid:
        #             result = lookup_country_qid(place_qid)
        #             if result:
        #                 country_qid, place_label, country_label = result
        #                 self.tracker.set_country_qid(
        #                     place_qid, place_label, country_qid, country_label
        #                 )
        #         if not country_qid:
        #             raise RuntimeError(
        #                 f"Country QID not found for place of birth claim in self.item {self.item.id}"
        #             )
        #         self.birth_country_qids.add(country_qid)
        #         self.country_qids.add(country_qid)

        # # Place of death
        # if self.item.claims.get("P20"):
        #     claims = filter_claims_by_rank(self.item.claims["P20"])
        #     for claim in claims:
        #         target = claim.getTarget()
        #         if not target:
        #             continue
        #         place_qid = target.id
        #         country_qid = self.tracker.get_country_qid(place_qid)
        #         if not country_qid:
        #             result = lookup_country_qid(place_qid)
        #             if result:
        #                 country_qid, place_label, country_label = result
        #                 self.tracker.set_country_qid(
        #                     place_qid, place_label, country_qid, country_label
        #                 )
        #         if not country_qid:
        #             raise RuntimeError(
        #                 f"Country QID not found for place of death claim in self.item {self.item.id}"
        #             )
        #         self.death_country_qids.add(country_qid)
        #         self.country_qids.add(country_qid)

        # # Country of citizenship
        # if self.item.claims.get("P27"):
        #     claims = filter_claims_by_rank(self.item.claims["P27"])
        #     for claim in claims:
        #         country_qid = claim.getTarget().id
        #         if not country_qid:
        #             raise RuntimeError(
        #                 f"Country QID not found for citizenship claim in self.item {self.item.id}"
        #             )
        #         self.country_qids.add(country_qid)

        # self.locale.sorted_countries = self.get_weighted_countries()
        # self.locale.sorted_languages = self.get_weighted_languages()
        self.sitekey = self.get_preferred_sitekey()
        if not self.sitekey:
            raise RuntimeError("No most relevant Wikipedia page")
        self.sitelink = self.item.sitelinks[self.sitekey]
        self.language = self.sitelink.site.lang
        if not self.language:
            raise RuntimeError("No language code for Wikipedia page")
        self.url = f":{self.sitelink.site.code}:{self.sitelink.title}"

        self.lang_config = tde.LanguageConfig(
            self.language, load_template_config("languages.yaml")
        )
        if not self.lang_config.month_map:
            if self.language != "en":
                raise RuntimeError(f"No month_map for language {self.language}")

        self.country = self.locale.get_country()
        if not self.country:
            country_code = self.lang_config.fallback_countrycode
            if not country_code:
                raise RuntimeError(
                    f"Language {self.language} has no fallback_countrycode"
                )
            info = self.country_lookup.get_country_by_code(country_code)
            if not info:
                raise RuntimeError(
                    f"Country code {country_code} not found in database for language {self.language}"
                )
            country_qid, country_code, country_label = info
            self.country = country_qid

        self.date_service = DateCalendarService(
            country_qid=self.country, country_lookup=self.country_lookup
        )
        # CountryConfig(
        #     self.country, load_template_config("countries.yaml")
        # )
        # if not self.date_service.first_gregorian_date:
        #     ensure_qid_in_yaml(
        #         qid=self.country, filename="countries.yaml", tracker=self.tracker
        #     )
        # if not self.date_service.first_gregorian_date:
        #     raise RuntimeError(f"No first_gregorian_date for {self.country}")
        self.wikipedia_qid = self.language_lookup.get_wikipedia_qid(self.language)
        if not self.wikipedia_qid:
            raise RuntimeError(f"No qid for language {self.language}")

    def get_preferred_sitekey(self) -> Optional[str]:
        sitelinks = self.item.sitelinks
        # Filter out unusable sitelinks
        usable_sitelinks = {
            k: v
            for k, v in sitelinks.items()
            if k != "commonswiki" and "wikisource" not in k and "wikiquote" not in k
        }

        if len(usable_sitelinks) == 0:
            raise RuntimeError("No usable Wikipedia page")
        if len(usable_sitelinks) == 1:
            # Only one usable sitelink, return it directly
            sitekey = next(iter(usable_sitelinks.keys()))
            return sitekey

        for lang in self.locale.get_languages():
            sitekey = f"{lang}wiki"
            if sitekey in usable_sitelinks:
                return sitekey

        # Tracker returns a list of wikis sorted by active users
        if self.language_lookup:
            languages = self.language_lookup.get_sorted_languages()
            if languages:
                for lang in languages:
                    sitekey = f"{lang}wiki"
                    if sitekey in usable_sitelinks:
                        return sitekey

        return None

    # def get_weighted_countries(self):
    #     weights = {
    #         3: self.birth_country_qids,
    #         2: self.death_country_qids,
    #         1: self.country_qids,
    #     }

    #     country_scores = defaultdict(int)

    #     for weight, qid_set in weights.items():
    #         for country_qid in qid_set:
    #             country_scores[country_qid] += weight

    #     # Sort by score descending and return only the QIDs
    #     sorted_country_qids = [
    #         qid for qid, _ in sorted(country_scores.items(), key=lambda x: -x[1])
    #     ]
    #     return sorted_country_qids

    # def get_weighted_languages(self):
    #     weights = {
    #         3: self.birth_country_qids,
    #         2: self.death_country_qids,
    #         1: self.country_qids,
    #     }

    #     language_scores = defaultdict(int)

    #     for weight, qid_set in weights.items():
    #         for country_qid in qid_set:
    #             langs = self.tracker.get_languages_for_country(country_qid)
    #             if not langs:
    #                 self.tracker.ensure_country_info(qid=country_qid)

    #                 raise RuntimeError(
    #                     f"No languages found for country QID {country_qid} in item {self.item.id}"
    #                 )
    #             for lang_qid in langs:
    #                 language_scores[lang_qid] += weight

    #     # Sort by score descending
    #     sorted_language_qids = [
    #         lang for lang, _ in sorted(language_scores.items(), key=lambda x: -x[1])
    #     ]
    #     return sorted_language_qids


def walk_templates(wikicode, parent=None, graph=None):
    if graph is None:
        graph = []

    for node in wikicode.nodes:
        if isinstance(node, mwparserfromhell.nodes.Template):
            graph.append((node, parent))  # (child, parent)
            # Recursively walk parameters
            for param in node.params:
                walk_templates(param.value, parent=node, graph=graph)
        elif isinstance(node, mwparserfromhell.wikicode.Wikicode):
            walk_templates(node, parent=parent, graph=graph)

    return graph


class EntityDateReconciler:
    def __init__(
        self,
        page: cwd.WikiDataPage,
        locale: PersonLocale,
        tracker: WikidataStatusTracker,
    ):
        self.page = page
        self.sitelink = locale.sitelink
        self.locale = locale
        self.tracker = tracker
        self.wikicode: Optional[mwparserfromhell.wikicode.Wikicode] = None
        self.qid = self.page.item.id

    def extract_distinct_dates(self) -> PersonDates:
        template_graph = walk_templates(self.wikicode)
        dob_dates = []
        dod_dates = []
        for child, parent in template_graph:
            name = tde.normalize_wikicode_name(child.name.strip_code())
            if name in self.locale.lang_config.date_templates:
                continue
            if name not in self.locale.lang_config.template_map:
                continue

            if parent:
                parent_name = tde.normalize_wikicode_name(parent.name.strip_code())
                if not self.locale.lang_config.is_known_template(parent_name):
                    raise RuntimeError(
                        f"Unknown parent template: {parent_name}, child: {name}"
                    )

            for tpl_cfg in self.locale.lang_config.template_map[name]:
                extractor = tde.TemplateDateExtractor(
                    tpl_cfg, child, self.locale.lang_config, self.locale.date_service
                )
                for typ, wbt in extractor.get_all_dates():
                    if typ == "birth":
                        dob_dates.append(wbt)
                    elif typ == "death":
                        dod_dates.append(wbt)
        result = PersonDates(birth=dob_dates, death=dod_dates)
        result.deduplicate()
        if len(result.birth) > 1 or len(result.death) > 1:
            raise RuntimeError(f"Multiple DOBs or DODs detected: {result.to_iso()}")
        return result

    def find_single_param_date_matches(self, wikidata_dates: PersonDates) -> list[dict]:
        matches = []
        if not self.wikicode:
            return matches
        for tpl in self.wikicode.filter_templates():
            name = tde.normalize_wikicode_name(tpl.name.strip_code())
            # skip generic date templates
            if name in self.locale.lang_config.date_templates:
                continue
            if name in self.locale.lang_config.ignore_templates:
                continue
            for p in tpl.params:
                param = p.value.strip_code().strip()
                param_name = str(p.name).strip()
                if not param:
                    continue
                for dayfirst in [True, False]:
                    try:
                        parsed_date = date_parse(
                            self.locale.lang_config.normalize_date_str(param),
                            dayfirst=dayfirst,
                            fuzzy=True,
                        ).date()
                    except Exception:
                        continue

                    iso_date = parsed_date.isoformat()
                    for match_type in ["birth", "death"]:
                        if wikidata_dates.match_date(parsed_date, include=match_type):
                            matches.append(
                                {
                                    "language": self.locale.language,
                                    "template": name,
                                    "params": param,
                                    "param_names": param_name,
                                    "date": iso_date,
                                    "match_type": match_type,
                                    "dayfirst": dayfirst,
                                }
                            )
        return matches

    def find_date_matches_any_order(self, wikidata_dates: PersonDates) -> list[dict]:
        matches = []
        if not self.wikicode:
            return matches
        for tpl in self.wikicode.filter_templates():
            name = tde.normalize_wikicode_name(tpl.name.strip_code())
            if name in self.locale.lang_config.date_templates:
                continue
            if name in self.locale.lang_config.ignore_templates:
                continue
            params = [p.value.strip_code().strip() for p in tpl.params]
            param_names = [str(p.name).strip() for p in tpl.params]
            for i in range(len(params) - 2):
                group = params[i : i + 3]
                group_names = param_names[i : i + 3]
                for dayfirst in [True, False]:
                    try:
                        parsed_date = date_parse(
                            self.locale.lang_config.normalize_date_str(" ".join(group)),
                            dayfirst=dayfirst,
                            fuzzy=True,
                        ).date()
                    except Exception:
                        continue

                    iso_date = parsed_date.isoformat()
                    for match_type in ["birth", "death"]:
                        if wikidata_dates.match_date(parsed_date, include=match_type):
                            matches.append(
                                {
                                    "language": self.locale.language,
                                    "template": name,
                                    "params": group,
                                    "param_names": group_names,
                                    "date": iso_date,
                                    "match_type": match_type,
                                    "dayfirst": dayfirst,
                                }
                            )
        return matches

    def create_ref(self) -> cwd.Reference:
        if not self.locale.wikipedia_qid:
            raise RuntimeError(f"No qid for language {self.locale.language}")

        return cwd.WikipediaReference(self.locale.wikipedia_qid, self.permalink)

    def reconcile_sitelink_dates(self):
        if not self.sitelink:
            raise RuntimeError("No sitelink")
        page = pwb.Page(self.sitelink.site, self.sitelink.title)
        if not page.exists():
            raise RuntimeError("Page does not exists")
        wikitext = page.text
        if not wikitext:
            raise RuntimeError("Wikipedia content not found")
        if wikitext.lstrip().upper().startswith("#REDIRECT"):
            raise RuntimeError("Page is a redirect")
        self.permalink = page.permalink(percent_encoded=False, with_protocol=True)
        self.wikicode = mwparserfromhell.parse(wikitext)

        wikipedia_dates = self.extract_distinct_dates()
        wikidata_dates = extract_unsourced_dates_from_item(self.page.item)

        birth_mismatch = self.has_dates_mismatch(
            wikidata_dates, wikipedia_dates, "birth"
        )
        death_mismatch = self.has_dates_mismatch(
            wikidata_dates, wikipedia_dates, "death"
        )
        if birth_mismatch and death_mismatch:
            raise RuntimeError("Mismatch birth+death dates")
        if birth_mismatch:
            raise RuntimeError("Mismatch birth dates")
        if death_mismatch:
            raise RuntimeError("Mismatch death dates")

        matched_wikipedia_birth, unmatched_wikidata_birth = compare_dates_asymmetric(
            wikipedia_dates.birth, wikidata_dates.birth, wbtime_key_ignore
        )
        matched_wikipedia_death, unmatched_wikidata_death = compare_dates_asymmetric(
            wikipedia_dates.death, wikidata_dates.death, wbtime_key_ignore
        )

        if (not wikidata_dates.birth or matched_wikipedia_birth) and (
            not wikidata_dates.death or matched_wikipedia_death
        ):

            pairs = []
            if matched_wikipedia_birth:
                pairs.append((matched_wikipedia_birth[0], cwd.DateOfBirth))
            if matched_wikipedia_death:
                pairs.append((matched_wikipedia_death[0], cwd.DateOfDeath))

            for date, StatementClass in pairs:
                statement = StatementClass(
                    date=cwd.Date.create_from_WbTime(date),
                    ignore_calendar_model=True,
                    require_unreferenced=True,
                    only_change=True,
                )
                self.page.add_statement(statement, reference=self.create_ref())

            self.page.summary = f"from [[{self.locale.wikipedia_qid}]]"

            self.tracker.mark_done(
                self.qid,
                self.locale.language,
                "successfully sourced dates",
            )
        else:
            # Partial or no matches — attempt template tracing
            print(
                f"Partial match for {self.qid} in {self.locale.language} wiki: {self.sitelink.title}"
            )
            unmatched_dates = PersonDates(
                birth=unmatched_wikidata_birth, death=unmatched_wikidata_death
            )
            matches = self.find_date_matches_any_order(
                unmatched_dates
            ) + self.find_single_param_date_matches(unmatched_dates)

            if not matches:
                print(
                    f"No date matches found for {self.qid} in {self.locale.language} wiki: {self.sitelink.title}"
                )

                # save the lead sentence
                lead_sentence = extract_lead_sentence(wikitext)
                self.tracker.add_lead_sentence(
                    self.qid,
                    self.locale.language if self.locale.language else "?",
                    lead_sentence,
                )

                self.tracker.mark_done(
                    self.qid,
                    self.locale.language if self.locale.language else "?",
                    "no matches found",
                )
            else:
                print(
                    f"Found {len(matches)} date matches for {self.qid} in {self.locale.language} wiki: {self.sitelink.title}"
                )
                save_matches_to_yaml(self.qid, matches)
                self.tracker.mark_done(self.qid, self.locale.language, "matches found")

    def has_dates_mismatch(
        self, wikidata_dates, wikipedia_dates: PersonDates, kind: str
    ) -> bool:
        """
        Raise if both self and other have a date of the given kind and they are different.
        Allows match if all fields except calendarmodel match, and at least one calendarmodel is URL_UNSPECIFIED_CALENDAR.
        """
        if kind == "birth":
            self_dates = wikidata_dates.birth
            other_dates = wikipedia_dates.birth
        elif kind == "death":
            self_dates = wikidata_dates.death
            other_dates = wikipedia_dates.death
        else:
            raise ValueError(f"Unknown kind: {kind}")

        if not (self_dates and other_dates):
            return False

        if len(other_dates) > 1:
            raise RuntimeError(
                f"Multiple {kind} dates found in Wikipedia for {self.qid}: {other_dates}"
            )
        wp = other_dates[0].normalize()
        mismatch = True

        for wd0 in self_dates:
            wd = wd0.normalize()
            if (wd.year, wd.month, wd.day, wd.precision) == (
                wp.year,
                wp.month,
                wp.day,
                wp.precision,
            ):
                mismatch = False
                break

        if mismatch:
            print(
                f"{kind.capitalize()} date mismatch for {self.qid,}:"
                f"Wikidata {print_dates(self_dates)} vs Wikipedia {print_dates(other_dates)}"
            )

            self.tracker.add_mismatch(
                self.qid,
                self.locale.language if self.locale.language else "?",
                kind,
                self_dates,
                other_dates,
                self.locale.url,
            )
        return mismatch


def extract_unsourced_dates_from_item(item: pwb.ItemPage) -> PersonDates:
    cwd.ensure_loaded(item)

    claims = item.claims
    result = PersonDates()

    for pid, target_list in [("P569", result.birth), ("P570", result.death)]:
        for claim in claims.get(pid, []):
            if claim.rank == "deprecated":
                continue

            refs = claim.getSources()
            if refs:  # skip sourced claims
                continue

            value = claim.getTarget()
            if isinstance(value, pwb.WbTime) and value.precision in {9, 10, 11}:
                target_list.append(value)

    result.deduplicate()
    return result


def save_matches_to_yaml(qid: str, matches: list[dict]):
    output_path = YAML_DIR / "unmatched_templates.yaml"

    if os.path.exists(output_path):
        with output_path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    else:
        data = {}

    data[qid] = matches

    with output_path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)


def lookup_country_qid(place_qid: str):
    query = f"""
            SELECT ?country ?placeLabel ?countryLabel WHERE {{
                values ?place {{wd:{place_qid}}}
                ?place wdt:P17 ?country.
            SERVICE wikibase:label {{ bd:serviceParam wikibase:language "[AUTO_LANGUAGE],en". }}
            }}
            """
    query_object = sparql.SparqlQuery()
    payload = query_object.query(query=query)
    if payload:
        for row in payload["results"]["bindings"]:
            country_qid = row["country"]["value"].split("/")[-1]
            place_label = row["placeLabel"]["value"]
            country_label = row["countryLabel"]["value"]
            return country_qid, place_label, country_label

    return None


def lookup_country_info_by_qid(country_qid: Optional[str]):
    if not country_qid:
        return None

    query = f"""
            SELECT ?alpha3 ?label WHERE {{
            VALUES ?country {{ wd:{country_qid} }}  

            OPTIONAL {{ ?country wdt:P298 ?alpha3 }}  # ISO 3166-1 alpha-3 code
            OPTIONAL {{
                ?country rdfs:label ?label
                FILTER(LANG(?label) IN ("en", "mul"))
            }}
            }}
            """
    query_object = sparql.SparqlQuery()
    payload = query_object.query(query=query)
    if payload:
        for row in payload["results"]["bindings"]:
            if "alpha3" in row:
                country_code = row["alpha3"]["value"]
            else:
                country_code = ""
            country_desc = row["label"]["value"]
            return country_qid, country_code, country_desc

    return None


def lookup_country_info_by_code(country_code: Optional[str]):
    if not country_code:
        return None

    query = f"""
                SELECT DISTINCT ?country ?countryLabel WHERE {{
                VALUES ?code {{"{country_code}"}}
                ?country p:P298 ?statement0.
                ?statement0 ps:P298 ?code.
                ?country p:P31 ?statement1.
                ?statement1 (ps:P31/(wdt:P279*)) wd:Q6256.
                SERVICE wikibase:label {{ bd:serviceParam wikibase:language "mul,en". }}
                }}
            """
    query_object = sparql.SparqlQuery()
    payload = query_object.query(query=query)
    if payload:
        for row in payload["results"]["bindings"]:
            country_qid = row["country"]["value"].split("/")[-1]
            country_desc = row["countryLabel"]["value"]
            return country_qid, country_code, country_desc

    return None


def first_non_template_line_with_index(wikitext: str) -> Tuple[int, str]:
    """
    Scan the raw wikitext and return:
      1. The 0-based line number of the first non-blank, non-template line
      2. The stripped text of that line

    Args:
        wikitext: The full raw page text (e.g. page.text()).

    Returns:
        (line_number, line_text). If nothing is found, returns (-1, "").
    """
    wikicode = mwparserfromhell.parse(wikitext)
    cumulative_line = 0

    for node in wikicode.nodes:
        # If it's a template, advance the line counter by how many lines its raw text occupies
        if isinstance(node, Template):
            raw = str(node)
            cumulative_line += raw.count("\n")
            continue
        # same for wikilink
        if isinstance(node, Wikilink):
            raw = str(node)
            cumulative_line += raw.count("\n")
            continue

        raw = str(node)
        lines = raw.splitlines()
        if not lines:
            continue
        for local_idx, raw_line in enumerate(lines):
            stripped = raw_line.strip()
            # Skip blanks & lines starting with another template
            if not stripped or stripped.startswith("{{"):
                continue

            # Return the global line index and the stripped content
            return cumulative_line + local_idx, stripped

        # If none in this text node matched, advance by its line count
        cumulative_line += raw.count("\n")

    # Fallback if no matching line is found
    return -1, ""


def extract_lead_sentence(wikitext: str) -> str:
    idx, line = first_non_template_line_with_index(wikitext)
    print("Line #:", idx)
    print("Text  :", line)

    raw_lines = wikitext.splitlines()
    raw_line = raw_lines[idx] if 0 <= idx < len(raw_lines) else ""
    print("Raw   :", raw_line)
    return raw_line.strip() if raw_line else ""


def reconcile_dates(
    item: pwb.ItemPage,
    country_lookup: CountryLookupInterface,
    place_lookup: PlaceLookupInterface,
    language_lookup: LanguageLookupInterface,
    tracker: WikidataStatusTracker,
    check_already_done: bool = True,
    locale: Optional[PersonLocale] = None,
    test: bool = True,
):
    """
    Reconcile dates for a Wikidata item, using a status tracker to avoid reprocessing.
    """
    lang = ""
    if check_already_done:
        if tracker.is_done(item.id):
            print(f"Item {item.id} already processed.")
            return
        if tracker.is_error(item.id):
            print(f"Item {item.id} already processed.")
            return

    try:
        print(f"-- {item.id} --")
        page = cwd.WikiDataPage(item, test=test)

        if not item.sitelinks:
            tracker.mark_done(item.id, None, "no sitelinks")
            return
        if not locale:
            locale = PersonLocale(
                item, country_lookup, place_lookup, language_lookup, tracker
            )
            locale.load()
            lang = locale.sitekey

        reconciler = EntityDateReconciler(page, locale, tracker)
        reconciler.reconcile_sitelink_dates()

        if len(page.actions) > 0:
            page.check_date_statements()
            page.apply()

    except RuntimeError as e:
        print(f"Error processing item {item.id}: {lang} {e}")
        tracker.mark_error(item.id, f"{lang} {str(e)}".strip())
    except ValueError as e:
        print(f"Value error for item {item.id}: {lang} {e}")
        tracker.mark_error(item.id, f"{lang} {str(e)}".strip())


# process_query_items(preferred_language='', all_sitelinks=True)
# try_item_by_qid(qid = "Q4314620", preferred_language='', all_sitelinks=True)
# try_item_by_qid(qid = "Q15446832", preferred_language='', all_sitelinks=True)
# try_item_by_qid(qid = "Q110452906", preferred_language='', all_sitelinks=True)
# try_item_by_qid(qid = "Q102853", preferred_language='', all_sitelinks=True)
# try_item_by_qid(qid = "Q1693202", preferred_language='', all_sitelinks=True)
# try_item_by_qid(qid = "Q128926780", preferred_language='', all_sitelinks=True) # spain
# try_item_by_qid(qid = "Q12306500", preferred_language='', all_sitelinks=True) # da
# try_item_by_qid(qid = "Q352808", preferred_language='', all_sitelinks=True) # ca
# try_item_by_qid(qid = "Q3132358", preferred_language='', all_sitelinks=True) # fr
# try_item_by_qid(qid = "Q3172832", preferred_language='', all_sitelinks=True) # fr
# try_item_by_qid(qid = "Q3132478", preferred_language='it', all_sitelinks=False)
# try_item_by_qid(qid = "Q3106260", preferred_language='fr', all_sitelinks=False)
# try_item_by_qid(qid = "Q2976644", preferred_language='fr', all_sitelinks=False)
# try_item_by_qid(qid = "Q1233849", preferred_language='hu', all_sitelinks=False)

# try_item_by_qid(qid = "Q1414762", preferred_language='en', all_sitelinks=False)
# try_item_by_qid(qid = "Q116976643", preferred_language='it', all_sitelinks=False)
# try_item_by_qid(qid = "Q1692863", preferred_language='de', all_sitelinks=False)
# try_item_by_qid(qid = "Q108516", preferred_language='nl', all_sitelinks=False)
# try_item_by_qid(qid = "Q942476", preferred_language='sk', all_sitelinks=False)
# try_item_by_qid(qid = "Q5334070", preferred_language='nl', all_sitelinks=False)
# try_item_by_qid(qid = "Q942476", preferred_language='sk', all_sitelinks=False)
# try_item_by_qid(qid = "Q2842428", preferred_language='fr', all_sitelinks=False)
# try_item_by_qid(qid = "Q124395480", preferred_language='nl', all_sitelinks=False)
# try_item_by_qid(qid = "Q123977192", preferred_language='pl', all_sitelinks=False)
# try_item_by_qid(qid = "Q17280357", preferred_language='pt', all_sitelinks=False)
# try_item_by_qid(qid = "Q2450987", preferred_language='nl', all_sitelinks=False)
# try_item_by_qid(qid = "Q3085430", preferred_language='fr', all_sitelinks=False)
# try_item_by_qid(qid = "Q16110728", preferred_language='hr', all_sitelinks=False)
# try_item_by_qid(qid = "Q5974893", preferred_language='sv', all_sitelinks=False)
