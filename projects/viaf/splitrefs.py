from collections import OrderedDict
import pywikibot as pwb
from pywikibot import pagegenerators

import requests
import re
import logging

from statedin import StatedIn
from reporting import Reporting
import constants as wd
import references

from typing import List, Dict, Set

SITE = pwb.Site("wikidata", "wikidata")
SITE.login()
SITE.get_tokens("csrf")
REPO = SITE.data_repository()

WD = "http://www.wikidata.org/entity/"
WDQS_ENDPOINT = "https://query.wikidata.org/sparql"
READ_TIMEOUT = 60  # sec


logger = logging.getLogger("splitrefs")


ARCHIVE_URLS = ["web.archive.org", "archive.is", "wayback.archive-it.org"]


def is_archive_url(url: str) -> bool:
    if not url:
        return False
    return any(archive in url.lower() for archive in ARCHIVE_URLS)


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


def get_count(pid: str, url: str):
    count = 0
    index = 0
    limit = 1_000_000
    while True:
        # url = idref.fr
        # pid = P269
        template = """SELECT (count(distinct ?item) as ?count) WHERE {{
                    SERVICE bd:slice {{
                        ?ref pr:P854 ?url.
                        bd:serviceParam bd:slice.offset {index} . # Start at item number (not to be confused with QID)
                        bd:serviceParam bd:slice.limit {limit}  . # List this many items
                    }}
                    ?item ?prop ?statement.
                    ?statement prov:wasDerivedFrom ?ref.
                    FILTER(CONTAINS(LCASE(STR(?url)), "{url}"))
                    FILTER(NOT EXISTS {{ ?ref pr:{pid} ?s. }})
                    FILTER(?prop != p:{pid})
                    }}

                    """
        query = template.format(index=index, limit=limit, pid=pid, url=url)
        sub_count = get_qry_count(query)
        if sub_count == None:
            break
        count = count + sub_count
        logger.info(f"{index}: {sub_count}; total = {count}")
        index = index + limit

    return count


class UnknownURLStrategy:
    def unknown_url(self, qid: str, url: str) -> None:
        pass


class ItemContext:
    """
    Attributes:
        item (ItemPage): The current item being processed.
        test (bool): A flag to indicate test mode.
        qid (str): The QID of the current item.
        unknown_url_strategy (UnknownURLStrategy): Strategy to handle unknown URLs.
    """

    def __init__(
        self,
        item,
        test: bool,
        stated_in: StatedIn,
        unknown_url_strategy: UnknownURLStrategy,
    ) -> None:

        self.item = item
        self.qid = self.item.title()
        self.test = test
        self.stated_in = stated_in
        self.unknown_url_strategy = unknown_url_strategy


class ClaimContext:
    def __init__(self, prop, claim) -> None:
        self.prop = prop
        self.claim = claim
        self.sources = claim.sources
        self.minor_change = False
        self.major_change = False

    def get_is_changed(self):
        return self.minor_change or self.major_change


class ChangeSourceStrategy:
    """
    A strategy class to change sources of claims in Wikidata items.

    Attributes:
        changed_pids (list): List of PIDs where the reference URL is changed to an external id. This is used for reporting.
        something_done (bool): Wikidata item is changed by this strategy
    """

    def __init__(self, item_context: ItemContext) -> None:
        self.item_context = item_context
        self.changed_pids = []
        self.something_done = False

    def change_sources(self, context: ClaimContext) -> None:
        """
        Placeholder function to change sources of a claim.

        Args:
            context (ClaimContext): The context of the claim to change sources for.
        """
        pass

    def get_changed_pids(self):
        return self.changed_pids

    # Function to format properties
    def format_properties(self, summary_list, ids, action: str, template: str):
        if len(ids) > 0:
            ids = [template.format(id=id) for id in ids]
            summary_list.append(f"{action} " + ", ".join(ids))

    def append_summary(self, summary_list: List[str]) -> List[str]:
        """
        Appends a summary to the list if changes were made.

        This function checks if any changes were made and, if so, appends a
        summary of those changes to the provided summary list.

        Args:
            summary_list (List[str]): The list to append the summary to.

        Returns:
            List[str]: The updated list of summaries.
        """
        pass

    def claim_changed(self, context: ClaimContext, major_change: bool = False) -> None:
        if major_change:
            context.major_change = True
        else:
            context.minor_change = True
        self.something_done = True

    def unknown_url(self, url: str):
        if self.item_context.unknown_url_strategy:
            self.item_context.unknown_url_strategy.unknown_url(
                self.item_context.qid, url
            )


class RemoveEnglishWikipedia(ChangeSourceStrategy):

    def change_sources(self, context: ClaimContext) -> None:
        new_sources = []
        for src in context.sources:
            changed, new_src = self.remove_english_wikipedia(src)
            if changed:
                self.claim_changed(context)
                if new_src:
                    new_sources.append(new_src)
            else:
                # nothing changed, add original source
                new_sources.append(src)
        context.sources = new_sources

    def remove_english_wikipedia(self, src: Dict):
        changed = False
        new_source = OrderedDict()
        for prop in src:
            new_list = []
            for claim in src[prop]:
                if claim and claim.type == "wikibase-item":
                    qid = claim.getTarget().getID()
                    if (
                        qid == wd.QID_ENGLISHWIKIPEDIA
                        or qid == wd.QID_GERMANWIKIPEDIA
                        or qid == wd.QID_WEBSITE
                        or qid == wd.QID_BIRTH_CERTIFICATE
                        or qid == wd.QID_DEATH_CERTIFICATE
                        or qid == wd.QID_MARRIAGECERTIFICATE
                        or qid == wd.QID_DOCUMENT
                        or qid == wd.QID_REPORT
                    ):
                        # skip
                        changed = True
                        continue
                new_list.append(claim)

            if new_list != []:
                new_source[prop] = new_list

        return changed, new_source

    def append_summary(self, summary_list: List[str]) -> List[str]:
        if self.something_done:
            summary = f"removed [[{wd.QID_ENGLISHWIKIPEDIA}]]"
            summary_list.append(summary)
        return summary_list


