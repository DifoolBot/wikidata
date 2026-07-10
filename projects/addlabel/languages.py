import json
import os.path
from typing import Dict
from addlabel.paths import DATA_DIR
from addlabel.wdqs_client import query_wdqs_simple

CYRILLIC = "Cyrillic"
LATIN = "Latin"
ARABIC = "Arabic"
HEBREW = "Hebrew"
GREEK = "Greek"
NON_LATIN = "Non-Latin"
UNDETERMINED = "Undetermined"

WRITING_SYSTEM_CYRILLIC_SCRIPT = "Cyrillic script"
WRITING_SYSTEM_LATIN_SCRIPT = "Latin script"
WRITING_SYSTEM_ARABIC_SCRIPT = "Arabic script"
WRITING_SYSTEM_HEBREW_ALPHABET = "Hebrew alphabet"
WRITING_SYSTEM_ARABIC_ALPHABET = "Arabic alphabet"
WRITING_SYSTEM_GAJS_LATIN_ALPHABET = "Gaj's Latin alphabet"
WRITING_SYSTEM_SERBIAN_CYRILLIC_ALPHABET = "Serbian Cyrillic alphabet"
WRITING_SYSTEM_PERSIAN_ALPHABET = "Persian alphabet"
WRITING_SYSTEM_GREEK_ALPHABET = "Greek alphabet"
WRITING_SYSTEM_HANGUL = "Hangul"
WRITING_SYSTEM_HANJA = "Hanja"

