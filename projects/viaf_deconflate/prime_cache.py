"""Prime the redirect-scan selection cache from a downloaded SPARQL CSV.

When qlever and WDQS are both unavailable for the heavy ``multi`` aggregation,
the population can still be fetched in cheap slices from the WDQS GUI (e.g.
``query-main.wikidata.org``) using the Blazegraph slice service::

    PREFIX bd: <http://www.bigdata.com/rdf#>
    PREFIX wd: <http://www.wikidata.org/entity/>
    PREFIX wdt: <http://www.wikidata.org/prop/direct/>
    SELECT ?item ?v WHERE {
      SERVICE bd:slice {
        ?item wdt:P214 ?v .
        bd:serviceParam bd:slice.offset 0 .
        bd:serviceParam bd:slice.limit 200000 .
      }
      ?item wdt:P31 wd:Q5 .
    }

That returns raw ``(item, v)`` pairs (best-rank / non-deprecated truthy values --
the same set the redirect scan uses, minus the rare item whose preferred rank
suppresses normal-rank siblings). This script does the per-item counting that the
slice query cannot (you cannot slice and GROUP BY at once), then writes the cache
file ``deconflate.py`` reuses.

Two ways to supply the pairs:

  --fetch  page the slice query over HTTP yourself (default endpoint
           query-main.wikidata.org, which excludes scholarly articles and so
           beats the timeout the full-graph aggregation hits). This is the easy
           path -- it loops offset until a page comes back empty:

               python projects/viaf_deconflate/prime_cache.py --fetch

  CSV(s)   one or more WDQS CSV exports of (item, v) pairs. NOTE the slice limit
           applies to the P214 pattern *before* the Q5 filter, so each exported
           page comes back under the limit even when it is full -- one download
           is only a fraction of the population. List every page you exported:

               python projects/viaf_deconflate/prime_cache.py p0.csv p1.csv ...

``multi`` keeps items with >= --min-count distinct values (default 2); ``long``
keeps items with any value >= 19 characters. The next
``deconflate.py --redirect-scan <kind>`` run reuses the primed cache with no
network query (no --refresh-selection).
"""

import argparse
import csv
import io
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

# Must match deconflate.py's SELECTION_CACHE_DIR / cache payload layout.
CACHE_DIR = Path(__file__).resolve().parent / "output" / "selection_cache"

# query-main excludes the scholarly-article subgraph, so the P214 scan is far
# smaller than on the full query.wikidata.org graph.
DEFAULT_ENDPOINT = "https://query-main.wikidata.org/sparql"
DEFAULT_PAGE_SIZE = 200000
DEFAULT_MAX_PAGES = 40  # safety stop (~8M P214 statements at the default size)
USER_AGENT = "DifoolBot/1.0 (https://www.wikidata.org/wiki/User:DifoolBot)"

# VIAF long-format ids (the newer, gapped form) are >= 19 chars; matches
# build_long_viaf_query()'s STRLEN filter.
LONG_MIN_LEN = 19


def _qid(item: str) -> str:
    """QID from a full entity URI or a bare QID; '' if it is neither."""
    tail = item.strip().rsplit("/", 1)[-1]
    return tail if tail.startswith("Q") and tail[1:].isdigit() else ""


def read_pairs(paths: list[Path]) -> dict[str, set[str]]:
    """Fold the (item, v) rows of one or more CSVs into {qid: {value, ...}}.

    Accepts a header row with columns named 'item' and 'v' (WDQS CSV export); if
    the header is absent or unnamed, falls back to the first two columns."""
    values: dict[str, set[str]] = {}
    for path in paths:
        with open(path, encoding="utf-8-sig", newline="") as fh:
            reader = csv.reader(fh)
            try:
                header = next(reader)
            except StopIteration:
                continue
            lower = [h.strip().lower() for h in header]
            i_col = lower.index("item") if "item" in lower else 0
            v_col = lower.index("v") if "v" in lower else 1
            # A header we did not recognise as names is real data -> re-process it.
            if "item" not in lower and "v" not in lower:
                _add_row(values, header, i_col, v_col)
            for row in reader:
                _add_row(values, row, i_col, v_col)
    return values


def _add_row(values: dict[str, set[str]], row: list[str], i_col: int, v_col: int) -> None:
    if len(row) <= max(i_col, v_col):
        return
    qid = _qid(row[i_col])
    val = row[v_col].strip()
    if qid and val:
        values.setdefault(qid, set()).add(val)


def build_slice_query(offset: int, limit: int) -> str:
    """One slice window of the raw (item, v) P214 pairs on Q5 items. bd:slice
    wraps a single triple pattern (the P214 statement); Q5 filters outside it."""
    return f"""PREFIX bd: <http://www.bigdata.com/rdf#>
PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
SELECT ?item ?v WHERE {{
  SERVICE bd:slice {{
    ?item wdt:P214 ?v .
    bd:serviceParam bd:slice.offset {offset} .
    bd:serviceParam bd:slice.limit {limit} .
  }}
  ?item wdt:P31 wd:Q5 .
}}"""