class Treccani(ChangeSourceStrategy):
    def __init__(self, item_context: ItemContext) -> None:
        super().__init__(item_context)
        self.pids = set()

    def change_sources(self, context: ClaimContext) -> None:
        new_sources = []
        claim_changed = False
        for src in context.sources:
            if wd.PID_TRECCANI_ID in src:
                if len(src[wd.PID_TRECCANI_ID]) != 1:
                    raise RuntimeError(
                        f"Treccani: nr of ids = {len(src[wd.PID_TRECCANI_ID])}"
                    )
                treccani_id = src[wd.PID_TRECCANI_ID][0].getTarget()
                if "(" not in treccani_id:
                    # nothing changed, add original source
                    new_sources.append(src)
                    continue
                normalized_treccani_id = treccani_id.replace("(", "_(").replace(
                    "__(", "_("
                )
                normalized_treccani_id = normalized_treccani_id.rstrip("/")

                url = "https://www.treccani.it/enciclopedia/" + normalized_treccani_id
                found_list = self.item_context.stated_in.extract_ids_from_url(url)
                found = None
                for item in found_list:
                    pid, __, id = item
                    if "(" in id:
                        continue
                    if found:
                        raise RuntimeError(
                            f"Treccani: multiple found: {pid} - {found[0]}: {url}"
                        )
                    found = item
                if not found:
                    raise RuntimeError(f"Treccani: no id found for {url}")

                pid, stated_in, id, keep_url = found
                if pid == context.prop:
                    # external id reference; change to url
                    new_src = self.change_external_id_ref(src, found, treccani_id)
                    new_sources.append(new_src)
                else:
                    # normal reference; change stated in
                    new_src = self.change_ref(src, found, treccani_id)
                    new_sources.append(new_src)

                claim_changed = True
                self.claim_changed(context, major_change=True)
                continue

            # nothing changed, add original source
            new_sources.append(src)

        if claim_changed:
            context.sources = new_sources

    def change_external_id_ref(self, src, t, treccani_id):
        self.external_id_ref_changed = True
        pid, stated_in, id = t
        url = "https://www.treccani.it/enciclopedia/" + treccani_id

        if wd.PID_REFERENCE_URL in src:
            raise RuntimeError("Unexpeced reference URL")
        new_source = OrderedDict()
        for prop in src:
            if prop == wd.PID_STATED_IN:
                if len(src[prop]) != 1:
                    raise RuntimeError("length != 1")
                act_stated_in = src[prop][0].getTarget().getID()
                if act_stated_in != stated_in:
                    continue
            elif prop == wd.PID_TRECCANI_ID:
                if len(src[prop]) != 1:
                    raise RuntimeError("length != 1")
                act_id = src[prop][0].getTarget()
                if act_id != treccani_id:
                    raise RuntimeError("diff id")

                ref_url_claim = pwb.Claim(REPO, wd.PID_REFERENCE_URL)
                ref_url_claim.isReference = True
                ref_url_claim.setTarget(url)
                ref_url_claim.on_item = self.item
                new_source[wd.PID_REFERENCE_URL] = [ref_url_claim]

                self.pids.add(wd.PID_REFERENCE_URL)
                continue

            new_source[prop] = src[prop]
        return new_source

    def change_ref(self, src, t, treccani_id):
        self.ref_changed = True
        pid, stated_in, id = t
        new_source = OrderedDict()
        for prop in src:
            if prop == wd.PID_STATED_IN:
                if len(src[prop]) != 1:
                    raise RuntimeError("length != 1")
                # act_stated_in = src[prop][0].getTarget().getID()
                # if act_stated_in == stated_in:
                #    continue
                stated_in_claim = pwb.Claim(REPO, wd.PID_STATED_IN)
                stated_in_claim.isReference = True
                stated_in_claim.setTarget(pwb.ItemPage(REPO, stated_in))
                stated_in_claim.on_item = self.item
                new_source[wd.PID_STATED_IN] = [stated_in_claim]
                continue
            elif prop == wd.PID_TRECCANI_ID:
                if len(src[prop]) != 1:
                    raise RuntimeError("length != 1")
                act_id = src[prop][0].getTarget()
                if act_id != treccani_id:
                    raise RuntimeError("diff id")

                pid_claim = pwb.Claim(REPO, pid)
                pid_claim.isReference = True
                pid_claim.setTarget(id)
                pid_claim.on_item = self.item
                new_source[pid] = [pid_claim]

                self.pids.add(pid)
                continue
            elif prop == pid:
                raise RuntimeError("unexpected prop pid")
            new_source[prop] = src[prop]
        return new_source

    def append_summary(self, summary_list: List[str]) -> List[str]:
        self.format_properties(
            summary_list,
            self.pids,
            f"changed [[Property:{wd.PID_TRECCANI_ID}]] into",
            "[[Property:{id}]]",
        )

        return summary_list


class SplitSources(ChangeSourceStrategy):
    def __init__(self, item_context: ItemContext) -> None:
        super().__init__(item_context)
        self.has_archive = False

    def change_sources(self, context: ClaimContext) -> None:
        if context.prop not in [
            wd.PID_SEX_OR_GENDER,
            wd.PID_DATE_OF_BIRTH,
            wd.PID_DATE_OF_DEATH,
            wd.PID_ISNI,
            wd.PID_OCCUPATION,
        ]:
            return

        new_sources = []
        claim_changed = False
        for src in context.sources:
            if self.can_split_source(src):
                source_changed, source_list = self.split_source(src)
                if source_changed:
                    self.something_done = self.something_done
                    claim_changed = True
                    new_sources.extend(source_list)
                    continue

            # nothing changed, add original source
            new_sources.append(src)

        if claim_changed:
            context.sources = new_sources

    def can_split_source(self, src: Dict) -> bool:
        if wd.PID_REFERENCE_URL not in src:
            return False

        count = len(src[wd.PID_REFERENCE_URL])
        if count <= 1:
            return False

        for prop in src:
            if self.split_getty and prop == wd.PID_UNION_LIST_OF_ARTIST_NAMES_ID:
                continue
            if self.split_getty and prop == wd.PID_STATED_IN:
                if len(src[prop]) != 1:
                    return False
                qid = src[prop][0].getTarget().getID()
                if qid == wd.QID_UNION_LIST_OF_ARTIST_NAMES:
                    continue
                else:
                    return False

            if prop not in (
                wd.PID_REFERENCE_URL,
                wd.PID_RETRIEVED,
                wd.PID_ARCHIVE_DATE,
                wd.PID_ARCHIVE_URL,
            ):
                if wd.PID_REFERENCE_URL in src and len(src[wd.PID_REFERENCE_URL]) > 1:
                    raise RuntimeError(f"Multiple Reference url, with {prop}")
                return False

        # do not accept multiple PID_ARCHIVE_URL
        if wd.PID_ARCHIVE_URL in src and len(src[wd.PID_ARCHIVE_URL]) > 1:
            raise RuntimeError("Multiple Archive URL")

        # do not accept multiple PID_ARCHIVE_DATE
        if wd.PID_ARCHIVE_DATE in src and len(src[wd.PID_ARCHIVE_DATE]) > 1:
            raise RuntimeError("Multiple Archive date")

        # do not accept multiple PID_RETRIEVED
        if wd.PID_RETRIEVED in src and len(src[wd.PID_RETRIEVED]) > 1:
            raise RuntimeError("Multiple Retrieved")

        if wd.PID_ARCHIVE_URL in src or wd.PID_ARCHIVE_DATE in src:
            self.has_archive = True

        if wd.PID_ARCHIVE_URL in src:
            archive_url = src[wd.PID_ARCHIVE_URL][0].getTarget()
            found = False
            for value in src[wd.PID_REFERENCE_URL]:
                url = value.getTarget()
                if url in archive_url:
                    found = True
                    break
            if not found:
                raise RuntimeError(f"Unrecognized archive url: {archive_url}")

        domains = set()
        for value in src[wd.PID_REFERENCE_URL]:
            url = value.getTarget()
            if is_archive_url(url):
                raise RuntimeError(f"Found archive url {url}")

            stated_in_qid = self.item_context.stated_in.get_stated_in_from_url(url)
            if not stated_in_qid:
                # prevent splitting reference urls with the same domain but different language, for example:
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
                            raise RuntimeError(f"Found duplicate domain {domain}")
                        domains.add(domain)

        return True

    def split_source(self, src: Dict):
        """
        Splits source with multiple reference urls into multiple sources with one reference url.

        Returns:
            tuple: A tuple containing a boolean flag indicating if any changes were made (changed) and a list of sources.
        """
        sources = []
        retrieved_claim = self.get_single_claim(src, wd.PID_RETRIEVED)
        archive_date_claim = self.get_single_claim(src, wd.PID_ARCHIVE_DATE)
        archive_url_claim = self.get_single_claim(src, wd.PID_ARCHIVE_URL)
        if archive_url_claim:
            archive_url = archive_url_claim.getTarget()
        else:
            archive_url = None
        changed = len(src[wd.PID_REFERENCE_URL]) > 1
        for value in src[wd.PID_REFERENCE_URL]:
            source = OrderedDict()

            url = value.getTarget()
            stated_in_qid = self.item_context.stated_in.get_stated_in_from_url(url)
            if stated_in_qid:
                stated_in_claim = pwb.Claim(REPO, wd.PID_STATED_IN)
                stated_in_claim.isReference = True
                stated_in_claim.setTarget(pwb.ItemPage(REPO, stated_in_qid))
                stated_in_claim.on_item = self.item
                source[wd.PID_STATED_IN] = [stated_in_claim]
                changed = True

            ref = pwb.Claim(REPO, wd.PID_REFERENCE_URL)
            ref.isReference = True
            ref.setTarget(url)
            ref.on_item = self.item
            source[wd.PID_REFERENCE_URL] = [ref]

            if retrieved_claim is not None:
                retr = pwb.Claim(REPO, wd.PID_RETRIEVED)
                retr.isReference = True
                dt = retrieved_claim.getTarget()
                retr.setTarget(dt)
                retr.on_item = self.item
                source[wd.PID_RETRIEVED] = [retr]

            if archive_url and url in archive_url:
                arch_url = pwb.Claim(REPO, wd.PID_ARCHIVE_URL)
                arch_url.isReference = True
                arch_url.setTarget(archive_url)
                arch_url.on_item = self.item
                source[wd.PID_ARCHIVE_URL] = [arch_url]

                if archive_date_claim is not None:
                    arch_date = pwb.Claim(REPO, wd.PID_ARCHIVE_DATE)
                    arch_date.isReference = True
                    dt = archive_date_claim.getTarget()
                    arch_date.setTarget(dt)
                    arch_date.on_item = self.item
                    source[wd.PID_ARCHIVE_DATE] = [arch_date]

                archive_url = None

            sources.append(source)

        return changed, sources

    def append_summary(self, summary_list: List[str]) -> List[str]:
        if self.something_done:
            if self.has_archive:
                summary = f"split reference with multiple [[Property:{wd.PID_REFERENCE_URL}]] and [[Property:{wd.PID_ARCHIVE_URL}]] "
            else:
                summary = (
                    f"split reference with multiple [[Property:{wd.PID_REFERENCE_URL}]]"
                )
            summary_list.append(summary)

        return summary_list


