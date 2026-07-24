import os
import time
from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum, auto
from functools import cached_property

import pywikibot as pwb
import requests
import viaf.wdqs_client
from viaf.authority_sources import AuthorityRecord, AuthoritySource
from viaf.exceptions import SkipRecord
from viaf.paths import DATA_DIR
# Re-exported: the bot's own callers import these from here.
from viaf.report_backend import BotState, ReportBackend
from viaf.viaf_api_client import ViafApiClient, ViafRateLimitExceeded, ViafStatus
from viaf.viaf_inferred_from_reference import ViafInferredFromReference
from viaf.wdqs_client import WdqsQueryError

import shared_lib.change_wikidata as cwd
import shared_lib.constants as wd
from shared_lib.wikidata_site import REPO, SITE

WIKIDATA_ENTITY_PREFIX = "http://www.wikidata.org/entity/"
# An "unknown value" (somevalue) claim has no id behind it. Wikidata's RDF export
# skolemises the blank node into an IRI under this prefix, so it arrives from
# qlever/WDQS looking like an ordinary value. Note it is a real IRI, not a blank
# node: isBlank() does not match it, only the prefix does.
WIKIDATA_GENID_PREFIX = "http://www.wikidata.org/.well-known/genid/"


class SessionOutcome(Enum):
    """How a single run_session / iterate_qlever pass ended."""

    # every row of the qlever file was processed
    COMPLETED = auto()
    # the VIAF API reported its daily rate limit was hit
    RATE_LIMITED = auto()
    # the DUPLICATES table reached the configured max_duplicates cap
    MAX_DUPLICATES = auto()
    # WDQS stayed unreachable, so duplicates could not be verified. Each item
    # costs a VIAF lookup (~1000/day) before its duplicate check runs, so
    # carrying on would spend that budget on items we cannot verify anyway.
    WDQS_UNAVAILABLE = auto()


AUTHORITY_SOURCE_CODE_WIKIDATA = "WKP"

PAGE_TITLE = "User:Difool/viaf_already_somewhere"
WIKI_FILE = str(DATA_DIR / "wiki.txt")
DEFAULT_QLEVER_FILE = str(DATA_DIR / "qlever_viaf_index.txt")

MAX_LAG_BACKOFF_SECS = 10 * 60
SLEEP_AFTER_ERROR = 10  # sec
SLEEP_AFTER_RUNTIMEERROR = 2  # sec


def _add_viaf(
    item: pwb.ItemPage,
    auth_src: AuthoritySource,
    viaf_cluster_id: str | None,
) -> None:
    if viaf_cluster_id is None:
        raise RuntimeError("Cannot add VIAF ID without a viaf_cluster_id")

    wdpage = cwd.WikiDataPage(item, test=False)
    wdpage.add_statement(
        cwd.ExternalIDStatement(prop=wd.PID_VIAF_ID, external_id=viaf_cluster_id),
        reference=ViafInferredFromReference(wd.PID_VIAF_ID, viaf_cluster_id),
    )
    wdpage.summary = f"Adding VIAF ID based on {auth_src.description}"
    wdpage.apply()


def _execute_qlever_query(query: str) -> list[dict[str, str]]:
    """Execute a qlever query and return rows with qid and local_auth_id."""
    qlever_url = "https://qlever.cs.uni-freiburg.de/api/wikidata"
    try:
        response = requests.get(qlever_url, params={"query": query}, timeout=300)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as e:
        pwb.error(f"Error querying qlever: {e}")
        return []
    except ValueError as e:
        pwb.error(f"Error parsing qlever response: {e}")
        return []

    if "results" not in data or "bindings" not in data["results"]:
        return []

    rows: list[dict[str, str]] = []
    for binding in data["results"]["bindings"]:
        item_uri = binding.get("item", {}).get("value", "")
        if not item_uri:
            continue
        qid = item_uri.split("/")[-1]
        if not qid.startswith("Q"):
            continue
        local_auth_id = binding.get("local_auth_id", {}).get("value", "")
        rows.append({"qid": qid, "local_auth_id": local_auth_id})

    return rows


