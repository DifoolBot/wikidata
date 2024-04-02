import requests
import re

PID_BANQ_AUTHORITY_ID = "P3280"
PID_BIBLIOTECA_NACIONAL_DE_ESPANA_ID = "P950"
PID_BIBLIOTHEQUE_NATIONALE_DE_FRANCE_ID = "P268"
PID_BNMM_AUTHORITY_ID = "P3788"
PID_BNRM_ID = "P7058"
PID_CANADIANA_NAME_AUTHORITY_ID = "P8179"
PID_CANTIC_ID = "P9984"
PID_CINII_BOOKS_AUTHOR_ID = "P271"
PID_CONOR_SI_ID = "P1280"
PID_CYT_CCS = "P10307"
PID_DBC_AUTHOR_ID = "P3846"
PID_EGAXA_ID = "P1309"
PID_ELNET_ID = "P6394"
PID_FAST_ID = "P2163"
PID_FLEMISH_PUBLIC_LIBRARIES_ID = "P7024"
PID_GND_ID = "P227"
PID_IDREF_ID = "P269"
PID_ISNI = "P213"
PID_LEBANESE_NATIONAL_LIBRARY_ID = "P7026"
PID_LIBRARIES_AUSTRALIA_ID = "P409"
PID_LIBRARY_OF_CONGRESS_AUTHORITY_ID = "P244"
PID_LIBRIS_URI = "P5587"
PID_NATIONALE_THESAURUS_VOOR_AUTEURSNAMEN_ID = "P1006"
PID_NATIONAL_LIBRARY_BOARD_SINGAPORE_ID = "P3988"
PID_NATIONAL_LIBRARY_OF_BRAZIL_ID = "P4619"
PID_NATIONAL_LIBRARY_OF_CHILE_ID = "P7369"
PID_NATIONAL_LIBRARY_OF_GREECE_ID = "P3348"
PID_NATIONAL_LIBRARY_OF_ICELAND_ID = "P7039"
PID_NATIONAL_LIBRARY_OF_IRELAND_ID = "P10227"
PID_NATIONAL_LIBRARY_OF_ISRAEL_J9U_ID = "P8189"
PID_NATIONAL_LIBRARY_OF_KOREA_ID = "P5034"
PID_NATIONAL_LIBRARY_OF_LATVIA_ID = "P1368"
PID_NATIONAL_LIBRARY_OF_LITHUANIA_ID = "P7699"
PID_NATIONAL_LIBRARY_OF_LUXEMBOURG_ID = "P7028"
PID_NATIONAL_LIBRARY_OF_RUSSIA_ID = "P7029"
PID_NDL_AUTHORITY_ID = "P349"
PID_NL_CR_AUT_ID = "P691"
PID_NORAF_ID = "P1015"
PID_NSK_ID = "P1375"
PID_NSZL_NAME_AUTHORITY_ID = "P3133"
PID_NSZL_VIAF_ID = "P951"
PID_NUKAT_ID = "P1207"
PID_PERSEUS_AUTHOR_ID = "P7041"
PID_PLWABN_ID = "P7293"
PID_PORTUGUESE_NATIONAL_LIBRARY_AUTHOR_ID = "P1005"
PID_RERO_ID_OBSOLETE = "P3065"
PID_RILM_ID = "P9171"
PID_RISM_ID = "P5504"
PID_SBN_AUTHOR_ID = "P396"
PID_SLOVAK_NATIONAL_LIBRARY_VIAF_ID = "P7700"
PID_SYRIAC_BIOGRAPHICAL_DICTIONARY_ID = "P6934"
PID_UAE_UNIVERSITY_LIBRARIES_ID = "P10021"
PID_UNION_LIST_OF_ARTIST_NAMES_ID = "P245"
PID_VATICAN_LIBRARY_VCBA_ID = "P8034"


class AuthorityID:
    def __init__(self, qid: str, id_from_wikidata: str):
        self.qid = qid
        self.id_from_wikidata = id_from_wikidata
        self.viaf_id = None
        self.search_code = None
        self.other_code = None