QID_ABKHAZ = "Q5111"
QID_AFRIKAANS = "Q14196"
QID_ALBANIAN = "Q8748"
QID_AMHARIC = "Q28244"
QID_AMIS = "Q35132"
QID_ARABIC = "Q13955"
QID_ARMENIAN = "Q8785"
QID_ATAYAL = "Q715766"
# QID_AUSLAN = "Q29525"
QID_AUSTRALIAN_ENGLISH = "Q44679"
QID_AYMARA = "Q4627"
QID_AZERBAIJANI = "Q9292"
QID_BADYARA = "Q35095"
QID_BAJAN_CREOLE = "Q2524014"
QID_BALANTA = "Q35006"
QID_BALOCHI = "Q33049"
QID_BAMBARA = "Q33243"
QID_BANGLA = "Q9610"
QID_BARWE = "Q8826802"
QID_BELARUSIAN = "Q9091"
QID_BISLAMA = "Q35452"
QID_BISSA = "Q32934"
QID_BOBO = "Q12628055"
QID_BOKMAL = "Q25167"
QID_BOSNIAN = "Q9303"
QID_BOZO = "Q35021"
QID_BRITISH_ENGLISH = "Q7979"
QID_BULGARIAN = "Q7918"
QID_BUNUN = "Q56505"
QID_BURMESE = "Q9228"
QID_CAPE_VERDEAN_CREOLE = "Q35963"
QID_CAROLINIAN = "Q28427"
QID_CATALAN = "Q7026"
QID_CHAMORRO = "Q33262"
QID_CHEWA = "Q33273"
QID_CHINESE = "Q7850"
QID_COMORIAN = "Q33077"
QID_COOK_ISLANDS_MAORI = "Q36745"
QID_CROATIAN = "Q6654"
QID_CZECH = "Q9056"
QID_DANISH = "Q9035"
QID_DARI = "Q178440"
QID_DEMOTIC_GREEK = "Q35392"  # subclass of
QID_DIOULA = "Q32706"
QID_DOGON = "Q1234776"
QID_DUTCH = "Q7411"
QID_DZONGKHA = "Q33081"
QID_ENGLISH = "Q1860"
QID_ESTONIAN = "Q9072"
QID_FAROESE = "Q25258"
QID_FIJI_HINDI = "Q46728"
QID_FIJIAN = "Q33295"
QID_FILIPINO = "Q33298"
QID_FINNISH = "Q1412"
QID_FRENCH = "Q150"
QID_FULA = "Q33454"
QID_GEORGIAN = "Q8108"
QID_GERMAN = "Q188"
QID_GILBERTESE = "Q30898"
QID_GREEK = "Q9129"
QID_GREENLANDIC = "Q25355"
QID_GRENADIAN_CREOLE_ENGLISH = "Q4252500"
QID_GUARANI = "Q35876"
QID_HAITIAN_CREOLE = "Q33491"
QID_HASSANIYA_ARABIC = "Q56231"
QID_HEBREW = "Q9288"
QID_HINDI = "Q1568"
QID_HIRI_MOTU = "Q33617"
QID_HUNGARIAN = "Q9067"
QID_ICELANDIC = "Q294"
QID_INDONESIAN = "Q9240"
QID_IRISH = "Q9142"
QID_ITALIAN = "Q652"
QID_JAPANESE = "Q5287"
QID_KALANGA = "Q33672"
QID_KANAKANAVU = "Q172244"
QID_KASSONKE = "Q36905"
QID_KAVALAN = "Q716627"
QID_KAZAKH = "Q9252"
QID_KHMER = "Q9205"
QID_KHOISAN = "Q33614"
QID_KINMEN_DIALECT = "Q56278342"
QID_KINYARWANDA = "Q33573"
QID_KIRUNDI = "Q33583"
QID_KOREAN = "Q9176"
QID_KRIO = "Q35744"
QID_KURDISH = "Q36368"
QID_KYRGYZ = "Q9255"
QID_LANGUAGES_OF_CHINA = "Q835866"
QID_LANGUAGES_OF_MEXICO = "Q1661395"
QID_LAO = "Q9211"
QID_LATIN = "Q397"
QID_LATVIAN = "Q9078"
QID_LITHUANIAN = "Q9083"
QID_LUXEMBOURGISH = "Q9051"
QID_MACEDONIAN = "Q9296"
QID_MALAGASY = "Q7930"
QID_MALAY = "Q9237"
QID_MALDIVIAN = "Q32656"
QID_MALTESE = "Q9166"
QID_MANINKA = "Q36186"
QID_MAORI = "Q36451"
QID_MARSHALLESE = "Q36280"
QID_MATSU_DIALECT = "Q19599280"
QID_MINYANKA = "Q36187"
QID_MIRANDESE = "Q13330"
QID_MODERN_GREEK = "Q36510"
QID_MONGOLIAN = "Q9246"
QID_MONTENEGRIN = "Q8821"
QID_MOORE = "Q36096"
QID_NAHUATL = "Q13300"
QID_NAMBYA = "Q3553981"
QID_NAURUAN = "Q13307"
QID_NDAU = "Q13311"
QID_NEPALI = "Q33823"
QID_NIUEAN = "Q33790"
QID_NORTH_KOREAN_STANDARD_LANGUAGE = "Q18784"
QID_NORTHERN_NDEBELE = "Q35613"
QID_NORTHERN_SOTHO = "Q33890"
QID_NORWEGIAN = "Q9043"
QID_NURISTANI = "Q161804"
QID_NYNORSK = "Q25164"
QID_O_KU_UA = "Q61055662"
QID_PAIWAN = "Q715755"
QID_PALAUAN = "Q33776"
QID_PAMIR = "Q1772864"
QID_PAPIAMENTO = "Q33856"
QID_PASHAYI = "Q36670"
QID_PASHTO = "Q58680"
QID_PERSIAN = "Q9168"
QID_POLISH = "Q809"
QID_PORTUGUESE = "Q5146"
QID_PUYUMA = "Q716690"
QID_QUECHUA = "Q5218"
QID_QUICHUA = "Q1740805"
QID_ROMANIAN = "Q7913"
QID_ROMANSH = "Q13199"
QID_RUKAI = "Q49232"
QID_RUSSIAN = "Q7737"
QID_SAAROA = "Q716599"
QID_SAISIYAT = "Q716695"
QID_SAKIZAYA = "Q718269"
QID_SAMI = "Q56463"
QID_SAMOAN = "Q34011"
QID_SANGO = "Q33954"
QID_SEEDIQ = "Q716686"
QID_SENUFO = "Q33795"
QID_SERBIAN = "Q9299"
QID_SERBO_CROATIAN = "Q9301"
QID_SESOTHO = "Q34340"
QID_SEYCHELLOIS_CREOLE = "Q34015"
QID_SHONA = "Q34004"
QID_SHUAR = "Q617291"
QID_SINHALA = "Q13267"
QID_SLOVAK = "Q9058"
QID_SLOVENE = "Q9063"
QID_SOMALI = "Q13275"
QID_SONGHAY = "Q505198"
QID_SONINKE = "Q36660"
QID_SOUTHERN_NDEBELE = "Q36785"
QID_SPANISH = "Q1321"
QID_STANDARD_ALGERIAN_BERBER = "Q61053330"
QID_STANDARD_MANDARIN = "Q727694"
QID_STANDARD_MOROCCAN_AMAZIGH = "Q7598268"
QID_STANDARD_TAIWANESE_MANDARIN = "Q262828"
QID_SWAHILI = "Q7838"
QID_SWAZI = "Q34014"
QID_SWEDISH = "Q9027"
QID_TAIWANESE_HAKKA = "Q2391532"
QID_TAIWANESE_HOKKIEN = "Q36778"
QID_TAJIK = "Q9260"
QID_TAMASHEQ = "Q4670066"
QID_TAMIL = "Q5885"
QID_TETUM = "Q34125"
QID_THAI = "Q9217"
QID_TIGRINYA = "Q34124"
QID_TOK_PISIN = "Q34159"
QID_TONGA = "Q34101"
QID_TONGAN = "Q34094"
QID_TRUKU = "Q11071864"
QID_TSONGA = "Q34327"
QID_TSOU = "Q716681"
QID_TSWANA = "Q34137"
QID_TURKISH = "Q256"
QID_TURKMEN = "Q9267"
QID_TUVALUAN = "Q34055"
QID_UKRAINIAN = "Q8798"
QID_URDU = "Q1617"
QID_UZBEK = "Q9264"
QID_VENDA = "Q32704"
QID_VIETNAMESE = "Q9199"
QID_WOLOF = "Q34257"
QID_XHOSA = "Q13218"
QID_YAMI = "Q715760"
QID_YUCATEC_MAYA = "Q13354"
QID_ZULU = "Q10179"