class RemoveReferenceURL(ChangeSourceStrategy):
    """
    A strategy class to remove redundant reference URLs from sources in Wikidata items.

    Attributes:
        removed_count (int): The total number of reference URLs that are removed from a page.
    """

    def __init__(self, item_context: ItemContext) -> None:
        super().__init__(item_context)
        self.removed_count = 0

    def change_sources(self, context: ClaimContext) -> None:
        new_sources = []
        for src in context.sources:
            new_src = self.remove_redundant_reference_url(src, context.prop)
            if new_src:
                self.removed_count += 1
                new_sources.append(new_src)

                self.claim_changed(context)
            else:
                # nothing changed, add original source
                new_sources.append(src)

        context.sources = new_sources

    def remove_redundant_reference_url(self, src: Dict, skip_prop: str) -> Dict | None:
        if wd.PID_REFERENCE_URL not in src:
            return None

        count = len(src[wd.PID_REFERENCE_URL])
        if count > 1:
            return None

        # seen in Q18638122
        if wd.PID_IMPORTED_FROM_WIKIMEDIA_PROJECT in src:
            # todo ; log
            return None
        if wd.PID_WIKIMEDIA_IMPORT_URL in src:
            # todo ; log
            return None

        try:
            pid = self.item_context.stated_in.get_pid_from_source(src)
            if not pid or not pid.startswith("P"):
                # BOOK
                return None

            if pid == skip_prop:
                return None
        except RuntimeError as e:
            # multiple pids
            return None

        keep_url = self.item_context.stated_in.get_keep_url(pid, src)
        if keep_url:
            return None

        if self.item_context.test:
            logger.info(
                f"Removed {skip_prop} - {pid} - {self.item_context.stated_in.get_id_from_source(src)}"
            )

        new_source = OrderedDict()

        for prop in src:
            if prop == wd.PID_REFERENCE_URL:
                continue
            new_source[prop] = src[prop]

        return new_source

    def append_summary(self, summary_list: List[str]) -> List[str]:
        if self.removed_count > 0:
            summary_list.append(
                f"removed [[Property:{wd.PID_REFERENCE_URL}]] ({self.removed_count}x)"
            )
        return summary_list


class RemoveWeakSources(ChangeSourceStrategy):
    def __init__(self, item_context: ItemContext) -> None:
        super().__init__(item_context)
        self.pids_removed = set()

    def change_sources(self, context: ClaimContext) -> None:
        # only execute this if something major was already changed
        if not context.major_change:
            return

        new_sources = []
        for src in context.sources:
            pid = self.get_weak_source_pid(src)
            if pid:
                self.pids_removed.add(pid)
                self.claim_changed(context, major_change=True)
            else:
                # nothing changed, add original source
                new_sources.append(src)

        context.sources = new_sources

    def get_weak_source_pid(self, source: Dict) -> str | None:
        if wd.PID_IMPORTED_FROM_WIKIMEDIA_PROJECT in source:
            return wd.PID_IMPORTED_FROM_WIKIMEDIA_PROJECT
        elif wd.PID_WIKIMEDIA_IMPORT_URL in source:
            return wd.PID_WIKIMEDIA_IMPORT_URL
        else:
            return None

    def append_summary(self, summary_list: List[str]) -> List[str]:
        self.format_properties(
            summary_list, self.pids_removed, "removed", "[[Property:{id}]]"
        )
        return summary_list