def default_is_same_id(id_from_viaf: str, aid: AuthorityID) -> bool:
    return id_from_viaf.replace(" ", "").replace(".", "") == aid.id_from_wikidata.replace(" ", "").replace(".", "")


def searchcode_is_same_id(id_from_viaf: str, aid: AuthorityID) -> bool:
    return id_from_viaf == aid.search_code


def gnd_is_same_id(id_from_viaf: str, aid: AuthorityID) -> bool:
    # http://d-nb.info/gnd/171910605 vs 171910605
    id_from_viaf = id_from_viaf.replace('http://d-nb.info/gnd/', '')
    return id_from_viaf == aid.id_from_wikidata


def sbn_is_same_id(id_from_viaf: str, aid: AuthorityID) -> bool:
    # IT\\ICCU\\SBLV\\015759 vs SBLV015759
    id_from_viaf = id_from_viaf.replace('IT\\ICCU', '').replace('\\', '')
    return id_from_viaf == aid.id_from_wikidata


def nla_determine_search_code(aid: AuthorityID):
    # 35585588 -> 000035585588
    #             123456789012
    res = "000000000000" + aid.id_from_wikidata
    res = res[-12:]
    aid.search_code = res


def rism_determine_search_code(aid: AuthorityID):
    aid.search_code = aid.id_from_wikidata.replace(
        'people', 'pe').replace('_', '').replace('/', '')


def rero_determine_search_code(aid: AuthorityID):
    aid.search_code = aid.id_from_wikidata.replace(
        '02-', '').replace('02_', '')


def perseus_determine_search_code(aid: AuthorityID):
    # urn:cite:perseus:author.384.1
    aid.search_code = 'urn:cite:perseus:author.' + aid.id_from_wikidata


def srp_determine_search_code(aid: AuthorityID):
    aid.search_code = 'person_' + aid.id_from_wikidata


def nlr_determine_search_code(aid: AuthorityID):
    aid.search_code = 'RU NLR AUTH ' + aid.id_from_wikidata


def nlr_is_same_id(id_from_viaf: str, aid: AuthorityID) -> bool:
    id_from_viaf = id_from_viaf.replace('RU\\NLR\\AUTH\\', '')
    return id_from_viaf == aid.id_from_wikidata


def generate_bnf_ark_from_8digits(orig_id):
    bnf_xdigits = '0123456789bcdfghjkmnpqrstvwxz'
    bnf_check_digit = 0

    id = 'cb' + orig_id
    for i in range(len(id)):
        bnf_check_digit += bnf_xdigits.index(id[i]) * (i+1)
    # 29 is the radix
    return id + bnf_xdigits[bnf_check_digit % len(bnf_xdigits)]


def bnf_determine_search_code(aid: AuthorityID):
    # remove checksum
    sc = aid.id_from_wikidata[:-1]
    bnf_ark = generate_bnf_ark_from_8digits(sc)
    if bnf_ark == 'cb' + aid.id_from_wikidata:
        aid.search_code = sc
    else:
        aid.search_code = aid.id_from_wikidata


def bnf_is_same_id(id_from_viaf: str, aid: AuthorityID) -> bool:
    if id_from_viaf.startswith('FRBNF'):
        id_from_viaf = id_from_viaf[5:]
        # remove possible incorrect checksum
        if len(id_from_viaf) == 9:
            id_from_viaf = id_from_viaf[:-1]
        return id_from_viaf == aid.search_code
    else:
        # http://catalogue.bnf.fr/ark:/12148/cb14480351s
        id_from_viaf = id_from_viaf.replace(
            'http://catalogue.bnf.fr/ark:/12148/', '')
        bnf_ark = generate_bnf_ark_from_8digits(aid.search_code)
        return id_from_viaf == bnf_ark


def lnb_determine_search_code(aid: AuthorityID):
    # 000011784 -> LNC10-000011784
    #
    aid.search_code = "LNC10-" + aid.id_from_wikidata
    # todo; nakijken ; deze kan ook een LNB: link hebben