QID_ACEHNESE = "Q27683"  # ace
QID_AFAR = "Q27811"  # aar
QID_AKKADIAN = "Q35518"  # akk
QID_ANCIENT_GREEK = "Q35497"  # grc
QID_ANGIKA = "Q28378"  # anp
QID_ARAGONESE = "Q8765"  # arg
QID_ARAPAHO = "Q56417"  # arp
QID_ASSAMESE = "Q29401"  # asm
QID_BASHKIR = "Q13389"
QID_BHOJPURI = "Q33268"  # bho
QID_BRAJ_BHASHA = "Q35243"  # bra
QID_BRETON = "Q12107"  # bre
QID_BURYAT = "Q33120"  # bua
QID_CADDO = "Q56756"
QID_COPTIC = "Q36155"
QID_CORSICAN = "Q33111"
QID_CRIMEAN_TATAR = "Q33357"
QID_EGYPTIAN = "Q50868"
QID_GALICIAN = "Q9307"
QID_IMPERIAL_ARAMAIC = "Q7079491"  # arc
QID_KALMYK = "Q33634"  # xal
QID_LUGANDA = "Q33368"
QID_MALAYALAM = "Q36236"
QID_MARATHI = "Q1571"
QID_MIDDLE_PERSIAN = "Q32063"  # pal
QID_OLD_ENGLISH = "Q42365"  # ang
QID_OLD_FRENCH = "Q35222"
QID_OTTOMAN_TURKISH = "Q36730"  # ota
QID_PUNJABI = "Q58635"
QID_SANSKRIT = "Q11059"  # san
QID_TIBETAN = "Q34271"  # bod
QID_VEPS = "Q32747"
QID_WELSH = "Q9309"
QID_YAKUT = "Q34299"
QID_YIDDISH = "Q8641"  # yid
QID_PUNJABI = "Q58635"
QID_BASQUE = "Q8752"
QID_ODIA = "Q33810"  # ory
QID_CHAGATAI = "Q36831"  # chg
QID_OCCITAN = "Q14185"  # oci
QID_VLAX_ROMANI = "Q2669199"
QID_YORUBA = "Q34311"  # yor
QID_GUJARATI = "Q5137"  # guj
QID_TELUGU = "Q8097"  # tel
QID_SYRIAC = "Q33538"  # syc
QID_ROMANI = "Q13201"  # rom
QID_HONG_KONG_ENGLISH = "Q1068863"  # "en-HK"
QID_HAWAIIAN = "Q33569"  # haw
QID_MIDDLE_FRENCH = "Q1473289"  # frm
QID_IRANIAN = "Q33527"  # ira
QID_CHAGATAI = "Q36831"  # chg
QID_TWI = "Q36850"  # twi
QID_AUSTRALIAN_ABORIGINAL_LANGUAGES = "Q205143"  # aus
QID_SORBIAN = "Q25442"  # wen
QID_MIDDLE_HIGH_GERMAN = "Q837985"  # gmh
QID_GERMANIC = "Q21200"  # gem
QID_GE_EZ = "Q35667"  # gez
QID_SCOTTISH_GAELIC = "Q9314"  # gla
QID_GOTHIC = "Q35722"  # got
QID_SWISS_GERMAN = "Q387066"  # gsw
QID_OLD_HIGH_GERMAN = "Q35218"  # goh
QID_MIDDLE_DUTCH = "Q178806"  # dum
QID_DUALA = "Q33013"  # dua
QID_LOWER_SORBIAN = "Q13286"  # dsb
QID_KOMI = "Q36126"  # kom
# QID_KANAKANAVU = "Q172244"
QID_PRAKRIT = "Q192170"
QID_AUSTRALIAN_ABORIGINAL_LANGUAGES = "Q205143"
QID_SLAVIC = "Q23526"
QID_SOUTHERN_ATHABASKAN = "Q27758"
QID_FRENCH_BASED_CREOLE_LANGUAGES = "Q33260"
QID_ALGONQUIAN = "Q33392"
QID_INDO_ARYAN = "Q33577"
QID_MAYAN = "Q33738"
QID_NIGER_CONGO = "Q33838"
QID_ORIYA_LANGUAGES = "Q7102899"
QID_TAI = "Q749720"
QID_FINNO_UGRIC = "Q79890"
QID_PHILIPPINE = "Q947858"


QID_MULTIPLE_LANGUAGES = "Q20923490"
QID_UNDETERMINED_LANGUAGE = "Q22282914"

qid_macro_language = {
    "ori": QID_ODIA,  # Oriya (macrolanguage)
    "syr": QID_SYRIAC,
}


# SELECT DISTINCT ?iso2 ?iso3 ?itemLabel WHERE {
#   ?item wdt:P219 ?iso2;
#     wdt:P220 ?iso3.
#   FILTER(?iso2 != ?iso3).
#   SERVICE wikibase:label {
#        bd:serviceParam wikibase:language "en".
#        ?item rdfs:label ?itemLabel.
#      }
# } order by ?iso2

# https://id.loc.gov/vocabulary/languages.html
# https://id.loc.gov/vocabulary/languages/x

iso639_2_dict = {
    "alb": QID_ALBANIAN,  # Albanian
    "arm": QID_ARMENIAN,  # Armenian
    "baq": QID_BASQUE,
    "bur": QID_BURMESE,  # Burmese
    "chi": QID_CHINESE,  # Chinese
    "cze": QID_CZECH,  # Czech
    "dut": QID_DUTCH,  # Dutch
    "fre": QID_FRENCH,  # French
    "geo": QID_GEORGIAN,  # Georgian
    "ger": QID_GERMAN,  # German
    "gre": QID_MODERN_GREEK,  # Modern Greek
    "ice": QID_ICELANDIC,  # Icelandic
    "lav": QID_LATVIAN,  # Latvian
    "mac": QID_MACEDONIAN,  # Macedonian
    "mao": QID_MAORI,  # Māori
    "may": QID_MALAY,  # Malay
    "ori": QID_ODIA,
    "per": QID_PERSIAN,  # Persian
    "rum": QID_ROMANIAN,  # Romanian
    "slo": QID_SLOVAK,  # Slovak
    "tib": QID_TIBETAN,  # Tibetan
    "wel": QID_WELSH,  # Welsh
}


# wikidata_language = {
#     "ar": QID_ARABIC,
#     "de": QID_GERMAN,
#     "el": QID_GREEK,
#     "pl": QID_POLISH,
#     "en": QID_ENGLISH,
#     "fr": QID_FRENCH,
#     "hy": QID_ARMENIAN,
#     "ja": QID_JAPANESE,
#     "ky": QID_KYRGYZ,
#     "nl": QID_DUTCH,
#     "ru": QID_RUSSIAN,
#     "uk": QID_UKRAINIAN,
# }

