import requests
import json
import pywikibot as pwb
from datetime import datetime
import os.path


WD = 'http://www.wikidata.org/entity/'
WDQS_ENDPOINT = 'https://query.wikidata.org/sparql'
VIAF_ENDPOINT = 'https://viaf.org/viaf/search'

PID_VIAF_ID = 'P214'
PID_UNION_LIST_OF_ARTIST_NAMES_ID = 'P245'
PID_STATED_IN = 'P248'
PID_RETRIEVED = 'P813'
PID_REFERENCE_URL = 'P854'
PID_BASED_ON_HEURISTIC = 'P887'

QID_VIRTUAL_INTERNATIONAL_AUTHORITY_FILE = 'Q54919'
QID_INFERRED_FROM_VIAF_ID_CONTAINING_AN_ID_ALREADY_PRESENT_IN_THE_ITEM = 'Q115111315'

AUTHORITY_SOURCE_CODE_GETTY_RESEARCH_INSTITUTE = 'JPG'
AUTHORITY_SOURCE_CODE_WIKIDATA = 'WKP'

SITE = pwb.Site('wikidata', 'wikidata')
SITE.login()
SITE.get_tokens('csrf')
REPO = SITE.data_repository()

DUPLICATES_FILE = 'duplicates.json'
PAGE_TITLE = 'User:Difool/viaf_already_somewhere'
 

class AuthoritySource:
    pass

class GettyAuthoritySource(AuthoritySource):
    def getCode(self):
        return AUTHORITY_SOURCE_CODE_GETTY_RESEARCH_INSTITUTE
    
    def getPID(self):
        return PID_UNION_LIST_OF_ARTIST_NAMES_ID
    
    def getDescription(self):
        return 'Getty ULAN'

