import requests
import json
from requests.utils import requote_uri
import pywikibot as pwb
from datetime import datetime
import re


WD = 'http://www.wikidata.org/entity/'
WDQS_ENDPOINT = 'https://query.wikidata.org/sparql'
VIAF_ENDPOINT = 'https://viaf.org/viaf/search'

PID_VIAF_ID = 'P214'
PID_UNION_LIST_OF_ARTIST_NAMES_ID = 'P245'
PID_STATED_IN = 'P248'
PID_RETRIEVED = 'P813'
PID_REFERENCE_URL = 'P854'
QID_VIRTUAL_INTERNATIONAL_AUTHORITY_FILE = 'Q54919'

SITE = pwb.Site('wikidata', 'wikidata')
SITE.login()
SITE.get_tokens('csrf')
REPO = SITE.data_repository()


def query_wdqs(query):
    data = requests.get(WDQS_ENDPOINT, params={'query': query, 'format': 'json'}).json()
    return data['results']['bindings']


def query_viaf(name):
    query = 'local.personalNames all "{name}" and local.sources any "jpg"'.format(name = name)
    data = requests.get(VIAF_ENDPOINT, params={'query': query, 'httpAccept': 'application/json'}).json()
    return data['searchRetrieveResponse']['records']


def check_viaf_record(record, getty_id, qid):
    res = {}
    record_data = record['record']['recordData']

    res['viaf_id'] = record_data['viafID']
    res['has_getty'] = False
    res['has_wikidata'] = False

    source = record_data['sources']['source']

    if isinstance(source, dict):
        source = [source]
    for s in source:
        id = s['@nsid']
        text = s['#text']
        if text.startswith('JPG|'):
            if getty_id != id:
                return None
            else:
                res['has_getty'] = True
        elif text.startswith('WKP|'):
            if qid != id:
                return None
            else:
                res['has_wikidata'] = True
    return res

    
def create_viaf_ref(viaf_id):
    today = datetime.today() 
    viaf_url = "https://viaf.org/viaf/{viaf}/".format(viaf = viaf_id)

    stated_in = pwb.Claim(REPO, PID_STATED_IN)  
    stated_in.setTarget(pwb.ItemPage(REPO, QID_VIRTUAL_INTERNATIONAL_AUTHORITY_FILE))
    id = pwb.Claim(REPO, PID_VIAF_ID)  
    id.setTarget(viaf_id)
    retr = pwb.Claim(REPO, PID_RETRIEVED) 
    dateCre = pwb.WbTime(year=int(today.strftime("%Y")), month=int(today.strftime("%m")), day=int(today.strftime("%d")))
    retr.setTarget(dateCre)  
    ref = pwb.Claim(REPO, PID_REFERENCE_URL)  
    ref.setTarget(viaf_url)

    return [stated_in, id, retr, ref]


def is_viaf_source(src, viaf_id) -> bool:
    if PID_VIAF_ID in src:
        for claim in src[PID_VIAF_ID]:
            if (claim.getTarget() == viaf_id):
                return True

    regex = r"https?:\/\/viaf.org\/viaf\/{viaf_id}\/?".format(viaf_id=viaf_id)

    if PID_REFERENCE_URL in src:
        for claim in src[PID_REFERENCE_URL]:
            url = claim.getTarget()
            matches = re.search(regex, url, re.IGNORECASE)
            if matches:
                return True

    return False


def has_viaf_source(claim, viaf_id) -> bool:
    srcs = claim.getSources() 
    for src in srcs: 
        if is_viaf_source(src, viaf_id):
            return True

    return False


def change_wikidata(qid, viaf_id, getty_id, has_wikidata) -> None:
    if not qid.startswith('Q'):  # ignore property pages and lexeme pages
        return

    item = pwb.ItemPage(REPO, qid)

    if not item.exists():
        return

    if item.isRedirectPage():
        return

    existing_claims = item.get().get("claims")

    if not item.botMayEdit():
        print("Skipping %s because it cannot be edited by bots" % qid)
        return

    if PID_VIAF_ID in existing_claims:
        print("Skipping %s because it already has a VIAF ID" % qid)
        return

    print('Adding VIAF ID {viaf_id} to {qid}'.format(viaf_id=viaf_id, qid=qid))
    try:
        claim = pwb.Claim(REPO, PID_VIAF_ID)
        claim.setTarget(viaf_id)
        item.addClaim(claim, summary="Adding VIAF ID based on Union List of Artist Names ID")

        if has_wikidata:
            claim.addSources(create_viaf_ref(viaf_id), summary="Adding VIAF reference")

        if PID_UNION_LIST_OF_ARTIST_NAMES_ID in existing_claims:
            for claim in existing_claims[PID_UNION_LIST_OF_ARTIST_NAMES_ID]:
                if claim.getTarget() != getty_id:
                    continue
                
                if has_viaf_source(claim, viaf_id):
                    continue

                claim.addSources(create_viaf_ref(viaf_id), summary="Adding VIAF reference")
                break

    except Exception as e:
        print("Error adding claims: %s" % e)


def iterate_viaf(qid, name, getty_id) -> None:
    for record in query_viaf(name):
        res = check_viaf_record(record, getty_id, qid)
        if res is not None:
            viaf_id = res['viaf_id']
            has_getty = res['has_getty']
            has_wikidata = res['has_wikidata']
            if has_getty:
                change_wikidata(qid, viaf_id, getty_id, has_wikidata)


def main() -> None:
    # instance of (P31)
    # VIAF ID (P214)
    # Union List of Artist Names ID (P245)
    # ECARTICO person ID (P2915)

    # humans with an ECARTICO person ID and a Union List of Artist Names ID, 
    #  without a VIAF ID
    query_template = """SELECT DISTINCT ?item ?itemLabel ?Union_List_of_Artist_Names_ID WHERE {
        SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
        {
            SELECT DISTINCT ?item ?Union_List_of_Artist_Names_ID WHERE {
            ?item p:P2915 ?statement0.
            ?statement0 ps:P2915 _:anyValueP2915.
            ?item p:P31 ?statement1.
            ?statement1 ps:P31 wd:Q5.
            ?item p:P245 ?statement2.
            ?statement2 ps:P245 _:anyValueP245.
            ?item wdt:P245 ?Union_List_of_Artist_Names_ID.
            MINUS {
                ?item p:P214 ?statement3.
                ?statement3 ps:P214 _:anyValueP214.
            }
            }
            LIMIT 2
        }
        }"""

    for row in query_wdqs(query_template):
        qid = row.get('item', {}).get('value', '').replace(WD, '')
        name = row.get('itemLabel', {}).get('value', '')
        getty_id = row.get('Union_List_of_Artist_Names_ID', {}).get('value', '')
        if len(qid) == 0:
            continue
        if len(name) == 0:
            continue
        if len(getty_id) == 0:
            continue
        iterate_viaf(qid, name, getty_id)


if __name__=='__main__':
    main()

