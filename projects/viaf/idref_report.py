import requests
import pywikibot as pwb
import os.path
import json
import time

WD = "http://www.wikidata.org/entity/"
WDQS_ENDPOINT = "https://query.wikidata.org/sparql"
READ_TIMEOUT = 60  # sec

PAGE_TITLE = "Property talk:P269/Gender mismatches"
WIKI_FILE = "wiki.txt"
RESULT_FILE = "idref.json"

SLEEP_AFTER_RESULT = 10  # sec

LIMIT_SIZE = 5000


def query_wdqs(query: str):
    response = requests.get(
        WDQS_ENDPOINT, params={"query": query, "format": "json"}, timeout=READ_TIMEOUT
    )
    payload = response.json()
    return payload["results"]["bindings"]


def load_slice(offset: int, limit: int):
    template = """SELECT DISTINCT ?item ?idref ?gender_wd ?gender_idref
                WITH {{
                    SELECT ?item ?idref ?gender_wd WHERE {{
                    SERVICE bd:slice {{
                        ?item wdt:P269 ?idref_id.
                        bd:serviceParam bd:slice.offset {offset} ;
                        bd:slice.limit {limit} .
                    }}
                    ?item wdt:P21 ?gender.
                    BIND(IRI(CONCAT("http://www.idref.fr/", ?idref_id, "/id")) AS ?idref)
                    BIND(IF(?gender = wd:Q6581097, "male", IF(?gender = wd:Q6581072, "female", "other")) AS ?gender_wd)
                    }}                
                }} AS %wikidata
                WITH {{
                SELECT ?idref ?gender_idref WHERE {{
                    INCLUDE %wikidata
                    SERVICE <https://data.idref.fr/sparql> {{
                    SELECT DISTINCT ?idref ?gender_idref WHERE {{
                        ?idref <http://xmlns.com/foaf/0.1/gender> ?gender_idref .
                    }}
                    }}
                }}
                }} AS %idrefdata
                WHERE {{
                INCLUDE %wikidata .
                INCLUDE %idrefdata .
                FILTER (?gender_wd != ?gender_idref)
                }}"""

    qry = template.format(offset=offset, limit=limit)

    res = {}
    for row in query_wdqs(qry):
        item = row.get("item", {}).get("value", "").replace(WD, "")
        idref = row.get("idref").get("value", "")
        gender_wd = row.get("gender_wd").get("value", "")
        gender_idref = row.get("gender_idref").get("value", "")
        t = (
            idref,
            gender_wd,
            gender_idref,
        )
        res[item] = t

    return res


def load_result():
    qids = {}
    if os.path.exists(RESULT_FILE):
        with open(RESULT_FILE, "r") as infile:
            qids = json.load(infile)
    return qids


def save_result(qids):
    with open(RESULT_FILE, "w") as outfile:
        json.dump(qids, outfile, indent=4)


def make_wikitext():
    qids = load_result()
    # sort ignoring the starting Q
    sorted_qids = sorted(qids.keys(), key=lambda x: int(x[1:]))
    index = 1
    body = ""
    line = "\n|-\n| {nr}\n| {{{{Q|{qid}}}}}\n| [{url} {idref}]\n| {gender_wd}\n| {gender_idref}\n| \n| "
    for qid in sorted_qids:
        url, gender_wd, gender_idref = qids[qid]

        idref = url.split("/")[-2]

        body += line.format(
            nr=index,
            qid=qid,
            url=url,
            idref=idref,
            gender_wd=gender_wd,
            gender_idref=gender_idref,
        )
        index += 1

    heading = ""
    header = '{| class="wikitable sortable" style="vertical-align:bottom;"\n|-\n! Nr\n! Item\n! IdRef\n! Gender Wd\n! Gender IdRef\n! Judgement\n! Note'
    footer = "\n|}"

    wikitext = f"{heading}{header}{body}{footer}"

    return wikitext


def iterate():
    qids = load_result()
    index = 0
    while True:
        print(index)
        qids.update(load_slice(index * LIMIT_SIZE, LIMIT_SIZE))
        save_result(qids)
        print(f" count = {len(qids)}")
        index += 1
        time.sleep(SLEEP_AFTER_RESULT)


def write_to_wiki(wikitext) -> None:
    site = pwb.Site("wikidata", "wikidata")
    page = pwb.Page(site, PAGE_TITLE)
    page.text = wikitext
    page.save(summary="upd", minor=False)


def write_to_file(wikitext) -> None:
    with open(WIKI_FILE, "w") as outfile:
        outfile.write(wikitext)


if __name__ == "__main__":
    iterate()
    # write_to_wiki(make_wikitext())