class ViafBot:
    def __init__(self, auth_src: AuthoritySource, report: ReportBackend):
        self.auth_src = auth_src
        self.test = False
        self.report = report
        # when set, skip items VIAF returned 'not_found' for (under this source)
        # since this instant, and cache new not_found results
        self.not_found_cutoff: datetime | None = None

    @cached_property
    def formatter_url(self) -> str | None:
        """This authority source's formatter URL (P1630), e.g. 'https://www.idref.fr/$1'.

        Read once per source and used to link local authority ids in the reports.
        None when the property has no usable formatter URL, in which case the
        reports fall back to plain unlinked ids.
        """
        try:
            claims = pwb.PropertyPage(REPO, self.auth_src.pid).get().get("claims", {})
        except Exception as e:
            pwb.warning(f"No formatter URL for {self.auth_src.pid}: {e}")
            return None
        for claim in claims.get(wd.PID_FORMATTER_URL, []):
            if claim.getRank() == "deprecated":
                continue
            target = claim.getTarget()
            if target:
                return str(target)
        return None

    def local_auth_id_link(self, local_auth_id: str) -> str:
        """Wikitext for a local authority id: an external link when the source has
        a formatter URL, otherwise the bare id."""
        formatter = self.formatter_url
        if not formatter or "$1" not in formatter:
            return local_auth_id
        return f"[{formatter.replace('$1', local_auth_id)} {local_auth_id}]"

    def _report_heading(self) -> str:
        """Section heading for this source's report.

        {{P|Pxxx}} renders the property's label in the reader's own language and
        follows renames on Wikidata, so the heading cannot go stale the way a
        description baked in here does. It is also the form viaf_score's
        _extract_pid looks for first: its plain-text fallback map names only 30
        of the 54 sources, and a section it cannot resolve to a PID is skipped.
        """
        return "=={{P|" + self.auth_src.pid + "}}==\n"

    def _report_summary(self, what: str) -> str:
        """Edit summary naming the section just appended, e.g. the wikitext
        'add duplicate items for [[Property:P269]]', which Wikidata renders as
        'add duplicate items for IdRef ID (P269)' with the property linked.

        Both reports head their section with the source's description, so the
        page history otherwise cannot say which authority source an edit was
        for; the linked property makes that clear at a glance. The description
        is not printed literally as well -- Wikidata already expands the
        property link to its label, so doing so would duplicate it.
        """
        return f"add {what} for [[Property:{self.auth_src.pid}]]"

    def generate_duplicate_locals_report(self):
        self.write_to_wiki(
            self.make_duplicate_locals_wikitext(),
            self._report_summary("duplicate local authority ids"),
        )

    def generate_duplicates_report(self):
        self.write_to_wiki(
            self.make_duplicates_wikitext(),
            self._report_summary("duplicate items"),
        )

    def end_session(self):
        self.report.end_session(self.auth_src.pid)

    def run(self):
        self.run_session()

    def run_session(
        self,
        output_file: str = DEFAULT_QLEVER_FILE,
        max_duplicates: int | None = None,
    ) -> SessionOutcome:
        """Run one qlever-based pass over the current authority source.

        Unless the pass was cut short (by the VIAF API rate limit, or by WDQS
        being unreachable), the accumulated duplicate/wikitext reports are
        published and a new reporting session is started (which clears the
        per-session tables).

        Returns the SessionOutcome describing how the pass ended.
        """
        outcome = self.iterate_qlever(
            output_file=output_file, max_duplicates=max_duplicates
        )
        if outcome not in (
            SessionOutcome.RATE_LIMITED,
            SessionOutcome.WDQS_UNAVAILABLE,
        ):
            self.report.run_maintenance()
            self.generate_duplicate_locals_report()
            self.generate_duplicates_report()
            self.end_session()
        return outcome

    def change_wikidata(self, record: AuthorityRecord) -> None:
        # These three used to return silently, so the row was consumed and left no
        # trace in ADDED or ERRORS at all. They are reported like every other
        # skip below: a redirect in particular is worth seeing, since it means
        # someone merged the item (often after reading these very reports).
        if not record.qid.startswith("Q"):
            raise SkipRecord("Skipping, because it is not an item")

        item = pwb.ItemPage(REPO, record.qid)

        try:
            if not item.exists():
                raise SkipRecord("Skipping, because the item does not exist")
        except pwb.exceptions.MaxlagTimeoutError as ex:
            time.sleep(MAX_LAG_BACKOFF_SECS)
            raise SkipRecord("max lag timeout. sleeping. failed to add claim")

        if item.isRedirectPage():
            raise SkipRecord("Skipping, because the item is a redirect")

        existing_claims = item.get().get("claims")

        if not item.botMayEdit():
            raise SkipRecord("Skipping, because it cannot be edited by bots")

        if not existing_claims:
            raise SkipRecord("Skipping, because it has no claims")

        if wd.PID_VIAF_ID in existing_claims:
            raise SkipRecord("Skipping, because it already has a VIAF ID")

        if self.auth_src.pid not in existing_claims:
            raise SkipRecord(f"Skipping, because it has no {self.auth_src.pid} PID")

        found = False
        for claim in existing_claims[self.auth_src.pid]:
            claim_target = claim.getTarget()
            if claim_target == record.wikidata_external_id:
                if claim.getRank() == "deprecated":
                    raise SkipRecord(
                        f"Skipping, because the {self.auth_src.pid} {record.wikidata_external_id} is deprecated"
                    )
                found = True
                break

        if not found:
            raise SkipRecord(
                f"Skipping, because it has no {self.auth_src.pid} {record.wikidata_external_id}"
            )

        if self.test:
            return

        pwb.output(f"Adding VIAF ID {record.viaf_cluster_id} to {record.qid}")
        _add_viaf(item, self.auth_src, viaf_cluster_id=record.viaf_cluster_id)
        self.report.add_done(qid=record.qid)

    def get_duplicate_qids(self, record: AuthorityRecord):
        """Items other than record.qid that already carry this VIAF id.

        A WdqsQueryError propagates: process_record records it as an error and
        skips the item, so the VIAF id is never added on the strength of a
        duplicate check that did not actually run.
        """
        duplicate_qids = []
        query = 'SELECT DISTINCT ?item WHERE {{ ?item p:P214 ?statement0. ?statement0 (ps:P214) "{viaf_id}". FILTER (?item != wd:{qid})}} LIMIT 5'.format(
            viaf_id=record.viaf_cluster_id, qid=record.qid
        )

        bindings = viaf.wdqs_client.query_wdqs(query)
        if not bindings:  # query ran, matched nothing
            return duplicate_qids
        for row in bindings:
            other_qid = (
                row.get("item", {}).get("value", "").replace(WIKIDATA_ENTITY_PREFIX, "")
            )
            duplicate_qids.append(other_qid)
        return duplicate_qids

    def process_record(self, record: AuthorityRecord) -> None:
        try:
            if self.report.has_done(record.qid):
                return
            if self.report.has_duplicate(record.qid):
                return
            if self.report.has_duplicate_local_auth_id(record.qid):
                return
            if self.report.has_error(record.qid):
                return
            if self.report.has_ignore(record.qid):
                return
            if self.not_found_cutoff is not None and self.report.has_recent_not_found(
                record.qid, self.auth_src.pid, self.not_found_cutoff
            ):
                return

            # Bail out before the VIAF lookup: there is no id to search for, and
            # compute_viaf_search_key would happily normalise the genid IRI into a
            # plausible-looking key, spending one of the ~1000 daily VIAF calls on
            # a certain miss.
            if record.wikidata_external_id.startswith(WIKIDATA_GENID_PREFIX):
                raise SkipRecord(
                    f"Skipping, because the {self.auth_src.pid} is an unknown value"
                )

            viaf_code = self.auth_src.viaf_code
            self.auth_src.compute_viaf_search_key(record)

            if not record.viaf_search_key:
                raise SkipRecord("No search key")

            client = ViafApiClient()
            if viaf_code == "LC":
                lookup = client.query_viaf_lccn(record.viaf_search_key)
            else:
                lookup = client.query_viaf_sourceid(viaf_code, record.viaf_search_key)
            if lookup.status != ViafStatus.FOUND:
                if (
                    lookup.status == ViafStatus.NOT_FOUND
                    and self.not_found_cutoff is not None
                ):
                    self.report.add_not_found(record.qid, self.auth_src.pid)
                raise SkipRecord(f"status {lookup.status}")
            if not lookup.viaf_cluster_id:
                raise SkipRecord("no viaf_cluster_id")

            record.viaf_cluster_id = lookup.viaf_cluster_id

            other_wikidata_ids = []
            local_auth_ids = []
            has_local_auth_id = False

            if self.auth_src.viaf_code in lookup.source_mapping:
                for nsid, content_id in lookup.source_mapping[self.auth_src.viaf_code]:
                    if self.auth_src.matches_viaf_external_id(nsid, content_id, record):
                        has_local_auth_id = True
                    # Deduplicate on the canonical form so old/new-style
                    # notations of the same record (e.g. RISM people/NNN vs
                    # peNNN) are not counted as two distinct local auth ids.
                    canonical = self.auth_src.canonical_local_auth_id(nsid)
                    if canonical not in local_auth_ids:
                        local_auth_ids.append(canonical)

            if AUTHORITY_SOURCE_CODE_WIKIDATA in lookup.source_mapping:
                for other_qid, content_id in lookup.source_mapping[
                    AUTHORITY_SOURCE_CODE_WIKIDATA
                ]:
                    if other_qid != record.qid:
                        if other_qid not in other_wikidata_ids:
                            other_wikidata_ids.append(other_qid)

            duplicate_qids = list(
                set(self.get_duplicate_qids(record)).union(other_wikidata_ids)
            )
            if duplicate_qids:
                for duplicate_qid in duplicate_qids:
                    self.report.add_duplicate(
                        record.qid,
                        duplicate_qid,
                        record.wikidata_external_id,
                        record.viaf_cluster_id,
                    )
                raise SkipRecord(f"has duplicates: {duplicate_qids}")

            if len(local_auth_ids) == 0:
                raise SkipRecord("no local_auth_ids")
            if len(local_auth_ids) > 1:
                self.report.add_duplicate_local_auth_id(
                    record.qid,
                    record.wikidata_external_id,
                    record.viaf_cluster_id,
                )
                for local_auth_id in local_auth_ids:
                    self.report.add_duplicate_local_auth_id(
                        record.qid,
                        local_auth_id,
                        record.viaf_cluster_id,
                    )
                raise SkipRecord(f"multiple local_auth_ids {local_auth_ids}")
            if not has_local_auth_id:
                raise SkipRecord("local_auth_id not found")
            # if len(reader.wikidata_ids) == 0:
            #     raise SkipRecord("no wikidata_ids")
            if len(other_wikidata_ids) > 1:
                raise SkipRecord(f"multiple wikidata_ids {other_wikidata_ids}")
            # if not reader.has_wikidata_id:
            #     raise RuntimeError(f"wikidata_id not found")

            pwb.output(
                "{qid} -> {viaf_id}; {desc} {local_auth_id}".format(
                    qid=record.qid,
                    viaf_id=record.viaf_cluster_id,
                    desc=self.auth_src.description,
                    local_auth_id=record.wikidata_external_id,
                )
            )
            self.change_wikidata(record)
        except ViafRateLimitExceeded:
            # Not a per-item failure - let the caller (iterate_qlever) stop the run.
            raise
        except WdqsQueryError:
            # Also not a per-item failure. WDQS held up long enough that its own
            # retries gave up, so the next item would almost certainly fail the
            # same way - after spending another VIAF lookup to get there. Stop
            # the run instead and keep the remaining daily budget; this item's
            # line stays in the qlever file and is retried on the next run.
            raise
        except SkipRecord as e:
            # Expected, recorded outcomes (status not_found, no viaf_cluster_id,
            # has duplicates, multiple local_auth_ids, ...). They are stored in
            # the DB report via add_error, so log them at info level -> the job's
            # .out, keeping .err for the genuinely unexpected Exception below.
            pwb.output(f"Skipped {record.qid}: {e}")
            self.report.add_error(record.qid, str(e))
            time.sleep(SLEEP_AFTER_RUNTIMEERROR)
        except Exception as e:
            # Anything not explicitly a SkipRecord is unexpected (including a
            # bare RuntimeError from a library): surface it on stderr.
            pwb.error(f"Exception: {e}")
            self.report.add_error(record.qid, str(e))
            time.sleep(SLEEP_AFTER_ERROR)

    def make_duplicates_wikitext(self):
        heading = self._report_heading()
        header = '\n{| class="wikitable sortable" style="vertical-align:bottom;"\n|-\n! VIAF\n! QID on the item\n! ID from cluster\n! 2nd QID\n! class="unsortable" | Compare'
        body = ""
        line = "\n|-\n| https://viaf.org/viaf/{viaf_id}\n| {{{{Q|{qid}}}}}\n| {auth_code}|{local_auth_id}\n| {{{{Q|{duplicate_qid}}}}}\n| {compare}"
        has_duplicates = False
        duplicates = self.report.get_duplicates()
        if not duplicates:
            return ""
        for row in duplicates:
            qid, duplicate_qid, local_auth_id, viaf_id = row
            # https://dicare.toolforge.org/wikidata-diff/?qids=Q3218809+Q2920825&language=en
            compare = "[https://dicare.toolforge.org/wikidata-diff/?qids={qid1}+{qid2}&language=en compare]".format(
                qid1=qid, qid2=duplicate_qid
            )
            body = body + line.format(
                viaf_id=viaf_id,
                qid=qid,
                auth_code=self.auth_src.viaf_code,
                local_auth_id=local_auth_id,
                duplicate_qid=duplicate_qid,
                compare=compare,
            )
            has_duplicates = True
        if not has_duplicates:
            return ""
        footer = "\n|}"
        stats = self.report.get_stats()
        if not stats:
            return ""
        checked, added, not_found = stats
        if checked == added + not_found:
            return ""

        stats = (
            "\n"
            + " ".join(
                [
                    f"Checked: {checked};" if checked else "",
                    f"Added: {added};" if added else "",
                    f"Not found: {not_found}" if not_found else "",
                ]
            ).strip()
        )
        wikitext = f"{heading}{stats}{header}{body}{footer}"

        return wikitext

    def make_duplicate_locals_wikitext(self):
        heading = self._report_heading()
        header = '\n{| class="wikitable sortable" style="vertical-align:bottom;"\n|-\n! VIAF\n! QID on the item\n! ID from cluster'
        body = ""
        line = "\n|-\n| https://viaf.org/viaf/{viaf_id}\n| {{{{Q|{qid}}}}}\n|{local_auth_ids}"
        has_duplicates = False
        for row in self.report.get_duplicate_local_auth_ids():
            qid, local_auth_id_set, viaf_id = row
            links = set()
            for local_auth_id in local_auth_id_set:
                links.add(self.local_auth_id_link(local_auth_id))
            local_auth_ids = ", ".join(sorted(links))
            body = body + line.format(
                viaf_id=viaf_id,
                qid=qid,
                auth_code=self.auth_src.viaf_code,
                local_auth_ids=local_auth_ids,
            )
            has_duplicates = True
        if not has_duplicates:
            return ""
        footer = "\n|}"
        wikitext = f"{heading}{header}{body}{footer}"

        return wikitext

    def write_to_file(self, wikitext) -> None:
        if not wikitext:
            return
        with open(WIKI_FILE, "w", encoding="utf-8") as outfile:
            outfile.write(wikitext)

    def write_to_wiki(self, wikitext, summary: str) -> None:
        if not wikitext:
            return
        page = pwb.Page(SITE, PAGE_TITLE)
        page.text = page.text + "\n" + wikitext
        page.save(summary=summary, minor=False)

    def iterate(self):
        index = 1_300_000
        while True:
            pwb.output(f"Index = {index}")
            if not self.iterate_index(index):
                return
            index = index + 100_000

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

        query = query_template.format(pid=self.auth_src.pid, index=index)
        # A WdqsQueryError propagates rather than ending the paging loop: only an
        # empty result means this source is exhausted, a failed query means we do
        # not know, and must not report the source as finished.
        rows = viaf.wdqs_client.query_wdqs(query)
        if not rows:  # query ran, no rows left at this offset
            return False
        for row in rows:
            qid = (
                row.get("item", {}).get("value", "").replace(WIKIDATA_ENTITY_PREFIX, "")
            )
            local_auth_id = row.get("local_auth_id", {}).get("value", "")
            if len(qid) == 0:
                continue
            if len(local_auth_id) == 0:
                continue
            record = AuthorityRecord(qid, local_auth_id)
            self.process_record(record)
        return True

    def _qlever_header(self) -> str:
        """Marker line identifying which authority source a qlever output_file is for."""
        return f"# pid={self.auth_src.pid}"

    def fetch_qlever_results(self, output_file: str = DEFAULT_QLEVER_FILE) -> int:
        """Execute the iterate_index query on qlever without the slice part and save the output.

        The output file starts with a header line identifying self.auth_src.pid,
        followed by QID and local authority ID pairs separated by tabs.
        """
        query_template = """
                        PREFIX wikibase: <http://wikiba.se/ontology#>
                        PREFIX wd: <http://www.wikidata.org/entity/>
                        PREFIX wdt: <http://www.wikidata.org/prop/direct/>
                        PREFIX p: <http://www.wikidata.org/prop/>
                        PREFIX ps: <http://www.wikidata.org/prop/statement/>
                        SELECT DISTINCT ?item ?local_auth_id WHERE {{
                        ?item wdt:{pid} ?local_auth_id .
                        FILTER EXISTS {{?item wdt:P31 wd:Q5}}
                        MINUS {{?item p:P214 ?viaf}}
                        OPTIONAL {{?item p:{pid} ?statement0.
                                    ?statement0 ps:{pid} _:anyValueP245;
                                        wikibase:rank ?rank }}
                        FILTER(?rank != wikibase:DeprecatedRank)
                    }}
                    """
        query = query_template.format(pid=self.auth_src.pid)
        results = _execute_qlever_query(query)
        if not results:
            pwb.warning("No results returned from qlever.")
            return 0

        with open(output_file, "w", encoding="utf-8") as fh:
            fh.write(self._qlever_header() + "\n")
            for row in results:
                fh.write(f"{row['qid']}\t{row['local_auth_id']}\n")

        pwb.output(f"Wrote {len(results)} rows to {output_file}")
        return len(results)

    def iterate_qlever(
        self,
        output_file: str = DEFAULT_QLEVER_FILE,
        max_duplicates: int | None = None,
    ) -> SessionOutcome:
        """Run qlever once and iterate the resulting items.

        If output_file already exists but its header doesn't match self.auth_src
        (e.g. it's a leftover from a previous, differently-configured run), it is
        discarded and refetched rather than trusted blindly.

        Stops early, leaving the remaining rows (plus the header) in output_file
        for the next run, if either:
          - the VIAF API reports its rate limit was hit (RATE_LIMITED), or
          - the DUPLICATES table reaches max_duplicates rows (MAX_DUPLICATES).

        If every row is processed the file is removed and COMPLETED is returned.
        """
        header = self._qlever_header()

        if os.path.exists(output_file):
            with open(output_file, "r", encoding="utf-8") as fh:
                first_line = fh.readline().strip()
            if first_line != header:
                pwb.warning(
                    f"{output_file} header {first_line!r} doesn't match "
                    f"{header!r}; discarding and refetching."
                )
                os.remove(output_file)

        if not os.path.exists(output_file):
            pwb.output(f"Fetching qlever results into {output_file}...")
            count = self.fetch_qlever_results(output_file=output_file)
            if count == 0:
                pwb.warning("No qlever rows to process.")
                return SessionOutcome.COMPLETED
            # Only knowable here: later runs read a file already truncated to the
            # rows still to do, so this is the one chance to record the total.
            self.report.start_source_session(self.auth_src.pid, count)
        else:
            pwb.output(f"Using existing qlever file: {output_file}")

        with open(output_file, "r", encoding="utf-8") as fh:
            lines = [line for line in fh if line.strip()]
        if lines and lines[0].strip() == header:
            lines = lines[1:]

        total_lines = len(lines)

        processed = 0
        malformed = 0
        remaining_lines: list[str] = []
        outcome = SessionOutcome.COMPLETED
        for index, line in enumerate(lines):
            if (
                max_duplicates is not None
                and self.report.count_duplicates() >= max_duplicates
            ):
                pwb.warning(
                    f"DUPLICATES reached {max_duplicates} rows; "
                    "publishing report and moving on."
                )
                remaining_lines = lines[index:]
                outcome = SessionOutcome.MAX_DUPLICATES
                break

            stripped = line.strip()
            parts = stripped.split("\t")
            if len(parts) != 2:
                malformed += 1
                pwb.warning(f"Skipping malformed line: {stripped}")
                continue
            qid, local_auth_id = parts
            record = AuthorityRecord(qid, local_auth_id)
            try:
                self.process_record(record)
            except ViafRateLimitExceeded as e:
                pwb.warning(f"{e}; stopping for now.")
                remaining_lines = lines[index:]
                outcome = SessionOutcome.RATE_LIMITED
                break
            except WdqsQueryError as e:
                pwb.warning(f"{e}; stopping to preserve the VIAF daily budget.")
                remaining_lines = lines[index:]
                outcome = SessionOutcome.WDQS_UNAVAILABLE
                break
            processed += 1
            if processed % 100 == 0 or processed == total_lines:
                pct = (processed / total_lines * 100) if total_lines else 0.0
                pwb.output(
                    f"Processed {processed}/{total_lines} valid items ({pct:.1f}%), malformed lines skipped: {malformed}"
                )
                # Keep the status page's progress live during a long run, not just
                # at the stops below. One UPDATE per 100 rows is negligible.
                self.report.set_remaining_rows(total_lines - processed)

        if outcome != SessionOutcome.COMPLETED:
            self.report.set_remaining_rows(len(remaining_lines))
            with open(output_file, "w", encoding="utf-8") as fh:
                fh.write(header + "\n")
                fh.writelines(remaining_lines)
            pwb.output(
                f"{len(remaining_lines)} unprocessed row(s) left in {output_file}."
            )
            return outcome

        self.report.set_remaining_rows(0)
        try:
            os.remove(output_file)
            pwb.output(f"Removed temporary qlever file {output_file}")
        except OSError as e:
            pwb.error(f"Failed to remove temporary file {output_file}: {e}")

        return SessionOutcome.COMPLETED