class RemoveRetrievedSources(ChangeSourceStrategy):

    def change_sources(self, context: ClaimContext) -> None:

        EXCLUDED_CLAIM_IDS = [
            wd.PID_APPLIES_TO_JURISDICTION,
            wd.PID_BASED_ON,
            wd.PID_BUSINESS_DIVISION,
            wd.PID_CATALOG_CODE,
            wd.PID_CATALOG,
            wd.PID_CHARTED_IN,
            wd.PID_COLLECTION,
            wd.PID_COPYRIGHT_HOLDER,
            wd.PID_COPYRIGHT_REPRESENTATIVE,
            wd.PID_COPYRIGHT_STATUS_AS_A_CREATOR,
            wd.PID_CURATOR,
            wd.PID_DERIVATIVE_WORK,
            wd.PID_DESCRIBED_AT_URL,
            wd.PID_DESCRIBED_BY_SOURCE,
            wd.PID_DIFFERENT_FROM,
            wd.PID_DISTRIBUTED_BY,
            wd.PID_EDITION_OR_TRANSLATION_OF,
            wd.PID_FOLLOWED_BY,
            wd.PID_FOLLOWS,
            wd.PID_FOUNDED_BY,
            wd.PID_HAS_CHARACTERISTIC,  # complex; skip
            wd.PID_HAS_EDITION_OR_TRANSLATION,
            wd.PID_HAS_PARTS,
            wd.PID_HAS_SUBSIDIARY,
            wd.PID_HEADQUARTERS_LOCATION,  # moment in time?
            wd.PID_INDUSTRY,
            wd.PID_INVENTORY_NUMBER,
            wd.PID_LEGAL_FORM,
            wd.PID_LOCATED_IN_THE_ADMINISTRATIVE_TERRITORIAL_ENTITY,
            wd.PID_MEMBER_OF,
            wd.PID_ON_FOCUS_LIST_OF_WIKIMEDIA_PROJECT,
            wd.PID_OPERATOR,
            wd.PID_ORAL_HISTORY_AT,
            wd.PID_PARENT_ORGANIZATION,
            wd.PID_PART_OF_THE_SERIES,
            wd.PID_PART_OF,
            wd.PID_PUBLISHED_IN,  # not sure; skip
            wd.PID_RECORDING_OR_PERFORMANCE_OF,
            wd.PID_RELATED_CATEGORY,
            wd.PID_RELEASE_OF,
            wd.PID_REPLACED_BY,
            wd.PID_REPLACES,
            wd.PID_SAID_TO_BE_THE_SAME_AS,
            wd.PID_TRANSLATOR,
            wd.PID_WORK_LOCATION,  # moment in time?
            wd.PID_RESIDENCE,
            wd.PID_ARCHIVES_AT,
            wd.PID_OWNED_BY,
            wd.PID_TRADING_NAME,
            wd.PID_OPERATING_AREA,
            wd.PID_PUBLISHER,
            wd.PID_CONTRIBUTOR_TO_THE_CREATIVE_WORK_OR_SUBJECT,
            wd.PID_EMPLOYER,
            wd.PID_COMPOSER,
            wd.PID_EDUCATED_AT,
            wd.PID_OWNER_OF,
            wd.PID_HAS_WORKS_IN_THE_COLLECTION,
            wd.PID_DIRECTOR,
            wd.PID_LOCATION_OF_FORMATION,
            wd.PID_CREATOR,
            wd.PID_MODIFIED_VERSION_OF,
            wd.PID_COMMONS_CATEGORY,
            wd.PID_ADAPTED_BY,
            wd.PID_LYRICIST,
            wd.PID_PARTNER_IN_BUSINESS_OR_SPORT,
            wd.PID_AFFILIATION,
            wd.PID_MUSICAL_CONDUCTOR,
            wd.PID_ORIGINAL_LANGUAGE_OF_FILM_OR_TV_SHOW,
            wd.PID_DEDICATED_TO,
            wd.PID_COVER_ART_BY,
            wd.PID_NATIVE_LABEL,
            wd.PID_MUSIC_VIDEO,
            wd.PID_SOCIAL_MEDIA_FOLLOWERS,
            wd.PID_ACADEMIC_DEGREE,
            wd.PID_INSTRUMENT,
            wd.PID_NUMBER_OF_REPRESENTATIONS,
            wd.PID_DIRECTOR_MANAGER,
            wd.PID_REISSUE_OF,
            wd.PID_LOCATION_OF_FIRST_PERFORMANCE,
            wd.PID_HASHTAG,
            wd.PID_TOPICS_MAIN_CATEGORY,
            wd.PID_FIELD_OF_WORK,
            wd.PID_DESIGNED_BY,
            wd.PID_TRANSLATION_OF,
            wd.PID_HAS_LIST,
            wd.PID_LIST_OF_WORKS,
            wd.PID_CONFERRED_BY,
            wd.PID_DONATED_BY,
            wd.PID_DOCUMENTATION_FILES_AT,
            wd.PID_PRODUCT_OR_MATERIAL_PRODUCED_OR_SERVICE_PROVIDED,
            wd.PID_STUDENT_OF,
            wd.PID_FLOORS_ABOVE_GROUND,
            wd.PID_NUMBER_OF_EPISODES,
            wd.PID_EMPLOYEES,
            wd.PID_ITEM_OPERATED,
            wd.PID_REPRESENTS,
            wd.PID_FACET_OF,
            wd.PID_FILMOGRAPHY,
            wd.PID_OFFICEHOLDER,
            wd.PID_PARTICIPANT_IN,
            wd.PID_NOMINATED_FOR,
            wd.PID_AFFILIATION,
            wd.PID_HERITAGE_DESIGNATION,
            wd.PID_MOTTO_TEXT,
            wd.PID_ARCHITECTURAL_STYLE,
            wd.PID_CAST_MEMBER,
            wd.PID_PLAINTIFF,
            wd.PID_STRUCTURE_REPLACED_BY,
            wd.PID_FREQUENCY,
            wd.PID_USES,
            wd.PID_OFFICE_HELD_BY_HEAD_OF_THE_ORGANIZATION,
            wd.PID_NUMBER_OF_SEASONS,
            wd.PID_NARRATOR,
            wd.PID_PLACE_OF_DETENTION,
            wd.PID_INTERESTED_IN,
            wd.PID_HAS_PARTS_OF_THE_CLASS,
            wd.PID_PRODUCTION_COMPANY,
            wd.PID_PRODUCED_BY,
            wd.PID_PUBLICATION_INTERVAL,
            wd.PID_IS_A_LIST_OF,
            wd.PID_HAS_USE,
            wd.PID_NUMBER_OF_SUBSCRIBERS,
            wd.PID_ORIGINAL_FILM_FORMAT,
            wd.PID_MEMBERS_HAVE_OCCUPATION,
            wd.PID_SOUNDTRACK_RELEASE,
            wd.PID_MILITARY_OR_POLICE_RANK,
            wd.PID_CATEGORY_FOR_EMPLOYEES_OF_THE_ORGANIZATION,
            wd.PID_CONTAINS,
            wd.PID_ORIGINAL_BROADCASTER,
            wd.PID_SHARES_BORDER_WITH,
            wd.PID_CHAIRPERSON,
            wd.PID_MEMBER_OF_SPORTS_TEAM,
            wd.PID_ACCREDITED_BY,
            wd.PID_TIME_OF_DISCOVERY_OR_INVENTION,
            wd.PID_MAJORITY_OPINION_BY,
            wd.PID_EXHIBITION_HISTORY,
            wd.PID_QUOTES_WORK,
            wd.PID_ADVERTISES,
            wd.PID_HAS_WRITTEN_FOR,
            wd.PID_PARTICIPANT,
            wd.PID_SERVICE_ENTRY,
            wd.PID_AUTHORITY,
            wd.PID_CONNECTING_LINE,
            wd.PID_LIBRETTIST,
            wd.PID_PRINTED_BY,
            wd.PID_COMMISSIONED_BY,
            wd.PID_FILMING_LOCATION,
            wd.PID_MAIN_REGULATORY_TEXT,
            wd.PID_ARTIST_FILES_AT,
            wd.PID_LEGAL_CITATION_OF_THIS_TEXT,
            wd.PID_NUMBER_OF_LIKES,
            wd.PID_NUMBER_OF_ELEVATORS,
            wd.PID_ADJACENT_STATION,
            wd.PID_OCCUPANT,
            wd.PID_NUMBER_OF_VIEWERSLISTENERS,
            wd.PID_INFLUENCED_BY,
            wd.PID_SOUNDEX,
            wd.PID_STUDENT,
            wd.PID_MAINTAINED_BY,
            wd.PID_COMMONS_CREATOR_PAGE,
            wd.PID_JUDGE,
            wd.PID_CHIEF_EXECUTIVE_OFFICER,
            wd.PID_STOCK_EXCHANGE,
        ]

        NO_QUAL_CLAIM_IDS = [
            wd.PID_OCCUPATION,
            wd.PID_POSITION_HELD,
        ]
        REMOVABLE_CLAIM_IDS = [
            wd.PID_ANNOUNCEMENT_DATE,
            wd.PID_AUTHOR_NAME_STRING,
            wd.PID_AUTHOR,
            wd.PID_AWARD_RECEIVED,
            wd.PID_BIRTH_NAME,
            wd.PID_CALL_SIGN,
            wd.PID_CAUSE_OF_DEATH,
            wd.PID_CHILD,
            wd.PID_COLOR,
            wd.PID_CONFLICT,
            wd.PID_CONVICTED_OF,
            wd.PID_COPYRIGHT_STATUS,
            wd.PID_COUNTRY_OF_CITIZENSHIP,
            wd.PID_COUNTRY_OF_ORIGIN,
            wd.PID_COUNTRY,
            wd.PID_DATE_OF_BIRTH,
            wd.PID_DATE_OF_DEATH,
            wd.PID_DATE_OF_FIRST_PERFORMANCE,
            wd.PID_DATE_OF_OFFICIAL_CLOSURE,
            wd.PID_DATE_OF_OFFICIAL_OPENING,
            wd.PID_DISCOGRAPHY,
            wd.PID_DISSOLVED_ABOLISHED_OR_DEMOLISHED_DATE,  # date
            wd.PID_DISTRIBUTION_FORMAT,
            wd.PID_DURATION,
            wd.PID_EDITION_NUMBER,
            wd.PID_EDITOR,
            wd.PID_END_TIME,  # date
            wd.PID_ETHNIC_GROUP,
            wd.PID_EXHIBITED_CREATOR,
            wd.PID_EYE_COLOR,
            wd.PID_EYE_COLOR,
            wd.PID_FABRICATION_METHOD,
            wd.PID_FAMILY_NAME,
            wd.PID_FAMILY,
            wd.PID_FATHER,
            wd.PID_FIRST_LINE,
            wd.PID_FLORUIT,
            wd.PID_FORM_OF_CREATIVE_WORK,
            wd.PID_GENRE,
            wd.PID_GIVEN_NAME,
            wd.PID_HAIR_COLOR,
            wd.PID_HAS_MELODY,
            wd.PID_HEIGHT,
            wd.PID_HONORIFIC_PREFIX,
            wd.PID_HONORIFIC_SUFFIX,
            wd.PID_INCEPTION,
            wd.PID_INSPIRED_BY,
            wd.PID_INSTANCE_OF,
            wd.PID_ISSUE,
            wd.PID_KILLED_BY,
            wd.PID_LANGUAGE_OF_WORK_OR_NAME,
            wd.PID_LANGUAGES_SPOKEN_WRITTEN_OR_SIGNED,
            wd.PID_LAST_LINE,
            wd.PID_LAST_UPDATE,
            wd.PID_LENGTH,
            wd.PID_LOCATED_ON_STREET,
            wd.PID_LOCATION_OF_CREATION,
            wd.PID_LOCATION,
            wd.PID_MADE_FROM_MATERIAL,
            wd.PID_MAIN_SUBJECT,
            wd.PID_MANNER_OF_DEATH,
            wd.PID_MANUFACTURER,
            wd.PID_MARRIED_NAME,
            wd.PID_MASS,
            wd.PID_MEDICAL_CONDITION,
            wd.PID_MEMBER_OF_POLITICAL_PARTY,
            wd.PID_MOTHER,
            wd.PID_NAME_IN_NATIVE_LANGUAGE,
            wd.PID_NAME,
            wd.PID_NAMED_AFTER,
            wd.PID_NATIVE_LANGUAGE,
            wd.PID_NICKNAME,
            wd.PID_NOBLE_TITLE,
            wd.PID_NOTABLE_WORK,
            wd.PID_NUMBER_OF_CHILDREN,
            wd.PID_NUMBER_OF_PAGES,
            wd.PID_NUMBER_OF_PARTS_OF_THIS_WORK,
            wd.PID_OFFICIAL_NAME,
            wd.PID_PAGES,
            wd.PID_PERFORMER,
            wd.PID_PHONE_NUMBER,
            wd.PID_PHONE_NUMBER,
            wd.PID_PLACE_OF_BIRTH,
            wd.PID_PLACE_OF_BURIAL,
            wd.PID_PLACE_OF_DEATH,
            wd.PID_PLACE_OF_PUBLICATION,
            wd.PID_POINT_IN_TIME,
            wd.PID_POLITICAL_IDEOLOGY,
            wd.PID_POSTAL_CODE,
            wd.PID_PRODUCER,
            wd.PID_PRODUCT_OR_MATERIAL_PRODUCED_OR_SERVICE_PROVIDED,
            wd.PID_PRODUCTION_DATE,  # date
            wd.PID_PSEUDONYM,
            wd.PID_PUBLICATION_DATE,
            wd.PID_RECORD_LABEL,
            wd.PID_RECORDED_AT_STUDIO_OR_VENUE,
            wd.PID_RECORDING_DATE,
            wd.PID_RELATIVE,
            wd.PID_RELIGION_OR_WORLDVIEW,
            wd.PID_RELIGIOUS_NAME,
            wd.PID_SCANDINAVIAN_MIDDLE_FAMILY_NAME,
            wd.PID_SECOND_FAMILY_NAME_IN_SPANISH_NAME,
            wd.PID_SEX_OR_GENDER,
            wd.PID_SHORT_NAME,
            wd.PID_SIBLING,
            wd.PID_SIGNIFICANT_EVENT,
            wd.PID_SIGNIFICANT_EVENT,
            wd.PID_SOCIAL_CLASSIFICATION,
            wd.PID_SPOUSE,
            wd.PID_START_TIME,
            wd.PID_STREET_ADDRESS,
            wd.PID_SUBCLASS_OF,
            wd.PID_SUBTITLE,
            wd.PID_TIME_OF_EARLIEST_WRITTEN_RECORD,
            wd.PID_TITLE,
            wd.PID_TRACKLIST,
            wd.PID_UNMARRIED_PARTNER,
            wd.PID_VOICE_TYPE,
            wd.PID_VOLUME,
            wd.PID_WIDTH,
            wd.PID_WORK_PERIOD_END,
            wd.PID_WORK_PERIOD_START,
            wd.PID_WRITING_LANGUAGE,
            wd.PID_PENALTY,
            wd.PID_THICKNESS,
            wd.PID_HEIGHT_OF_LETTERS,
        ]

        # Check if claim.id is in the excluded list
        if context.claim.id in EXCLUDED_CLAIM_IDS:
            return

        # Ensure there is exactly one source
        if len(context.sources) != 1:
            return

        src = context.sources[0]

        # Check if PID_RETRIEVED is in the source
        if wd.PID_RETRIEVED not in src:
            return

        # Ensure PID_RETRIEVED is the only property in the source
        if any(prop != wd.PID_RETRIEVED for prop in src):
            return

        # Acceptable claim types
        if context.claim.type in ["external-id", "url"]:
            return

        # Skip specific claim types
        if context.claim.type not in [
            "monolingualtext",
            "wikibase-item",
            "string",
            "time",
            "quantity",
        ]:
            return

        # Remove if claim.id is in the removable list
        if context.claim.id in REMOVABLE_CLAIM_IDS:

            references.check_retrieved_year(src)
            self.claim_changed(context)
            context.sources = []
            return

        if context.claim.id in NO_QUAL_CLAIM_IDS:
            if context.claim.qualifiers and len(context.claim.qualifiers) > 0:
                return
            else:

                references.check_retrieved_year(src)
                self.claim_changed(context)
                context.sources = []
                return

        raise RuntimeError(
            f"remove_retrieved_sources: {context.claim.id} - {context.prop}"
        )

    def append_summary(self, summary_list: List[str]) -> List[str]:
        if self.something_done:
            summary_list.append(f"removed [[Property:{wd.PID_RETRIEVED}]]")
        return summary_list


