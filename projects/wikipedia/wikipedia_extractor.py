from abc import ABC, abstractmethod
import yaml
from datetime import datetime
from dataclasses import dataclass, field
from typing import List

import pywikibot as pwb
from pywikibot.pagegenerators import WikidataSPARQLPageGenerator

import mwparserfromhell
from mwparserfromhell.nodes import Template, Text, Wikilink
from typing import Tuple
from dateutil.parser import parse as date_parse
import os
import template_date_extractor
from pywikibot.data import sparql
from collections import defaultdict
import re


# todo
# O if only diff is cal model, then can change if no sources; Q23659454
# - Q3290522: 'July 28, 2008 (aged 87)' -> date parse error
# - Q6097011: ''16 de November de 2002 (81 años)' -> date parser error
# - Q12441676: '20 January 1993(aged 72)' -> date parse error
# - Q4978907: alder in template with birth param
# - Q3894616: weird date parse errors
# - lead text to database
# - generate report of mismatches
# - item.get aanpassen
# - circa? -> raise exception

# steps:
#    1. move code to other computer
#    2. check in code
#    3. review, clean up code
#    4. changes:
#         - lead text to database
#         - generate report of mismatches
#    5. make request
#    6. iterate 50 items
#    7. publish request



# Abstract base class for tracking Wikidata item processing status
class WikidataStatusTracker(ABC):
    @abstractmethod
    def is_done(self, qid: str) -> bool:
        """Return True if the item is already marked as done."""
        pass

    @abstractmethod
    def mark_done(self, qid: str, language: str, message: str):
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

    @abstractmethod
    def get_country_qid(self, place_qid: str):
        """Return the QID of the country for a given place QID."""
        pass

    @abstractmethod
    def set_country_info(self, country_qid: str, info):
        pass

    @abstractmethod
    def get_country_info(self, country_qid: str):
        pass

    @abstractmethod
    def set_country_qid(self, place_qid: str, place_label: str, country_qid: str, country_label: str):
        """Set the country QID for a given place QID."""
        pass
    
    @abstractmethod
    def get_languages_for_country(self, country_qid: str):
        """Return a list of languages for a given country QID."""
        pass

    @abstractmethod
    def get_sorted_languages(self):
        pass


def wbtime_key(w: pwb.WbTime):
    w_norm = w.normalize()
    return (w_norm.year, w_norm.month, w_norm.day, w_norm.precision, w_norm.calendarmodel)

def wbtime_key_flexible(w: pwb.WbTime):
    # Returns a tuple, but with calendarmodel set to None if unspecified
    w_norm = w.normalize()
    if w_norm.calendarmodel == template_date_extractor.URL_UNSPECIFIED_CALENDAR:
        return (w_norm.year, w_norm.month, w_norm.day, w_norm.precision, None)
    return (w_norm.year, w_norm.month, w_norm.day, w_norm.precision, w_norm.calendarmodel)

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

    def match_date(self, parsed, match_type="strict", include="both") -> list[pwb.WbTime]:
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
                    wb.year == parsed.year and
                    wb.month == parsed.month and
                    wb.day == parsed.day
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
    result = []
    for date in dates:
        arr = []
        if date.year and (date.precision >= 9):
            arr.append(f'y={date.year}')
        if date.month and (date.precision >= 10):
            arr.append(f'm={date.month}')
        if date.day and (date.precision >= 11):
            arr.append(f'd={date.day}')
        arr.append(f'p={date.precision}')
        if date.calendarmodel == template_date_extractor.URL_PROLEPTIC_JULIAN_CALENDAR:
            arr.append('Julian')
        if date.calendarmodel == template_date_extractor.URL_PROLEPTIC_GREGORIAN_CALENDAR:
            arr.append('Gregorian')
        if date.calendarmodel == template_date_extractor.URL_UNSPECIFIED_CALENDAR:
            arr.append('Unspecified')
        result.append(",".join(arr))
    return ";".join(result)
        
     

