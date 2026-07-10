"""AddLabelBot: add missing labels, sex and birth/death dates to Wikidata
person items, based on the authority-control records (LoC, BnF, IdRef, GND)
already linked from the item.

For every candidate item the bot retrieves all linked authority records,
combines them through the Collector, and — when the sources agree and the
person's locale writes latin script — queues label/alias/claim edits through
shared_lib.change_wikidata.
"""

import json
import time
import unicodedata
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional

import pywikibot as pwb

import shared_lib.change_wikidata as cwd
import shared_lib.constants as wd
from shared_lib.date_value import Date
from shared_lib.wikidata_site import REPO

import addlabel.person_name as pn
from addlabel.bnf_page import BnfPage
from addlabel.collector import Collector, DateFinding
from addlabel.countries import Countries
from addlabel.gnd_page import GndPage
from addlabel.idref_page import IdrefPage
from addlabel.languages import Languages
from addlabel.loc_page import LocPage
from addlabel.paths import DATA_DIR
from addlabel.wdqs_client import query_wdqs
from addlabel.wikidata_page import WikidataPage

WD_ENTITY_PREFIX = "http://www.wikidata.org/entity/"

SLEEP_AFTER_UNCAUGHT_ERROR = 10  # sec
SLEEP_AFTER_READ = 5  # sec
SLEEP_AFTER_WRITE = 30  # sec

# number of identifiers fetched per WDQS bd:slice window
SCAN_SLICE_SIZE = 100_000

# Wikidata items that must never be touched
SKIPPED_QIDS = {"Q119113198"}

# IdRef records known to contain bad data; per QID
IDREF_IGNORE_FILE = DATA_DIR / "idref_ignore.json"

# labels are only added for these languages, and 'mul' is only considered once
# all of them are present
LABEL_LANGUAGES = ["en", "fr", "de"]

# languages skipped when checking whether every existing label equals the
# proposed 'mul' label
MUL_EXEMPT_LANGUAGES = {
    "hu",  # Hungarian name order
    "ar",
    "ru",
}


class ExamineResult(Enum):
    READ = "read"  # item examined, nothing changed
    WRITE = "write"  # item examined and changed
    SKIPPED = "skipped"


@dataclass(frozen=True)
class LabelSource:
    """One authority source the bot can scan: which identifier property to
    iterate over and which label language that source provides."""

    pid: str
    label_language: str


# page class per identifier property; every linked identifier of these
# properties is retrieved for an examined item, whatever the scanned source
AUTHORITY_PAGE_CLASSES = {
    wd.PID_LIBRARY_OF_CONGRESS_AUTHORITY_ID: LocPage,
    wd.PID_BIBLIOTHEQUE_NATIONALE_DE_FRANCE_ID: BnfPage,
    wd.PID_IDREF_ID: IdrefPage,
    wd.PID_GND_ID: GndPage,
}

SOURCES = {
    "loc": LabelSource(wd.PID_LIBRARY_OF_CONGRESS_AUTHORITY_ID, "en"),
    "bnf": LabelSource(wd.PID_BIBLIOTHEQUE_NATIONALE_DE_FRANCE_ID, "fr"),
    "idref": LabelSource(wd.PID_IDREF_ID, "fr"),
    "gnd": LabelSource(wd.PID_GND_ID, "de"),
}


class ReportBackend(ABC):
    """Tracking store for processed/failed items and scan progress."""

    @abstractmethod
    def has_error(self, qid: str) -> bool:
        pass

    @abstractmethod
    def is_done(self, qid: str) -> bool:
        pass

    @abstractmethod
    def add_non_latin(self, qid: str, locale: str) -> None:
        """Record an item skipped because the locale is non-latin."""
        pass

    @abstractmethod
    def add_error(self, qid: str, msg: str) -> None:
        pass

    @abstractmethod
    def add_done(self, qid: str) -> None:
        pass

    @abstractmethod
    def get_index(self, pid: str) -> int:
        """Scan progress (bd:slice offset) for a source property."""
        pass

    @abstractmethod
    def set_index(self, pid: str, index: int) -> None:
        pass

    @abstractmethod
    def get_retry(self) -> List[str]:
        """QIDs of errors flagged for retry."""
        pass

    @abstractmethod
    def get_todo(self) -> List[str]:
        pass

    def add_birth_death(
        self, qid: str, birth_year: Optional[int], death_year: Optional[int]
    ) -> None:
        """Record a suspicious birth/death year combination for review."""
        print(f"*** check birth/death years for {qid}: {birth_year}-{death_year}")