class MergeRetrieved(ChangeSourceStrategy):
    def __init__(self, item_context: ItemContext) -> None:
        super().__init__(item_context)
        self.did_merge_retrieved = False
        self.did_remove_retrieved = False

    def change_sources(self, context: ClaimContext) -> None:

        if len(context.sources) <= 1:
            return

        ref = references.References(context.claim, context.sources)
        ref.remove_single_retrieved()
        if ref.did_merge or ref.did_remove:
            self.claim_changed(context)
            if ref.did_merge:
                self.did_merge_retrieved = True
            if ref.did_remove:
                self.did_remove_retrieved = True
            context.sources = ref.sources

        if "R" in ref.get_tokens():
            if context.claim.type not in ["external-id", "url"]:
                raise RuntimeError(
                    f"merge_retrieved: {context.claim.id} - {context.prop} - {ref.get_tokens()}"
                )

    def append_summary(self, summary_list: List[str]) -> List[str]:
        if self.did_merge_retrieved:
            summary_list.append(f"merged [[Property:{wd.PID_RETRIEVED}]]")
        if self.did_remove_retrieved:
            summary_list.append(f"removed [[Property:{wd.PID_RETRIEVED}]]")
        return summary_list


class SplitStatedInSources(ChangeSourceStrategy):

    def change_sources(self, context: ClaimContext) -> None:
        new_sources = []
        for src in context.sources:
            if self.has_only_stated_in(src):

                for stated_in in src[wd.PID_STATED_IN]:
                    new_source = OrderedDict()
                    new_source[wd.PID_STATED_IN] = [stated_in]
                    new_sources.append(new_source)

                self.claim_changed(context)
            else:
                # nothing changed, add original source
                new_sources.append(src)

        context.sources = new_sources

    def has_only_stated_in(self, src: Dict) -> bool:
        if wd.PID_STATED_IN not in src:
            return False
        if len(src[wd.PID_STATED_IN]) <= 1:
            return False
        for prop in src:
            if prop != wd.PID_STATED_IN:
                return False
        return True

    def append_summary(self, summary_list: List[str]) -> List[str]:
        if self.something_done:
            summary_list.append(f"split [[Property:{wd.PID_STATED_IN}]]")
        return summary_list