# # https://en.wikipedia.org/wiki/List_of_Wikipedias
# wikidata_sitelink = {
#     "arzwiki": "Q29919",
#     "azwiki": QID_AZERBAIJANI,
#     "bawiki": QID_BASHKIR,
#     "be_x_oldwiki": QID_BELARUSIAN,  # Q9091
#     "bewiki": QID_BELARUSIAN,
#     "bgwiki": QID_BULGARIAN,
#     # "bswiki": QID_BOSNIAN,  # bosnian
#     "cawiki": QID_CATALAN,
#     "commonswiki": "",
#     "cswiki": QID_CZECH,
#     "dewiki": QID_GERMAN,
#     "enwiki": QID_ENGLISH,
#     "enwikisource": QID_ENGLISH,
#     "hewiki": QID_HEBREW,
#     "hrwiki": QID_CROATIAN,
#     "huwiki": QID_HUNGARIAN,
#     "jawiki": QID_JAPANESE,
#     "kkwiki": QID_KAZAKH,
#     "kuwiki": QID_KURDISH,  # Kurdish (Kurmanji)
#     "kywiki": QID_KYRGYZ,
#     "ltwiki": QID_LITHUANIAN,
#     "lvwiki": QID_LATVIAN,
#     "mkwiki": QID_MACEDONIAN,
#     "mnwiki": QID_MONGOLIAN,
#     "mrwiki": QID_MARATHI,
#     "plwiki": QID_POLISH,
#     "plwikiquote": QID_POLISH,
#     # "pnbwiki": QID_PUNJABI,  # Western Punjabi
#     "ruwiki": QID_RUSSIAN,
#     "sahwiki": QID_YAKUT,  # Yakut
#     "svwiki": QID_SWEDISH,
#     "tewiki": QID_TELUGU,  # Telugu
#     "trwiki": QID_TURKISH,
#     "ttwiki": "Q25285",  # Tatar
#     "ukwiki": QID_UKRAINIAN,
#     "viwiki": QID_VIETNAMESE,
#     "zhwiki": QID_CHINESE,
#     "eswiki": QID_SPANISH,
#     "etwiki": QID_ESTONIAN,
#     "fawiki": QID_PERSIAN,
#     "itwikisource": QID_ITALIAN,
#     "nlwiki": QID_DUTCH,
# }

SCRIPTS_FILE = DATA_DIR / "scripts.json"
LANGUAGES_FILE = DATA_DIR / "languages.json"
LANGUAGES_QID_FILE = DATA_DIR / "languages_qid.json"
LANGUAGES_CODE_FILE = DATA_DIR / "languages_code.json"
LANGUAGES_WIKI_FILE = DATA_DIR / "languages_wiki.json"
WD = "http://www.wikidata.org/entity/"


class Language:
    def __init__(
        self,
        qid: str,
        description: str | None = None,
        iso3: str | None = None,
        wiki: str | None = None,
        code: str | None = None,
        scripts=None,
        is_latin: bool | None = None,
        is_arabic: bool | None = None,
        is_greek: bool | None = None,
        is_hebrew: bool | None = None,
        is_cyrillic: bool | None = None,
    ):
        self.qid = qid
        self.description = description
        self.iso3 = iso3
        self.wiki = wiki
        self.code = code
        self.scripts = scripts
        self.is_latin = is_latin
        self.is_arabic = is_arabic
        self.is_greek = is_greek
        self.is_hebrew = is_hebrew
        self.is_cyrillic = is_cyrillic

    def get_code(self) -> str:
        return self.code or self.iso3 or self.qid

    def get_description(self) -> str:
        return self.description or self.get_code()

    def get_is_hebrew(self):
        return self.is_hebrew or False

    def get_is_cyrillic(self):
        return self.is_cyrillic or False

    def get_is_latin(self):
        if self.qid == QID_UNDETERMINED_LANGUAGE:
            return None
        if self.qid == QID_MULTIPLE_LANGUAGES:
            return None

        if self.is_latin is None:
            raise RuntimeError(
                f"Language {self.qid} {self.get_description()} does not specify 'is_latin'."
            )

        return self.is_latin

    def get_is_non_latin(self):
        is_latin = self.get_is_latin()
        if is_latin is None:
            return None
        else:
            return not is_latin

    def set_is_latin(self, is_latin: bool):
        if self.is_latin is not None:
            if self.is_latin != is_latin:
                raise RuntimeError(
                    f"{self.get_code()} - {self.get_description()}: is_latin already set"
                )
        self.is_latin = is_latin

    def add_script(self, script: str):
        if not self.scripts:
            self.scripts = []
        if script not in self.scripts:
            self.scripts.append(script)

    # Method to serialize selected properties
    def to_dict(self):
        properties = [
            "description",
            "iso3",
            "wiki",
            "code",
            "scripts",
            "is_latin",
            "is_arabic",
            "is_greek",
            "is_hebrew",
            "is_cyrillic",
        ]
        return {
            prop: getattr(self, prop)
            for prop in properties
            if getattr(self, prop) is not None
        }

    # Class method to create an object from a dictionary
    @classmethod
    def from_dict(cls, qid: str, data):
        if not qid:
            raise ValueError("Missing required field: 'qid'")

        return cls(
            qid=qid,
            description=data.get("description"),
            iso3=data.get("iso3"),
            wiki=data.get("wiki"),
            code=data.get("code"),
            scripts=data.get("scripts"),
            is_latin=data.get("is_latin"),
            is_arabic=data.get("is_arabic"),
            is_greek=data.get("is_greek"),
            is_hebrew=data.get("is_hebrew"),
            is_cyrillic=data.get("is_cyrillic"),
        )


