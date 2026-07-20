"""Replace Google search links on Wikidata items with proper identifiers.

Google-search URLs carrying an explicit kgmid= parameter are converted: the
URL statement is removed and a P646 Freebase ID / P2671 Google Knowledge
Graph ID statement is added instead. Search URLs inside references are
likewise stripped, with the id added as a reference value where it fits.
g.co short links are resolved via HTTP redirect first.

Keyword-only search URLs (no kgmid=) are never touched: resolving the search
text via the KG Search API is a relevance-ranked guess that regularly lands
on the wrong entity, so those URLs are only logged for manual review.

Dry-run by default. Pass --save to actually edit (requires pywikibot auth).

    python projects/clean_google/clean_google_links.py               # dry run, whole list
    python projects/clean_google/clean_google_links.py --limit 5     # dry run, 5 items
    python projects/clean_google/clean_google_links.py --qid Q123    # one item, even if done
    python projects/clean_google/clean_google_links.py --save        # really edit
    python projects/clean_google/clean_google_links.py --fetch-items # rebuild input/items.txt
"""

import argparse
import random
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pywikibot
import requests

import shared_lib.change_wikidata as cwd
import shared_lib.constants as wd
from shared_lib.qlever import build_url_items_query, fetch_qids_to_file

# URL statement properties scanned by fetch_and_fill_items; edit/expand to widen
# the search.
QLEVER_URL_PROPERTIES = [
    "P854",
    "P856",
    "P953",
    "P973",
    "P1325",
    "P2699",
    "P2888",
    "P8214",
]
# only items whose URL value contains one of these substrings are collected
QLEVER_DOMAIN_SUBSTRINGS = ["google.com/search"]

HERE = Path(__file__).parent
ITEMS_FILE = HERE / "input" / "items.txt"
OUTPUT_DIR = HERE / "output"
DONE_FILE = OUTPUT_DIR / "done.txt"
FAILED_FILE = OUTPUT_DIR / "failed.txt"
REVIEW_FILE = OUTPUT_DIR / "review.txt"

site = pywikibot.Site("wikidata", "wikidata")
repo = site.data_repository()

# see https://www.wikidata.org/wiki/Talk:Q4937233
# query: https://qlever.dev/wikidata/c1T82F

# Global cache
_url_cache = {}
_classify_cache = {}


def resolve_url(url):
    """Resolve shortened g.co URLs to their final destination, with caching.

    Network failures propagate so the item lands in failed.txt and is retried
    later, instead of being marked done with the link untouched.
    """
    if url in _url_cache:
        return _url_cache[url]

    r = requests.head(url, allow_redirects=True, timeout=10)
    final_url = r.url

    _url_cache[url] = final_url
    return final_url


def _classify_google_url(url):
    """
    Classify a Google URL as either a search link or a Knowledge Graph/Freebase link.
    Returns a dict with flags and extracted ID info.
    """
    result = {
        "is_search": False,
        "is_knowledge_graph": False,
        "property_id": None,  # P646 for Freebase, P2671 for KG
        "id_value": None,
        "url": None,
    }

    parsed = urlparse(url)
    netloc = parsed.netloc.lower()
    path = parsed.path.lower()
    query_params = parse_qs(parsed.query)

    # Check for Google Search (any TLD)
    if not (netloc.startswith("google.") or netloc.startswith("www.google.")):
        return result

    if path.startswith("/search"):
        result["is_search"] = True

    # Only an explicit kgmid= parameter identifies the entity reliably.
    # Resolving the q= search text via the KG Search API is a relevance-ranked
    # guess that regularly returns the wrong entity, so it is deliberately not
    # attempted; kgmid-less search URLs go to review.txt instead.
    if "kgmid" in query_params:
        kgmid_value = query_params["kgmid"][0]
        result["is_knowledge_graph"] = True
        result["id_value"] = kgmid_value

        # Decide property based on prefix
        if kgmid_value.startswith("/m/"):
            result["property_id"] = wd.PID_FREEBASE_ID
        elif kgmid_value.startswith("/g/"):
            result["property_id"] = wd.PID_GOOGLE_KNOWLEDGE_GRAPH_ID
        # https://www.google.com/search?kgmid=/m/0fpdf90&hl=en-US&q=Kenneth+E.+Goodson&kgs=67736d53770a74e9&shndl=17&source=sh/x/kp/osrp/1
        if "hl" in query_params:
            result["url"] = (
                f"https://www.google.com/search?kgmid={kgmid_value}"
                f"&hl={query_params['hl'][0]}"
            )
        else:
            result["url"] = f"https://www.google.com/search?kgmid={kgmid_value}"

    return result


def classify_google_url(url):
    if url in _classify_cache:
        return _classify_cache[url]

    result = _classify_google_url(url)
    _classify_cache[url] = result
    return result