def assert_no_conflicting_dates(wikidata_dates, wikipedia_dates: PersonDates, kind: str, item_id: str):
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
    if self_dates and other_dates:
        if len(other_dates) > 1:
            raise RuntimeError(f"Multiple {kind} dates found in Wikipedia for {item_id}: {other_dates}")
        mismatch = True
        same_except_julian = False
        same_except_gregorian = False
        wp = other_dates[0].normalize()
        for wd0 in self_dates:
            wd = wd0.normalize()
            if wd.year == wp.year and wd.month == wp.month and wd.day == wp.day and wd.precision == wp.precision:
                if (
                    wd.calendarmodel == wp.calendarmodel or
                    wd.calendarmodel == template_date_extractor.URL_UNSPECIFIED_CALENDAR or
                    wp.calendarmodel == template_date_extractor.URL_UNSPECIFIED_CALENDAR
                ):
                    mismatch = False
                    break
                elif wp.calendarmodel == template_date_extractor.URL_PROLEPTIC_JULIAN_CALENDAR:
                    same_except_julian = True
                elif wp.calendarmodel == template_date_extractor.URL_PROLEPTIC_GREGORIAN_CALENDAR:
                    same_except_gregorian = True
        if mismatch:
            if same_except_julian:
                raise RuntimeError(f"{kind.capitalize()} date mismatch for {item_id}: should be Julian")
            if same_except_gregorian:
                raise RuntimeError(f"{kind.capitalize()} date mismatch for {item_id}: should be Gregorian")
            raise RuntimeError(f"{kind.capitalize()} date mismatch for {item_id}: Wikidata {print_dates(self_dates)} vs Wikipedia {print_dates(other_dates)}")

def compare_person_dates(wikidata_dates: PersonDates, wikipedia_dates: PersonDates) -> dict:
    # Flexible key sets: treat unspecified as wildcard
    def keys_with_unspecified(dates):
        # Returns a set of keys, with calendarmodel None for unspecified
        return {wbtime_key_flexible(d) for d in dates}

    wd_birth_keys = keys_with_unspecified(wikidata_dates.birth)
    wd_death_keys = keys_with_unspecified(wikidata_dates.death)
    wp_birth_keys = keys_with_unspecified(wikipedia_dates.birth)
    wp_death_keys = keys_with_unspecified(wikipedia_dates.death)

    # Helper: match if all fields except calendarmodel match, or if either calendarmodel is None
    def is_match(key1, key2):
        return key1[:4] == key2[:4] and (key1[4] is None or key2[4] is None or key1[4] == key2[4])

    def find_matches(wd_dates, wp_dates):
        matches = []
        unmatched = []
        for wd in wd_dates:
            wd_key = wbtime_key_flexible(wd)
            found = False
            for wp in wp_dates:
                wp_key = wbtime_key_flexible(wp)
                if is_match(wd_key, wp_key):
                    found = True
                    break
            if found:
                matches.append(wd)
            else:
                unmatched.append(wd)
        return matches, unmatched

    matched_birth, unmatched_birth = find_matches(wikidata_dates.birth, wikipedia_dates.birth)
    matched_death, unmatched_death = find_matches(wikidata_dates.death, wikipedia_dates.death)

    return {
        "unmatched_birth": unmatched_birth,
        "unmatched_death": unmatched_death,
        "matched_birth": matched_birth,
        "matched_death": matched_death
    }

def find_claim_by_wbtime(item: pwb.ItemPage, property_id: str, target: pwb.WbTime) -> list[pwb.Claim]:
    item.get()
    matching_claims = []

    for claim in item.claims.get(property_id, []):
        if claim.rank == 'deprecated':
            continue
        value = claim.getTarget()
        if isinstance(value, pwb.WbTime) and wbtime_key(value) == wbtime_key(target):
            matching_claims.append(claim)

    return matching_claims

def fetch_page(site, title):
    page = pwb.Page(site, title)
    if not page.exists():
        return None
    return page.text  # raw wikitext

def load_template_config(path: str):
    with open(path, encoding='utf-8') as f:
        config = yaml.safe_load(f)
    return config

def get_country_qid_from_yaml(country_code: str, path: str) -> str:
    with open(path, encoding='utf-8') as f:
        config = yaml.safe_load(f)
    for key, value in config.items():
        if value.get('code') == country_code:
            return key
    return None 


