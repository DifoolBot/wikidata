import requests
import json
from requests.utils import requote_uri
import pywikibot as pwb
from datetime import datetime
import re
import os.path
import authsource

WD = 'http://www.wikidata.org/entity/'
WDQS_ENDPOINT = 'https://query.wikidata.org/sparql'
REPORT_FILE = 'report.json'
PAGE_TITLE = 'User:Difool/viaf_counts'

SITE = pwb.Site('wikidata', 'wikidata')
SITE.login()
SITE.get_tokens('csrf')
REPO = SITE.data_repository()

REPORT_COUNT = 'count'
REPORT_NAME = 'name'
REPORT_QID = 'qid'
REPORT_LOCAL_AUTH_ID = 'local_auth_id'

WIKI_FILE = 'wiki.txt'
DONE_FILE = 'done.json'

def query_wdqs(query):
    try:
        data = requests.get(WDQS_ENDPOINT, params={
                            'query': query, 'format': 'json'}).json()
        return data['results']['bindings']
    except:
        return []


def get_count(pid, desc) -> str:
    if len(pid) == 0:
        return ''

    template = """SELECT (COUNT(*) AS ?count) WHERE {{
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
                                    }}"""

    qry = template.format(pid=pid)
    d = query_wdqs(qry)
    if d == []:
        return 'ERROR'

    for row in d:
        count = row.get('count', {}).get('value', '')
        print(f'{desc} ({pid}), {count}')
        return count

def get_sliced_count(pid, index, desc) -> int:
    if len(pid) == 0:
        return ''

    template = """SELECT (COUNT(DISTINCT ?item) AS ?count) WHERE {{

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
                    }}"""

    qry = template.format(index=index,pid=pid)
    d = query_wdqs(qry)
    if d == []:
        return None

    for row in d:
        count = int(row.get('count', {}).get('value', ''))
        return count



def check_count(report, pid: str, code: str, desc: str):
    if pid in report:
        return
    count = get_count(pid, desc)
    report[pid] = {'code': code, 'desc': desc, 'count': count}
    save_report(report)

def check_sliced_count(report, pid: str, code: str, desc: str):
    count = 0
    index = 0
    while True:
        print(index)
        sub_count = get_sliced_count(pid, index, desc)
        if sub_count == None:
            break
        count = count + sub_count
        index = index + 100000

    obj = report[pid]
    obj[REPORT_COUNT] = count
    report[pid] = obj
    save_report(report)

def get_name(report, pid: str, qid: str):
    query = """SELECT DISTINCT ?item ?itemLabel WHERE {{
                SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,de,fr,nl,ar,ru,pt,lv". }}
                {{
                    BIND(wd:{qid} AS ?item)
                }}
                }}"""
    qry = query.format(qid=qid)
    for row in query_wdqs(qry):
        lbl = row.get('itemLabel', {}).get('value', '')
        obj = report[pid]
        obj[REPORT_NAME] = lbl
        report[pid] = obj
        save_report(report)