class AddExternalID(ChangeSourceStrategy):
    def __init__(self, item_context: ItemContext) -> None:
        super().__init__(item_context)
        self.pids_addid = set()

    def change_sources(self, context: ClaimContext) -> None:
        new_sources = []
        for src in context.sources:
            new_src = self.add_external_id(src, context.prop)
            if new_src:
                self.claim_changed(context, major_change=True)
                new_sources.append(new_src)
            else:
                # nothing changed, add original source
                new_sources.append(src)

        context.sources = new_sources

    def add_external_id(self, src: Dict, skip_prop: str) -> Dict | None:
        """
        Adds an external ID to a source if applicable.

        Args:
            src (Dict): The source to add the external ID to.
            skip_prop (str): The property to skip during addition.

        Returns:
            Dict: The new source with the added external ID, or None if no changes were made.
        """

        if wd.PID_REFERENCE_URL not in src:
            return None

        count = len(src[wd.PID_REFERENCE_URL])
        if count > 1:
            return None

        # seen in Q18638122
        if wd.PID_IMPORTED_FROM_WIKIMEDIA_PROJECT in src:
            # todo ; log
            return None
        if wd.PID_WIKIMEDIA_IMPORT_URL in src:
            # todo ; log
            return None

        for prop in src:
            # could be wrong pid, but we'll ignore that for now
            # for example: X username, X post ID
            if self.item_context.stated_in.is_id_pid(prop):
                return None

        ref = src[wd.PID_REFERENCE_URL][0]
        url = ref.getTarget()
        tuple = self.item_context.stated_in.get_id_from_reference_url(src)
        if tuple is None:
            logger.info(f"unknown url {url}")
            self.unknown_url(url)
            return None

        pid, stated_in, id = tuple
        if pid == skip_prop:
            return None

        keep_url = self.item_context.stated_in.get_keep_url(pid, src)

        if self.test:
            logger.info(f"{skip_prop} url: {url} => {pid} {id}")

        new_source = OrderedDict()

        if stated_in:
            stated_in_claim = pwb.Claim(REPO, wd.PID_STATED_IN)
            stated_in_claim.isReference = True
            stated_in_claim.setTarget(pwb.ItemPage(REPO, stated_in))
            stated_in_claim.on_item = self.item
            new_source[wd.PID_STATED_IN] = [stated_in_claim]

        if pid and id:
            self.pids_addid.add(pid)
            self.changed_pids.append(pid)
            pid_claim = pwb.Claim(REPO, pid)
            pid_claim.isReference = True
            pid_claim.setTarget(id)
            pid_claim.on_item = self.item
            new_source[pid] = [pid_claim]

        for prop in src:
            if prop == wd.PID_STATED_IN:
                continue
            if not keep_url and (prop == wd.PID_REFERENCE_URL):
                continue
            new_source[prop] = src[prop]

        return new_source

    def append_summary(self, summary_list: List[str]) -> List[str]:
        self.format_properties(
            summary_list,
            self.pids_addid,
            f"changed [[Property:{wd.PID_REFERENCE_URL}]] into",
            "[[Property:{id}]]",
        )
        return summary_list


class MultipleStatedIn(ChangeSourceStrategy):
    """
    A strategy class to handle cases where multiple 'stated in' values are present in sources of Wikidata items.

    Attributes:
        TYPE_OF_REFERENCE_IDS (List[str]): A list of QIDs that are considered types of references.
        QIDS (Dict[str, str]): A dictionary mapping QIDs to their corresponding PIDs.
    """
    TYPE_OF_REFERENCE_IDS = [
        wd.QID_OFFICIAL_WEBSITE,
        wd.QID_CURRICULUM_VITAE,
        wd.QID_BIRTH_REGISTRY,
        wd.QID_BIRTH_CERTIFICATE,
        wd.QID_DEATH_REGISTRY,
        wd.QID_DEATH_CERTIFICATE,
        wd.QID_OBITUARY,
        wd.QID_DEATH_NOTICE,
        wd.QID_OFFICIAL_MEMBER_PAGE,
        wd.QID_PRESS_RELEASE,
        wd.QID_FUNERAL_SERMON,
    ]

    QIDS = {
        wd.QID_INTEGRATED_AUTHORITY_FILE: wd.PID_GND_ID,
        wd.QID_GERMAN_NATIONAL_LIBRARY: wd.PID_GND_ID,
        wd.QID_BNF_AUTHORITIES: wd.PID_BIBLIOTHEQUE_NATIONALE_DE_FRANCE_ID,
        wd.QID_GENERAL_CATALOG_OF_BNF: wd.PID_BIBLIOTHEQUE_NATIONALE_DE_FRANCE_ID,
        wd.QID_BIBLIOTHEQUE_NATIONALE_DE_FRANCE: wd.PID_BIBLIOTHEQUE_NATIONALE_DE_FRANCE_ID,
        wd.QID_CERL_THESAURUS: wd.PID_CERL_THESAURUS_ID,
        wd.QID_CONSORTIUM_OF_EUROPEAN_RESEARCH_LIBRARIES: wd.PID_CERL_THESAURUS_ID,
        wd.QID_NETHERLANDS_INSTITUTE_FOR_ART_HISTORY: wd.PID_RKDARTISTS_ID,
    }

    def change_sources(self, context: ClaimContext) -> None:
        new_sources = []
        for src in context.sources:
            new_src = self.remove_multiple_stated_in(src)
            if new_src:
                self.claim_changed(context)

                new_sources.append(new_src)
            else:
                # nothing changed, add original source
                new_sources.append(src)

        context.sources = new_sources

    def get_stated_in_qids(self, src: Dict) -> tuple[List[str], List[str]]:
        stated_in_qids = []
        type_of_reference_qids = []

        for claim in src:
            qid = claim.getTarget().getID()
            if qid in self.TYPE_OF_REFERENCE_IDS:
                if qid not in type_of_reference_qids:
                    type_of_reference_qids.append(qid)
            elif qid in self.QIDS:
                pid = self.QIDS[qid]
                qid = self.item_context.stated_in.get_stated_in_from_pid(pid)
                if qid not in stated_in_qids:
                    stated_in_qids.append(qid)
            elif qid not in stated_in_qids:
                stated_in_qids.append(qid)

        return stated_in_qids, type_of_reference_qids

    def remove_multiple_stated_in(self, src: Dict) -> Dict | None:
        if wd.PID_STATED_IN not in src:
            return None
        if len(src[wd.PID_STATED_IN]) <= 1:
            return None

        stated_in_qids, type_of_reference_qids = self.get_stated_in_qids(
            src[wd.PID_STATED_IN]
        )
        if (len(type_of_reference_qids) == 0) and (
            len(stated_in_qids) == len(src[wd.PID_STATED_IN])
        ):
            # nothing changed
            return None

        new_source = OrderedDict()
        for prop in src:
            if prop == wd.PID_STATED_IN:
                for qid in stated_in_qids:
                    claim = pwb.Claim(REPO, wd.PID_STATED_IN)
                    claim.isReference = True
                    claim.setTarget(pwb.ItemPage(REPO, qid))
                    claim.on_item = self.item

                    new_source.setdefault(wd.PID_STATED_IN, []).append(claim)
                for qid in type_of_reference_qids:
                    claim = pwb.Claim(REPO, wd.PID_TYPE_OF_REFERENCE)
                    claim.isReference = True
                    claim.setTarget(pwb.ItemPage(REPO, qid))
                    claim.on_item = self.item

                    new_source.setdefault(wd.PID_TYPE_OF_REFERENCE, []).append(claim)
            else:
                for value in src[prop]:
                    new_source.setdefault(prop, []).append(value)

        return new_source

    def append_summary(self, summary_list: List[str]) -> List[str]:
        if self.something_done:
            summary_list.append(f"changed [[Property:{wd.PID_STATED_IN}]]")
        return summary_list


class SetArchiveURLSources(ChangeSourceStrategy):

    def change_sources(self, context: ClaimContext) -> None:
        new_sources = []
        for src in context.sources:
            new_src = self.set_archive_url(src)
            if new_src:
                self.claim_changed(context)

                new_sources.append(new_src)
            else:
                # nothing changed, add original source
                new_sources.append(src)

        context.sources = new_sources

    def set_archive_url(self, src: Dict):
        if wd.PID_REFERENCE_URL not in src:
            return None

        has_archive_url = False
        for value in src[wd.PID_REFERENCE_URL]:
            url = value.getTarget()
            if is_archive_url(url):
                has_archive_url = True
                break

        if not has_archive_url:
            return None

        new_source = OrderedDict()
        for prop in src:
            if prop == wd.PID_REFERENCE_URL:
                for value in src[prop]:
                    url = value.getTarget()
                    if is_archive_url(url):
                        arch_url = pwb.Claim(REPO, wd.PID_ARCHIVE_URL)
                        arch_url.isReference = True
                        arch_url.setTarget(url)
                        arch_url.on_item = self.item

                        new_source.setdefault(wd.PID_ARCHIVE_URL, []).append(arch_url)
                    else:
                        new_source.setdefault(prop, []).append(value)
            elif prop == wd.PID_ARCHIVE_URL:
                for value in src[prop]:
                    new_source.setdefault(prop, []).append(value)
            else:
                new_source[prop] = src[prop]

        return new_source

    def append_summary(self, summary_list: List[str]) -> List[str]:
        if self.something_done:
            summary_list.append(
                f"changed [[Property:{wd.PID_REFERENCE_URL}]] into [[Property:{wd.PID_ARCHIVE_URL}]]"
            )
        return summary_list