class Languages:
    def __init__(self):
        self.scripts = self.load_scripts()
        self.qid_dict, self.code_dict, self.wiki_dict = self.load_languages()

    def get_language(self, qid: str) -> Language:
        if qid not in self.qid_dict:
            raise RuntimeError(f"Unknown language qid {qid}")
        return self.qid_dict[qid]

    # def get_code(self, qid: str) -> str:
    #     if qid not in self.qid_dict:
    #         raise RuntimeError(f"Unknown language qid {qid}")

    #     if "code" in self.qid_dict[qid]:
    #         return self.qid_dict[qid]["code"]
    #     else:
    #         return qid

    def get_language_from_wiki(self, wiki: str) -> None | str:
        if wiki.endswith("_x_oldwiki"):
            wiki = wiki[: -len("_x_oldwiki")]
        elif wiki.endswith("wiki"):
            wiki = wiki[: -len("wiki")]
        elif wiki.endswith("wikiquote"):
            wiki = wiki[: -len("wikiquote")]
        elif wiki.endswith("wikisource"):
            wiki = wiki[: -len("wikisource")]

        if wiki == "commons":
            return None
        if wiki == "species":
            return None

        if wiki not in self.wiki_dict:
            raise RuntimeError(f"Unknown wiki {wiki}")

        # todo; what to do with multiple
        return self.wiki_dict[wiki][0]

    # todo : change name
    def get_language_from_iso(self, iso: str) -> str:
        if iso in self.code_dict:
            # todo; what to do with multiple
            return self.code_dict[iso][0]
        # needed for ori/ory
        if iso in iso639_2_dict:
            return iso639_2_dict[iso]
        if iso in qid_macro_language:
            return qid_macro_language[iso]
        if iso == "und":
            return QID_UNDETERMINED_LANGUAGE
        if iso == "mul":
            return QID_MULTIPLE_LANGUAGES

        # art - http://www.lexvo.org/page/iso639-5/art - https://id.loc.gov/vocabulary/iso639-5/art.html
        # cai - Central American Indian - https://id.loc.gov/vocabulary/languages/cai.html

        raise RuntimeError(f"Unknown language iso code {iso}")

    # todo : change name
    def get_language_from_iso639_2(self, iso639_2: str) -> str:
        if iso639_2 in iso639_2_dict:
            return iso639_2_dict[iso639_2]
        else:
            return self.get_language_from_iso(iso639_2)

    def load_scripts(self):
        if os.path.exists(SCRIPTS_FILE):
            with open(SCRIPTS_FILE, "r") as infile:
                script_dict = json.load(infile)
        else:
            script_dict = self.construct_hebrew_scripts(
                self.construct_arabic_scripts(
                    self.construct_cyrillic_scripts(
                        self.construct_greek_scripts(
                            self.construct_non_latin_scripts(
                                self.construct_latin_scripts({})
                            )
                        )
                    )
                )
            )
            self.save_scripts(script_dict)
        return script_dict

    def load_languages(self):
        if os.path.exists(LANGUAGES_FILE):
            # with open(LANGUAGES_FILE, "r") as infile:
            #     dict = json.load(infile)

            # Read the JSON file and deserialize into a dictionary of objects
            with open(LANGUAGES_FILE, "r") as file:
                data = json.load(file)

            qid_dict = {
                key: Language.from_dict(key, value) for key, value in data.items()
            }
            qid_dict = self.corrections(qid_dict)
        else:
            qid_dict = self.examine_dict(
                self.construct_script_dict(self.construct_language_dict())
            )
            self.save_languages(qid_dict)

        code_dict = {}
        wiki_dict = {}
        for qid, language in qid_dict.items():
            if language.code:
                if language.code not in code_dict:
                    code_dict[language.code] = []
                code_dict[language.code].append(qid)
            if language.wiki:
                if language.wiki not in wiki_dict:
                    wiki_dict[language.wiki] = []
                wiki_dict[language.wiki].append(qid)

        return qid_dict, code_dict, wiki_dict

    def corrections(self, lan_dict: Dict[str, Language]) -> Dict[str, Language]:

        # fill up
        # latin
        lan_dict[QID_GERMANIC].set_is_latin(True)

        # non-latin
        lan_dict[QID_ALGONQUIAN].set_is_latin(False)
        lan_dict[QID_AUSTRALIAN_ABORIGINAL_LANGUAGES].set_is_latin(False)
        lan_dict[QID_BISSA].set_is_latin(False)
        lan_dict[QID_FINNO_UGRIC].set_is_latin(False)
        lan_dict[QID_FRENCH_BASED_CREOLE_LANGUAGES].set_is_latin(True)
        lan_dict[QID_IMPERIAL_ARAMAIC].set_is_latin(False)
        lan_dict[QID_INDO_ARYAN].set_is_latin(False)
        lan_dict[QID_IRANIAN].set_is_latin(False)
        lan_dict[QID_KANAKANAVU].set_is_latin(False)
        lan_dict[QID_MAYAN].set_is_latin(False)
        lan_dict[QID_NIGER_CONGO].set_is_latin(False)
        lan_dict[QID_ORIYA_LANGUAGES].set_is_latin(False)
        lan_dict[QID_PHILIPPINE].set_is_latin(False)
        lan_dict[QID_PRAKRIT].set_is_latin(False)
        lan_dict[QID_SAMI].set_is_latin(True)  # writing system (P282) Latin script
        lan_dict[QID_SHUAR].set_is_latin(False)
        lan_dict[QID_SLAVIC].set_is_latin(False)
        lan_dict[QID_SONGHAY].set_is_latin(False)
        lan_dict[QID_SOUTHERN_ATHABASKAN].set_is_latin(False)
        lan_dict[QID_TAI].set_is_latin(False)
        lan_dict[QID_DEMOTIC_GREEK].set_is_latin(False)
        lan_dict[QID_YAMI].set_is_latin(False)
        lan_dict[QID_PAIWAN].set_is_latin(False)

        lan_dict[QID_TSOU].set_is_latin(False)
        lan_dict["Q716690"].set_is_latin(False)
        lan_dict["Q716599"].set_is_latin(False)
        lan_dict["Q716627"].set_is_latin(False)
        # lan_dict[QID_SEEDIQ].set_is_latin(False)
        # lan_dict[QID_SAISIYAT].set_is_latin(False)
        # lan_dict[QID_SAKIZAYA].set_is_latin(False)
        lan_dict["Q2391532"].set_is_latin(False)
        lan_dict["Q11071864"].set_is_latin(False)
        lan_dict["Q61055662"].set_is_latin(False)
        lan_dict["Q19599280"].set_is_latin(False)
        lan_dict["Q56278342"].set_is_latin(False)
        # lan_dict["Q35132"].set_is_latin(False)
        lan_dict[QID_TAIWANESE_HOKKIEN].set_is_latin(False)
        # lan_dict["Q56505"].set_is_latin(False)
        # lan_dict[QID_RUKAI].set_is_latin(False)

        lan_dict[QID_BOSNIAN].set_is_latin(
            False
        )  # Bosnian; Latin (Gaj's Latin alphabet) Cyrillic (Serbian Cyrillic alphabet)[a]
        lan_dict[QID_QUICHUA].set_is_latin(True)  # Northern Quichua
        lan_dict[QID_BALANTA].set_is_latin(False)  # Balanta
        lan_dict[QID_BARWE].set_is_latin(True)  # Barwe
        lan_dict[QID_NURISTANI].set_is_latin(False)  # Nuristani

        lan_dict[QID_NORTH_KOREAN_STANDARD_LANGUAGE].set_is_latin(
            False
        )  #  North Korean standard language
        lan_dict["Q44661"].set_is_latin(True)  #  New Zealand English
        lan_dict["Q25448"].set_is_latin(False)  #  Berber
        lan_dict["Q837169"].set_is_latin(False)  #  Old Mandarin

        return lan_dict

    def examine_dict(self, lan_dict: Dict[str, Language]) -> Dict[str, Language]:
        for qid, language in lan_dict.items():
            kinds = set()
            if language.scripts:
                for script in language.scripts:
                    if script in self.scripts:
                        kind = self.scripts[script]
                        kinds.add(kind)

                if len(kinds) > 1:
                    kinds = set(NON_LATIN)

                if CYRILLIC in kinds:
                    language.is_cyrillic = True
                elif ARABIC in kinds:
                    language.is_arabic = True
                elif HEBREW in kinds:
                    language.is_hebrew = True
                elif GREEK in kinds:
                    language.is_greek = True

                language.is_latin = LATIN in kinds

        lan_dict = self.corrections(lan_dict)
        return lan_dict

    def construct_non_latin_scripts(self, script_dict):
        print("Loading non-latin scripts")

        # add subclass of Arabic script Q1828555 - arabic
        # add instance of logographic writing system Q3953107 - sinograms

        # instance of (P31)
        # subclass of (P279)
        qry = """SELECT DISTINCT ?itemLabel WHERE {
                SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
                {
                    SELECT DISTINCT ?item WHERE {
                    {
                        ?item p:P31 ?statement0.
                        ?statement0 (ps:P31/(wdt:P279*)) wd:Q1828555.
                    }
                    UNION
                    {
                        ?item p:P279 ?statement1.
                        ?statement1 (ps:P279/(wdt:P279*)) wd:Q467037.
                    }
                    UNION
                    {
                        ?item p:P31 ?statement2.
                        ?statement2 (ps:P31/(wdt:P279*)) wd:Q335806.
                    }
                    UNION
                    {
                        ?item p:P31 ?statement3.
                        ?statement3 (ps:P31/(wdt:P279*)) wd:Q867570.
                    }
                    UNION
                    {
                        ?item p:P279 ?statement1.
                        ?statement1 (ps:P279/(wdt:P279*)) wd:Q1828555.
                    }
                    UNION
                    {
                        ?item p:P31 ?statement0.
                        ?statement0 (ps:P31/(wdt:P279*)) wd:Q3953107.
                    }
                    UNION
                    {
                        ?item p:P279 ?statement0.
                        ?statement0 (ps:P279/(wdt:P279*)) wd:Q56070706.
                    }
                    UNION
                    {
                        ?item p:P31 ?statement0.
                        ?statement0 (ps:P31/(wdt:P279*)) wd:Q28698154.
                    }
                    UNION
                    {
                        ?item p:P31 ?statement0.
                        ?statement0 (ps:P31/(wdt:P279*)) wd:Q182133.
                    }
                    UNION
                    {
                        ?item p:P31 ?statement0.
                        ?statement0 (ps:P31/(wdt:P279*)) wd:Q1049394.
                    }
                    UNION
                    {
                        ?item p:P279 ?statement0.
                        ?statement0 (ps:P279/(wdt:P279*)) wd:Q3110592.
                    }
                    }
                }
                }"""
        for row in query_wdqs_simple(qry):
            description = row.get("itemLabel", {}).get("value", "").replace(WD, "")
            script_dict[description] = NON_LATIN

        # Ogham (Q184661)
        script_dict["Ogham"] = NON_LATIN
        script_dict["Hebrew script based alphabet"] = NON_LATIN
        script_dict["unwritten language"] = NON_LATIN
        script_dict["Old Turkic"] = NON_LATIN
        script_dict["runes"] = NON_LATIN
        script_dict["Coptic script"] = NON_LATIN
        script_dict["Okinawan scripts"] = NON_LATIN
        script_dict["Elder Futhark"] = NON_LATIN  # sub class of runes
        script_dict["Neo-Tifinagh"] = NON_LATIN
        script_dict["Gothic script"] = NON_LATIN
        script_dict["Mongolian"] = NON_LATIN

        return script_dict

    def construct_latin_scripts(self, script_dict):
        print("Loading latin scripts")

        qry = """SELECT DISTINCT ?itemLabel WHERE {
                    SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
                    {
                        SELECT DISTINCT ?item WHERE {
                        ?item p:P31 ?statement0.
                        ?statement0 (ps:P31/(wdt:P279*)) wd:Q29575627.
                        }
                    }
                    }"""
        for row in query_wdqs_simple(qry):
            description = row.get("itemLabel", {}).get("value", "").replace(WD, "")
            script_dict[description] = LATIN

        script_dict[WRITING_SYSTEM_LATIN_SCRIPT] = LATIN

        return script_dict

    def construct_cyrillic_scripts(self, script_dict):
        print("Loading cyrillic scripts")

        qry = """SELECT DISTINCT ?itemLabel WHERE {
                SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
                {
                    SELECT DISTINCT ?item WHERE {
                    {
                        ?item p:P31 ?statement3.
                        ?statement3 (ps:P31/(wdt:P279*)) wd:Q867570.
                    }
                    }
                }
                }"""
        for row in query_wdqs_simple(qry):
            description = row.get("itemLabel", {}).get("value", "").replace(WD, "")
            script_dict[description] = CYRILLIC

        script_dict[WRITING_SYSTEM_CYRILLIC_SCRIPT] = CYRILLIC

        return script_dict

    def construct_hebrew_scripts(self, script_dict):
        print("Loading hebrew scripts")

        script_dict[WRITING_SYSTEM_HEBREW_ALPHABET] = HEBREW
        script_dict["Yiddish alphabet"] = HEBREW

        return script_dict

    def construct_greek_scripts(self, script_dict):
        print("Loading greek scripts")

        qry = """SELECT DISTINCT ?itemLabel WHERE {
                SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
                {
                    SELECT DISTINCT ?item WHERE {
                    ?item p:P144 ?statement0.
                    ?statement0 (ps:P144/(wdt:P279*)) wd:Q8216.
                    }
                }
                }"""
        for row in query_wdqs_simple(qry):
            description = row.get("itemLabel", {}).get("value", "").replace(WD, "")
            script_dict[description] = GREEK

        script_dict[WRITING_SYSTEM_GREEK_ALPHABET] = GREEK

        return script_dict

    def construct_arabic_scripts(self, script_dict):
        print("Loading arabic scripts")

        qry = """SELECT DISTINCT ?itemLabel WHERE {
                        SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
                        {
                            SELECT DISTINCT ?item WHERE {
                            {
                                ?item p:P31 ?statement0.
                                ?statement0 (ps:P31/(wdt:P279*)) wd:Q1828555.
                            }
                            UNION
                            {
                                ?item p:P279 ?statement1.
                                ?statement1 (ps:P279/(wdt:P279*)) wd:Q1828555.
                            }
                            }
                        }
                        }"""
        for row in query_wdqs_simple(qry):
            description = row.get("itemLabel", {}).get("value", "").replace(WD, "")
            script_dict[description] = ARABIC

        script_dict[WRITING_SYSTEM_ARABIC_SCRIPT] = ARABIC
        script_dict[WRITING_SYSTEM_ARABIC_ALPHABET] = ARABIC

        return script_dict

    def construct_language_dict(self) -> Dict[str, Language]:
        print("Constructing languages")

        qry = """SELECT DISTINCT ?language ?languageLabel ?lan_iso639_3 ?wiki ?c WHERE {
                    {
                        ?language p:P31 ?statement0.
                        ?statement0 (ps:P31/(wdt:P279*)) wd:Q20162172.
                    }
                    UNION
                    {
                        ?language p:P279 ?statement0.
                        ?statement0 (ps:P279/(wdt:P279*)) wd:Q20162172.
                    }
                    UNION
                    {
                        ?language p:P31 ?statement1.
                        ?statement1 (ps:P31/(wdt:P279*)) wd:Q20825842.
                    }
                    UNION
                    {
                        ?language p:P31 ?statement2.
                        ?statement2 (ps:P31/(wdt:P279*)) wd:Q4536543.
                    }
                    OPTIONAL { ?language wdt:P220  ?lan_iso639_3. } # language 
                    OPTIONAL { ?language wdt:P1798 ?lan_iso639_5. } # language fam  
                    OPTIONAL { ?language wdt:P221  ?lan_iso639_6. } # language variant 
                    OPTIONAL { ?language wdt:P305  ?lan_ietf.     }
                    OPTIONAL { ?language wdt:P1232 ?lan_lin.      }
                    OPTIONAL { ?language wdt:P1394 ?lan_glotto.   }
                    OPTIONAL { ?language wdt:P424  ?wiki.         }
                    SERVICE wikibase:label {
                        bd:serviceParam wikibase:language "en".
                        ?language rdfs:label ?languageLabel.
                    }
                    BIND(COALESCE(?lan_iso639_3, ?lan_iso639_5, ?lan_iso639_6, ?lan_ietf, ?lan_lin, ?lan_glotto, ?languageLabel) AS ?c)
                    }"""
        lan_dict = {}
        for row in query_wdqs_simple(qry):
            qid = row.get("language", {}).get("value", "").replace(WD, "")
            description = row.get("languageLabel", {}).get("value", "")
            iso3 = row.get("lan_iso639_3", {}).get("value", "")
            wiki = row.get("wiki", {}).get("value", "")
            code = row.get("c", {}).get("value", "")
            if not qid.startswith("Q"):
                # unknown value, for example P12193
                continue

            lan_dict[qid] = Language(
                qid=qid, description=description, iso3=iso3, wiki=wiki, code=code
            )

        lan_dict[QID_MULTIPLE_LANGUAGES] = Language(
            qid=QID_MULTIPLE_LANGUAGES,
            description="multiple languages",
            iso3="mul",
            wiki="mul",
        )

        lan_dict[QID_UNDETERMINED_LANGUAGE] = Language(
            qid=QID_UNDETERMINED_LANGUAGE,
            description="undetermined language",
            iso3="und",
            wiki="und",
        )
        lan_dict[QID_LANGUAGES_OF_CHINA] = Language(
            qid=QID_LANGUAGES_OF_CHINA,
            description="languages of China",
            is_latin=False,
        )
        lan_dict[QID_LANGUAGES_OF_MEXICO] = Language(
            qid=QID_LANGUAGES_OF_MEXICO,
            description="languages of Mexico",
            is_latin=True,  # unchecked
        )
        lan_dict["Q56278342"] = Language(
            qid="Q56278342",
            description="Kinmen dialect",
            is_latin=False,
        )
        lan_dict["Q56278342"] = Language(
            qid="Q1389492",
            description="Western Punjabi",
            is_latin=False,
        )

        return lan_dict

    def construct_script_dict(self, lan_dict: Dict[str, Language]):
        print("Constructing scripts of languages")

        # instance of language; human language misses items
        qry = """SELECT DISTINCT ?language ?ws ?wsLabel WHERE {
                ?language p:P31 ?statement0.
                ?statement0 (ps:P31/(wdt:P279*)) wd:Q34770.
                ?language wdt:P282 ?ws.
                SERVICE wikibase:label {
                    bd:serviceParam wikibase:language "en".
                    ?ws rdfs:label ?wsLabel.
                }
                }"""
        for row in query_wdqs_simple(qry):
            qid = row.get("language", {}).get("value", "").replace(WD, "")
            script_qid = row.get("ws", {}).get("value", "").replace(WD, "")
            script = row.get("wsLabel", {}).get("value", "")
            if not qid.startswith("Q"):
                # unknown value, for example P12193
                continue
            if not script_qid.startswith("Q"):
                # unknown value, for example P12193
                continue

            if qid in lan_dict:
                lan_dict[qid].add_script(script)

        return lan_dict

    def save_languages(self, qid_dict):
        # with open(LANGUAGES_FILE, "w") as outfile:
        #     json.dump(qid_dict, outfile, indent=4)

        # Serialize the dictionary to a JSON file
        with open(LANGUAGES_FILE, "w") as file:
            json.dump({key: obj.to_dict() for key, obj in qid_dict.items()}, file)

    def save_scripts(self, script_dict):
        with open(SCRIPTS_FILE, "w") as outfile:
            json.dump(script_dict, outfile, indent=4)

    def save_files(self):
        with open(LANGUAGES_QID_FILE, "w") as outfile:
            json.dump(self.qid_dict, outfile, indent=4)
        with open(LANGUAGES_CODE_FILE, "w") as outfile:
            json.dump(self.code_dict, outfile, indent=4)
        with open(LANGUAGES_WIKI_FILE, "w") as outfile:
            json.dump(self.wiki_dict, outfile, indent=4)


