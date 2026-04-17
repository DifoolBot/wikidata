from urllib.parse import parse_qs, urlparse

import pywikibot
import requests

import shared_lib.change_wikidata as cwd
import shared_lib.constants as wd

site = pywikibot.Site("wikidata", "wikidata")
repo = site.data_repository()

# see https://www.wikidata.org/wiki/Talk:Q4937233
# query: https://qlever.dev/wikidata/c1T82F

# Global cache
_url_cache = {}
_classify_cache = {}


# Your interface functions (stubs here)
def remove_property(item_id, property_id, claim_id):
    print(f"Removing property {property_id} (claim {claim_id}) from {item_id}")
    # Call your actual interface here


def remove_reference_value(item_id, property_id, claim_id, ref_hash):
    print(
        f"Removing reference value from {item_id}, property {property_id}, claim {claim_id}, ref {ref_hash}"
    )
    # Call your actual interface here


def resolve_url(url):
    """Resolve shortened g.co URLs to their final destination, with caching."""
    if url in _url_cache:
        return _url_cache[url]

    try:
        r = requests.head(url, allow_redirects=True, timeout=10)
        final_url = r.url
    except Exception as e:
        print(f"Error resolving {url}: {e}")
        final_url = url

    _url_cache[url] = final_url
    return final_url


def is_google_search_url(url):
    """Check if URL is a Google search link."""
    if "google.com/search" in url:
        return True
    return False


def extract_google_query(url):

    # Parse the URL
    parsed_url = urlparse(url)

    # Extract query parameters into a dictionary
    params = parse_qs(parsed_url.query)

    # Get the 'q' value (list of values, so take the first one)
    query_value = params.get("q", [None])[0]

    return query_value


import requests


def get_kg_ids(query: str, api_key: str):
    """
    Query the Google Knowledge Graph Search API for a given search text
    and return Freebase ID (/m/...) and Google KG ID (/g/...).

    Args:
        query (str): The search text (e.g., "Hazel Crane").
        api_key (str): Your Google API key.

    Returns:
        dict: A dictionary with 'freebase_id' and 'google_kg_id' if found.
    """
    url = "https://kgsearch.googleapis.com/v1/entities:search"
    params = {
        "query": query,
        "key": api_key,
        "limit": 1,  # return only the top match
        "indent": True,
    }

    response = requests.get(url, params=params)
    data = response.json()

    result = {"freebase_id": None, "google_kg_id": None}

    if "itemListElement" in data and data["itemListElement"]:
        entity = data["itemListElement"][0]["result"]

        # Normalize @id values like 'kg:/m/...' or 'kg:/g/...'
        raw_id = entity.get("@id", "")
        if raw_id.startswith("kg:"):
            raw_id = raw_id.replace("kg:", "")

        if raw_id.startswith("/m/"):
            result["freebase_id"] = raw_id
        elif raw_id.startswith("/g/"):
            result["google_kg_id"] = raw_id

        # Sometimes identifiers are listed separately
        if "identifier" in entity:
            for ident in entity["identifier"]:
                if ident.startswith("kg:"):
                    ident = ident.replace("kg:", "")
                if ident.startswith("/m/"):
                    result["freebase_id"] = ident
                elif ident.startswith("/g/"):
                    result["google_kg_id"] = ident

    return result


# Example usage:
# api_key = "YOUR_API_KEY"
# ids = get_kg_ids("Hazel Crane", api_key)
# print(ids)  # {'freebase_id': '/m/04my8sb', 'google_kg_id': '/g/11b6c4z0w5'}


# Example usage:
# api_key = "YOUR_API_KEY"
# ids = get_kg_ids("Hazel Crane", api_key)
# print(ids)  # {'freebase_id': '/m/xxxx', 'google_kg_id': '/g/xxxx'}


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

    try:
        parsed = urlparse(url)
        netloc = parsed.netloc.lower()
        path = parsed.path.lower()
        query_params = parse_qs(parsed.query)

        # Check for Google Search (any TLD)
        if not (netloc.startswith("google.") or netloc.startswith("www.google.")):
            return result

        if path.startswith("/search"):
            result["is_search"] = True

        # Check for Knowledge Graph (kgmid param)
        if not "kgmid" in query_params:
            q = extract_google_query(url)
            if q:
                ids = get_kg_ids(q, api_key=API_KEY)
                if ids["google_kg_id"]:
                    result["is_knowledge_graph"] = True
                    result["id_value"] = ids["google_kg_id"]
                    result["property_id"] = wd.PID_GOOGLE_KNOWLEDGE_GRAPH_ID
                    result["url"] = url

                    return result
                elif ids["freebase_id"]:
                    result["is_knowledge_graph"] = True
                    result["id_value"] = ids["freebase_id"]
                    result["property_id"] = wd.PID_FREEBASE_ID
                    result["url"] = url

                    return result

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

    except Exception as e:
        print(f"Error parsing URL {url}: {e}")

    return result


def classify_google_url(url):
    if url in _classify_cache:
        return _classify_cache[url]

    result = _classify_google_url(url)
    _classify_cache[url] = result
    return result


def process_item(item_id, test: bool):
    item = pywikibot.ItemPage(repo, item_id)
    page = cwd.WikiDataPage(item, test=test)

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
                    if c["is_search"]:
                        # Remove entire property
                        page.remove_property(prop_id, claim)
                    if c["is_knowledge_graph"] and c["id_value"] and c["property_id"]:
                        kgmid = c["id_value"]
                        page.add_statement(
                            cwd.ExternalIDStatement("", c["property_id"], kgmid)
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

                            if (
                                c["is_knowledge_graph"]
                                and c["id_value"]
                                and c["property_id"]
                            ):
                                if prop_id != c["property_id"]:
                                    kgmid = c["id_value"]
                                    page.add_ref_value(
                                        prop_id,
                                        claim,
                                        claim.sources.index(source),
                                        c["property_id"],
                                        kgmid,
                                    )

                            if c["is_search"] or c["is_knowledge_graph"]:
                                page.remove_ref_value(
                                    prop_id,
                                    claim,
                                    claim.sources.index(source),
                                    ref_prop,
                                    ref_target,
                                )

    page.summary = "remove google search links"
    page.apply()


def load_items_from_file(filename):
    with open(filename, "r", encoding="utf-8") as f:
        # Strip whitespace and skip empty lines
        return [line.strip() for line in f if line.strip()]


def main():
    # Example input list from qlever
    # items = ["Q847100"]
    items = load_items_from_file("C:\\Users\\User\\Downloads\\wikidata_iNxxeO.csv")
    for qid in items:
        print(f"Processing {qid}...")
        process_item(qid, test=False)


if __name__ == "__main__":
    main()
