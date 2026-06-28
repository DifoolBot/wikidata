import os
import time
from abc import ABC, abstractmethod
from collections.abc import Iterator

import pywikibot as pwb
import requests
import viaf.authority_sources
import viaf.viaf_api_client
import viaf.wdqs_client
from viaf.viaf_inferred_from_reference import ViafInferredFromReference

import shared_lib.change_wikidata as cwd
import shared_lib.constants as wd

WD = "http://www.wikidata.org/entity/"

AUTHORITY_SOURCE_CODE_WIKIDATA = "WKP"

SITE = pwb.Site("wikidata", "wikidata")
SITE.login()
SITE.get_tokens("csrf")
REPO = SITE.data_repository()

PAGE_TITLE = "User:Difool/viaf_already_somewhere"
WIKI_FILE = "wiki.txt"

MAX_LAG_BACKOFF_SECS = 10 * 60
SLEEP_AFTER_ERROR = 10  # sec
SLEEP_AFTER_RUNTIMEERROR = 2  # sec


class ReportBackend(ABC):
    @abstractmethod
    def has_duplicate(self, qid: str) -> bool:
        pass

    @abstractmethod
    def has_duplicate_local_auth_id(self, qid: str) -> bool:
        pass

    @abstractmethod
    def has_done(self, qid: str) -> bool:
        pass

    @abstractmethod
    def has_error(self, qid: str) -> bool:
        pass

    @abstractmethod
    def has_ignore(self, qid: str) -> bool:
        pass

    @abstractmethod
    def add_duplicate(
        self, qid: str, duplicate_qid: str, local_auth_id: str | None, viaf_id: str
    ) -> None:
        pass

    @abstractmethod
    def add_duplicate_local_auth_id(
        self, qid: str, local_auth_id: str, viaf_cluster_id: str | None
    ) -> None:
        pass

    @abstractmethod
    def add_error(self, qid: str, msg: str) -> None:
        pass

    @abstractmethod
    def add_done(self, qid: str) -> None:
        pass

    @abstractmethod
    def get_duplicates(self) -> list[tuple[str, str, str, str]]:
        pass

    @abstractmethod
    def get_dup_locals(self) -> Iterator[tuple[str, set[str], str]]:
        pass

    @abstractmethod
    def get_stats(self) -> tuple[int, int, int] | None:
        pass

    @abstractmethod
    def end_session(self, pid: str) -> None:
        pass