def get_example(report, pid: str):
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
                            }} LIMIT 1
                            """

    qry = query_template.format(pid=pid)
    for row in query_wdqs(qry):
        qid = row.get('item', {}).get('value', '').replace(WD, '')
        local_auth_id = row.get('local_auth_id', {}).get('value', '')
        obj = report[pid]
        obj[REPORT_QID] = qid
        obj[REPORT_LOCAL_AUTH_ID] = local_auth_id
        report[pid] = obj
        save_report(report)


def check(report, pid: str, code: str, desc: str):
    if len(pid) == 0:
        return
    if pid not in report:
        check_count(report, pid, code, desc)
    if pid not in report:
        return
    if REPORT_COUNT in report[pid]:
        if report[pid][REPORT_COUNT] == 'ERROR':
            check_sliced_count(report, pid, code, desc)
    if REPORT_QID not in report[pid]:
        get_example(report, pid)
    if REPORT_QID in report[pid]:
        if REPORT_NAME not in report[pid]:
            get_name(report, pid, report[pid][REPORT_QID])
    save_report(report)


def load_report():
    if os.path.exists(REPORT_FILE):
        with open(REPORT_FILE, "r") as infile:
            report = json.load(infile)
    else:
        report = {}
    return report


def save_report(report):
    with open(REPORT_FILE, "w") as outfile:
        json.dump(report, outfile)


def check_all(report):
    authsrcs = authsource.AuthoritySources()
    for pid in authsrcs.dict:
        src = authsrcs.get(pid)
        check(report, pid, src.codes[0], src.description)

    return

    # return

    # getest met Montgommary Q152025
    # Vatican Library VcBA ID (P8034)
    # "BAV": [
    #     "495/224267"
    # ],
    # https://viaf.org/viaf/sourceID/BAV|495_224267/justlinks.json OK
    check(report, 'P8034', 'BAV', 'Biblioteca Apostolica Vaticana')
    # BIBSYS work ID (P6211)
    # "BIBSYS": ["90642693"]
    # https://viaf.org/viaf/sourceID/BIBSYS|90642693/justlinks.json OK
    check(report, 'P1015', 'BIBSYS', 'BIBSYS')
    # National Library of Brazil ID (P4619)
    # "BLBNB": [
    #     "000299413"
    # ],
    # https://viaf.org/viaf/sourceID/BLBNB|000299413/justlinks.json OK
    check(report, 'P4619', 'BLBNB', 'National Library of Brazil')
    # CANTIC ID (P9984)
    # "BNC": [
    #     "981058581298206706"
    # ],
    # https://viaf.org/viaf/sourceID/BNC|981058581298206706/justlinks.json OK
    check(report, 'P9984', 'BNC', 'National Library of Catalonia')
    # National Library of Chile ID (P7369)
    #  "BNCHL": [
    #     "BNC10000000000000000091878"
    # ],
    # 000091878
    # https://viaf.org/viaf/sourceID/BNCHL|0000000000000000091878/justlinks.json NOT FOUND
    check(report, 'P9984', 'BNCHL', 'National Library of Chile')
    # Biblioteca Nacional de España ID (P950)
    # "BNE": ["XX1260576"]
    # https://viaf.org/viaf/sourceID/BNE|XX1260576/justlinks.json OK
    check(report, 'P950', 'BNE', 'Biblioteca Nacional de España')
    # Bibliothèque nationale de France ID (P268)
    # "BNF": ["http://catalogue.bnf.fr/ark:/12148/cb12898033k"
    # https://viaf.org/viaf/sourceID/BNF|http://catalogue.bnf.fr/ark:/12148/cb12898033k/justlinks.json
    # https://viaf.org/viaf/sourceID/BNF|FRBNF124390022/justlinks.json
    # FRBNF124390022
    # not working
    # "BNF": [
    #     "http://catalogue.bnf.fr/ark:/12148/cb12898033k"
    # ],
    check(report, 'P268', 'BNF', 'Bibliothèque Nationale de France')
    # not listed
    check(report, '', 'BNL', 'National Library of Luxembourg')
    # BAnQ authority ID (P3280)
    # "B2Q": [
    #     "0000028540"
    # ],
    # https://viaf.org/viaf/sourceID/B2Q|0000028540/justlinks.json OK
    check(report, 'P3280', 'B2Q', 'National Library and Archives of Quèbec')
    # NCL ID (P1048) - 000004528
    #     "CYT": [
    #     "AC000004528"
    # ],
    # https://viaf.org/viaf/sourceID/CYT|000004528/justlinks.json NOT FOUND
    # https://viaf.org/viaf/sourceID/CYT|AC000004528/justlinks.json OK
    check(report, 'P1048', 'CYT', 'National Central Library, Taiwan')
    # DBC author ID (P3846)
    # "DBC": [
    #     "870979.68718872"
    # ],
    # zonder punt?
    # https://viaf.org/viaf/sourceID/DBC|870979.68718872/justlinks.json NOT FOUND
    # https://viaf.org/viaf/sourceID/DBC|87097968718872/justlinks.json OK
    check(report, 'P3846', 'DBC', 'DBC (Danish Bibliographic Center)')
    # GND ID (P227)
    # "DNB": [
    #     "http://d-nb.info/gnd/118602152"
    # ],
    # https://viaf.org/viaf/sourceID/DNB|118602152/justlinks.json OK
    # te lang
    # check(report, 'P227', 'DNB', 'Deutsche Nationalbibliothek')
    # EGAXA ID (P1309)
    # "EGAXA": [
    #     "vtls000902186"
    # ],
    # https://viaf.org/viaf/sourceID/EGAXA|vtls000902186/justlinks.json OK
    check(report, 'P1309', 'EGAXA', 'Bibliotheca Alexandrina (Egypt)')
    # ELNET ID (P6394)
    #  "ERRR": [
    #     "a1152361x"
    # ],
    # https://viaf.org/viaf/sourceID/ERRR|a1152361x/justlinks.json OK
    check(report, 'P6394', 'ERRR', 'National Library of Estonia')
    # SBN author ID (P396) - CFIV003068
    # "ICCU": [
    #     "IT\\ICCU\\CFIV\\003068"
    # ],
    # https://viaf.org/viaf/sourceID/ICCU|CFIV003068/justlinks.json OK
    check(report, 'P396', 'ICCU', 'Istituto Centrale per il Catalogo Unico')
    # ISNI (P213)
    # "ISNI": [
    #     "0000000108869032"
    # ],
    # https://viaf.org/viaf/sourceID/ISNI|0000000108869032/justlinks.json OK
    check(report, 'P213', 'ISNI', 'ISNI')
    # Union List of Artist Names ID (P245)
    # "JPG": [
    #     "500048070"
    # ],
    check(report, 'P245', 'JPG', 'Getty Research Institute')
    # National Library of Korea ID (P5034) - KAC199611832
    # "KRNLK": [
    #     "KAC199611832"
    # ],
    # https://viaf.org/viaf/sourceID/KRNLK|KAC199611832/justlinks.json OK
    check(report, 'P5034', 'KRNLK', 'National Library of Korea')
    # Library of Congress authority ID (P244)
    # "LC": [
    #     "n50048042"
    # ],
    # https://viaf.org/viaf/sourceID/LC|n50048042/justlinks.json OK
    check(report, 'P244', 'LC', 'Library of Congress/NACO')
    # obsolete
    check(report, '', 'LAC', 'Library and Archives Canada')
    # "LNB": [
    #     "LNC10-000005272",
    #     "LNB:0sB;=BL"
    # ],
    # https://viaf.org/viaf/sourceID/LNB|000005272/justlinks.json NOT FOUND
    # https://viaf.org/viaf/sourceID/LNB|0sB;=BL/justlinks.json NOT FOUND
    check(report, '', 'LNB', 'National Library of Latvia')
    # Lebanese National Library ID (P7026)
    # "LNL": [
    #     "48405"
    # ],
    # https://viaf.org/viaf/sourceID/LNL|48405/justlinks.json OK
    check(report, 'P7026', 'LNL', 'Lebanese National Library')
    # BNRM ID (P7058)
    # "MRBNR": [
    #     "vtls000967769"
    # ],
    # https://viaf.org/viaf/sourceID/MRBNR|vtls000967769/justlinks.json OK
    check(report, 'P7058', 'MRBNR', 'National Library of Morocco')
    # NDL Authority ID (P349) - 00442747
    # "NDL": [
    #     "00442747"
    # ],
    # https://viaf.org/viaf/sourceID/NDL|00442747/justlinks.json OK
    check(report, 'P349', 'NDL', 'National Diet Library, Japan')
    # CiNii Books author ID (P271)
    # "NII": [
    #     "DA00543731"
    # ],
    # https://viaf.org/viaf/sourceID/NII|DA00543731/justlinks.json OK
    check(report, 'P271', 'NII', 'National Institute of Informatics (Japan)')
    # NL CR AUT ID (P691)
    # "NKC": [
    #     "jn19990007110"
    # ],
    # https://viaf.org/viaf/sourceID/NKC|jn19990007110/justlinks.json OK
    check(report, 'P691', 'NKC', 'National Library of the Czech Republic')
    # Libraries Australia ID (P409)
    # "NLA": [
    #     "000035459667"
    # ],
    # 35459667 !! nul
    # https://viaf.org/viaf/sourceID/NLA|35459667/justlinks.json ERROR
    # https://viaf.org/viaf/sourceID/NLA|000035459667/justlinks.json OK
    check(report, 'P409', 'NLA', 'National Library of Australia')
    # National Library Board Singapore ID (P3988)
    check(report, '', 'NLB', 'National Library Board, Singapore')
    check(report, '', 'NLI', 'National Library of Israel')
    check(report, '', 'NLIara', 'National Library of Israel (Arabic)')
    check(report, '', 'NLIcyr', 'National Library of Israel (Cyrillic)')
    check(report, '', 'NLIheb', 'National Library of Israel (Hebrew)')
    check(report, '', 'NLIlat', 'National Library of Israel (Latin)')
    check(report, '', 'NLP', 'National Library of Poland')
    # National Library of Russia ID (P7029)
    # "NLR": [
    #     "RU\\NLR\\AUTH\\7721773",
    #     "RU\\NLR\\AUTH\\770241423"
    # ],
    # https://viaf.org/viaf/sourceID/NLR|7721773/justlinks.json NOT FOUND
    # https://viaf.org/viaf/sourceID/NLR|770241423/justlinks.json NOT FOUND
    check(report, 'P7029', 'NLR', 'National Library of Russia')
    # NSK ID (P1375) - 000010853
    # "NSK": [
    #     "000010853"
    # ],
    # https://viaf.org/viaf/sourceID/NSK|000010853/justlinks.json OK
    check(report, 'P1375', 'NSK', 'National and University Library in Zagreb')
    # NSZL (VIAF) ID (P951)
    check(report, '', 'NSZL', 'National Szèchènyi Library, Hungary')
    # Nationale Thesaurus voor Auteursnamen ID (P1006)
    # "NTA": [
    #     "070012393"
    # ],
    # https://viaf.org/viaf/sourceID/NTA|070012393/justlinks.json OK
    check(report, 'P1006', 'NTA', 'National Library of the Netherlands')
    # NUKAT ID (P1207)
    # "NUKAT": [
    #     "vtls000542741"
    # ],
    # https://viaf.org/viaf/sourceID/NUKAT|vtls000542741/justlinks.json NOT FOUND
    check(report, '', 'NUKAT', 'NUKAT Center of Warsaw University Library')
    # PLWABN ID (P7293)
    check(report, 'P7293', 'PLWABN', 'National Library of Poland')
    # National Library of Ireland ID (P10227)
    # "N6I": [
    #     "vtls000028406"
    # ],
    # https://viaf.org/viaf/sourceID/N6I|vtls000028406/justlinks.json OK
    check(report, 'P10227', 'N6I', 'National Library of Ireland')
    # Non-Contributor VIAF source
    check(report, '', 'PERSEUS', 'PERSEUS')
    # Portuguese National Library author ID (P1005)
    # "PTBNP": [
    #     "1178908"
    # ],
    # https://viaf.org/viaf/sourceID/PTBNP|1178908/justlinks.json OK
    check(report, 'P1005', 'PTBNP', 'Biblioteca Nacional de Portugal')
    # obsolete
    # "RERO": [
    #     "A003755868"
    # ],
    # https://viaf.org/viaf/sourceID/RERO|A003755868/justlinks.json OK
    check(report, '', 'RERO', 'RERO.Library Network of Western Switzerland')
    # Libris-URI (P5587)
    # "SELIBR": [
    #     "64jmq9fq21x1w63"
    # ],
    # https://viaf.org/viaf/sourceID/SELIBR|64jmq9fq21x1w63/justlinks.json NOT FOUND
    check(report, 'P5587', 'SELIBR', 'National Library of Sweden')
    check(report, '', 'SRP', 'Syriac Reference Portal')
    # IdRef ID (P269)
    # "SUDOC": [
    #     "066890063"
    # ],
    # https://viaf.org/viaf/sourceID/SUDOC|066890063/justlinks.json OK
    check(report, 'P269', 'SUDOC', 'Sudoc [ABES], France')
    # HelveticArchives ID (P1255)
    check(report, '', 'SWNL', 'Swiss National Library')
    # National Library of Iceland ID (P7039)
    check(report, 'P7039', 'UIY',
          'National and University Library of Iceland (NULI)')
    # Flemish Public Libraries ID (P7024)
    check(report, '', 'VLACC', 'Flemish Public Libraries')
    check(report, '', 'WKP', 'Wikidata')
    check(report, '', 'W2Z', 'National Library of Norway')
    check(report, '', 'X', '')
    check(report, '', 'xA', '(eXtended Authorities)')
    check(report, '', 'XR', 'xR (eXtended Relationships)')
    # FAST ID (P2163)
    check(report, 'P2163', 'FAST', 'FAST')


def make_wikitext(report, done):
    header = '{| class="wikitable sortable" style="vertical-align:bottom;"\n|-\n! PID\n! Code\n! Count\n! Example\n! ID\n! URL\n! Last done'
    body = ''
    line = '\n|-\n| {{{{P|{pid}}}}}\n| {code}\n| {count}\n| {qid}\n| {id}\n| {urls}\n| {last_done}'
    for pid in report:
        code = report[pid]['code']
        # desc = report[pid]['desc']
        count = report[pid][REPORT_COUNT]
        if count == 'ERROR':
            count = 'time-out'

        if REPORT_QID in report[pid]:
            if REPORT_NAME in report[pid]:
                name = report[pid][REPORT_NAME]
            else:
                name = ''
            # name = 'onbekend'
            qid = report[pid][REPORT_QID]
            qid = '{{{{Q|{qid}}}}}'.format(qid=qid)
            local_auth_id = report[pid][REPORT_LOCAL_AUTH_ID]
            s = authsource.AuthoritySources().get(pid)
            aid = authsource.AuthorityID(qid, local_auth_id)
            try:
                s.determine_search_code(aid)
            except:
                aid.search_code = local_auth_id
            
            # local_auth_id = report[pid][REPORT_LOCAL_AUTH_ID]
            # local_auth_id = local_auth_id.replace(' ', '')
            # local_auth_id = local_auth_id.replace('.', '')
            # local_auth_id = local_auth_id.replace('/', '_')
            url1 = 'https://viaf.org/viaf/sourceID/{code}&#124;{local_auth_id} viaf'.format(
                code=code, local_auth_id=aid.search_code
            )
            url2 = 'https://viaf.org/viaf/sourceID/{code}&#124;{local_auth_id}/justlinks.json justlinks'.format(
                code=code, local_auth_id=aid.search_code
            )
            qry = 'local.personalNames all "{name}" and local.sources any "{code}"'.format(
                name=name, code=code.lower()
            )
            url3 = requote_uri(
                'https://viaf.org/viaf/search?query={qry}'.format(qry=qry))
            url3 = url3 + ' name'
            urls = '[{url1}] [{url2}] [{url3}]'.format(url1=url1, url2=url2,url3=url3)
        else:
            qid = ''
            local_auth_id = ''
            urls=''

        if pid in done:
            last_done = done[pid] 
        else:
            last_done = ''

        body = body + line.format(
            pid=pid, code=code, id=local_auth_id,
            count=count, qid=qid, urls=urls, last_done=last_done
        )
    footer = '\n|}'

    wikitext = f'{header}{body}{footer}'

    return wikitext


def write_to_wiki(wikitext) -> None:
    #with open(WIKI_FILE, "w") as outfile:
    #   outfile.write(wikitext)
    #return
    site = pwb.Site('wikidata', 'wikidata')
    page = pwb.Page(site, PAGE_TITLE)
    page.text = wikitext
    page.save(summary='upd', minor=False)


def main() -> None:
    report = load_report()
    #check(report, 'P213', 'ISNI', 'ISNI')
    check_all(report)

    if os.path.exists(DONE_FILE):
        with open(DONE_FILE, "r") as infile:
            done = json.load(infile)
    else:
        done = {}

    write_to_wiki(make_wikitext(report, done))
    save_report(report)


if __name__ == '__main__':
    main()