class BaseMergeSources(ChangeSourceStrategy):
    def __init__(self, item_context: ItemContext) -> None:
        super().__init__(item_context)
        self.pids_merged = set()
        self.qids_merged = set()

    def merge(self, src_id, src1, src2):
        pid, stated_in_qid, id = src_id
        keep_url = self.item_context.stated_in.get_keep_url(
            pid, src1
        ) or self.item_context.stated_in.get_keep_url(pid, src2)

        new_source = OrderedDict()

        if stated_in_qid:
            stated_in = pwb.Claim(REPO, wd.PID_STATED_IN)
            stated_in.isReference = True
            stated_in.setTarget(pwb.ItemPage(REPO, stated_in_qid))
            stated_in.on_item = self.item
            new_source[wd.PID_STATED_IN] = [stated_in]

        if pid and id:
            self.pids_merged.add(pid)
            pid_claim = pwb.Claim(REPO, pid)
            pid_claim.isReference = True
            pid_claim.setTarget(id)
            pid_claim.on_item = self.item
            new_source[pid] = [pid_claim]
        elif stated_in_qid:
            self.qids_merged.add(stated_in_qid)

        # remove reference urls;
        # skip stated in, retrieved and pid; these are already done above
        props = []
        for prop in src1:
            if prop not in props:
                props.append(prop)
        for prop in src2:
            if prop not in props:
                props.append(prop)
        skip = set([wd.PID_STATED_IN, wd.PID_RETRIEVED, wd.PID_PUBLICATION_DATE, pid])
        if not keep_url:
            skip.add(wd.PID_REFERENCE_URL)

        props = [x for x in props if x not in skip]

        t = references.get_old_new_src(src1, src2)
        for prop in props:
            # use the value of the newest, or the oldest (if the newest doesn't have the prop);
            # if prop is title/subject named as, then only newest
            references.set_pid(
                prop,
                t,
                new_source,
                use_only_newest_list=[
                    wd.PID_SUBJECT_NAMED_AS,
                    wd.PID_OBJECT_NAMED_AS,
                    wd.PID_TITLE,
                ],
            )

        references.set_pid(wd.PID_PUBLICATION_DATE, t, new_source, [])
        references.set_pid(wd.PID_RETRIEVED, t, new_source, [])

        return new_source

    def append_summary(self, summary_list: List[str]) -> List[str]:
        self.format_properties(
            summary_list, self.pids_merged, "merged", "[[Property:{id}]]"
        )
        self.format_properties(
            summary_list,
            self.qids_merged,
            f"merged [[Property:{wd.PID_STATED_IN}]] ",
            "[[{id}]]",
        )
        return summary_list


class MergeStatedIn(ChangeSourceStrategy):
    def __init__(self, item_context: ItemContext) -> None:
        super().__init__(item_context)
        self.qids_merged = set()

    def change_sources(self, context: ClaimContext) -> None:

        if len(context.sources) <= 1:
            return

        new_sources = []
        # Dictionary to store unique source identifiers
        mergeable = {}
        for src in context.sources:
            stated_in = self.get_statedin(src)
            if stated_in:
                if self.is_single_statedin(src):
                    if stated_in in mergeable:
                        # If the source identifier already exists, merge the sources
                        index = mergeable[stated_in]
                        new_sources[index] = references.get_merge(
                            new_sources[index], src
                        )
                        self.claim_changed(context)
                        self.qids_merged.add(stated_in)
                        continue
                    else:
                        # Otherwise, add the source identifier to the mergeable dictionary
                        mergeable[stated_in] = len(new_sources)
                elif stated_in in mergeable:
                    # If the source identifier already exists, merge the sources if the first was a single stated in
                    index = mergeable[stated_in]
                    if self.is_single_statedin(new_sources[index]):
                        new_sources[index] = references.get_merge(
                            new_sources[index], src
                        )
                        self.claim_changed(context)
                        self.qids_merged.add(stated_in)
                        continue
                else:
                    # Otherwise, add the source identifier to the mergeable dictionary
                    mergeable[stated_in] = len(new_sources)

            # Add the source, unless the source was merged above
            new_sources.append(src)

        context.sources = new_sources

    def get_statedin(self, src: Dict) -> str | None:
        if wd.PID_STATED_IN not in src:
            return None
        if len(src[wd.PID_STATED_IN]) > 1:
            return None
        claim = src[wd.PID_STATED_IN][0]
        stated_in_qid = claim.getTarget().getID()
        return stated_in_qid

    def is_single_statedin(self, src: Dict) -> bool:
        if wd.PID_STATED_IN not in src:
            return False
        if len(src[wd.PID_STATED_IN]) > 1:
            return False

        for prop in src:
            if prop != wd.PID_STATED_IN and prop != wd.PID_RETRIEVED:
                return False

        return True

    def append_summary(self, summary_list):
        self.format_properties(
            summary_list,
            self.qids_merged,
            f"merged [[Property:{wd.PID_STATED_IN}]] ",
            "[[{id}]]",
        )
        return summary_list


class RemoveSources(ChangeSourceStrategy):
    def __init__(self, item_context: ItemContext) -> None:
        super().__init__(item_context)
        self.pids_removed = set()

    def change_sources(self, context: ClaimContext) -> None:
        new_sources = []
        for src in context.sources:
            pid = self.get_always_remove_source_pid(src)
            if pid:
                self.pids_removed.add(pid)
                self.claim_changed(context)
            else:
                # nothing changed, add original source
                new_sources.append(src)

        context.sources = new_sources

    def get_always_remove_source_pid(self, source):
        if wd.PID_WORLDCAT_IDENTITIES_ID_SUPERSEDED in source:
            return wd.PID_WORLDCAT_IDENTITIES_ID_SUPERSEDED
        else:
            return None

    def append_summary(self, summary_list):
        self.format_properties(
            summary_list, self.pids_removed, "removed", "[[Property:{id}]]"
        )
        return summary_list


class MergeSources(BaseMergeSources):

    def change_sources(self, context: ClaimContext) -> None:
        if len(context.sources) <= 1:
            return

        new_sources = []
        # Dictionary to store unique source identifiers
        mergeable = {}
        error_dict = {}
        count_dict = {}
        for src in context.sources:
            src_id = self.item_context.stated_in.get_id_from_source(src)
            if src_id and not self.never_merge(src):
                count_dict[src_id] = count_dict.get(src_id, 0) + 1
                error = self.can_merge(src, src_id)
                if error:
                    # collect the errors, we only show the errors if we have duplicate src ids
                    error_dict.setdefault(src_id, []).append(error)
                elif src_id in mergeable:
                    # If the source identifier already exists, merge the sources
                    index = mergeable[src_id]
                    new_sources[index] = self.merge(src_id, new_sources[index], src)
                    self.claim_changed(context, major_change=True)
                    continue
                else:
                    # Otherwise, add the source identifier to the mergeable dictionary
                    mergeable[src_id] = len(new_sources)

            # Add the source, unless the source was merged above
            new_sources.append(src)

        # show the errors for duplicate src ids
        error_list = []
        for src_id in error_dict:
            if count_dict[src_id] > 1:
                for error in error_dict[src_id]:
                    msg = f"{context.prop} - {src_id[0]} {src_id[2]}: {error}"
                    logger.warning(msg)
                    error_list.append(msg)

        if error_list != []:
            # make unique
            error_list = list(dict.fromkeys(error_list))
            error_msg = ", ".join(error_list)

            raise RuntimeError(f"Error while merging: {error_msg}")

        context.sources = new_sources

    def never_merge(self, src: Dict) -> bool:
        if wd.PID_BASED_ON_HEURISTIC in src:
            return True
        # change stated_in to inferred_from
        # if PID_INFERRED_FROM in src:
        #     return True
        if wd.PID_PAGES in src:
            return True
        if wd.PID_SECTION_VERSE_PARAGRAPH_OR_CLAUSE in src:
            return True
        # Q98536289
        if wd.PID_QUOTATION in src:
            return True

        return False

    def can_merge(self, src: Dict, src_id_triple):
        src_pid, src_stated_in, src_id = src_id_triple

        ref_urls = src.get(wd.PID_REFERENCE_URL, [])
        if len(ref_urls) > 1:
            # Don't merge sources with multiple reference URLs;
            # these sources should probably be cleaned up first
            return "Source contains multiple reference urls"

        if len(ref_urls) == 1:
            refurl_id_triple = self.item_context.stated_in.get_id_from_reference_url(
                src
            )
            url = ref_urls[0].getTarget()

            # the reference url must return the same id as the id in the source because we
            # remove the reference url during the merge
            # For example, the next code will give an error:
            #    * if the reference url is an old unrecognized url -> manually add new regular expression to PID page
            #    * if the reference url is wrong -> manually correct url
            #    * if the reference url contains more info than the id alone; for example the page of a book

            if not refurl_id_triple:
                return f"Can not determine ID from reference URL: {src_id_triple} {url}"

            refurl_pid, __, refurl_id = refurl_id_triple

            if refurl_pid != src_pid:
                return f"Different PID from reference URL: {src_id_triple} {url}"

            if refurl_id != src_id:
                return f"Different ID from reference URL: {src_id_triple} {url}"

        for prop in src:
            # Don't merge if the source contains other properties than these
            if prop not in [
                wd.PID_STATED_IN,
                wd.PID_REFERENCE_URL,
                wd.PID_RETRIEVED,
                wd.PID_SUBJECT_NAMED_AS,
                wd.PID_OBJECT_NAMED_AS,
                wd.PID_PUBLICATION_DATE,
                wd.PID_LAST_UPDATE,
                wd.PID_PUBLISHER,
                wd.PID_LANGUAGE_OF_WORK_OR_NAME,
                wd.PID_TITLE,
                wd.PID_ARCHIVE_URL,
                wd.PID_ARCHIVE_DATE,
                wd.PID_PUBLISHED_IN,
                src_pid,
            ]:

                return f"Source cannot be merged because it contains prop {prop}"

        return None