def ensure_qid_in_yaml(filepath, qid, tracker):
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    # Check if any line starts with the QID followed by a colon
    qid_present = any(re.match(rf'^{re.escape(qid)}\s*:', line) for line in lines)

    if not qid_present:
        info = tracker.get_country_info(qid)
        if not info:
            load = True
        else:
            code, description = info
            load = not code or not description
        if load:
            info = lookup_country_info(qid)
            if info:
                tracker.set_country_info(qid, info)
        if not info:
            raise RuntimeError(f'No country info for {qid}')

        code, description = info

        block = f"\n{qid}:\n    code: {code}\n    description: {description}\n"
        with open(filepath, 'a', encoding='utf-8') as f:
            f.write(block)

class PersonLocale:
    def __init__(self, item: pwb.ItemPage, tracker: WikidataStatusTracker):
        self.item = item
        self.tracker = tracker
        self.birth_country_qids = set()
        self.death_country_qids = set()
        self.country_qids = set()
        self.country = None
        self.language = None
        self.sitelink = None

    def load(self):
        self.item.get()

        # Helper to filter claims by rank
        def filter_claims_by_rank(claims):
            preferred_claims = [c for c in claims if getattr(c, 'rank', '').lower() == 'preferred']
            if preferred_claims:
                return preferred_claims
            # If no preferred, use normal (or any non-deprecated)
            return [c for c in claims if getattr(c, 'rank', '').lower() not in ('deprecated',)]

        # Place of birth
        if self.item.claims.get('P19'):
            claims = filter_claims_by_rank(self.item.claims['P19'])
            for claim in claims:
                target = claim.getTarget()
                if not target:
                    continue
                place_qid = target.id
                country_qid = self.tracker.get_country_qid(place_qid)
                if not country_qid:
                    result = lookup_country_qid(place_qid)
                    if result:
                        country_qid, place_label, country_label = result
                        self.tracker.set_country_qid(place_qid, place_label, country_qid, country_label)
                if not country_qid:
                    raise RuntimeError(f"Country QID not found for place of birth claim in self.item {self.item.id}")
                self.birth_country_qids.add(country_qid)
                self.country_qids.add(country_qid)

        # Place of death
        if self.item.claims.get('P20'):
            claims = filter_claims_by_rank(self.item.claims['P20'])
            for claim in claims:
                target = claim.getTarget()
                if not target:
                    continue
                place_qid = target.id
                country_qid = self.tracker.get_country_qid(place_qid)
                if not country_qid:
                    result = lookup_country_qid(place_qid)
                    if result:
                        country_qid, place_label, country_label = result
                        self.tracker.set_country_qid(place_qid, place_label, country_qid, country_label)
                if not country_qid:
                    raise RuntimeError(f"Country QID not found for place of death claim in self.item {self.item.id}")
                self.death_country_qids.add(country_qid)
                self.country_qids.add(country_qid)

        # Country of citizenship
        if self.item.claims.get('P27'):
            claims = filter_claims_by_rank(self.item.claims['P27'])
            for claim in claims:
                country_qid = claim.getTarget().id
                if not country_qid:
                    raise RuntimeError(f"Country QID not found for citizenship claim in self.item {self.item.id}")
                self.country_qids.add(country_qid)

        self.sorted_countries = self.get_weighted_countries()
        self.sorted_languages = self.get_weighted_languages()
        self.wikicode = self.get_preferred_wikicode()
        if not self.wikicode:
            raise RuntimeError('No most relevant Wikipedia page')
        self.sitelink = self.item.sitelinks[self.wikicode]
        self.language = self.sitelink.site.lang

        self.lang_config = template_date_extractor.LanguageConfig(
            self.language,
            load_template_config('dob_dod_templates.yaml'))
        if not self.lang_config.month_map:
            if self.language != 'en':
                raise RuntimeError(f'No month_map for language {self.language}')

        if self.sorted_countries:
            self.country = self.sorted_countries[0]
        else:
            country_code = self.lang_config.fallback_countrycode
            if not country_code:
                raise RuntimeError(f'Language {self.language} has no fallback_countrycode')
            self.country = get_country_qid_from_yaml(country_code, path='countries.yaml')

        self.country_config = template_date_extractor.CountryConfig(
            self.country, 
            load_template_config('countries.yaml'))
        if not self.country_config.first_gregorian_date:
            ensure_qid_in_yaml(qid = self.country, filepath = 'countries.yaml', tracker = self.tracker)
        if not self.country_config.first_gregorian_date:
            raise RuntimeError(f'No first_gregorian_date for {self.country}')

    def get_preferred_wikicode(self) -> str:
        sitelinks = self.item.sitelinks
        # Filter out unusable sitelinks
        usable_sitelinks = {k: v for k, v in sitelinks.items() if k != 'commonswiki' and 'wikisource' not in k and 'wikiquote' not in k}

        if len(usable_sitelinks) == 0:
            raise RuntimeError('No usable Wikipedia page')
        if len(usable_sitelinks) == 1:
            # Only one usable sitelink, return it directly
            wikicode = next(iter(usable_sitelinks.keys()))
            return wikicode

        for lang in self.sorted_languages:
            wikicode = f'{lang}wiki'
            if wikicode in usable_sitelinks:
                return wikicode

        # tracker returns a list of wikis sorted by active users
        for lang in self.tracker.get_sorted_languages():
            wikicode = f'{lang}wiki'
            if wikicode in usable_sitelinks:
                return wikicode

        return None            

    def get_weighted_countries(self):
        weights = {
            3: self.birth_country_qids,
            2: self.death_country_qids,
            1: self.country_qids
        }

        country_scores = defaultdict(int)

        for weight, qid_set in weights.items():
            for country_qid in qid_set:
                country_scores[country_qid] += weight

        # Sort by score descending and return only the QIDs
        sorted_country_qids = [qid for qid, _ in sorted(country_scores.items(), key=lambda x: -x[1])]
        return sorted_country_qids
    
    def get_weighted_languages(self):
        weights = {
            3: self.birth_country_qids,
            2: self.death_country_qids,
            1: self.country_qids
        }

        language_scores = defaultdict(int)

        for weight, qid_set in weights.items():
            for country_qid in qid_set:
                langs = self.tracker.get_languages_for_country(country_qid)
                if not langs:
                    raise RuntimeError(f"No languages found for country QID {country_qid} in item {self.item.id}")
                for lang_qid in langs:
                    language_scores[lang_qid] += weight

        # Sort by score descending
        sorted_language_qids = [lang for lang, _ in sorted(language_scores.items(), key=lambda x: -x[1])]
        return sorted_language_qids


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
    def __init__(self, item: pwb.ItemPage, locale: PersonLocale, tracker: WikidataStatusTracker = None):
        self.item = item
        self.sitelink = locale.sitelink
        self.locale = locale
        self.tracker = tracker
        self.wikicode = None

    def build_wbtime(self, y, m=None, d=None, calendarmodel=template_date_extractor.URL_UNSPECIFIED_CALENDAR):
        try:
            y, m, d = int(y), int(m) if m else None, int(d) if d else None
            if d:
                return pwb.WbTime(year=y, month=m, day=d, precision=11, calendarmodel=calendarmodel)
            elif m:
                return pwb.WbTime(year=y, month=m, precision=10, calendarmodel=calendarmodel)
            else:
                return pwb.WbTime(year=y, precision=9, calendarmodel=calendarmodel)
        except Exception:
            return None

    def parse_date_string(self, date_str, dayfirst=True):
        date_str = self.locale.lang_config.normalize_date_str(date_str)
        try:
            dt = date_parse(date_str, dayfirst=dayfirst, fuzzy=True)
            return dt.year, dt.month if dt.month else None, dt.day if dt.day else None
        except Exception:
            return None, None, None

    def extract_distinct_dates(self) -> PersonDates:
        template_graph = walk_templates(self.wikicode)
        dob_dates = []
        dod_dates = []
        for child, parent in template_graph:
            name = child.name.strip_code().strip().lower().replace('_', ' ')
            if name in self.locale.lang_config.date_templates:
                continue  
            if name not in self.locale.lang_config.template_map:
                continue
            for tpl_cfg in self.locale.lang_config.template_map[name]:
                extractor = template_date_extractor.TemplateDateExtractor(tpl_cfg, child, 
                    self.locale.lang_config, self.locale.country_config)
                for result in extractor.get_all_dates():
                    if parent:
                        parent_name = parent.name.strip_code().strip().lower().replace('_', ' ')
                        if not self.locale.lang_config.is_known_template(parent_name):
                            raise RuntimeError(f"Unknown parent template: {parent_name}, child: {name}")
                    # result is a tuple: (typ, y, m, d, cal_model)
                    if not result or len(result) < 5:
                        continue
                    typ, y, m, d, cal_model = result
                    if y:
                        wbt = self.build_wbtime(y, m, d, calendarmodel=cal_model)
                        if wbt:
                            if typ == 'birth':
                                dob_dates.append(wbt)
                            elif typ == 'death':
                                dod_dates.append(wbt)
        result = PersonDates(birth=dob_dates, death=dod_dates)
        result.deduplicate()
        if len(result.birth) > 1 or len(result.death) > 1:
            raise RuntimeError(f"Multiple DOBs or DODs detected: {result.to_iso()}")
        return result

    def find_single_param_date_matches(self, wikidata_dates: PersonDates) -> list[dict]:
        matches = []
        for tpl in self.wikicode.filter_templates():
            # todo; functie aanroepen
            name = tpl.name.strip_code().strip().lower().replace('_', ' ')
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
                        parsed_date = date_parse(self.locale.lang_config.normalize_date_str(param), dayfirst=dayfirst, fuzzy=True).date()
                    except Exception:
                        continue
                    
                    iso_date = parsed_date.isoformat()
                    for match_type in ["birth", "death"]:
                        if wikidata_dates.match_date(parsed_date, include=match_type):
                            matches.append({
                                "language": self.locale.language,
                                "template": name,
                                "params": param,
                                "param_names": param_name,
                                "date": iso_date,
                                "match_type": match_type,
                                "dayfirst": dayfirst
                            })
        return matches

    def find_date_matches_any_order(self, wikitext: str, wikidata_dates: PersonDates) -> list[dict]:
        matches = []
        for tpl in self.wikicode.filter_templates():
            name = tpl.name.strip_code().strip().lower().replace('_', ' ')
            if name in self.locale.lang_config.date_templates:
                continue
            if name in self.locale.lang_config.ignore_templates:
                continue
            params = [p.value.strip_code().strip() for p in tpl.params]
            param_names = [str(p.name).strip() for p in tpl.params]
            for i in range(len(params) - 2):
                group = params[i:i+3]
                group_names = param_names[i:i+3]
                for dayfirst in [True, False]:
                    try:
                        parsed_date = date_parse(self.locale.lang_config.normalize_date_str(" ".join(group)), dayfirst=dayfirst, fuzzy=True).date()
                    except Exception:
                        continue

                    iso_date = parsed_date.isoformat()
                    for match_type in ["birth", "death"]:
                        if wikidata_dates.match_date(parsed_date, include=match_type):
                            matches.append({
                                "language": self.locale.language,
                                "template": name,
                                "params": group,
                                "param_names": group_names,
                                "date": iso_date,
                                "match_type": match_type,
                                "dayfirst": dayfirst
                            })
        return matches

    def reconcile_sitelink_dates(self):
        wikitext = fetch_page(self.sitelink.site, self.sitelink.title)
        if not wikitext:
            raise RuntimeError('Wikipedia content not found')
        if wikitext.lstrip().upper().startswith('#REDIRECT'):
            raise RuntimeError("Page is a redirect")
        self.wikicode = mwparserfromhell.parse(wikitext)

        wikipedia_dates = self.extract_distinct_dates()
        wikidata_dates = extract_unsourced_dates_from_item(self.item)

        # Raise if both Wikidata and Wikipedia have a birth date and they are different
        assert_no_conflicting_dates(wikidata_dates, wikipedia_dates, "birth", self.item.id)
        # Raise if both Wikidata and Wikipedia have a death date and they are different
        assert_no_conflicting_dates(wikidata_dates, wikipedia_dates, "death", self.item.id)

        result = compare_person_dates(wikidata_dates, wikipedia_dates)
        matched_birth = result["matched_birth"]
        matched_death = result["matched_death"]
        unmatched_birth = result["unmatched_birth"]
        unmatched_death = result["unmatched_death"]
        if ((not wikidata_dates.birth or matched_birth) and (not wikidata_dates.death or matched_death)):
            # Safe to source both birth and death claims
            pairs = []
            if matched_birth and len(matched_birth) > 0:
                pairs.append((matched_birth[0], "P569"))
            if matched_death and len(matched_death) > 0:
                pairs.append((matched_death[0], "P570"))
            for date, pid in pairs:
                claims = find_claim_by_wbtime(self.item, pid, date)
                if len(claims) != 1:
                    raise RuntimeError(f"{self.item.id}: Expected one claim for {pid}, got {len(claims)}")
                add_source_to_claim(claims[0], self.sitelink)
            if self.tracker:
                self.tracker.mark_done(self.item.id, self.locale.language, 'successfully sourced dates')
        else:
            # Partial or no matches — attempt template tracing
            print(f"Partial match for {self.item.id} in {self.locale.language} wiki: {self.sitelink.title}")
            unmatched_dates = PersonDates(birth=unmatched_birth, death=unmatched_death)
            matches = self.find_date_matches_any_order(unmatched_dates) + self.find_single_param_date_matches(unmatched_dates)

            if not matches:
                print(f"No date matches found for {self.item.id} in {self.locale.language} wiki: {self.sitelink.title}")
                save_lead_sentence_to_yaml(self.item.id, self.locale.language, wikitext)
                if self.tracker:
                    self.tracker.mark_done(self.item.id, self.locale.language, 'no matches found')
            else:
                print(f"Found {len(matches)} date matches for {self.item.id} in {self.locale.language} wiki: {self.sitelink.title}")
                save_matches_to_yaml(self.item.id, matches)
                if self.tracker:
                    self.tracker.mark_done(self.item.id, self.locale.language, 'matches found')