def lnb_is_same_id(id_from_viaf: str, aid: AuthorityID) -> bool:
    return id_from_viaf == aid.search_code

def bnchl_determine_search_code(aid: AuthorityID):
    # 10000000000000000823902
    # 12345678901234567890123
    res = ("0" * 22) + aid.id_from_wikidata
    res = '1' + res[-22:]
    aid.search_code = res


def bnchl_is_same_id(id_from_viaf: str, aid: AuthorityID) -> bool:
    return id_from_viaf == 'BNC' + aid.search_code

def query_selibr(aid: AuthorityID):
    url = "https://libris.kb.se/{code}/data.json".format(
        code=aid.id_from_wikidata
    )
    response = requests.get(url, timeout=20)
    payload = response.json()
    return payload['controlNumber']


def query_nukat(aid: AuthorityID):
    # test: http://katalog.nukat.edu.pl/lib/authority?lccn=n%20%2001041400
    #       http://katalog.nukat.edu.pl/lib/authority?lccn=n 01041400
    if aid.id_from_wikidata.startswith('n'):
        ncode = 'n ' + aid.id_from_wikidata[1:]
    else:
        return None
    url = "http://katalog.nukat.edu.pl/lib/authority?lccn={ncode}".format(
        ncode=ncode
    )
    response = requests.get(url, timeout=20)
    regex = r'\<tr\>\s*<td width="10">001<\/td>.*?<td class="tagdata">(.*?)<\/td>'
    matches = re.search(regex, response.text, re.MULTILINE | re.DOTALL)
    if matches:
        return matches.group(1)
    else:
        return None


def selibr_determine_search_code(aid: AuthorityID):
    aid.search_code = query_selibr(aid)


def nukat_determine_search_code(aid: AuthorityID):
    aid.other_code = query_nukat(aid)
    if aid.other_code is None:
        aid.search_code = None
    elif aid.id_from_wikidata.startswith('n'):
        aid.search_code = 'n ' + aid.id_from_wikidata[1:]


def nukat_is_same_id(id_from_viaf: str, aid: AuthorityID) -> bool:
    return (id_from_viaf.replace(' ', '') == aid.id_from_wikidata) or (id_from_viaf == aid.other_code)


class AuthoritySource:
    def __init__(self, pid: str, code: str, description: str, is_same_id_func, determine_search_code_func):
        self.pid = pid
        self.codes = [code]
        self.description = description
        self.is_same_id_func = is_same_id_func
        self.determine_search_code_func = determine_search_code_func

    def is_same_id(self, id_from_viaf: str, aid: AuthorityID):
        if default_is_same_id(id_from_viaf, aid):
            return True

        if self.is_same_id_func is not None:
            if self.is_same_id_func(id_from_viaf, aid):
                return True

        return False

    def determine_search_code(self, aid: AuthorityID):
        aid.search_code = aid.id_from_wikidata.replace(
            ' ', '').replace('.', '').replace('/', '_')

        if self.determine_search_code_func is not None:
            self.determine_search_code_func(aid)