def _add_viaf(
    item: pwb.ItemPage,
    auth_src: viaf.authority_sources.AuthoritySource,
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
    def __init__(
        self, auth_src: viaf.authority_sources.AuthoritySource, report: ReportBackend
    ):
        self.auth_src = auth_src
        self.test = False
        self.report = report

    def generate_dup_report(self):
        self.write_to_wiki(self.make_duplocal_wikitext())

    def generate_report(self):
        self.write_to_wiki(self.make_wikitext())

    def end_session(self):
        self.report.end_session(self.auth_src.pid)

    def run(self):
        self.run_session()

    def run_session(self) -> None:
        """Run one qlever-based pass and, if it ran to completion (i.e. wasn't cut
        short by the VIAF API rate limit), publish the duplicate/wikitext
        reports and start a new reporting session."""
        finished = self.iterate_qlever()
        if finished:
            self.generate_dup_report()
            self.generate_report()
            self.end_session()

    def change_wikidata(self, record: viaf.authority_sources.AuthorityRecord) -> None:
        if not record.qid.startswith("Q"):  # ignore property pages and lexeme pages
            return

        item = pwb.ItemPage(REPO, record.qid)

        try:
            if not item.exists():
                return
        except pwb.exceptions.MaxlagTimeoutError as ex:
            time.sleep(MAX_LAG_BACKOFF_SECS)
            raise RuntimeError("max lag timeout. sleeping. failed to add claim")

        if item.isRedirectPage():
            return

        existing_claims = item.get().get("claims")

        if not item.botMayEdit():
            raise RuntimeError("Skipping, because it cannot be edited by bots")

        if not existing_claims:
            raise RuntimeError("Skipping, because it has no claims")

        if wd.PID_VIAF_ID in existing_claims:
            raise RuntimeError("Skipping, because it already has a VIAF ID")

        if self.auth_src.pid not in existing_claims:
            raise RuntimeError(f"Skipping, because it has no {self.auth_src.pid} PID")

        found = False
        for claim in existing_claims[self.auth_src.pid]:
            claim_target = claim.getTarget()
            if claim_target == record.wikidata_external_id:
                if claim.getRank() == "deprecated":
                    raise RuntimeError(
                        f"Skipping, because the {self.auth_src.pid} {record.wikidata_external_id} is deprecated"
                    )
                found = True
                break

        if not found:
            raise RuntimeError(
                f"Skipping, because it has no {self.auth_src.pid} {record.wikidata_external_id}"
            )

        if self.test:
            return

        pwb.output(f"Adding VIAF ID {record.viaf_cluster_id} to {record.qid}")
        _add_viaf(item, self.auth_src, viaf_cluster_id=record.viaf_cluster_id)
        self.report.add_done(qid=record.qid)

    def get_duplicates_qids(self, record: viaf.authority_sources.AuthorityRecord):
        res = []
        query = 'SELECT DISTINCT ?item WHERE {{ ?item p:P214 ?statement0. ?statement0 (ps:P214) "{viaf_id}". FILTER (?item != wd:{qid})}} LIMIT 5'.format(
            viaf_id=record.viaf_cluster_id, qid=record.qid
        )

        bindings = viaf.wdqs_client.query_wdqs(query)
        if not bindings:
            return res
        for row in bindings:
            other_qid = row.get("item", {}).get("value", "").replace(WD, "")
            # other_qid = row.get("item", {}).get("value", "").replace(WD, "")
            res.append(other_qid)
        return res

    def examine(self, record: viaf.authority_sources.AuthorityRecord) -> None:
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

            code = self.auth_src.viaf_code
            self.auth_src.compute_viaf_search_key(record)

            if not record.viaf_search_key:
                raise RuntimeError("No search key")

            qry = viaf.viaf_api_client.ViafApiClient()
            if code == "LC":
                res = qry.query_viaf_lccn(record.viaf_search_key)
            else:
                res = qry.query_viaf_sourceid(code, record.viaf_search_key)
            if res.status != "found":
                raise RuntimeError(f"status {res.status}")
            if not res.viaf_cluster_id:
                raise RuntimeError(f"no viaf_cluster_id")

            record.viaf_cluster_id = res.viaf_cluster_id

            other_wikidata_ids = []
            local_auth_ids = []
            has_local_auth_id = False

            if self.auth_src.viaf_code in res.source_mapping:
                for nsid, content_id in res.source_mapping[self.auth_src.viaf_code]:
                    if self.auth_src.matches_viaf_external_id(nsid, content_id, record):
                        has_local_auth_id = True
                    if nsid not in local_auth_ids:
                        local_auth_ids.append(nsid)

            if AUTHORITY_SOURCE_CODE_WIKIDATA in res.source_mapping:
                for other_qid, content_id in res.source_mapping[
                    AUTHORITY_SOURCE_CODE_WIKIDATA
                ]:
                    if other_qid != record.qid:
                        if other_qid not in other_wikidata_ids:
                            other_wikidata_ids.append(other_qid)

            duplicate_qids = list(
                set(self.get_duplicates_qids(record)).union(other_wikidata_ids)
            )
            if duplicate_qids:
                for duplicate_qid in duplicate_qids:
                    self.report.add_duplicate(
                        record.qid,
                        duplicate_qid,
                        record.wikidata_external_id,
                        record.viaf_cluster_id,
                    )
                raise RuntimeError(f"has duplicates: {duplicate_qids}")

            if len(local_auth_ids) == 0:
                raise RuntimeError("no local_auth_ids")
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
                raise RuntimeError(f"multiple local_auth_ids {local_auth_ids}")
            if not has_local_auth_id:
                raise RuntimeError(f"local_auth_id not found")
            # if len(reader.wikidata_ids) == 0:
            #     raise RuntimeError("no wikidata_ids")
            if len(other_wikidata_ids) > 1:
                raise RuntimeError(f"multiple wikidata_ids {other_wikidata_ids}")
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
        except viaf.viaf_api_client.ViafRateLimitExceeded:
            # Not a per-item failure - let the caller (iterate_qlever) stop the run.
            raise
        except RuntimeError as e:
            pwb.warning(f"Runtime error: {e}")
            self.report.add_error(record.qid, e.__repr__())
            time.sleep(SLEEP_AFTER_RUNTIMEERROR)
        except Exception as e:
            pwb.error(f"Exception: {e}")
            self.report.add_error(record.qid, e.__repr__())
            time.sleep(SLEEP_AFTER_ERROR)

    def make_wikitext(self):
        heading = "=={description}==\n".format(description=self.auth_src.description)
        header = '\n{| class="wikitable sortable" style="vertical-align:bottom;"\n|-\n! VIAF\n! QID on the item\n! ID from cluster\n! 2nd QID\n! class="unsortable" | Compare'
        body = ""
        line = "\n|-\n| https://viaf.org/viaf/{viaf_id}\n| {{{{Q|{qid}}}}}\n| {auth_code}|{local_auth_id}\n| {{{{Q|{duplicate_qid}}}}}\n| {compare}"
        has_duplicates = False
        duplicates = self.report.get_duplicates()
        if not duplicates:
            raise RuntimeError("No duplicates")
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
            raise RuntimeError("No stats")
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

    def make_duplocal_wikitext(self):
        heading = "=={description}==\n".format(description=self.auth_src.description)
        header = '\n{| class="wikitable sortable" style="vertical-align:bottom;"\n|-\n! VIAF\n! QID on the item\n! ID from cluster'
        body = ""
        line = "\n|-\n| https://viaf.org/viaf/{viaf_id}\n| {{{{Q|{qid}}}}}\n|{local_auth_ids}"
        has_duplicates = False
        for row in self.report.get_dup_locals():
            qid, local_auth_id_set, viaf_id = row
            strs = set()
            for local_auth_id in local_auth_id_set:
                str = f"[https://d-nb.info/gnd/{local_auth_id} {local_auth_id}]"
                strs.add(str)
            local_auth_ids = ", ".join(sorted(strs))
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

    def write_to_wiki(self, wikitext) -> None:
        if not wikitext:
            return
        site = pwb.Site("wikidata", "wikidata")
        page = pwb.Page(site, PAGE_TITLE)
        page.text = page.text + "\n" + wikitext
        page.save(summary="upd", minor=False)

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

        qry = query_template.format(pid=self.auth_src.pid, index=index)
        r = viaf.wdqs_client.query_wdqs(qry)
        if not r:
            return False
        for row in r:
            qid = row.get("item", {}).get("value", "").replace(WD, "")
            local_auth_id = row.get("local_auth_id", {}).get("value", "")
            if len(qid) == 0:
                continue
            if len(local_auth_id) == 0:
                continue
            record = viaf.authority_sources.AuthorityRecord(qid, local_auth_id)
            self.examine(record)
        return True

    def fetch_qlever_results(self, output_file: str = "qlever_viaf_index.txt") -> int:
        """Execute the iterate_index query on qlever without the slice part and save the output.

        The output file contains QID and local authority ID pairs separated by tabs.
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
        qry = query_template.format(pid=self.auth_src.pid)
        results = _execute_qlever_query(qry)
        if not results:
            pwb.warning("No results returned from qlever.")
            return 0

        with open(output_file, "w", encoding="utf-8") as fh:
            for row in results:
                fh.write(f"{row['qid']}\t{row['local_auth_id']}\n")

        pwb.output(f"Wrote {len(results)} rows to {output_file}")
        return len(results)

    def iterate_qlever(self, output_file: str = "qlever_viaf_index.txt") -> bool:
        """Run qlever once and iterate the resulting items.

        Stops early if the VIAF API reports its rate limit was hit, leaving
        the remaining rows in output_file for the next run.

        Returns True if every row in output_file was processed (and the file
        was removed), False if the run was cut short by the rate limit.
        """
        if not os.path.exists(output_file):
            pwb.output(f"Fetching qlever results into {output_file}...")
            count = self.fetch_qlever_results(output_file=output_file)
            if count == 0:
                pwb.warning("No qlever rows to process.")
                return True
        else:
            pwb.output(f"Using existing qlever file: {output_file}")

        total_lines = 0
        with open(output_file, "r", encoding="utf-8") as fh:
            total_lines = sum(1 for line in fh if line.strip())

        processed = 0
        malformed = 0
        remaining_lines: list[str] = []
        finished = True
        with open(output_file, "r", encoding="utf-8") as fh:
            for line in fh:
                stripped = line.strip()
                if not stripped:
                    continue

                parts = stripped.split("\t")
                if len(parts) != 2:
                    malformed += 1
                    pwb.warning(f"Skipping malformed line: {stripped}")
                    continue
                qid, local_auth_id = parts
                record = viaf.authority_sources.AuthorityRecord(qid, local_auth_id)
                try:
                    self.examine(record)
                except viaf.viaf_api_client.ViafRateLimitExceeded as e:
                    pwb.warning(f"{e}; stopping for now.")
                    remaining_lines = [line] + list(fh)
                    finished = False
                    break
                processed += 1
                if processed % 100 == 0 or processed == total_lines:
                    pct = (processed / total_lines * 100) if total_lines else 0.0
                    pwb.output(
                        f"Processed {processed}/{total_lines} valid items ({pct:.1f}%), malformed lines skipped: {malformed}"
                    )

        if not finished:
            with open(output_file, "w", encoding="utf-8") as fh:
                fh.writelines(remaining_lines)
            pwb.output(f"{len(remaining_lines)} unprocessed row(s) left in {output_file}.")
            return False

        try:
            os.remove(output_file)
            pwb.output(f"Removed temporary qlever file {output_file}")
        except OSError as e:
            pwb.error(f"Failed to remove temporary file {output_file}: {e}")

        return True