def extract_unsourced_dates_from_item(item: pwb.ItemPage) -> PersonDates:
    item.get()
    claims = item.claims
    result = PersonDates()

    for pid, target_list in [('P569', result.birth), ('P570', result.death)]:
        for claim in claims.get(pid, []):
            if claim.rank == 'deprecated':
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
    output_path = "unmatched_templates.yaml"

    # Load existing content if present
    if os.path.exists(output_path):
        with open(output_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    else:
        data = {}

    # Add or update the entry for this QID
    data[qid] = matches

    # Write updated content back
    with open(output_path, "w", encoding="utf-8") as f:
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
    payload = query_object.query(query = query)
    for row in payload['results']['bindings']:
        country_qid = row['country']['value'].split('/')[-1]
        place_label = row['placeLabel']['value']
        country_label = row['countryLabel']['value']    
        return country_qid, place_label, country_label

    return None

def lookup_country_info(country_qid: str):
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
    payload = query_object.query(query = query)
    for row in payload['results']['bindings']:
        if 'alpha3' in row:
            alpha3 = row['alpha3']['value']
        else:
            alpha3 = ''
        country = row['label']['value']
        return alpha3, country

    return None
    


def add_source_to_claim(claim: pwb.Claim, sitelink: pwb.Page):
    print(f"Adding source to claim {claim.id} for sitelink {sitelink.title}")


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
        if isinstance(node, Wikilink):
            raw = str(node)
            cumulative_line += raw.count("\n")
            continue

        # For plain text nodes, split into lines and test each
        #if isinstance(node, Text):
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

def save_lead_sentence_to_yaml(qid: str, lang: str, wikitext: str):
    output_path = "lead_sentences.yaml"
    lead_sentence = extract_lead_sentence(wikitext)

    entry = {
        'qid': qid,
        'language': lang,
        'lead_sentence': lead_sentence,
        'timestamp': datetime.utcnow().isoformat() + 'Z'
    }

    # Append as a new document for easy split/loading
    with open(output_path, 'a', encoding='utf-8') as f:
        yaml.dump([entry], f, allow_unicode=True)
        f.write("\n")  # separate documents

def reconcile_entity_dates_with_tracker(item: pwb.ItemPage, tracker: WikidataStatusTracker):
    """
    Reconcile dates for a Wikidata item, using a status tracker to avoid reprocessing.
    """
    lang = ''
    if tracker.is_done(item.id):
        print(f"Item {item.id} already processed.")
        return
    if tracker.is_error(item.id):
        print(f"Item {item.id} already processed.")
        return

    try:
        if not item.sitelinks:
            tracker.mark_done(item.id, None, 'no sitelinks')
            return
        locale = PersonLocale(item, tracker)
        locale.load()
        lang = locale.wikicode

        reconciler = EntityDateReconciler(item, locale, tracker)
        reconciler.reconcile_sitelink_dates() 
    except RuntimeError as e:
        print(f"Error processing item {item.id}: {lang} {e}")
        tracker.mark_error(item.id, f'{lang} {str(e)}'.strip())
    except ValueError as e:
        print(f"Value error for item {item.id}: {lang} {e}")
        tracker.mark_error(item.id, f'{lang} {str(e)}'.strip())

#process_query_items(preferred_language='', all_sitelinks=True)
#try_item_by_qid(qid = "Q4314620", preferred_language='', all_sitelinks=True)
#try_item_by_qid(qid = "Q15446832", preferred_language='', all_sitelinks=True)
#try_item_by_qid(qid = "Q110452906", preferred_language='', all_sitelinks=True)
#try_item_by_qid(qid = "Q102853", preferred_language='', all_sitelinks=True)
#try_item_by_qid(qid = "Q1693202", preferred_language='', all_sitelinks=True)
# try_item_by_qid(qid = "Q128926780", preferred_language='', all_sitelinks=True) # spain
# try_item_by_qid(qid = "Q12306500", preferred_language='', all_sitelinks=True) # da
# try_item_by_qid(qid = "Q352808", preferred_language='', all_sitelinks=True) # ca
#try_item_by_qid(qid = "Q3132358", preferred_language='', all_sitelinks=True) # fr
#try_item_by_qid(qid = "Q3172832", preferred_language='', all_sitelinks=True) # fr
#try_item_by_qid(qid = "Q3132478", preferred_language='it', all_sitelinks=False)
#try_item_by_qid(qid = "Q3106260", preferred_language='fr', all_sitelinks=False) 
#try_item_by_qid(qid = "Q2976644", preferred_language='fr', all_sitelinks=False) 
#try_item_by_qid(qid = "Q1233849", preferred_language='hu', all_sitelinks=False)

#try_item_by_qid(qid = "Q1414762", preferred_language='en', all_sitelinks=False)
#try_item_by_qid(qid = "Q116976643", preferred_language='it', all_sitelinks=False)
#try_item_by_qid(qid = "Q1692863", preferred_language='de', all_sitelinks=False)
# try_item_by_qid(qid = "Q108516", preferred_language='nl', all_sitelinks=False)
# try_item_by_qid(qid = "Q942476", preferred_language='sk', all_sitelinks=False)
#try_item_by_qid(qid = "Q5334070", preferred_language='nl', all_sitelinks=False)
#try_item_by_qid(qid = "Q942476", preferred_language='sk', all_sitelinks=False)
#try_item_by_qid(qid = "Q2842428", preferred_language='fr', all_sitelinks=False)
#try_item_by_qid(qid = "Q124395480", preferred_language='nl', all_sitelinks=False)
#try_item_by_qid(qid = "Q123977192", preferred_language='pl', all_sitelinks=False)
#try_item_by_qid(qid = "Q17280357", preferred_language='pt', all_sitelinks=False)
# try_item_by_qid(qid = "Q2450987", preferred_language='nl', all_sitelinks=False)
# try_item_by_qid(qid = "Q3085430", preferred_language='fr', all_sitelinks=False)
# try_item_by_qid(qid = "Q16110728", preferred_language='hr', all_sitelinks=False)
#try_item_by_qid(qid = "Q5974893", preferred_language='sv', all_sitelinks=False)