def _fetch_page(endpoint: str, offset: int, page_size: int, retries: int) -> str:
    """CSV text for one slice window, retrying a flaky call. Raises after the last
    attempt so a failed page aborts the run rather than priming a partial cache."""
    last: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(
                endpoint,
                params={"query": build_slice_query(offset, page_size)},
                headers={"User-Agent": USER_AGENT, "Accept": "text/csv"},
                timeout=180,
            )
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as exc:
            last = exc
            wait = 30 * attempt
            print(f"    page at offset {offset} failed ({exc}); "
                  f"retry {attempt}/{retries - 1} in {wait}s." if attempt < retries
                  else f"    page at offset {offset} failed ({exc}); giving up.")
            if attempt < retries:
                time.sleep(wait)
    raise RuntimeError(f"slice fetch failed at offset {offset}: {last}")


def fetch_pairs(endpoint: str, page_size: int, delay: float,
                max_pages: int, retries: int = 3) -> dict[str, set[str]]:
    """Page the slice query until a window returns no rows, folding to
    {qid: {value, ...}}. The Q5 filter runs after the slice, so a page under
    ``page_size`` is normal (density, not the end) -- only an empty page means the
    P214 space is exhausted. Keep ``page_size`` small enough that a window is not
    truncated server-side (50000 is safe; 200000 truncates over HTTP). Waits
    ``delay`` seconds between calls to stay under WDQS limits."""
    values: dict[str, set[str]] = {}
    for page in range(max_pages):
        offset = page * page_size
        if page:
            time.sleep(delay)
        reader = csv.reader(io.StringIO(_fetch_page(endpoint, offset, page_size, retries)))
        try:
            next(reader)  # header
        except StopIteration:
            break
        rows = 0
        for row in reader:
            _add_row(values, row, 0, 1)
            rows += 1
        print(f"  page {page} (offset {offset}): {rows} human row(s); "
              f"{len(values)} distinct item(s) so far.")
        if rows == 0:
            break
    else:
        print(f"  stopped at the {max_pages}-page safety cap; "
              f"raise --max-pages if the population is larger.")
    return values


def select(values: dict[str, set[str]], kind: str, min_count: int) -> list[str]:
    """QIDs (sorted by number) matching the redirect-scan subset, mirroring
    build_multi_viaf_query() / build_long_viaf_query()."""
    if kind == "long":
        keep = [q for q, vs in values.items()
                if any(len(v) >= LONG_MIN_LEN for v in vs)]
    else:  # multi
        keep = [q for q, vs in values.items() if len(vs) >= min_count]
    return sorted(keep, key=lambda q: int(q[1:]))


def write_cache(cache_key: str, source: str, qids: list[str]) -> Path:
    """Write the selection cache in deconflate.py's bindings format: one uri
    binding per qid under ``item`` (the redirect scan reads only ``item``)."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    bindings = [
        {"item": {"type": "uri", "value": f"http://www.wikidata.org/entity/{q}"}}
        for q in qids
    ]
    payload = {
        "fetched": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source": source,
        "count": len(bindings),
        "bindings": bindings,
    }
    path = CACHE_DIR / f"{cache_key}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv", nargs="*", type=Path,
                    help="CSV export(s) of (item, v) pairs; multiple = slice pages")
    ap.add_argument("--fetch", action="store_true",
                    help="page the slice query over HTTP instead of reading CSVs")
    ap.add_argument("--endpoint", default=DEFAULT_ENDPOINT,
                    help=f"--fetch SPARQL endpoint (default {DEFAULT_ENDPOINT})")
    ap.add_argument("--page-size", type=int, default=DEFAULT_PAGE_SIZE,
                    help=f"--fetch slice window size (default {DEFAULT_PAGE_SIZE})")
    ap.add_argument("--delay", type=float, default=60.0,
                    help="--fetch seconds to wait between WDQS calls (default 60)")
    ap.add_argument("--max-pages", type=int, default=DEFAULT_MAX_PAGES,
                    help=f"--fetch safety cap on pages (default {DEFAULT_MAX_PAGES})")
    ap.add_argument("--kind", choices=["multi", "long"], default="multi",
                    help="which redirect-scan subset to prime (default multi)")
    ap.add_argument("--min-count", type=int, default=2,
                    help="multi: keep items with at least this many distinct "
                         "values (default 2)")
    ap.add_argument("--source", default=None,
                    help="source label recorded in the cache (default names the "
                         "origin)")
    args = ap.parse_args()

    if args.fetch:
        if args.csv:
            sys.exit("--fetch and CSV files are mutually exclusive.")
        print(f"fetching slices from {args.endpoint} "
              f"(page {args.page_size}, {args.delay:g}s between calls)...")
        values = fetch_pairs(args.endpoint, args.page_size, args.delay, args.max_pages)
        default_source = f"fetch:{args.endpoint}"
    else:
        if not args.csv:
            sys.exit("give one or more CSV files, or --fetch.")
        missing = [p for p in args.csv if not p.exists()]
        if missing:
            sys.exit(f"no such file: {', '.join(str(p) for p in missing)}")
        values = read_pairs(args.csv)
        default_source = f"csv:{args.kind}"
    total_pairs = sum(len(v) for v in values.values())
    print(f"total {total_pairs} (item, value) pair(s) over {len(values)} distinct item(s).")

    qids = select(values, args.kind, args.min_count)
    cache_key = f"redirect_{args.kind}"
    source = args.source or default_source
    path = write_cache(cache_key, source, qids)

    detail = (f">= {args.min_count} distinct values" if args.kind == "multi"
              else f"a value >= {LONG_MIN_LEN} chars")
    print(f"{len(qids)} item(s) with {detail} -> primed '{cache_key}' ({path}).")
    print("deconflate.py --redirect-scan "
          f"{args.kind} will now reuse this without a network query.")


if __name__ == "__main__":
    main()