class AllChangeSourceStrategy(ChangeSourceStrategy):
    """
    A strategy class that aggregates multiple strategies to change sources of claims in Wikidata items.

    Attributes:
        strategies (List[ChangeSourceStrategy]): A list of source change strategies.
    """

    def __init__(self, item_context: ItemContext, remove_english: bool = False) -> None:
        super().__init__(item_context)

        self.strategies: List[ChangeSourceStrategy] = []
        if remove_english:
            self.strategies += [
                RemoveEnglishWikipedia(item_context),
            ]
        self.strategies += [
            MultipleStatedIn(item_context),
            RemoveRetrievedSources(item_context),
            MergeRetrieved(item_context),
            SplitStatedInSources(item_context),
            AddExternalID(item_context),
            SetArchiveURLSources(item_context),
            MergeStatedIn(item_context),
            MergeSources(item_context),
            RemoveSources(item_context),
            RemoveWeakSources(item_context),
            RemoveReferenceURL(item_context),
        ]

    def get_changed_pids(self):
        res = []
        for strategy in self.strategies:
            res.extend(strategy.get_changed_pids())
        return res

    def change_sources(self, context: ClaimContext) -> None:
        for strategy in self.strategies:
            strategy.change_sources(context)

    def append_summary(self, summary_list: List[str]) -> List[str]:
        for strategy in self.strategies:
            summary_list = strategy.append_summary(summary_list)

        return summary_list


class ReportingUnknownURLStrategy(UnknownURLStrategy):
    def __init__(self, report: Reporting):
        self.report = report

    def unknown_url(self, qid: str, url: str) -> None:
        self.report.add_unknown_url(qid, url)


class ChangeSourcesBot:
    """
    A bot to change sources of claims in Wikidata items.

    Attributes:
        generator (generator): The generator to iterate over items.
        report (Reporting): The reporting instance to handle logging and reporting.
        item (ItemPage): The current item being processed.
        test (bool): A flag to indicate test mode.
        done_count (int): The count of processed items.
        skip_done_errors (bool): A flag to skip items in the done or error list
        skip_scholarly_article (bool): A flag to skip scholarly articles.
        remove_english (bool): A flag to remove English Wikipedia sources.
    """

    def __init__(
        self,
        generator,
        stated_in: StatedIn = None,
        report: Reporting = None,
        test: bool = True,
        skip_done_errors: bool = True,
        skip_scholarly_article: bool = True,
        remove_english: bool = False,
    ):
        self.generator = pagegenerators.PreloadingEntityGenerator(generator)
        self.item = None
        self.stated_in = stated_in
        self.report = report
        self.test = test
        self.done_count = 0
        self.skip_done_errors = skip_done_errors
        self.skip_scholarly_article = skip_scholarly_article
        self.remove_english = remove_english

    def examine(self, qid: str):
        """
        Examines a single item by its QID.

        Args:
            qid (str): The QID of the item to examine.
        """
        if not qid.startswith("Q"):  # ignore property pages and lexeme pages
            return

        if not self.test and self.skip_done_errors:
            if qid != wd.QID_WIKIDATASANDBOX3:
                if self.report.has_error(qid):
                    logger.info(f"{qid}: skipped, in error list")
                    return

                if self.report.has_done(qid):
                    logger.info(f"{qid}: skipped, in done list")
                    return

        self.item = pwb.ItemPage(REPO, qid)

        self.examine_item()

    def run(self):
        """
        Runs the bot on all items from the generator.
        """
        for item in self.generator:
            self.item = item
            self.examine_item()

    def examine_item(self):
        qid = self.item.title()
        if not self.test and self.skip_done_errors:
            if qid != wd.QID_WIKIDATASANDBOX3:
                if self.report.has_error(qid):
                    logger.info(f"{qid}: skipped, in error list")
                    return

                if self.report.has_done(qid):
                    logger.info(f"{qid}: skipped, in done list")
                    return

        if not self.item.exists():
            return

        if self.item.isRedirectPage():
            return

        claims = self.item.get().get("claims")

        if not self.item.botMayEdit():
            raise RuntimeError(f"Skipping {qid} because it cannot be edited by bots")

        # skip scholarly article
        if self.skip_scholarly_article:
            if wd.PID_INSTANCE_OF in claims:
                for claim in claims[wd.PID_INSTANCE_OF]:
                    target = claim.getTarget()
                    if target and target.getID() == wd.QID_SCHOLARLYARTICLE:
                        logger.error(f"{qid}: scholarly article")
                        self.report.add_error(qid, "scholarly article")
                        return

        logger.info(f"item = {qid} done = {self.done_count}")
        self.report.clear_unknown_urls(qid)

        item_context = ItemContext(
            self.item,
            self.test,
            self.stated_in,
            ReportingUnknownURLStrategy(self.report),
        )
        strategy = AllChangeSourceStrategy(
            item_context,
            remove_english=self.remove_english,
        )
        self.data = {}
        something_done = False

        try:
            for prop in claims:
                for claim in claims[prop]:
                    if not claim.sources:
                        continue

                    context = ClaimContext(prop, claim)
                    strategy.change_sources(context)

                    if context.get_is_changed():
                        claim.sources = context.sources
                        self.save_claim(claim)
                        something_done = True

            if something_done:
                summary_list = list(dict.fromkeys(strategy.append_summary([])))
                summary = ", ".join(summary_list)
                if summary == "":
                    raise RuntimeError("Empty summary")
                # summary = summary + ', test edit for [[Wikidata:Requests_for_permissions/Bot/DifoolBot_6]]'

                if self.test:
                    logger.info(summary)
                else:
                    self.item.editEntity(data=self.data, summary=summary)

            if not self.test:
                self.report.add_done(qid)
                self.report.add_pid_done(strategy.get_changed_pids())
            self.done_count = self.done_count + 1
        except RuntimeError as e:
            logger.error(f"{qid}: Runtime error: {e}")
            self.report.add_error(qid, e.__repr__())

    def save_claim(self, claim):
        if not claim.on_item:
            claim.on_item = self.item
        if "claims" not in self.data:
            self.data["claims"] = []
        # REPO.save_claim(claim, summary=summary)
        self.data["claims"].append(claim.toJSON())