class NullReport(ReportBackend):
    """No-op backend for single-item and test runs."""

    def has_error(self, qid: str) -> bool:
        return False

    def is_done(self, qid: str) -> bool:
        return False

    def add_non_latin(self, qid: str, locale: str) -> None:
        pass

    def add_error(self, qid: str, msg: str) -> None:
        pass

    def add_done(self, qid: str) -> None:
        pass

    def get_index(self, pid: str) -> int:
        return 0

    def set_index(self, pid: str, index: int) -> None:
        pass

    def get_retry(self) -> List[str]:
        return []

    def get_todo(self) -> List[str]:
        return []


def load_idref_ignore() -> dict:
    if IDREF_IGNORE_FILE.exists():
        with IDREF_IGNORE_FILE.open(encoding="utf-8") as infile:
            return json.load(infile)
    return {}


class AddLabelBot:
    def __init__(
        self,
        source: Optional[LabelSource],
        report: ReportBackend,
    ):
        # source is only needed for scan(); retry()/todo()/examine() work
        # without one
        self.source = source
        self.report = report
        self.test = True
        self.skip_sex = False
        self.force_name_order = pn.NAME_ORDER_UNDETERMINED
        # stop scanning after this many changed items (0 = no limit)
        self.max_change = 0
        self.label_changed_count = 0
        self.changed_count = 0
        self.checked_count = 0
        self.language_lookup = Languages()
        self.country_lookup = Countries()
        self.idref_ignore = load_idref_ignore()

    # ------------------------------------------------------------------ #
    #  Entry points                                                       #
    # ------------------------------------------------------------------ #

    def scan(self):
        """Walk all items carrying the source property, resuming from the
        stored slice index."""
        source = self.source
        if not source:
            raise RuntimeError("scan() requires a LabelSource")
        index = self.report.get_index(source.pid)
        while True:
            print(f"Index = {index}")
            if not self.scan_slice(source, index):
                return
            index = index + SCAN_SLICE_SIZE
            self.report.set_index(source.pid, index)

    def retry(self):
        """Re-examine the items whose errors were flagged for retry."""
        self.test = False
        self.skip_sex = False
        for qid in self.report.get_retry():
            self.try_examine(qid)

    def todo(self):
        """Examine the items queued in the backend's todo list."""
        self.test = False
        self.skip_sex = False
        for qid in self.report.get_todo():
            self.try_examine(qid)

    # ------------------------------------------------------------------ #
    #  Scanning                                                           #
    # ------------------------------------------------------------------ #

    def scan_slice(self, source: LabelSource, index: int) -> bool:
        """Examine one bd:slice window of source identifiers; False when the
        slice is exhausted or max_change is reached."""
        query_template = """SELECT DISTINCT ?item ?authid WHERE {{
                    SERVICE bd:slice {{
                        ?item wdt:{pid} ?authid.
                        bd:serviceParam bd:slice.offset {index} ;
                        bd:slice.limit {limit} .
                    }}
                    ?item wdt:P214 ?viaf;
                        wdt:P31 wd:Q5.
                    OPTIONAL {{
                        ?item p:{pid} ?statement0.
                        ?statement0 ps:{pid} _:anyValue;
                        wikibase:rank ?rank.
                    }}
                    FILTER(?rank != wikibase:DeprecatedRank)
                    FILTER(NOT EXISTS {{
                        ?item rdfs:label ?itemLabel.
                        FILTER(
                          LANG(?itemLabel) = "{language}" || LANG(?itemLabel) = "mul"
                          )
                    }})
                    }}"""

        qry = query_template.format(
            pid=source.pid,
            index=index,
            limit=SCAN_SLICE_SIZE,
            language=source.label_language,
        )
        rows = query_wdqs(qry)
        if not rows:
            return False
        for row in rows:
            qid = row.get("item", {}).get("value", "").replace(WD_ENTITY_PREFIX, "")
            authid = row.get("authid", {}).get("value", "")
            if not qid or not authid:
                continue

            print(f"{index}: {qid}")
            self.try_examine(qid)
            if self.max_change > 0 and self.changed_count >= self.max_change:
                return False

        return True

    def wait(self, reason: str, seconds: int):
        if seconds > 0:
            print(f"{reason}: waiting for {seconds:.2f} seconds.")
            time.sleep(seconds)

    def try_examine(self, qid: str):
        """examine() with error bookkeeping and polite sleeping."""
        try:
            result = self.examine(qid)

            if result == ExamineResult.READ:
                self.wait("After read", SLEEP_AFTER_READ)
            elif result == ExamineResult.WRITE:
                self.wait("After write", SLEEP_AFTER_WRITE)

        except RuntimeError as e:
            print(f"Runtime error: {e}")
            self.report.add_error(qid, repr(e))
            self.wait("RuntimeError", SLEEP_AFTER_READ)
        except pwb.exceptions.OtherPageSaveError as e:
            print(f"OtherPageSaveError: {e}")
            self.report.add_error(qid, repr(e))
            self.wait("OtherPageSaveError", SLEEP_AFTER_READ)
        except Exception as e:
            print(f"Uncaught error: {e}")
            self.report.add_error(qid, repr(e))
            self.wait("Exception", SLEEP_AFTER_UNCAUGHT_ERROR)

    # ------------------------------------------------------------------ #
    #  Examining one item                                                 #
    # ------------------------------------------------------------------ #

    def examine(self, qid: str) -> Optional[ExamineResult]:
        if not qid.startswith("Q"):
            # ignore property pages and lexeme pages
            return None

        if not self.test:
            if self.report.has_error(qid):
                print(f"{qid}: skipped, in error list")
                return None
            if self.report.is_done(qid):
                print(f"{qid}: skipped, in done list")
                return None

        if qid in self.idref_ignore:
            raise RuntimeError("idref ignore")
        if qid in SKIPPED_QIDS:
            print(f"{qid}: skipped, in special ignore list")
            return None

        self.item = pwb.ItemPage(REPO, qid)

        if not self.item.exists():
            return None

        if self.item.isRedirectPage():
            return None

        self.claims = self.item.get().get("claims", {})

        if not self.item.botMayEdit():
            raise RuntimeError(f"Skipping {qid} because it cannot be edited by bots")

        self.checked_count += 1

        collector = self.collect_authority_pages()

        if collector.has_duplicates():
            raise RuntimeError("has duplicate")

        if not collector.has_language_info():
            collector.add(
                WikidataPage(qid, self.language_lookup, self.country_lookup)
            )
            collector.retrieve()

        for page in collector.pages:
            print(page)

        self.wd_page = cwd.WikiDataPage(item=self.item, test=self.test)

        if not self.skip_sex:
            self.queue_sex(collector)

        self.queue_dates(collector)
        label_pages = self.queue_labels(collector)

        print(f"can_change_labels: {collector.can_change_labels()}")
        print(f"has_language_info: {collector.has_language_info()}")

        locale = self.get_locale_desc(collector.pages)
        if not locale:
            raise RuntimeError("Empty page_summary")

        if label_pages:
            from_text = self.get_short_desc(label_pages)
            if not from_text:
                raise RuntimeError("Empty from_text")
            summary = f"from {from_text}; country/language is {locale}"
        else:
            summary = f"country/language is {locale}"

        self.wd_page.summary = summary
        if len(self.wd_page.actions) > 0:
            self.wd_page.check_date_statements()
        print(summary)

        if label_pages:
            self.label_changed_count += 1
        else:
            self.report.add_non_latin(qid, locale)

        if self.test:
            self.wd_page.apply()
            return ExamineResult.READ

        something_changed = self.wd_page.apply()
        if something_changed:
            self.changed_count += 1
            print(
                f"checked: {self.checked_count} changed: {self.changed_count} "
                f"labels: {self.label_changed_count}"
            )
            self.check_lifespan(qid)
        else:
            print("nothing changed")
        self.report.add_done(qid)

        if something_changed:
            return ExamineResult.WRITE
        return ExamineResult.READ

    def collect_authority_pages(self) -> Collector:
        """Retrieve the authority records linked from the item; raises when a
        record is a redirect, not found, or duplicated."""
        collector = Collector(force_name_order=self.force_name_order)

        for authority_pid, page_class in AUTHORITY_PAGE_CLASSES.items():
            if authority_pid not in self.claims:
                continue
            for claim in self.claims[authority_pid]:
                if claim.getRank() == "deprecated":
                    continue
                target = claim.getTarget()
                if not target:
                    # skip 'no value', for example Q80727
                    continue
                collector.add(
                    page_class(
                        target,
                        language_lookup=self.language_lookup,
                        country_lookup=self.country_lookup,
                    )
                )

        collector.retrieve()
        if collector.has_redirect():
            for page in collector.pages:
                if page.is_redirect:
                    raise RuntimeError(
                        f"Redirect {page.pid} {page.initial_external_id}"
                    )
                elif page.not_found:
                    raise RuntimeError(
                        f"Not found {page.pid} {page.initial_external_id}"
                    )

            raise RuntimeError("collector.has_redirect")

        return collector

    # ------------------------------------------------------------------ #
    #  Queueing statements                                                #
    # ------------------------------------------------------------------ #

    def queue_sex(self, collector: Collector) -> None:
        sex_info = collector.get_sex_info()
        if not sex_info:
            return
        do_add = not self.has_claim_with_strong_source(wd.PID_SEX_OR_GENDER)
        print(f"sex: add: {do_add} {sex_info}")
        if not do_add:
            return
        if self.has_deprecated_claim_with_qid(wd.PID_SEX_OR_GENDER, sex_info.qid):
            return
        self.wd_page.add_statement(
            cwd.SexOrGender(qid=sex_info.qid),
            reference=sex_info.page.create_reference(),
        )

    def queue_dates(self, collector: Collector) -> None:
        birth_info = collector.get_date_info("birth")
        death_info = collector.get_date_info("death")

        # sanity check on the combination before adding either
        if birth_info and death_info:
            lifespan = death_info.date.year - birth_info.date.year
            if lifespan < 10:
                raise RuntimeError(
                    f"birth-death diff < 10: birth: {birth_info.date.year}, "
                    f"death: {death_info.date.year}"
                )
            if lifespan > 100:
                raise RuntimeError(
                    f"birth-death diff > 100: birth: {birth_info.date.year}, "
                    f"death: {death_info.date.year}"
                )

        if birth_info:
            self.queue_date(wd.PID_DATE_OF_BIRTH, cwd.DateOfBirth, birth_info)
        if death_info:
            self.queue_date(wd.PID_DATE_OF_DEATH, cwd.DateOfDeath, death_info)

    def queue_date(self, pid: str, statement_class, finding: DateFinding) -> None:
        do_add = not self.has_claim_with_strong_source(pid)
        print(f"{pid}: add: {do_add} {finding}")
        if not do_add:
            return
        if self.has_deprecated_claim_with_date(pid, finding.date):
            return
        self.wd_page.add_statement(
            statement_class(date=finding.date),
            reference=finding.page.create_reference(),
        )

    def queue_labels(self, collector: Collector) -> list:
        """Queue missing labels (per LABEL_LANGUAGES) and possibly a 'mul'
        label; returns the pages the added labels came from."""
        label_pages = []
        if "mul" in self.item.labels:
            return label_pages

        has_language = set()
        all_normalized_names = []
        english_name = None
        for language in LABEL_LANGUAGES:
            if language in self.item.labels:
                has_language.add(language)
                continue
            names = collector.get_names(language)
            if not names:
                continue

            for name_obj in names:
                name = name_obj["name"]
                pages = name_obj["pages"]
                print(f"{language} name: {name} from {self.get_short_desc(pages)}")
                if collector.can_change_labels():
                    self.wd_page.add_statement(
                        cwd.Label(name, language), reference=None
                    )
                    label_pages = label_pages + pages
                    has_language.add(language)
                    normalized_name = unicodedata.normalize("NFC", name)
                    if normalized_name not in all_normalized_names:
                        all_normalized_names.append(normalized_name)
                    if language == "en":
                        english_name = name

        if label_pages and has_language.issuperset(LABEL_LANGUAGES):
            self.queue_mul_label(all_normalized_names, english_name)

        return label_pages

    def queue_mul_label(self, all_normalized_names: list, english_name) -> None:
        """When every label (existing and just queued) is the same string, add
        it as the 'mul' label."""
        print(f"Now contains {'-'.join(LABEL_LANGUAGES)}")
        print(f"all_names={all_normalized_names}")
        for language in self.item.labels:
            if language in MUL_EXEMPT_LANGUAGES:
                continue

            name = self.item.labels[language]
            normalized_name = unicodedata.normalize("NFC", name)
            if normalized_name not in all_normalized_names:
                print(f"{language}: {normalized_name}")
                all_normalized_names.append(normalized_name)
        print(f"all_names={all_normalized_names}")
        if len(all_normalized_names) == 1:
            # use english
            if "en" in self.item.labels:
                english_name = self.item.labels["en"]
            if not english_name:
                raise RuntimeError("No English name")
            self.wd_page.add_statement(cwd.Label(english_name, "mul"), reference=None)

    # ------------------------------------------------------------------ #
    #  Claim inspection helpers                                           #
    # ------------------------------------------------------------------ #

    def has_claim_with_strong_source(self, pid: str) -> bool:
        """True when the property already has a claim with a non-weak source;
        raises when a deprecated claim exists (needs manual review)."""
        if pid not in self.claims:
            return False

        for claim in self.claims[pid]:
            if claim.getRank() == "deprecated":
                raise RuntimeError(f"Deprecated claim {pid}")
            if cwd.has_strong_source(claim):
                return True

        return False

    def has_deprecated_claim_with_date(self, pid: str, date) -> bool:
        """True when the same date already exists as a deprecated claim (in
        which case the date must not be re-added)."""
        if pid not in self.claims:
            return False
        for claim in self.claims[pid]:
            target = claim.getTarget()
            # can be None/Unknown value
            if target and Date.is_equal(date, target, ignore_calendar_model=False):
                if claim.getRank() == "deprecated":
                    return True
                break
        return False

    def has_deprecated_claim_with_qid(self, pid: str, qid: str) -> bool:
        if pid not in self.claims:
            return False
        for claim in self.claims[pid]:
            target = claim.getTarget()
            # can be None/Unknown value
            if target and target.getID() == qid:
                if claim.getRank() == "deprecated":
                    return True
                break
        return False

    def check_lifespan(self, qid: str) -> None:
        """After applying, flag suspicious birth/death year combinations found
        on the item as a whole."""
        if self.wd_page.birth_year_low and self.wd_page.death_year_high:
            diff = self.wd_page.death_year_high - self.wd_page.birth_year_low
            if diff > 100:
                self.report.add_birth_death(
                    qid, self.wd_page.birth_year_low, self.wd_page.death_year_high
                )
        if self.wd_page.birth_year_high and self.wd_page.death_year_low:
            diff = self.wd_page.death_year_low - self.wd_page.birth_year_high
            if diff < 10:
                self.report.add_birth_death(
                    qid, self.wd_page.birth_year_low, self.wd_page.death_year_high
                )

    # ------------------------------------------------------------------ #
    #  Summary helpers                                                    #
    # ------------------------------------------------------------------ #

    def get_short_desc(self, pages) -> str:
        descs = []
        for page in pages:
            short_desc = page.get_short_desc()
            if short_desc not in descs:
                descs.append(short_desc)
        return ", ".join(descs)

    def get_locale_desc(self, pages) -> str:
        countries = []
        languages = []
        for page in pages:
            for country in page.country_codes():
                if country not in countries:
                    countries.append(country)
            for language in page.language_codes():
                if language not in languages:
                    languages.append(language)
        locale_list = []
        if countries:
            locale_list.append(", ".join(countries))
        if languages:
            locale_list.append(", ".join(languages))
        return " - ".join(locale_list) or "NONE"