def process_item(item_id, edit_group: str, test: bool) -> tuple[bool, list[str]]:
    """Returns (changed, review_lines); review_lines are keyword-only search
    URLs that were left untouched for manual handling."""
    item = pywikibot.ItemPage(repo, item_id)
    page = cwd.WikiDataPage(item, test=test)
    page.edit_group = edit_group
    reviews: list[str] = []

    # Iterate over claims (properties)
    for prop_id, claims in page.claims.items():
        for claim in claims:
            # if claim.rank == "deprecated":
            #     continue
            if claim.type == "url":
                target = claim.getTarget()
                if isinstance(target, str) and target.startswith("http"):
                    url = target
                    if url.startswith("https://g.co/"):
                        url = resolve_url(url)

                    c = classify_google_url(url)
                    has_id = bool(
                        c["is_knowledge_graph"] and c["id_value"] and c["property_id"]
                    )
                    if c["is_search"] and not has_id:
                        # No kgmid= to convert; leave the URL for manual review
                        reviews.append(f"{item_id}\tstatement\t{prop_id}\t{url}")
                    elif c["is_search"]:
                        # Remove entire property
                        page.remove_property(prop_id, claim)
                    if has_id:
                        page.add_statement(
                            cwd.ExternalIDStatement("", c["property_id"], c["id_value"])
                        )

            if prop_id == wd.PID_FREEBASE_ID:
                continue
            if prop_id == wd.PID_GOOGLE_KNOWLEDGE_GRAPH_ID:
                continue

            # Check references
            for source in claim.sources:
                for ref_prop, ref_values in source.items():
                    for ref_val in ref_values:
                        if ref_val.type != "url":
                            continue
                        # if ref_val.rank == "deprecated":
                        #     continue

                        ref_target = ref_val.getTarget()
                        if isinstance(ref_target, str) and ref_target.startswith(
                            "http"
                        ):
                            url = ref_target
                            if url.startswith("https://g.co/"):
                                url = resolve_url(url)

                            c = classify_google_url(url)
                            if not (c["is_search"] or c["is_knowledge_graph"]):
                                continue

                            has_id = bool(
                                c["is_knowledge_graph"]
                                and c["id_value"]
                                and c["property_id"]
                            )
                            if not has_id:
                                # No kgmid= to convert; leave for manual review
                                reviews.append(
                                    f"{item_id}\treference\t{prop_id}\t{url}"
                                )
                                continue

                            if prop_id != c["property_id"]:
                                page.add_ref_value(
                                    prop_id,
                                    claim,
                                    claim.sources.index(source),
                                    c["property_id"],
                                    c["id_value"],
                                )

                            page.remove_ref_value(
                                prop_id,
                                claim,
                                claim.sources.index(source),
                                ref_prop,
                                ref_target,
                            )

    page.summary = "remove google search links"
    return page.apply(), reviews


def load_items_from_file(filename):
    with open(filename, "r", encoding="utf-8") as f:
        # Strip whitespace and skip empty lines
        return [line.strip() for line in f if line.strip()]


def load_processed() -> set:
    """QIDs already recorded in done.txt or failed.txt (first tab-field)."""
    processed = set()
    for path in (DONE_FILE, FAILED_FILE):
        if path.exists():
            with open(path, encoding="utf-8") as f:
                processed |= {
                    line.split("\t", 1)[0].strip() for line in f if line.strip()
                }
    return processed


def append_line(path: Path, line: str) -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def fetch_and_fill_items() -> int:
    """Query qlever for items with a Google search URL and write their QIDs to ITEMS_FILE."""
    query = build_url_items_query(QLEVER_URL_PROPERTIES, QLEVER_DOMAIN_SUBSTRINGS)
    count = fetch_qids_to_file(query, ITEMS_FILE)
    print(f"Wrote {count} items to {ITEMS_FILE}")
    return count


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Replace Google search links with Freebase/Knowledge Graph ids."
    )
    parser.add_argument(
        "--save",
        action="store_true",
        help="really edit Wikidata and record results (default: dry run)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        metavar="N",
        help="stop after processing N not-yet-done items",
    )
    parser.add_argument(
        "--qid",
        action="append",
        default=[],
        metavar="QID",
        help="process only this QID, even if already processed (repeatable)",
    )
    parser.add_argument(
        "--fetch-items",
        action="store_true",
        help=f"regenerate {ITEMS_FILE.name} from qlever and exit",
    )
    args = parser.parse_args()

    if args.fetch_items:
        fetch_and_fill_items()
        return

    edit_group = f"{random.randrange(0, 2**48):x}"
    print(f"editgroup={edit_group} ({'SAVE' if args.save else 'dry run'})", flush=True)

    force = bool(args.qid)
    items = args.qid or load_items_from_file(ITEMS_FILE)
    done = load_processed()
    processed = 0
    for qid in items:
        if args.limit is not None and processed >= args.limit:
            break
        if not force and qid in done:
            continue
        print(f"Processing {qid}...", flush=True)
        processed += 1
        try:
            changed, reviews = process_item(
                qid, edit_group=edit_group, test=not args.save
            )
        except Exception as e:
            pywikibot.error(f"Error processing {qid}: {e}")
            if args.save:
                message = str(e).replace("\n", " ").replace("\t", " ")[:500]
                append_line(FAILED_FILE, f"{qid}\t{message}")
            continue
        for line in reviews:
            print(f"  REVIEW {line}", flush=True)
        # Dry runs record nothing, so they never block a later --save.
        if args.save:
            for line in reviews:
                append_line(REVIEW_FILE, line)
            note = "changed" if changed else "no-change"
            if reviews:
                note += f", review ({len(reviews)}x)"
            append_line(DONE_FILE, f"{qid}\t{note}")
    print(f"Done: {processed} item(s) processed.", flush=True)


if __name__ == "__main__":
    main()