def main() -> None:
    langs = Languages()
    # l.save_files()
    for language in langs.qid_dict:
        if langs.qid_dict[language].scripts:
            if langs.qid_dict[language].is_latin is None:
                print(
                    f"No is_latin for {language}: script = {langs.qid_dict[language]}"
                )

    # regression tests
    langs.get_language(QID_NAHUATL).get_is_latin()
    langs.get_language("Q1364815").get_is_latin()
    langs.get_language(QID_KANAKANAVU).get_is_latin()
    langs.get_language(QID_PRAKRIT).get_is_latin()
    langs.get_language(QID_AUSTRALIAN_ABORIGINAL_LANGUAGES).get_is_latin()
    langs.get_language(QID_GERMANIC).get_is_latin()
    langs.get_language(QID_SLAVIC).get_is_latin()
    langs.get_language(QID_SOUTHERN_ATHABASKAN).get_is_latin()
    langs.get_language(QID_BISSA).get_is_latin()
    langs.get_language(QID_FRENCH_BASED_CREOLE_LANGUAGES).get_is_latin()
    langs.get_language(QID_ALGONQUIAN).get_is_latin()
    langs.get_language(QID_IRANIAN).get_is_latin()
    langs.get_language(QID_INDO_ARYAN).get_is_latin()
    langs.get_language(QID_MAYAN).get_is_latin()
    langs.get_language(QID_NIGER_CONGO).get_is_latin()
    langs.get_language(QID_SONGHAY).get_is_latin()
    langs.get_language(QID_SAMI).get_is_latin()
    langs.get_language(QID_STANDARD_ALGERIAN_BERBER).get_is_latin()
    langs.get_language(QID_SHUAR).get_is_latin()
    langs.get_language(QID_IMPERIAL_ARAMAIC).get_is_latin()
    langs.get_language(QID_ORIYA_LANGUAGES).get_is_latin()
    langs.get_language(QID_TAI).get_is_latin()
    langs.get_language(QID_FINNO_UGRIC).get_is_latin()
    langs.get_language(QID_MONTENEGRIN).get_is_latin()
    langs.get_language(QID_PHILIPPINE).get_is_latin()
    langs.get_language(QID_DEMOTIC_GREEK).get_is_latin()
    langs.get_language(QID_YAMI).get_is_latin()
    langs.get_language(QID_PAIWAN).get_is_latin()

    # for p in wikidata_language:
    #     qid = l.get_language_from_wiki(p)
    #     if qid is None:
    #         raise RuntimeError(f"Unknown wiki {p}")
    #     if qid != wikidata_language[p]:
    #         raise RuntimeError(f"Diff wiki {p}; exp: {wikidata_language[p]} act: {qid}")

    # for p in wikidata_sitelink:
    #     qid = l.get_language_from_wiki(p)
    #     if qid is None and wikidata_sitelink[p] != "":
    #         raise RuntimeError(f"Unknown wiki {p}")
    #     if qid and qid != wikidata_sitelink[p]:
    #         raise RuntimeError(f"Diff wiki {p} act {qid} exp {wikidata_sitelink[p]}")

    # for qid in qid_language:
    #     code = l.get_code(qid)
    #     if code != qid_language[qid]:
    #         print(f"qid_language for {qid}: act {code} exp {qid_language[qid]:}")


if __name__ == "__main__":
    main()