class AuthoritySources:
    def __init__(self):

        self.dict = {}
        self.add(PID_BNMM_AUTHORITY_ID, "ARBABN", "BNMM authority ID")
        self.add(PID_BANQ_AUTHORITY_ID, "B2Q", "BAnQ authority ID")
        self.add(PID_VATICAN_LIBRARY_VCBA_ID, "BAV", "Vatican Library VcBA ID")
        self.add(PID_NORAF_ID, "BIBSYS", "NORAF ID")
        self.add(PID_NATIONAL_LIBRARY_OF_BRAZIL_ID,
                 "BLBNB", "National Library of Brazil ID")
        self.add(PID_CANTIC_ID, "BNC", "CANTIC ID")
        self.add(PID_NATIONAL_LIBRARY_OF_CHILE_ID,
                 "BNCHL", "National Library of Chile ID", bnchl_is_same_id, bnchl_determine_search_code)
        self.add(PID_BIBLIOTECA_NACIONAL_DE_ESPANA_ID,
                 "BNE", "Biblioteca Nacional de España ID")
        self.add(PID_BIBLIOTHEQUE_NATIONALE_DE_FRANCE_ID, "BNF",
                 "Bibliothèque nationale de France ID", bnf_is_same_id, bnf_determine_search_code)
        self.add(PID_NATIONAL_LIBRARY_OF_LUXEMBOURG_ID,
                 "BNL", "National Library of Luxembourg ID")
        self.add(PID_CANADIANA_NAME_AUTHORITY_ID,
                 "CAOONL", "Canadiana Name Authority ID")
        self.add(PID_CYT_CCS, "CYT", "CYT/CCS")  # 2 varianten
        self.add(PID_DBC_AUTHOR_ID, "DBC", "DBC author ID")
        self.add(PID_RISM_ID, "DE633", "RISM ID",
                 searchcode_is_same_id, rism_determine_search_code)
        self.add(PID_RISM_ID, "DE663", "RISM ID")
        self.add(PID_GND_ID, "DNB", "GND ID", gnd_is_same_id)
        self.add(PID_EGAXA_ID, "EGAXA", "EGAXA ID")
        self.add(PID_ELNET_ID, "ERRR", "ELNET ID")
        self.add(PID_FAST_ID, "FAST", "FAST ID")
        self.add(PID_NATIONAL_LIBRARY_OF_GREECE_ID,
                 "GRATEVE", "National Library of Greece ID")
        self.add(PID_SBN_AUTHOR_ID, "ICCU", "SBN author ID", sbn_is_same_id)
        self.add(PID_ISNI, "ISNI", "ISNI")  # werkt nu; veel fouten
        self.add(PID_NATIONAL_LIBRARY_OF_ISRAEL_J9U_ID, "J9U",
                 "National Library of Israel J9U ID")  # weinig fouten
        self.add(PID_UNION_LIST_OF_ARTIST_NAMES_ID,
                 "JPG", "Union List of Artist Names ID")
        self.add(PID_NATIONAL_LIBRARY_OF_KOREA_ID,
                 "KRNLK", "National Library of Korea ID")
        self.add(PID_LIBRARY_OF_CONGRESS_AUTHORITY_ID, "LC",
                 "Library of Congress authority ID")  # tested
        self.add(PID_NATIONAL_LIBRARY_OF_LITHUANIA_ID,
                 "LIH", "National Library of Lithuania ID")
        self.add(PID_NATIONAL_LIBRARY_OF_LATVIA_ID,
                 "LNB", "National Library of Latvia ID", lnb_is_same_id, lnb_determine_search_code)
        self.add(PID_LEBANESE_NATIONAL_LIBRARY_ID,
                 "LNL", "Lebanese National Library ID")
        self.add(PID_BNRM_ID, "MRBNR", "BNRM ID")
        self.add(PID_NATIONAL_LIBRARY_OF_IRELAND_ID,
                 "N6I", "National Library of Ireland ID")
        self.add(PID_NDL_AUTHORITY_ID, "NDL", "NDL Authority ID")
        self.add(PID_CINII_BOOKS_AUTHOR_ID, "NII", "CiNii Books author ID")
        self.add(PID_NL_CR_AUT_ID, "NKC", "NL CR AUT ID")
        self.add(PID_LIBRARIES_AUSTRALIA_ID, "NLA", "Libraries Australia ID",
                 searchcode_is_same_id, nla_determine_search_code)
        self.add(PID_NATIONAL_LIBRARY_BOARD_SINGAPORE_ID,
                 "NLB", "National Library Board Singapore ID")
        self.add(PID_NATIONAL_LIBRARY_OF_RUSSIA_ID,
                 "NLR", "National Library of Russia ID", nlr_is_same_id, nlr_determine_search_code)
        self.add(PID_NSK_ID, "NSK", "NSK ID")  # tested
        self.add(PID_NSZL_NAME_AUTHORITY_ID, "NSZL", "NSZL name authority ID")
        self.add(PID_NSZL_VIAF_ID, "NSZL", "NSZL (VIAF) ID")
        self.add(PID_NATIONALE_THESAURUS_VOOR_AUTEURSNAMEN_ID,
                 "NTA", "Nationale Thesaurus voor Auteursnamen ID")
        self.add(PID_NUKAT_ID, "NUKAT", "NUKAT ID",
                 nukat_is_same_id, nukat_determine_search_code)
        self.add(PID_RILM_ID, "NYNYRILM", "RILM ID")
        self.add(PID_PERSEUS_AUTHOR_ID, "PERSEUS", "Perseus author ID",
                 searchcode_is_same_id, perseus_determine_search_code)
        self.add(PID_PLWABN_ID, "PLWABN", "PLWABN ID")
        self.add(PID_PORTUGUESE_NATIONAL_LIBRARY_AUTHOR_ID,
                 "PTBNP", "Portuguese National Library author ID")
        self.add(PID_RERO_ID_OBSOLETE, "RERO", "RERO ID (obsolete)",
                 searchcode_is_same_id, rero_determine_search_code)
        self.add(PID_LIBRIS_URI, "SELIBR", "Libris-URI",
                 None, selibr_determine_search_code)
        self.add(PID_CONOR_SI_ID, "SIMACOB", "CONOR.SI ID")
        self.add(PID_SLOVAK_NATIONAL_LIBRARY_VIAF_ID,
                 "SKMASNL", "Slovak National Library (VIAF) ID")
        self.add(PID_SYRIAC_BIOGRAPHICAL_DICTIONARY_ID,
                 "SRP", "Syriac Biographical Dictionary ID", searchcode_is_same_id, srp_determine_search_code)
        self.add(PID_IDREF_ID, "SUDOC", "IdRef ID")
        self.add(PID_GND_ID, "SZ", "GND ID")
        self.add(PID_UAE_UNIVERSITY_LIBRARIES_ID,
                 "UAE", "UAE University Libraries ID")
        self.add(PID_NATIONAL_LIBRARY_OF_ICELAND_ID,
                 "UIY", "National Library of Iceland ID")
        self.add(PID_FLEMISH_PUBLIC_LIBRARIES_ID,
                 "VLACC", "Flemish Public Libraries ID")
        self.add(PID_NORAF_ID, "W2Z", "NORAF ID")

    def bnf_viaf_qry(self, wikidata_id):
        # Identifiant de la notice  : ark:/12148/cb11916320z
        # Notice n° : FRBNF11916320
        # https://viaf.org/viaf/sourceID/BNF|11916320/justlinks.json  -> FRBNF119163208
        #
        # Identifiant de la notice  : ark:/12148/cb120493546
        # Notice n° : FRBNF12049354
        # https://viaf.org/viaf/sourceID/BNF|12049354/justlinks.json  -> http://catalogue.bnf.fr/ark:/12148/cb12049354 ['6' weg]
        #
        # Identifiant de la notice  : ark:/12148/cb170700059
        # Notice n° : FRBNF17070005
        # https://viaf.org/viaf/sourceID/BNF|17070005/justlinks.json  -> not found
        #
        # Identifiant de la notice  : ark:/12148/cb17074051f
        # Notice n° : FRBNF17074051
        # https://viaf.org/viaf/sourceID/BNF|17074051/justlinks.json  -> not found
        #
        # Identifiant de la notice  : ark:/12148/cb16728223r
        # Notice n° : FRBNF16728223
        # https://viaf.org/viaf/sourceID/BNF|16728223/justlinks.json  -> not found
        #
        # Identifiant de la notice  : ark:/12148/cb101761115
        # Notice n° : FRBNF10176111
        # https://viaf.org/viaf/sourceID/BNF|10176111/justlinks.json  -> not found

        return wikidata_id[:-1]

    def add(self, pid: str, code: str, description: str, is_same_id_func=None, determine_search_code_func=None) -> None:
        if pid not in self.dict:
            self.dict[pid] = AuthoritySource(
                pid, code, description, is_same_id_func, determine_search_code_func)
        else:
            self.dict[pid].codes.append(code)

    def get(self, pid: str) -> AuthoritySource:
        return self.dict[pid]
