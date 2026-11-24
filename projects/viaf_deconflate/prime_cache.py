"""Prime the redirect-scan selection cache from a downloaded SPARQL CSV.

When the heavy ``multi`` aggregation is unavailable, the population can still be
fetched in cheap pages of raw (item, v) pairs from WDQS v2 (QLever backend,
``query-next.wikidata.org``; v1's Blazegraph ``bd:slice`` service does not exist
there) with an ordered subquery + LIMIT/OFFSET::

    SELECT ?item ?v WHERE {
      {
        SELECT ?item ?v WHERE { ?item wdt:P214 ?v ; wdt:P31 wd:Q5 . }
        ORDER BY ?item ?v
        LIMIT 100000 OFFSET 0
      }
    }

That returns raw ``(item, v)`` pairs (best-rank / non-deprecated truthy values --
the same set the redirect scan uses, minus the rare item whose preferred rank
suppresses normal-rank siblings). This script does the per-item counting, then
writes the cache file ``deconflate.py`` reuses.

Two ways to supply the pairs:

  --fetch  page the query over HTTP yourself (default endpoint
           query-next.wikidata.org). The easy path -- it loops the offset until a
           page comes back short, and checks that a short page really is the end
           (v2 cuts a response that runs past ~60 s yet still answers 200):

               python projects/viaf_deconflate/prime_cache.py --fetch

  CSV(s)   one or more CSV exports of (item, v) pairs, e.g. the pages above
           downloaded from the query GUI. The Q5 filter is inside the page, so
           every page but the last is full. List every page you exported:

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

# WDQS v2 (QLever); v1 query.wikidata.org / query-main may degrade from
# February 2027 and end in June 2027.
DEFAULT_ENDPOINT = "https://query-next.wikidata.org/sparql"
# 100k rows answer in ~7-15 s on v2; a 500k page ran past v2's ~60 s cut-off and
# came back truncated (373k rows, still HTTP 200) on 2026-11-24.
DEFAULT_PAGE_SIZE = 100000
DEFAULT_MAX_PAGES = 100  # safety stop (~10M pairs; 4.28M on 2026-11-24)
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


def build_page_query(offset: int, limit: int) -> str:
    """One page of the raw (item, v) P214 pairs on Q5 items, in a fixed order so
    consecutive offsets tile the population. The Q5 filter is inside the
    subquery, so every page but the last is full."""
    return f"""PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
SELECT ?item ?v WHERE {{
  {{
    SELECT ?item ?v WHERE {{
      ?item wdt:P214 ?v ;
            wdt:P31 wd:Q5 .
    }}
    ORDER BY ?item ?v
    LIMIT {limit} OFFSET {offset}
  }}
}}"""


def _get(endpoint: str, query: str, retries: int) -> str:
    """CSV text of one query, retrying a flaky call (429 included). Raises after
    the last attempt so a failed page aborts the run rather than priming a
    partial cache."""
    last: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(
                endpoint,
                params={"query": query},
                headers={"User-Agent": USER_AGENT, "Accept": "text/csv"},
                timeout=180,
            )
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as exc:
            last = exc
            wait = 30 * attempt
            print(f"    query failed ({exc}); retry {attempt}/{retries - 1} in {wait}s."
                  if attempt < retries else f"    query failed ({exc}); giving up.")
            if attempt < retries:
                time.sleep(wait)
    raise RuntimeError(f"SPARQL fetch failed: {last}")


def _rows(text: str) -> list[list[str]]:
    """Data rows of a CSV answer (header dropped)."""
    return list(csv.reader(io.StringIO(text)))[1:]


def fetch_pairs(endpoint: str, page_size: int, delay: float,
                max_pages: int, retries: int = 3) -> dict[str, set[str]]:
    """Page the query until a page comes back short, folding to
    {qid: {value, ...}}. A short page counts as the end only when a one-row
    probe at the next offset finds nothing; otherwise v2 cut the answer
    server-side, and the page is fetched again (the run aborts if it stays
    short). Waits ``delay`` seconds between calls."""
    values: dict[str, set[str]] = {}
    for page in range(max_pages):
        offset = page * page_size
        rows: list[list[str]] = []
        for attempt in range(retries):
            if page or attempt:
                time.sleep(delay)
            rows = _rows(_get(endpoint, build_page_query(offset, page_size), retries))
            if len(rows) >= page_size:
                break
            time.sleep(delay)
            if not _rows(_get(endpoint, build_page_query(offset + len(rows), 1), retries)):
                break
            print(f"    page {page} came back truncated ({len(rows)} rows); refetching.")
        else:
            raise RuntimeError(f"page at offset {offset} stays truncated; "
                               f"lower --page-size.")
        for row in rows:
            _add_row(values, row, 0, 1)
        print(f"  page {page} (offset {offset}): {len(rows)} row(s); "
              f"{len(values)} distinct item(s) so far.")
        if len(rows) < page_size:
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
                    help="CSV export(s) of (item, v) pairs; multiple = pages")
    ap.add_argument("--fetch", action="store_true",
                    help="page the query over HTTP instead of reading CSVs")
    ap.add_argument("--endpoint", default=DEFAULT_ENDPOINT,
                    help=f"--fetch SPARQL endpoint (default {DEFAULT_ENDPOINT})")
    ap.add_argument("--page-size", type=int, default=DEFAULT_PAGE_SIZE,
                    help=f"--fetch page size (default {DEFAULT_PAGE_SIZE})")
    ap.add_argument("--delay", type=float, default=5.0,
                    help="--fetch seconds to wait between WDQS calls (default 5)")
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
        print(f"fetching pages from {args.endpoint} "
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