class ViafBot:

    def __init__(self, auth_src):
        self.auth_src = auth_src

    def run(self):
        self.duplicates = self.load_duplicates()
        self.iterate()
        self.write_to_wiki(self.make_wikitext())

    def query_wdqs(self, query):
        data = requests.get(WDQS_ENDPOINT, params={'query': query, 'format': 'json'}).json()
        return data['results']['bindings']


    def query_viaf(self, local_auth_id):
        try:
            url = 'https://viaf.org/viaf/sourceID/{code}|{local_auth_id}/justlinks.json'.format(code=self.auth_src.getCode(), local_auth_id=local_auth_id)
            data = requests.get(url).json()
            return data
        except:
            print('{desc} ID {local_auth_id} returns an error'.format(desc=self.auth_src.getDescription(), local_auth_id=local_auth_id))
            return []

    def check_viaf_justlinks(self, data, qid, local_auth_id):
        res = {}

        if 'viafID' not in data:
            return None

        viaf_id = data['viafID']
        res['viaf_id'] = viaf_id
        res['has_local_auth_id'] = False
        res['has_wikidata'] = False
        res['has_error'] = False

        code = self.auth_src.getCode()

        if code in data:
            if local_auth_id in data[code]:
                res['has_local_auth_id'] = True
            elif len(data[code]) > 0:
                print("viaf id {viaf_id} of {qid} has another {desc} link".format(viaf_id=viaf_id, qid=qid, desc=self.auth_src.getDescription()))
                res['has_error'] = True

            if len(data[code]) > 2:
                print("viaf id {viaf_id} of {qid} has multiple {desc} links".format(viaf_id=viaf_id, qid=qid, desc=self.auth_src.getDescription()))
                res['has_error'] = True
                    
        if AUTHORITY_SOURCE_CODE_WIKIDATA in data:
            if qid in data[AUTHORITY_SOURCE_CODE_WIKIDATA]:
                res['has_wikidata'] = True
            elif len(data[AUTHORITY_SOURCE_CODE_WIKIDATA]) > 0:
                print("viaf id {viaf_id} of {qid} has another wikidata link".format(viaf_id=viaf_id, qid=qid))
                res['has_error'] = True

            if len(data[AUTHORITY_SOURCE_CODE_WIKIDATA]) > 2:
                print("viaf id {viaf_id} of {qid} has multiple wikidata links".format(viaf_id=viaf_id, qid=qid))
                res['has_error'] = True
            
        return res

        
    def create_viaf_ref(self, viaf_id):
        today = datetime.today() 

        stated_in = pwb.Claim(REPO, PID_STATED_IN)  
        stated_in.setTarget(pwb.ItemPage(REPO, QID_VIRTUAL_INTERNATIONAL_AUTHORITY_FILE))

        id = pwb.Claim(REPO, PID_VIAF_ID)  
        id.setTarget(viaf_id)

        retr = pwb.Claim(REPO, PID_RETRIEVED) 
        dateCre = pwb.WbTime(year=int(today.strftime("%Y")), month=int(today.strftime("%m")), day=int(today.strftime("%d")))
        retr.setTarget(dateCre)  

        ref = pwb.Claim(REPO, PID_BASED_ON_HEURISTIC)  
        ref.setTarget(pwb.ItemPage(REPO, QID_INFERRED_FROM_VIAF_ID_CONTAINING_AN_ID_ALREADY_PRESENT_IN_THE_ITEM))

        return [stated_in, id, retr, ref]



    def change_wikidata(self, qid, viaf_id) -> None:
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
            item.addClaim(claim, summary="Adding VIAF ID based on {desc} ID".format(desc=self.auth_src.getDescription()))

            claim.addSources(self.create_viaf_ref(viaf_id), summary="Adding VIAF reference")

        except Exception as e:
            print("Error adding claims: %s" % e)

    def get_duplicates_qids(self, viaf_id):
        res = []
        query = 'SELECT DISTINCT ?item WHERE {{ ?item p:P214 ?statement0. ?statement0 (ps:P214) "{viaf_id}".}} LIMIT 5'.format(viaf_id=viaf_id)
        
        for row in self.query_wdqs(query):
            qid = row.get('item', {}).get('value', '').replace(WD, '')
            res.append(qid)
        return res


    def iterate_viaf(self, qid, local_auth_id) -> None:
        if qid in self.duplicates:
            return 

        res = self.check_viaf_justlinks(self.query_viaf(local_auth_id), qid, local_auth_id)
        if res is None:
            return
        
        viaf_id = res['viaf_id']
        has_local_auth_id = res['has_local_auth_id']
        has_error = res['has_error']

        if not has_local_auth_id:
            print('{qid} has no {desc} link'.format(qid=qid, desc=self.auth_src.getDescription()))
            return

        duplicate_qids = self.get_duplicates_qids(viaf_id)
        if duplicate_qids != []:
            print('{qid} has duplicates: {dupl}'.format(qid=qid, dupl=duplicate_qids))
            for duplicate_qid in duplicate_qids:
                if qid not in self.duplicates:
                    self.duplicates[qid] = []
                self.duplicates[qid].append(
                    {'duplicate_qid': duplicate_qid, 'auth_code': self.auth_src.getCode(), 'local_auth_id': local_auth_id, 'viaf_id': viaf_id}
                     )
            self.save_duplicates(self.duplicates)
        elif has_error:
            print('{qid} has errors, but no duplicates'.format(qid=qid))
        else:
            print('{qid} -> {viaf_id}; {desc} {local_auth_id}'.format(qid=qid, viaf_id=viaf_id, desc=self.auth_src.getDescription(), local_auth_id=local_auth_id))
            self.change_wikidata(qid, viaf_id)
            

    def make_wikitext(self):
        header = '{| class="wikitable" style="vertical-align:bottom;"\n|-\n! VIAF\n! QID on the item\n! ID from cluster\n! 2nd QID'
        body = ''
        line = '\n|-\n| https://viaf.org/viaf/{viaf_id}\n| {{{{Q|{qid}}}}}\n| {auth_code}|{local_auth_id}\n| {{{{Q|{duplicate_qid}}}}}'
        for qid in self.duplicates:
            for row in self.duplicates[qid]:
                duplicate_qid = row['duplicate_qid']
                auth_code = row['auth_code']
                local_auth_id = row['local_auth_id']
                viaf_id = row['viaf_id']
                body = body + line.format(viaf_id=viaf_id, qid=qid, auth_code=auth_code, local_auth_id=local_auth_id, duplicate_qid=duplicate_qid)
        footer = '\n|}'

        wikitext = f'{header}{body}{footer}'

        return wikitext
    
    def write_to_wiki(self, wikitext) -> None:
        #print(wikitext)
        site = pwb.Site('wikidata', 'wikidata')
        page = pwb.Page(site, PAGE_TITLE)
        page.text = wikitext
        page.save(summary='upd', minor=False)

    def iterate(self):
        # instance of (P31)
        # VIAF ID (P214)
        # Union List of Artist Names ID (P245)

        # humans with a Union List of Artist Names ID - not deprecated, without a VIAF ID
        query_template = """SELECT DISTINCT ?item ?local_auth_id WHERE {{
                                    ?item p:{pid} ?statement0.
                                    ?statement0 ps:{pid} _:anyValueP245;
                                        wikibase:rank ?rank.
                                    ?item p:P31 ?statement1.
                                    ?statement1 ps:P31 wd:Q5.
                                    FILTER(?rank != wikibase:DeprecatedRank)
                                    ?item wdt:{pid} ?local_auth_id.
                                    MINUS {{
                                        ?item p:P214 ?statement2.
                                        ?statement2 ps:P214 _:anyValueP214.
                                    }}
                                    }}
                                    """

        qry = query_template.format(pid=self.auth_src.getPID())
        for row in self.query_wdqs(qry):
            qid = row.get('item', {}).get('value', '').replace(WD, '')
            local_auth_id = row.get('local_auth_id', {}).get('value', '')
            if len(qid) == 0:
                continue
            if len(local_auth_id) == 0:
                continue
            self.iterate_viaf(qid, local_auth_id)

    def load_duplicates(self):
        if os.path.exists(DUPLICATES_FILE):
            with open(DUPLICATES_FILE, "r") as infile:
                duplicates = json.load(infile)
        else:
            duplicates = {}
        return duplicates

    def save_duplicates(self, duplicates):
        with open(DUPLICATES_FILE, "w") as outfile:
            json.dump(duplicates, outfile)

def main() -> None:

    bot = ViafBot(GettyAuthoritySource())
    bot.run()

if __name__=='__main__':
    main()

