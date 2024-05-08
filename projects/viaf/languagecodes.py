import re

WRITING_SYSTEM_CYRILLIC_SCRIPT = "Cyrillic script"
WRITING_SYSTEM_LATIN_SCRIPT = "Latin script"
WRITING_SYSTEM_ARABIC_SCRIPT = "Arabic script"
WRITING_SYSTEM_HEBREW_ALPHABET = "Hebrew alphabet"
WRITING_SYSTEM_ARABIC_ALPHABET = "Arabic alphabet"
WRITING_SYSTEM_BELARUSIAN_CYRILLIC_ALPHABET = "Belarusian Cyrillic alphabet"
WRITING_SYSTEM_MONTENEGRIN_CYRILLIC_ALPHABET = "Montenegrin Cyrillic alphabet"
WRITING_SYSTEM_GAJS_LATIN_ALPHABET = "Gaj's Latin alphabet"
WRITING_SYSTEM_SERBIAN_CYRILLIC_ALPHABET = "Serbian Cyrillic alphabet"
WRITING_SYSTEM_PERSIAN_ALPHABET = "Persian alphabet"
WRITING_SYSTEM_GREEK_ALPHABET = "Greek alphabet"
WRITING_SYSTEM_HANGUL = "Hangul"
WRITING_SYSTEM_HANJA = "Hanja"
WRITING_SYSTEM_THAI_ALPHABET = "Thai alphabet"
WRITING_SYSTEM_HIRAGANA = "hiragana"
WRITING_SYSTEM_KANA = "kana"
WRITING_SYSTEM_KANJI = "kanji"
WRITING_SYSTEM_KATAKANA = "katakana"
WRITING_SYSTEM_SIMPLIFIED_CHINESE_CHARACTERS = "simplified Chinese characters"
WRITING_SYSTEM_SINOGRAMS = "sinograms"
WRITING_SYSTEM_TRADITIONAL_CHINESE_CHARACTERS = "traditional Chinese characters"
WRITING_SYSTEM_ARMENIAN_ALPHABET = "Armenian alphabet"
WRITING_SYSTEM_BURMESE = "Burmese"
WRITING_SYSTEM_GEORGIAN_SCRIPTS = "Georgian scripts"
WRITING_SYSTEM_OTTOMAN_TURKISH_ALPHABET = "Ottoman Turkish alphabet"
WRITING_SYSTEM_TIBETAN_ALPHABET = "Tibetan alphabet"
WRITING_SYSTEM_TIBETAN_SCRIPT = "Tibetan script"

hebrew_list = [WRITING_SYSTEM_HEBREW_ALPHABET]
cyrillic_list = [
    WRITING_SYSTEM_CYRILLIC_SCRIPT,
    WRITING_SYSTEM_BELARUSIAN_CYRILLIC_ALPHABET,
    WRITING_SYSTEM_MONTENEGRIN_CYRILLIC_ALPHABET,
    WRITING_SYSTEM_SERBIAN_CYRILLIC_ALPHABET,
]
not_latin_list = (
    [
        WRITING_SYSTEM_CYRILLIC_SCRIPT,
        WRITING_SYSTEM_ARABIC_SCRIPT,
        WRITING_SYSTEM_HEBREW_ALPHABET,
        WRITING_SYSTEM_ARABIC_ALPHABET,
        WRITING_SYSTEM_BELARUSIAN_CYRILLIC_ALPHABET,
        WRITING_SYSTEM_MONTENEGRIN_CYRILLIC_ALPHABET,
        WRITING_SYSTEM_SERBIAN_CYRILLIC_ALPHABET,
        WRITING_SYSTEM_PERSIAN_ALPHABET,
        WRITING_SYSTEM_GREEK_ALPHABET,
        WRITING_SYSTEM_HANGUL,
        WRITING_SYSTEM_HANJA,
        WRITING_SYSTEM_THAI_ALPHABET,
        WRITING_SYSTEM_HIRAGANA,
        WRITING_SYSTEM_KANA,
        WRITING_SYSTEM_KANJI,
        WRITING_SYSTEM_KATAKANA,
        WRITING_SYSTEM_SIMPLIFIED_CHINESE_CHARACTERS,
        WRITING_SYSTEM_SINOGRAMS,
        WRITING_SYSTEM_TRADITIONAL_CHINESE_CHARACTERS,
        WRITING_SYSTEM_ARMENIAN_ALPHABET,
        WRITING_SYSTEM_BURMESE,
        WRITING_SYSTEM_GEORGIAN_SCRIPTS,
        WRITING_SYSTEM_OTTOMAN_TURKISH_ALPHABET,
        WRITING_SYSTEM_TIBETAN_ALPHABET,
        WRITING_SYSTEM_TIBETAN_SCRIPT,
    ]
    + cyrillic_list
    + hebrew_list
)

hungarian_name_order_countries_list = ["HUN"]
# China, Japan, Korea, and Vietnam
eastern_name_order_countries_list = ["CHN", "JPN", "PRK", "KOR", "VNM", "MAC"]


def is_hebrew_script(script: str) -> bool:
    return script in hebrew_list


def is_cyrillic_script(script: str) -> bool:
    return script in cyrillic_list


def is_not_latin_script(script: str) -> bool:
    return script in not_latin_list


def is_hungarian_name_order_country(country: str) -> bool:
    return country in hungarian_name_order_countries_list


def is_hungarian_name_order_language(language: str) -> bool:
    for country in hungarian_name_order_countries_list:
        if language in official_languages_dict[country]:
            return True
    return False


def is_eastern_name_order_country(country: str) -> bool:
    return country in eastern_name_order_countries_list


def is_eastern_name_order_language(language: str) -> bool:
    for country in eastern_name_order_countries_list:
        if language in official_languages_dict[country]:
            return True
    return False


loc_locale_dict = {
    "Boston (Mass.)": "USA",
    "Italy": "ITA",
    "Melbourne (Vic.)": "AUS",
    "Palawan (Philippines : Province)": "PHL",
    "Romania": "ROU",
    "Selinus, Extinct city": "",
    "Africa": "",
    "Azerbaijan": "AZE",
    "Belarus": "BLR",
    "Birmingham (Ala.)": "USA",
    "Cambridge, Mass.": "USA",
    "Canada": "CAN",
    "China": "CHN",
    "Colombia": "COL",
    "Côte d'Ivoire": "CIV",
    "Denmark": "DNK",
    "Egypt": "EGY",
    "England": "GBR",
    "Georgia (Republic)": "GEO",
    "Germany": "DEU",
    "Great Britain": "GBR",
    "Greece": "GRC",
    "India": "IND",
    "Ireland": "IRL",
    "Israel": "ISR",
    "Japan": "JPN",
    "Jordan": "JOR",
    "Korea": "KOR",
    "Latvia": "LVA",
    "Malaysia": "MYS",
    "Monaco": "MCO",
    "Moscow, Russia": "RUS",
    "Poland": "POL",
    "Russia (Federation)": "RUS",
    "Russia": "RUS",
    "San Francisco Bay Area (Calif.)": "USA",
    "Scotland": "GBR",
    "Slovakia": "SVK",
    "Slovenia": "SVN",
    "Soviet Union": "SUN",
    "Sweden": "SWE",
    "U.S.": "USA",
    "Ukraine": "UKR",
    "United States": "USA",
    "Vietnam (Republic)": "VNM",
    "West Bank": "ISR",
    "Hungary": "HUN",
    "Singapore": "SGP",
    "Cambridge (Mass.)": "USA",
    "Tucson (Ariz.)": "USA",
}


def get_loc_locale_country(locale: str) -> str:
    # extract the part between parentheses
    match = re.search(r"\(([^)]+)\)", locale)
    if match:
        # parentheses text can be country, region, Federation/Republic
        parentheses_text = match.group(1)
        if parentheses_text in loc_locale_dict:
            return loc_locale_dict[parentheses_text]

    if locale not in loc_locale_dict:
        raise RuntimeError(f"Loc: Unknown locale: {locale}")

    return loc_locale_dict[locale]


# https://d-nb.info/standards/vocab/gnd/geographic-area-code.html
gnd_country_dict = {
    "XA-AT": "AUT",
    "XA-BA": "BIH",
    "XA-BE": "BEL",
    "XA-BG": "BGR",
    "XA-BY": "BLR",
    "XA-CH": "CHE",
    "XA-CZ": "CZE",
    "XA-DDDE": "DEU",  # Germany East
    "XA-DE": "DEU",
    "XA-DK": "DNK",
    "XA-ES": "ESP",
    "XA-FR": "FRA",
    "XA-GB": "GBR",
    "XA-GR": "GRC",
    "XA-HR": "HRV",
    "XA-HU": "HUN",
    "XA-IE": "IRL",
    "XA-IS": "ISL",
    "XA-IT": "ITA",
    "XA-LT": "LTU",
    "XA-LV": "LVA",
    "XA-MC": "MCO",
    "XA-MD": "MDA",  # Moldova
    "XA-ME": "MNE",
    "XA-MK": "MKD",
    "XA-MT": "MLT",
    "XA-NL": "NLD",
    "XA-NO": "NOR",
    "XA-PL": "POL",
    "XA-PT": "PRT",
    "XA-RO": "ROU",
    "XA-RS": "SRB",
    "XA-RU": "RUS",
    "XA-SE": "SWE",
    "XA-SI": "SVN",
    "XA-SK": "SVK",
    "XA-SUHH": "SUN",  # Soviet Union
    "XA-UA": "UKR",
    "XB-AM": "ARM",
    "XB-AZ": "AZE",
    "XB-CN-54": "CN-XZ",  # Tibet (China)
    "XB-CN": "CHN",
    "XB-IL": "ISR",
    "XB-IN": "IND",
    "XB-JO": "JOR",  # Jordan
    "XB-JP": "JPN",
    "XB-KR": "KOR",  # Korea (South)
    "XB-LB": "LBN",
    "XB-SY": "SYR",  # Syria
    "XB-TH": "THA",  # Thailand
    "XB-TR": "TUR",
    "XB-TW": "TWN",
    "XB-UZ": "UZB",
    "XB-VN": "VNM",  # Vietnam
    "XC-DZ": "DZA",
    "XC-EG": "EGY",
    "XC-MA": "MAR",
    "XC-NG": "NGA",
    "XC-SL": "SLE",
    "XC-SN": "SEN",
    "XC-ZA": "ZAF",
    "XD-AR": "ARG",
    "XD-BR": "BRA",
    "XD-CA": "CAN",
    "XD-CL": "CHL",
    "XD-CO": "COL",
    "XD-CU": "CUB",
    "XD-DO": "DOM",  # Dominican Republic
    "XD-HT": "HTI",
    "XD-MX": "MEX",
    "XD-PE": "PER",  # Peru
    "XD-US": "USA",
    "XD-UY": "URY",
    "XD-VE": "VEN",
    "XE-AU": "AUS",
    "XT": "",  # Rome
    "XX": "SAU",  # Arab Countries
    "XY": "ISR",  # Jews
    "ZZ": "",  # Country unknown
    "XB-IQ": "IRQ",  # Iraq
    "XA-FI": "FIN",  # Finland
    "XA-EE": "EST",  # Estonia
}

# select distinct ?country2 ?country_iso ?itemLabel WHERE {
# select distinct ?country2 ?country_iso ?itemLabel WHERE {

# SERVICE wikibase:label { bd:serviceParam wikibase:language "[AUTO_LANGUAGE]". }
#    {
# SELECT DISTINCT ?item ?country2 ?country_iso WHERE {
#        ?item p:P31 ?statement0.
#        ?statement0 (ps:P31/(wdt:P279*)) wd:Q6256.
#        ?item wdt:P4801 ?loc.
#         ?item  wdt:P298 ?country_iso.
#        FILTER (strstarts(str(?loc), 'countries'))
#        BIND(REPLACE(STR(?loc), "countries/", "") AS ?country2) .
#      } }}
#                 }
# ORDER BY ?itemLabel

# https://id.loc.gov/vocabulary/countries.html
loc_country_dict = {
    "af": "AFG",  # Afghanistan
    "aa": "ALB",  # Albania
    "ae": "DZA",  # Algeria
    "an": "AND",  # Andorra
    "ao": "AGO",  # Angola
    "aq": "ATG",  # Antigua and Barbuda
    "ag": "ARG",  # Argentina
    "ai": "ARM",  # Armenia
    "aw": "ABW",  # Aruba
    "at": "AUS",  # Australia
    "au": "AUT",  # Austria
    "aj": "AZE",  # Azerbaijan
    "ba": "BHR",  # Bahrain
    "bg": "BGD",  # Bangladesh
    "bb": "BRB",  # Barbados
    "bw": "BLR",  # Belarus
    "be": "BEL",  # Belgium
    "bh": "BLZ",  # Belize
    "dm": "BEN",  # Benin
    "bt": "BTN",  # Bhutan
    "bo": "BOL",  # Bolivia
    "bn": "BIH",  # Bosnia and Herzegovina
    "bs": "BWA",  # Botswana
    "bl": "BRA",  # Brazil
    "bx": "BRN",  # Brunei
    "bu": "BGR",  # Bulgaria
    "uv": "BFA",  # Burkina Faso
    "bd": "BDI",  # Burundi
    "cb": "KHM",  # Cambodia
    "cc": "CHN",  # ADDED; China
    "cm": "CMR",  # Cameroon
    "xxc": "CAN",  # Canada
    "cv": "CPV",  # Cape Verde
    "cx": "CAF",  # Central African Republic
    "cd": "TCD",  # Chad
    "cl": "CHL",  # Chile
    "ck": "COL",  # Colombia
    "cq": "COM",  # Comoros
    "cw": "COK",  # Cook Islands
    "cr": "CRI",  # Costa Rica
    "ci": "HRV",  # Croatia
    "cu": "CUB",  # Cuba
    "co": "CUW",  # Curaçao
    "cy": "CYP",  # Cyprus
    "xr": "CZE",  # Czech Republic
    "cs": "CSK",  # Czechoslovakia
    "cg": "COD",  # Democratic Republic of the Congo
    "dk": "DNK",  # Denmark
    "ft": "DJI",  # Djibouti
    "dq": "DMA",  # Dominica
    "dr": "DOM",  # Dominican Republic
    "em": "TLS",  # East Timor
    "ec": "ECU",  # Ecuador
    "ua": "EGY",  # Egypt
    "es": "SLV",  # El Salvador
    "eg": "GNQ",  # Equatorial Guinea
    "ea": "ERI",  # Eritrea
    "er": "EST",  # Estonia
    "sq": "SWZ",  # Eswatini
    "et": "ETH",  # Ethiopia
    "fa": "FRO",  # Faroe Islands
    "fm": "FSM",  # Federated States of Micronesia
    "fj": "FJI",  # Fiji
    "fi": "FIN",  # Finland
    "fr": "FRA",  # France
    "go": "GAB",  # Gabon
    "gs": "GEO",  # Georgia
    "gw": "DEU",  # Germany
    "gh": "GHA",  # Ghana
    "gi": "GIB",  # Gibraltar
    "gr": "GRC",  # Greece
    "gl": "GRL",  # Greenland
    "gd": "GRD",  # Grenada
    "gt": "GTM",  # Guatemala
    "gv": "GIN",  # Guinea
    "pg": "GNB",  # Guinea-Bissau
    "gy": "GUY",  # Guyana
    "ht": "HTI",  # Haiti
    "ho": "HND",  # Honduras
    "hu": "HUN",  # Hungary
    "ic": "ISL",  # Iceland
    "ii": "IND",  # India
    "io": "IDN",  # Indonesia
    "ir": "IRN",  # Iran
    "iq": "IRQ",  # Iraq
    "is": "ISR",  # Israel
    "it": "ITA",  # Italy
    "iv": "CIV",  # Ivory Coast
    "jm": "JAM",  # Jamaica
    "ja": "JPN",  # Japan
    "jo": "JOR",  # Jordan
    "kz": "KAZ",  # Kazakhstan
    "ke": "KEN",  # Kenya
    "gb": "KIR",  # Kiribati
    "ku": "KWT",  # Kuwait
    "kg": "KGZ",  # Kyrgyzstan
    "ls": "LAO",  # Laos
    "lv": "LVA",  # Latvia
    "le": "LBN",  # Lebanon
    "lo": "LSO",  # Lesotho
    "lb": "LBR",  # Liberia
    "ly": "LBY",  # Libya
    "lh": "LIE",  # Liechtenstein
    "li": "LTU",  # Lithuania
    "lu": "LUX",  # Luxembourg
    "mg": "MDG",  # Madagascar
    "mw": "MWI",  # Malawi
    "my": "MYS",  # Malaysia
    "xc": "MDV",  # Maldives
    "ml": "MLI",  # Mali
    "mm": "MLT",  # Malta
    "xe": "MHL",  # Marshall Islands
    "mu": "MRT",  # Mauritania
    "mf": "MUS",  # Mauritius
    "mx": "MEX",  # Mexico
    "mv": "MDA",  # Moldova
    "mc": "MCO",  # Monaco
    "mp": "MNG",  # Mongolia
    "mo": "MNE",  # Montenegro
    "mr": "MAR",  # Morocco
    "mz": "MOZ",  # Mozambique
    "br": "MMR",  # Myanmar
    "sx": "NAM",  # Namibia
    "nu": "NRU",  # Nauru
    "np": "NPL",  # Nepal
    "ne": "NLD",  # Netherlands
    "nz": "NZL",  # New Zealand
    "nq": "NIC",  # Nicaragua
    "ng": "NER",  # Niger
    "nr": "NGA",  # Nigeria
    "xh": "NIU",  # Niue
    "kn": "PRK",  # North Korea
    "xn": "MKD",  # North Macedonia
    "nw": "MNP",  # Northern Mariana Islands
    "no": "NOR",  # Norway
    "mk": "OMN",  # Oman
    "pk": "PAK",  # Pakistan
    "pw": "PLW",  # Palau
    "pn": "PAN",  # Panama
    "pp": "PNG",  # Papua New Guinea
    "py": "PRY",  # Paraguay
    "ch": "CHN",  # People's Republic of China
    "pe": "PER",  # Peru
    "ph": "PHL",  # Philippines
    "pl": "POL",  # Poland
    "po": "PRT",  # Portugal
    "qa": "QAT",  # Qatar
    "ie": "IRL",  # Republic of Ireland
    "cf": "COG",  # Republic of the Congo
    "rm": "ROU",  # Romania
    "ru": "RUS",  # Russia
    "rw": "RWA",  # Rwanda
    "xd": "KNA",  # Saint Kitts and Nevis
    "xk": "LCA",  # Saint Lucia
    "xm": "VCT",  # Saint Vincent and the Grenadines
    "ws": "WSM",  # Samoa
    "sm": "SMR",  # San Marino
    "su": "SAU",  # Saudi Arabia
    "sg": "SEN",  # Senegal
    "rb": "SRB",  # Serbia
    "yu": "SCG",  # Serbia and Montenegro
    "se": "SYC",  # Seychelles
    "sl": "SLE",  # Sierra Leone
    "si": "SGP",  # Singapore
    "sn": "SXM",  # Sint Maarten
    "xo": "SVK",  # Slovakia
    "xv": "SVN",  # Slovenia
    "bp": "SLB",  # Solomon Islands
    "so": "SOM",  # Somalia
    "sa": "ZAF",  # South Africa
    "ko": "KOR",  # South Korea
    "sd": "SSD",  # South Sudan
    "ur": "SUN",  # Soviet Union
    "xxr": "SUN",  # Soviet Union
    "sp": "ESP",  # Spain
    "ce": "LKA",  # Sri Lanka
    "sj": "SDN",  # Sudan
    "sr": "SUR",  # Suriname
    "sw": "SWE",  # Sweden
    "sz": "CHE",  # Switzerland
    "sy": "SYR",  # Syria
    "sf": "STP",  # São Tomé and Príncipe
    "ta": "TJK",  # Tajikistan
    "tz": "TZA",  # Tanzania
    "th": "THA",  # Thailand
    "bf": "BHS",  # The Bahamas
    "gm": "GMB",  # The Gambia
    "tg": "TGO",  # Togo
    "to": "TON",  # Tonga
    "tr": "TTO",  # Trinidad and Tobago
    "ti": "TUN",  # Tunisia
    "tu": "TUR",  # Turkey
    "tk": "TKM",  # Turkmenistan
    "tv": "TUV",  # Tuvalu
    "ug": "UGA",  # Uganda
    "un": "UKR",  # Ukraine
    "ts": "ARE",  # United Arab Emirates
    "xxk": "GBR",  # United Kingdom
    "xxu": "USA",  # United States of America
    "uy": "URY",  # Uruguay
    "uz": "UZB",  # Uzbekistan
    "nn": "VUT",  # Vanuatu
    "vc": "VAT",  # Vatican City
    "ve": "VEN",  # Venezuela
    "vm": "VNM",  # Vietnam
    "ye": "YEM",  # Yemen
    "za": "ZMB",  # Zambia
    "rh": "ZWE",  # Zimbabwe
}

# https://data.bnf.fr/vocabulary/countrycodes/x
bnf_country_dict = {
    "am": "ARM",  # Armenia
    "an": "NED",  # Antilles néerlandaises
    "ba": "BIH",  # Bosnia and Herzegovina
    "bn": "BRN",  # Brunei
    "cd": "COD",  # Congo (République démocratique)
    "cg": "COG",  # Congo
    "ir": "IRN",  # Iran
    "ru": "RUS",  # Russia
    "suhh": "SUN",  # Soviet Union (1922-1991)
    "tw": "TWN",  # Chine (République)
    "vn": "VNM",  # Viet Nam
    "xnhh": "NED",  # Belgique et Pays-Bas avant 1830
    "xdhh": "DEU",  # Allemagne avant 1945
    "yucs": "YUG",  # Yougoslavie (1918-2006)
    "ps": "PS",  # Autorité palestinienne
    "sy": "SYR",  # Syrie
    "hk": "HK",  # Hong Kong
}


#   SELECT distinct  ?c  (GROUP_CONCAT(DISTINCT ?wss; SEPARATOR = '@') AS ?wss_list)  WHERE {
#     ?item p:P31 ?statement0.
#     ?statement0 (ps:P31/(wdt:P279*)) wd:Q6256.
#     ?item wdt:P37 ?language;
#       wdt:P298 ?country_iso.
#     OPTIONAL { ?language wdt:P220 ?lan_iso3. }
#     OPTIONAL { ?language wdt:P221 ?lan_iso4. }
#     OPTIONAL { ?language wdt:P305 ?lan_ietf. }
#     OPTIONAL { ?language wdt:P1232 ?lan_lin. }
#     OPTIONAL { ?language wdt:P1394 ?lan_glotto. }
#     OPTIONAL { ?language wdt:P282 ?ws }
#     SERVICE wikibase:label {
#       bd:serviceParam wikibase:language "en".
#       ?item rdfs:label ?itemLabel.
#       ?language rdfs:label ?languageLabel.
#       ?ws rdfs:label ?wsLabel
#     }
#     BIND(COALESCE(?lan_iso3, ?lan_iso4, ?lan_ietf, ?lan_lin, ?lan_glotto, ?languageLabel) AS ?c).
#     BIND(COALESCE(?wsLabel, "EMPTY") as ?wss).
#     filter (! contains(?wss,"Braille"))
#   } group by ?c order by ?c

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
    "alb": "sqi",  # Albanian
    "arm": "hye",  # Armenian
    "baq": "eus",  # Basque
    "bur": "mya",  # Burmese
    "chi": "zho",  # Chinese
    "cze": "ces",  # Czech
    "dut": "nld",  # Dutch
    "fre": "fra",  # French
    "geo": "kat",  # Georgian
    "ger": "deu",  # German
    "gre": "ell",  # Modern Greek
    "ice": "isl",  # Icelandic
    "lav": "lvs",  # Latvian
    "mac": "mkd",  # Macedonian
    "mao": "mri",  # Māori
    "may": "msa",  # Malay
    "ori": "ory",  # Odia
    "per": "fas",  # Persian
    "rum": "ron",  # Romanian
    "slo": "slk",  # Slovak
    "tib": "bod",  # Tibetan
    "wel": "cym",  # Welsh
}


def get_iso639_3(iso639_2: str) -> str:
    if iso639_2 in iso639_2_dict:
        return iso639_2_dict[iso639_2]
    else:
        return iso639_2


# https://en.wikipedia.org/wiki/List_of_ISO_639-3_codes
iso639_3_dict = {
    "abk": [WRITING_SYSTEM_CYRILLIC_SCRIPT],  # Abkhaz
    "afr": [WRITING_SYSTEM_LATIN_SCRIPT],  # Afrikaans
    "sqi": [WRITING_SYSTEM_LATIN_SCRIPT, "Albanian alphabet"],  # Albanian
    "amh": ["Geʽez script"],  # Amharic
    "ami": [WRITING_SYSTEM_LATIN_SCRIPT],  # Amis
    "ara": [WRITING_SYSTEM_ARABIC_SCRIPT],  # Arabic
    "hye": [WRITING_SYSTEM_ARMENIAN_ALPHABET],  # Armenian
    "tay": [WRITING_SYSTEM_LATIN_SCRIPT],  # Atayal
    "asf": [],  # Auslan
    "en-AU": [WRITING_SYSTEM_LATIN_SCRIPT, "English alphabet"],  # Australian English
    "en-HK": [WRITING_SYSTEM_LATIN_SCRIPT, "English alphabet"],  # Hong Kong English
    "aym": [WRITING_SYSTEM_LATIN_SCRIPT],  # Aymara
    "aze": [
        WRITING_SYSTEM_ARABIC_ALPHABET,
        WRITING_SYSTEM_CYRILLIC_SCRIPT,
        WRITING_SYSTEM_LATIN_SCRIPT,
        WRITING_SYSTEM_PERSIAN_ALPHABET,
    ],  # Azerbaijani
    "pbp": [],  # Badyara
    "bjs": [],  # Bajan Creole
    "bala1300": [],  # Balanta
    "bal": [
        "Balochi Roman Orthography",
        "Balochi Standard Orthography",
        "Old Balochi Orthography",
    ],  # Balochi
    "bam": [WRITING_SYSTEM_LATIN_SCRIPT, "Ajami script", "NKo", "Masaba"],  # Bambara
    "ben": ["Bangla alphabet"],  # Bangla
    "bwg": [],  # Barwe
    "bel": [WRITING_SYSTEM_BELARUSIAN_CYRILLIC_ALPHABET],  # Belarusian
    "bis": [WRITING_SYSTEM_LATIN_SCRIPT, "Avoiuli"],  # Bislama
    "bib": [],  # Bissa
    "bobo": [],  # Bobo
    "nob": [WRITING_SYSTEM_LATIN_SCRIPT, "Dano-Norwegian alphabet"],  # Bokmål
    "bos": [WRITING_SYSTEM_GAJS_LATIN_ALPHABET],  # Bosnian
    "bozo1252": [],  # Bozo
    "bul": [WRITING_SYSTEM_CYRILLIC_SCRIPT, "Bulgarian alphabet"],  # Bulgarian
    "bnn": [WRITING_SYSTEM_LATIN_SCRIPT],  # Bunun
    "mya": ["Burmese alphabet", WRITING_SYSTEM_BURMESE],  # Burmese
    "kea": [WRITING_SYSTEM_LATIN_SCRIPT],  # Cape Verdean Creole
    "cal": [WRITING_SYSTEM_LATIN_SCRIPT],  # Carolinian
    "cat": [WRITING_SYSTEM_LATIN_SCRIPT],  # Catalan
    "cha": [WRITING_SYSTEM_LATIN_SCRIPT],  # Chamorro
    "nya": [WRITING_SYSTEM_LATIN_SCRIPT],  # Chewa
    "zho": [
        WRITING_SYSTEM_SINOGRAMS,
        WRITING_SYSTEM_TRADITIONAL_CHINESE_CHARACTERS,
        WRITING_SYSTEM_SIMPLIFIED_CHINESE_CHARACTERS,
    ],  # Chinese
    "como1260": [
        WRITING_SYSTEM_ARABIC_ALPHABET,
        WRITING_SYSTEM_LATIN_SCRIPT,
    ],  # Comorian
    "rar": [WRITING_SYSTEM_LATIN_SCRIPT],  # Cook Islands Maori
    "hrv": [WRITING_SYSTEM_GAJS_LATIN_ALPHABET],  # Croatian
    "ces": [WRITING_SYSTEM_LATIN_SCRIPT],  # Czech
    "dan": [WRITING_SYSTEM_LATIN_SCRIPT],  # Danish
    "prs": [
        "Q4363761",
        WRITING_SYSTEM_ARABIC_ALPHABET,
        WRITING_SYSTEM_PERSIAN_ALPHABET,
        WRITING_SYSTEM_ARABIC_SCRIPT,
    ],  # Dari
    "ell-dim": [],  # Demotic Greek
    "dyu": [WRITING_SYSTEM_LATIN_SCRIPT],  # Dioula
    "dogo1299": [],  # Dogon
    "nld": [WRITING_SYSTEM_LATIN_SCRIPT],  # Dutch
    "dzo": [WRITING_SYSTEM_TIBETAN_ALPHABET],  # Dzongkha
    "eng": [WRITING_SYSTEM_LATIN_SCRIPT, "English orthography"],  # English
    "est": [WRITING_SYSTEM_LATIN_SCRIPT],  # Estonian
    "fao": [WRITING_SYSTEM_LATIN_SCRIPT],  # Faroese
    "hif": [WRITING_SYSTEM_LATIN_SCRIPT, "Devanagari"],  # Fiji Hindi
    "fij": [WRITING_SYSTEM_LATIN_SCRIPT, "Devanagari"],  # Fijian
    "fil": [WRITING_SYSTEM_LATIN_SCRIPT],  # Filipino
    "fin": [WRITING_SYSTEM_LATIN_SCRIPT],  # Finnish
    "fra": [WRITING_SYSTEM_LATIN_SCRIPT],  # French
    "ful": [WRITING_SYSTEM_LATIN_SCRIPT, "Ajami script", "Adlam"],  # Fula
    "kat": [
        WRITING_SYSTEM_GEORGIAN_SCRIPTS,
        "Asomtavruli",
        "Mkhedruli",
        "Nuskhuri",
    ],  # Georgian
    "deu": [WRITING_SYSTEM_LATIN_SCRIPT, "German alphabet"],  # German
    "gil": [WRITING_SYSTEM_LATIN_SCRIPT],  # Gilbertese
    "grk": [WRITING_SYSTEM_GREEK_ALPHABET],  # Greek
    "kal": [WRITING_SYSTEM_LATIN_SCRIPT, "Eskimo alphabet"],  # Greenlandic
    "gcl": [],  # Grenadian Creole English
    "grn": [WRITING_SYSTEM_LATIN_SCRIPT],  # Guarani
    "hat": [WRITING_SYSTEM_LATIN_SCRIPT],  # Haitian Creole
    "mey": [WRITING_SYSTEM_ARABIC_ALPHABET],  # Hassaniya Arabic
    "heb": [WRITING_SYSTEM_HEBREW_ALPHABET],  # Hebrew
    "hin": ["Devanagari"],  # Hindi
    "hmo": [WRITING_SYSTEM_LATIN_SCRIPT],  # Hiri Motu
    "hun": [
        WRITING_SYSTEM_LATIN_SCRIPT,
        "Old Hungarian",
        "Hungarian alphabet",
    ],  # Hungarian
    "isl": [WRITING_SYSTEM_LATIN_SCRIPT, "Icelandic alphabet"],  # Icelandic
    "ind": [WRITING_SYSTEM_LATIN_SCRIPT],  # Indonesian
    "gle": [WRITING_SYSTEM_LATIN_SCRIPT, "Ogham", "Latin, Gaelic type"],  # Irish
    "ita": [WRITING_SYSTEM_LATIN_SCRIPT, "Italian alphabet"],  # Italian
    "jpn": [
        WRITING_SYSTEM_HIRAGANA,
        WRITING_SYSTEM_KANJI,
        WRITING_SYSTEM_KATAKANA,
        WRITING_SYSTEM_KANA,
    ],  # Japanese
    "kck": [],  # Kalanga
    "xnb": [],  # Kanakanavu
    "kao": [],  # Kassonke
    "ckv": [],  # Kavalan
    "kaz": [
        WRITING_SYSTEM_ARABIC_ALPHABET,
        WRITING_SYSTEM_CYRILLIC_SCRIPT,
        WRITING_SYSTEM_LATIN_SCRIPT,
    ],  # Kazakh
    "khm": ["Khmer"],  # Khmer
    "khi": [],  # Khoisan
    "Kinmen dialect": [],  # Kinmen dialect
    "kin": [WRITING_SYSTEM_LATIN_SCRIPT],  # Kinyarwanda
    "run": [WRITING_SYSTEM_LATIN_SCRIPT],  # Kirundi
    "kor": [WRITING_SYSTEM_HANGUL, WRITING_SYSTEM_HANJA],  # Korean
    "kri": [WRITING_SYSTEM_LATIN_SCRIPT],  # Krio
    "kur": [
        WRITING_SYSTEM_ARABIC_ALPHABET,
        WRITING_SYSTEM_CYRILLIC_SCRIPT,
        WRITING_SYSTEM_LATIN_SCRIPT,
    ],  # Kurdish
    "kir": [WRITING_SYSTEM_ARABIC_ALPHABET, WRITING_SYSTEM_CYRILLIC_SCRIPT],  # Kyrgyz
    "lao": ["Lao"],  # Lao
    "lat": [WRITING_SYSTEM_LATIN_SCRIPT, "Latin alphabet"],  # Latin
    "lav": [WRITING_SYSTEM_LATIN_SCRIPT, "Latvian alphabet"],  # Latvian
    "lvs": [WRITING_SYSTEM_LATIN_SCRIPT, "Latvian alphabet"],  # Latvian
    "lit": [WRITING_SYSTEM_LATIN_SCRIPT],  # Lithuanian
    "ltz": [WRITING_SYSTEM_LATIN_SCRIPT],  # Luxembourgish
    "mkd": [WRITING_SYSTEM_CYRILLIC_SCRIPT, "Macedonian alphabet"],  # Macedonian
    "mlg": [WRITING_SYSTEM_LATIN_SCRIPT, "Sorabe alphabet"],  # Malagasy
    "msa": [WRITING_SYSTEM_LATIN_SCRIPT, "Jawi", "Malay alphabet"],  # Malay
    "div": ["Thaana"],  # Maldivian
    "mlt": [WRITING_SYSTEM_LATIN_SCRIPT],  # Maltese
    "myq": [],  # Maninka
    "mah": [WRITING_SYSTEM_LATIN_SCRIPT],  # Marshallese
    "masu": [],  # Matsu dialect
    "myk": [],  # Minyanka
    "mwl": [WRITING_SYSTEM_LATIN_SCRIPT, "Mirandes alphabet"],  # Mirandese
    "ell": [WRITING_SYSTEM_GREEK_ALPHABET],  # Modern Greek
    "mon": [WRITING_SYSTEM_CYRILLIC_SCRIPT, "Mongolian"],  # Mongolian
    "cnr": [
        "Montenegrin Latin alphabet",
        WRITING_SYSTEM_MONTENEGRIN_CYRILLIC_ALPHABET,
    ],  # Montenegrin
    "mos": [WRITING_SYSTEM_LATIN_SCRIPT],  # Mooré
    "mri": [WRITING_SYSTEM_LATIN_SCRIPT, "Māori writing system"],  # Māori
    "nah": [WRITING_SYSTEM_LATIN_SCRIPT],  # Nahuatl
    "nmq": [WRITING_SYSTEM_LATIN_SCRIPT],  # Nambya
    "nau": [WRITING_SYSTEM_LATIN_SCRIPT],  # Nauruan
    "ndc": [],  # Ndau
    "nep": ["Devanagari"],  # Nepali
    "niu": [WRITING_SYSTEM_LATIN_SCRIPT],  # Niuean
    "ko-KP": [WRITING_SYSTEM_HANGUL],  # North Korean standard language
    "nde": [WRITING_SYSTEM_LATIN_SCRIPT],  # Northern Ndebele
    "nso": [WRITING_SYSTEM_LATIN_SCRIPT],  # Northern Sotho
    "nor": [WRITING_SYSTEM_LATIN_SCRIPT],  # Norwegian
    "nuri": [],  # Nuristani
    "nno": [WRITING_SYSTEM_LATIN_SCRIPT],  # Nynorsk
    "O-ku-uā": [],  # O-ku-uā
    "pwn": [],  # Paiwan
    "pau": [WRITING_SYSTEM_LATIN_SCRIPT],  # Palauan
    "pamr": [],  # Pamir
    "pap": [WRITING_SYSTEM_LATIN_SCRIPT],  # Papiamento
    "pash1270": [WRITING_SYSTEM_ARABIC_ALPHABET],  # Pashayi
    "pus": [WRITING_SYSTEM_ARABIC_ALPHABET, WRITING_SYSTEM_ARABIC_SCRIPT],  # Pashto
    "fas": [WRITING_SYSTEM_PERSIAN_ALPHABET, WRITING_SYSTEM_ARABIC_SCRIPT],  # Persian
    "pol": [WRITING_SYSTEM_LATIN_SCRIPT],  # Polish
    "por": [WRITING_SYSTEM_LATIN_SCRIPT, "Portuguese alphabet"],  # Portuguese
    "pyu": [],  # Puyuma
    "que": [WRITING_SYSTEM_LATIN_SCRIPT],  # Quechua
    "colo1257": [],  # Quichua
    "ron": [WRITING_SYSTEM_LATIN_SCRIPT],  # Romanian
    "roh": [WRITING_SYSTEM_LATIN_SCRIPT],  # Romansh
    "dru": [WRITING_SYSTEM_LATIN_SCRIPT],  # Rukai
    "rus": [WRITING_SYSTEM_CYRILLIC_SCRIPT, "Russian alphabet"],  # Russian
    "sxr": [],  # Saaroa
    "xsy": [WRITING_SYSTEM_LATIN_SCRIPT],  # Saisiyat
    "szy": [WRITING_SYSTEM_LATIN_SCRIPT],  # Sakizaya
    "smo": [WRITING_SYSTEM_LATIN_SCRIPT],  # Samoan
    "sag": [WRITING_SYSTEM_LATIN_SCRIPT],  # Sango
    "trv": [WRITING_SYSTEM_LATIN_SCRIPT],  # Seediq
    "snfo": [],  # Senufo
    "srp": [
        WRITING_SYSTEM_GAJS_LATIN_ALPHABET,
        WRITING_SYSTEM_SERBIAN_CYRILLIC_ALPHABET,
    ],  # Serbian
    "hbs": [
        WRITING_SYSTEM_CYRILLIC_SCRIPT,
        WRITING_SYSTEM_LATIN_SCRIPT,
        WRITING_SYSTEM_GAJS_LATIN_ALPHABET,
        WRITING_SYSTEM_SERBIAN_CYRILLIC_ALPHABET,
    ],  # Serbo-Croatian
    "sot": [WRITING_SYSTEM_LATIN_SCRIPT],  # Sesotho
    "crs": [WRITING_SYSTEM_LATIN_SCRIPT],  # Seychellois Creole
    "sna": [WRITING_SYSTEM_LATIN_SCRIPT],  # Shona
    "jiv": [],  # Shuar
    "sin": ["Sinhala"],  # Sinhala
    "slk": [WRITING_SYSTEM_LATIN_SCRIPT],  # Slovak
    "slv": [WRITING_SYSTEM_LATIN_SCRIPT],  # Slovene
    "som": [WRITING_SYSTEM_LATIN_SCRIPT, "Somali alphabets"],  # Somali
    "son": [],  # Songhay
    "snk": [WRITING_SYSTEM_LATIN_SCRIPT],  # Soninke
    "nbl": [WRITING_SYSTEM_LATIN_SCRIPT],  # Southern Ndebele
    "spa": [WRITING_SYSTEM_LATIN_SCRIPT],  # Spanish
    "Standard Algerian Berber": ["Berber Latin alphabet"],  # Standard Algerian Berber
    "huyu": [WRITING_SYSTEM_SINOGRAMS],  # Standard Mandarin
    "zgh": ["Neo-Tifinagh"],  # Standard Moroccan Amazigh
    "goyu": [],  # Standard Taiwanese Mandarin
    "swa": [WRITING_SYSTEM_LATIN_SCRIPT, "Swahili Ajami"],  # Swahili
    "ssw": [WRITING_SYSTEM_LATIN_SCRIPT],  # Swazi
    "swe": [WRITING_SYSTEM_LATIN_SCRIPT, "Swedish alphabet"],  # Swedish
    "smi": [WRITING_SYSTEM_LATIN_SCRIPT],  # Sámi
    "htia": [],  # Taiwanese Hakka
    "qtik": [],  # Taiwanese Hokkien
    "tgk": [
        WRITING_SYSTEM_CYRILLIC_SCRIPT,
        WRITING_SYSTEM_LATIN_SCRIPT,
        WRITING_SYSTEM_HEBREW_ALPHABET,
        WRITING_SYSTEM_PERSIAN_ALPHABET,
        "Tajik alphabet",
    ],  # Tajik
    "taq": [WRITING_SYSTEM_LATIN_SCRIPT, "Tifinagh"],  # Tamasheq
    "tam": [
        "Tamil script",
        WRITING_SYSTEM_ARABIC_SCRIPT,
        "Vatteluttu",
        "Koleluttu",
    ],  # Tamil
    "tet": [WRITING_SYSTEM_LATIN_SCRIPT, "Tetum alphabet"],  # Tetum
    "tha": [WRITING_SYSTEM_THAI_ALPHABET],  # Thai
    "tir": ["Geʽez script"],  # Tigrinya
    "tpi": [WRITING_SYSTEM_LATIN_SCRIPT],  # Tok Pisin
    "toi": [WRITING_SYSTEM_LATIN_SCRIPT],  # Tonga
    "ton": [WRITING_SYSTEM_LATIN_SCRIPT],  # Tongan
    "Truku": [],  # Truku
    "tso": [WRITING_SYSTEM_LATIN_SCRIPT],  # Tsonga
    "tsu": [],  # Tsou
    "tsn": [WRITING_SYSTEM_LATIN_SCRIPT],  # Tswana
    "tur": ["Turkish alphabet"],  # Turkish
    "tuk": [
        WRITING_SYSTEM_CYRILLIC_SCRIPT,
        WRITING_SYSTEM_LATIN_SCRIPT,
        "Turkmen alphabet",
        "Perso-Arabic script",
    ],  # Turkmen
    "tvl": [WRITING_SYSTEM_LATIN_SCRIPT],  # Tuvaluan
    "ukr": [WRITING_SYSTEM_CYRILLIC_SCRIPT],  # Ukrainian
    "urd": ["Urdu orthography"],  # Urdu
    "uzb": [
        WRITING_SYSTEM_ARABIC_ALPHABET,
        WRITING_SYSTEM_CYRILLIC_SCRIPT,
        WRITING_SYSTEM_LATIN_SCRIPT,
    ],  # Uzbek
    "ven": [WRITING_SYSTEM_LATIN_SCRIPT],  # Venda
    "vie": [
        WRITING_SYSTEM_LATIN_SCRIPT,
        "Vietnamese alphabet",
        "chữ Nôm",
    ],  # Vietnamese
    "wol": [
        WRITING_SYSTEM_ARABIC_ALPHABET,
        WRITING_SYSTEM_LATIN_SCRIPT,
        "Wolofal script",
    ],  # Wolof
    "xho": [WRITING_SYSTEM_LATIN_SCRIPT],  # Xhosa
    "tao": [],  # Yami
    "yua": [WRITING_SYSTEM_LATIN_SCRIPT],  # Yucatec Maya
    "zul": [WRITING_SYSTEM_LATIN_SCRIPT],  # Zulu
    "languages of China": [],  # languages of China; todo
    "languages of Mexico": [],  # languages of Mexico; todo
    # added - without country
    "fro": [WRITING_SYSTEM_LATIN_SCRIPT],  # Old French
    "frm": [WRITING_SYSTEM_LATIN_SCRIPT],  # Middle French
    "guj": ["Gujarati script"],  # Gujarati language
    "mul": [],  # multiple languages
    "und": [],  # undetermined
    "bod": [WRITING_SYSTEM_TIBETAN_SCRIPT],  # Lhasa Tibetan
    "fiu": [],  # iso639-5/fiu
    "yid": [WRITING_SYSTEM_HEBREW_ALPHABET, "Yiddish orthography"],  # Yiddish
    "ira": [WRITING_SYSTEM_PERSIAN_ALPHABET],  # The Iranian languages
    "ota": [WRITING_SYSTEM_OTTOMAN_TURKISH_ALPHABET],  # Ottoman Turkish
    "wen": [WRITING_SYSTEM_LATIN_SCRIPT],  # Sorbian languages
    "sah": [
        WRITING_SYSTEM_CYRILLIC_SCRIPT
    ],  # Sakha, or Yakut; Cyrillic (formerly Latin and Cyrillic-based)
    "tel": ["Telugu script"],  # Telugu language
    "orv-olr": [
        WRITING_SYSTEM_CYRILLIC_SCRIPT,
        "Belarusian Arabic alphabet",
        "Latin script",
    ],  # Ruthian
    "ang": ["Runic"],  # anglo-saxon (ca.450-1100)
    "pra": [],  # Prakrit
}

# SELECT ?country_iso (GROUP_CONCAT(DISTINCT ?c; SEPARATOR = '@') AS ?lan) ?itemLabel WHERE {
#   SELECT DISTINCT ?c ?country_iso ?itemLabel WHERE {
#     ?item p:P31 ?statement0.
#     ?statement0 (ps:P31/(wdt:P279*)) wd:Q6256.
#     ?item wdt:P37 ?language;
#       wdt:P298 ?country_iso.
#     OPTIONAL { ?language wdt:P220 ?lan_iso3. }
#     OPTIONAL { ?language wdt:P221 ?lan_iso4. }
#     OPTIONAL { ?language wdt:P305 ?lan_ietf. }
#     OPTIONAL { ?language wdt:P1232 ?lan_lin. }
#     OPTIONAL { ?language wdt:P1394 ?lan_glotto. }
#     FILTER(NOT EXISTS { ?language wdt:P31 wd:Q34228. })
#     SERVICE wikibase:label { bd:serviceParam wikibase:language "[AUTO_LANGUAGE]". }
#     SERVICE wikibase:label {
#       bd:serviceParam wikibase:language "en".
#       ?item rdfs:label ?itemLabel.
#       ?language rdfs:label ?languageLabel.
#     }
#     BIND(COALESCE(?lan_iso3, ?lan_iso4, ?lan_ietf, ?lan_lin, ?lan_glotto, ?languageLabel) AS ?c)
#   }
# } group by ?country_iso ?itemLabel order by ?itemLabel

official_languages_dict = {
    "ABW": ["nld", "pap"],  # Aruba
    "AFG": [
        "prs",
        "nuri",
        "uzb",
        "tuk",
        "ara",
        "bal",
        "pamr",
        "pash1270",
        "pus",
    ],  # Afghanistan
    "AGO": ["por"],  # Angola
    "ALB": ["sqi"],  # Albania
    "AND": ["cat"],  # Andorra
    "ARE": ["eng", "ara"],  # United Arab Emirates
    "ARG": ["spa"],  # Argentina
    "ARM": ["hye"],  # Armenia
    "ATG": ["eng"],  # Antigua and Barbuda
    "AUS": ["en-AU"],  # Australia
    "AUT": ["deu"],  # Austria
    "AZE": ["aze"],  # Azerbaijan
    "BDI": ["eng", "fra", "run"],  # Burundi
    "BEL": ["nld", "fra", "deu"],  # Belgium
    "BEN": ["fra"],  # Benin
    "BFA": ["dyu", "bib", "mos"],  # Burkina Faso
    "BGD": ["ben"],  # Bangladesh
    "BGR": ["bul"],  # Bulgaria
    "BHR": ["ara"],  # Bahrain
    "BHS": ["eng"],  # The Bahamas
    "BIH": ["hrv", "bos", "srp"],  # Bosnia and Herzegovina
    "BLR": ["rus", "bel"],  # Belarus
    "BLZ": ["eng"],  # Belize
    "BOL": ["spa", "que", "aym", "grn"],  # Bolivia
    "BRA": ["por"],  # Brazil
    "BRB": ["bjs", "eng"],  # Barbados
    "BRN": ["eng", "msa"],  # Brunei
    "BTN": ["dzo"],  # Bhutan
    "BWA": ["eng"],  # Botswana
    "CAF": ["fra", "sag"],  # Central African Republic
    "CAN": ["eng", "fra"],  # Canada
    "CHE": ["ita", "roh", "fra", "deu"],  # Switzerland
    "CHL": ["spa"],  # Chile
    "CHN": ["zho", "huyu", "languages of China"],  # People's Republic of China
    "CIV": ["fra"],  # Ivory Coast
    "CMR": ["eng", "fra"],  # Cameroon
    "CN-XZ": ["bod", "huyu", "zho"],
    "COD": ["fra"],  # Democratic Republic of the Congo
    "COG": ["fra"],  # Republic of the Congo
    "COK": ["eng", "rar"],  # Cook Islands
    "COL": ["spa"],  # Colombia
    "COM": ["ara", "fra", "como1260"],  # Comoros
    "CPV": ["por", "kea"],  # Cape Verde
    "CRI": ["spa"],  # Costa Rica
    "CSK": ["slk", "ces"],  # Czechoslovakia
    "CUB": ["spa"],  # Cuba
    "CUW": ["eng", "nld", "pap"],  # Curaçao
    "CYP": ["tur", "grk", "ell"],  # Cyprus
    "CZE": ["ces"],  # Czech Republic
    "DEU": ["deu"],  # Germany
    "DJI": ["ara", "fra"],  # Djibouti
    "DMA": ["eng"],  # Dominica
    "DNK": ["dan"],  # Denmark
    "DOM": ["spa"],  # Dominican Republic
    "DZA": ["ara", "Standard Algerian Berber"],  # Algeria
    "ECU": ["colo1257", "jiv", "spa"],  # Ecuador
    "EGY": ["ara"],  # Egypt
    "ERI": ["eng", "ara", "tir"],  # Eritrea
    "ESP": ["spa"],  # Spain
    "EST": ["est"],  # Estonia
    "ETH": ["amh"],  # Ethiopia
    "FIN": ["fin", "swe"],  # Finland
    "FJI": ["eng", "fij", "hif"],  # Fiji
    "FRA": ["fra"],  # France
    "FRO": ["dan", "fao"],  # Faroe Islands
    "FSM": ["eng"],  # Federated States of Micronesia
    "GAB": ["fra"],  # Gabon
    "GBR": ["eng"],  # United Kingdom
    "GEO": ["abk", "kat"],  # Georgia
    "GHA": ["eng"],  # Ghana
    "GIB": ["eng"],  # Gibraltar
    "GIN": ["fra"],  # Guinea
    "GMB": ["eng"],  # The Gambia
    "GNB": ["por"],  # Guinea-Bissau
    "GNQ": ["spa", "por", "fra"],  # Equatorial Guinea
    "GRC": ["grk", "ell-dim", "ell"],  # Greece
    "GRD": ["gcl", "eng"],  # Grenada
    "GRL": ["kal"],  # Greenland
    "GTM": ["spa"],  # Guatemala
    "GUY": ["eng"],  # Guyana
    "HND": ["spa"],  # Honduras
    "HRV": ["hrv"],  # Croatia
    "HTI": ["fra", "hat"],  # Haiti
    "HUN": ["hun"],  # Hungary
    "HVO": ["fra"],  # Republic of Upper Volta
    "IDN": ["ind"],  # Indonesia
    "IND": ["eng", "hin"],  # India
    "IRL": ["eng", "gle"],  # Republic of Ireland
    "IRN": ["fas"],  # Iran
    "IRQ": ["ara", "kur"],  # Iraq
    "ISL": ["isl"],  # Iceland
    "ISR": ["heb"],  # Israel
    "ITA": ["ita"],  # Italy
    "JAM": ["eng"],  # Jamaica
    "JOR": ["ara"],  # Jordan
    "JPN": ["jpn"],  # Japan
    "KAZ": ["rus", "kaz"],  # Kazakhstan
    "KEN": ["eng", "swa"],  # Kenya
    "KGZ": ["rus", "kir"],  # Kyrgyzstan
    "KHM": ["khm"],  # Cambodia
    "KIR": ["eng", "gil"],  # Kiribati
    "KNA": ["eng"],  # Saint Kitts and Nevis
    "KOR": ["kor"],  # South Korea
    "KWT": ["ara"],  # Kuwait
    "LAO": ["lao"],  # Laos
    "LBN": ["ara"],  # Lebanon
    "LBR": ["eng"],  # Liberia
    "LBY": ["ara"],  # Libya
    "LCA": ["eng"],  # Saint Lucia
    "LIE": ["deu"],  # Liechtenstein
    "LKA": ["tam", "sin"],  # Sri Lanka
    "LSO": ["eng", "sot"],  # Lesotho
    "LTU": ["lit"],  # Lithuania
    "LUX": ["ltz", "fra", "deu"],  # Luxembourg
    "LVA": ["lav", "lvs"],  # Latvia
    "MAC": ["zho", "por"],
    "MAR": ["zgh", "ara"],  # Morocco
    "MCO": ["fra"],  # Monaco
    "MDA": ["ron"],  # Moldova
    "MDG": ["mlg", "fra"],  # Madagascar
    "MDV": ["div"],  # Maldives
    "MEX": ["spa", "yua", "nah", "languages of Mexico"],  # Mexico
    "MHL": ["eng", "mah"],  # Marshall Islands
    "MKD": ["sqi", "mkd"],  # North Macedonia
    "MLI": [
        "dogo1299",
        "son",
        "bobo",
        "taq",
        "snfo",
        "bam",
        "ful",
        "bozo1252",
        "myq",
        "snk",
        "mey",
        "myk",
        "kao",
    ],  # Mali
    "MLT": ["eng", "mlt"],  # Malta
    "MMR": ["mya"],  # Myanmar
    "MNE": ["cnr"],  # Montenegro
    "MNG": ["mon"],  # Mongolia
    "MNP": ["eng", "cal", "cha"],  # Northern Mariana Islands
    "MOZ": ["por"],  # Mozambique
    "MRT": ["ara"],  # Mauritania
    "MUS": ["eng", "fra"],  # Mauritius
    "MWI": ["eng", "nya"],  # Malawi
    "MYS": ["msa"],  # Malaysia
    "NAM": ["eng"],  # Namibia
    "NER": ["fra"],  # Niger
    "NGA": ["eng"],  # Nigeria
    "NIC": ["spa"],  # Nicaragua
    "NIU": ["eng", "niu"],  # Niue
    "NLD": ["nld"],  # Kingdom of the Netherlands
    "NLD": ["nld"],  # Netherlands
    "NOR": ["nor", "nob", "nno", "smi"],  # Norway
    "NPL": ["nep"],  # Nepal
    "NRU": ["eng", "nau"],  # Nauru
    "NZL": ["eng", "mri"],  # New Zealand
    "OMN": ["ara"],  # Oman
    "PAK": ["urd", "eng"],  # Pakistan
    "PAN": ["spa"],  # Panama
    "PER": ["spa", "que", "aym"],  # Peru
    "PHL": ["eng", "fil"],  # Philippines
    "PLW": ["eng", "jpn", "pau"],  # Palau
    "PNG": ["eng", "hmo", "tpi"],  # Papua New Guinea
    "POL": ["pol"],  # Poland
    "PRK": ["kor", "ko-KP"],  # North Korea
    "PRT": ["por", "mwl"],  # Portugal
    "PRY": ["spa", "grn"],  # Paraguay
    "PS": ["ara", "heb", "eng"],
    "PSE": ["ara"],  # State of Palestine
    "Q172107": ["pol", "orv-olr", "lat"],  # Polish–Lithuanian Commonwealth (Q172107)
    "QAT": ["ara"],  # Qatar
    "ROU": ["ron"],  # Romania
    "RUS": ["rus"],  # Russia
    "RWA": ["eng", "swa", "fra", "kin"],  # Rwanda
    "SAU": ["ara"],  # Saudi Arabia
    "SCG": ["srp"],  # Serbia and Montenegro
    "SDN": ["eng", "ara"],  # Sudan
    "SEN": ["fra", "bala1300", "pbp", "wol"],  # Senegal
    "SGP": ["eng", "tam", "msa", "huyu"],  # Singapore
    "SLB": ["eng"],  # Solomon Islands
    "SLE": ["eng", "kri"],  # Sierra Leone
    "SLV": ["spa"],  # El Salvador
    "SMR": ["ita"],  # San Marino
    "SOM": ["som", "ara"],  # Somalia
    "SRB": ["srp"],  # Serbia
    "SSD": ["eng", "ara"],  # South Sudan
    "STP": ["por"],  # São Tomé and Príncipe
    "SUN": ["rus"],  # Soviet Union
    "SUN": ["rus"],  # Soviet Union (1922-1991)
    "SUR": ["nld"],  # Suriname
    "SVK": ["slk"],  # Slovakia
    "SVN": ["slv"],  # Slovenia
    "SWE": ["swe"],  # Sweden
    "SWZ": ["eng", "ssw"],  # Eswatini
    "SXM": ["eng", "nld"],  # Sint Maarten
    "SYC": ["eng", "fra", "crs"],  # Seychelles
    "SYR": ["ara"],  # Syria
    "TCD": ["ara", "fra"],  # Chad
    "TGO": ["fra"],  # Togo
    "THA": ["tha"],  # Thailand
    "TJK": ["rus", "tgk"],  # Tajikistan
    "TKM": ["tuk"],  # Turkmenistan
    "TLS": ["por", "tet"],  # East Timor
    "TON": ["eng", "ton"],  # Tonga
    "TTO": ["eng"],  # Trinidad and Tobago
    "TUN": ["ara"],  # Tunisia
    "TUR": ["tur"],  # Turkey
    "TUV": ["eng", "tvl"],  # Tuvalu
    "TWN": [
        "pwn",
        "szy",
        "tay",
        "trv",
        "xnb",
        "pyu",
        "tao",
        "xsy",
        "goyu",
        "tsu",
        "ckv",
        "sxr",
        "ami",
        "htia",
        "masu",
        "Kinmen dialect",
        "O-ku-uā",
        "Truku",
        "bnn",
        "dru",
        "qtik",
    ],  # Taiwan
    "TZA": ["eng", "swa"],  # Tanzania
    "UGA": ["eng", "swa"],  # Uganda
    "UKR": ["ukr"],  # Ukraine
    "URY": ["spa"],  # Uruguay
    "USA": ["eng"],  # United States of America
    "UZB": ["uzb"],  # Uzbekistan
    "VAT": ["lat", "ita", "fra"],  # Vatican City
    "VCT": ["eng"],  # Saint Vincent and the Grenadines
    "VEN": ["spa"],  # Venezuela
    "VNM": ["vie"],  # Vietnam
    "VUT": ["eng", "fra", "bis"],  # Vanuatu
    "WSM": ["eng", "smo"],  # Samoa
    "YEM": ["ara"],  # Yemen
    "YUG": ["mkd", "slv", "hbs", "srp"],
    # # todo : double
    # "YUG": [
    #     "mkd",
    #     "slv",
    #     "hbs",
    # ],  # Socialist Federal Republic of Yugoslavia 1945 to 1992
    # "YUG": ["srp"],  # Federal Republic of Yugoslavia 1992–2003
    "ZAF": [
        "eng",
        "zul",
        "xho",
        "ven",
        "afr",
        "nso",
        "ssw",
        "sot",
        "tsn",
        "tso",
        "nbl",
    ],  # South Africa
    "ZMB": ["eng"],  # Zambia
    "ZWE": [
        "bwg",
        "nmq",
        "eng",
        "xho",
        "ndc",
        "ven",
        "nya",
        "kck",
        "tsn",
        "tso",
        "nde",
        "sna",
        "toi",
        "sot",
        "khi",
    ],  # Zimbabwe
    "HK": ["zho", "en-HK"],
}

# SELECT DISTINCT ?item ?itemLabel ?geo ?iso WHERE {
#   SERVICE wikibase:label { bd:serviceParam wikibase:language "[AUTO_LANGUAGE]". }
#   {
#     SELECT DISTINCT ?item ?geo ?iso WHERE {
#       ?item p:P31 ?statement0.
#       ?statement0 (ps:P31/(wdt:P279*)) wd:Q6256.
#       ?item wdt:P1566 ?geo.
#       ?item wdt:P298 ?iso
#     }
#     LIMIT 5
#   }
# }
# http://sws.geonames.org/x
geonames_country_dict = {
    "1149361": "AFG",  # Afghanistan
    "783754": "ALB",  # Albania
    "2589581": "DZA",  # Algeria
    "3041565": "AND",  # Andorra
    "3351879": "AGO",  # Angola
    "3576396": "ATG",  # Antigua and Barbuda
    "3865483": "ARG",  # Argentina
    "174982": "ARM",  # Armenia
    "3577279": "ABW",  # Aruba
    "2077456": "AUS",  # Australia
    "2782113": "AUT",  # Austria
    "587116": "AZE",  # Azerbaijan
    "290291": "BHR",  # Bahrain
    "1210997": "BGD",  # Bangladesh
    "3374084": "BRB",  # Barbados
    "630336": "BLR",  # Belarus
    "2802361": "BEL",  # Belgium
    "3582678": "BLZ",  # Belize
    "2395170": "BEN",  # Benin
    "1252634": "BTN",  # Bhutan
    "3923057": "BOL",  # Bolivia
    "3277605": "BIH",  # Bosnia and Herzegovina
    "933860": "BWA",  # Botswana
    "3469034": "BRA",  # Brazil
    "1820814": "BRN",  # Brunei
    "732800": "BGR",  # Bulgaria
    "2361809": "BFA",  # Burkina Faso
    "433561": "BDI",  # Burundi
    "1831722": "KHM",  # Cambodia
    "2233387": "CMR",  # Cameroon
    "6251999": "CAN",  # Canada
    "3374766": "CPV",  # Cape Verde
    "239880": "CAF",  # Central African Republic
    "2434508": "TCD",  # Chad
    "3895114": "CHL",  # Chile
    "3686110": "COL",  # Colombia
    "921929": "COM",  # Comoros
    "1899402": "COK",  # Cook Islands
    "3624060": "CRI",  # Costa Rica
    "3202326": "HRV",  # Croatia
    "3562981": "CUB",  # Cuba
    "7626836": "CUW",  # Curaçao
    "146669": "CYP",  # Cyprus
    "3077311": "CZE",  # Czech Republic
    "8505031": "CSK",  # Czechoslovakia
    "203312": "COD",  # Democratic Republic of the Congo
    "2623032": "DNK",  # Denmark
    "223816": "DJI",  # Djibouti
    "3575830": "DMA",  # Dominica
    "3508796": "DOM",  # Dominican Republic
    "1966436": "TLS",  # East Timor
    "3658394": "ECU",  # Ecuador
    "357994": "EGY",  # Egypt
    "3585968": "SLV",  # El Salvador
    "2309096": "GNQ",  # Equatorial Guinea
    "338010": "ERI",  # Eritrea
    "453733": "EST",  # Estonia
    "934841": "SWZ",  # Eswatini
    "337996": "ETH",  # Ethiopia
    "2622320": "FRO",  # Faroe Islands
    "2081918": "FSM",  # Federated States of Micronesia
    "2205218": "FJI",  # Fiji
    "660013": "FIN",  # Finland
    "3017382": "FRA",  # France
    "2400553": "GAB",  # Gabon
    "614540": "GEO",  # Georgia
    "2921044": "DEU",  # Germany
    "2300660": "GHA",  # Ghana
    "2411586": "GIB",  # Gibraltar
    "2411585": "GIB",  # Gibraltar
    "390903": "GRC",  # Greece
    "3425505": "GRL",  # Greenland
    "3580239": "GRD",  # Grenada
    "3595528": "GTM",  # Guatemala
    "2420477": "GIN",  # Guinea
    "2372248": "GNB",  # Guinea-Bissau
    "3378535": "GUY",  # Guyana
    "3723988": "HTI",  # Haiti
    "3608932": "HND",  # Honduras
    "719819": "HUN",  # Hungary
    "2629691": "ISL",  # Iceland
    "1269750": "IND",  # India
    "1643084": "IDN",  # Indonesia
    "130758": "IRN",  # Iran
    "99237": "IRQ",  # Iraq
    "294640": "ISR",  # Israel
    "3175395": "ITA",  # Italy
    "2287781": "CIV",  # Ivory Coast
    "3489940": "JAM",  # Jamaica
    "1861060": "JPN",  # Japan
    "248816": "JOR",  # Jordan
    "1522867": "KAZ",  # Kazakhstan
    "192950": "KEN",  # Kenya
    "2750405": "NLD",  # Kingdom of the Netherlands
    "4030945": "KIR",  # Kiribati
    "285570": "KWT",  # Kuwait
    "1527747": "KGZ",  # Kyrgyzstan
    "1655842": "LAO",  # Laos
    "458258": "LVA",  # Latvia
    "272103": "LBN",  # Lebanon
    "932692": "LSO",  # Lesotho
    "2275384": "LBR",  # Liberia
    "2215636": "LBY",  # Libya
    "3042058": "LIE",  # Liechtenstein
    "597427": "LTU",  # Lithuania
    "2960313": "LUX",  # Luxembourg
    "1062947": "MDG",  # Madagascar
    "927384": "MWI",  # Malawi
    "1733045": "MYS",  # Malaysia
    "1282028": "MDV",  # Maldives
    "2453866": "MLI",  # Mali
    "2562770": "MLT",  # Malta
    "2080185": "MHL",  # Marshall Islands
    "2378080": "MRT",  # Mauritania
    "934292": "MUS",  # Mauritius
    "3996063": "MEX",  # Mexico
    "617790": "MDA",  # Moldova
    "2993457": "MCO",  # Monaco
    "2029969": "MNG",  # Mongolia
    "3194884": "MNE",  # Montenegro
    "2542007": "MAR",  # Morocco
    "1036973": "MOZ",  # Mozambique
    "1327865": "MMR",  # Myanmar
    "3355338": "NAM",  # Namibia
    "2110425": "NRU",  # Nauru
    "1282988": "NPL",  # Nepal
    "2750405": "NLD",  # Netherlands
    "2186224": "NZL",  # New Zealand
    "3617476": "NIC",  # Nicaragua
    "2440476": "NER",  # Niger
    "2328926": "NGA",  # Nigeria
    "4036232": "NIU",  # Niue
    "1873107": "PRK",  # North Korea
    "718075": "MKD",  # North Macedonia
    "4041468": "MNP",  # Northern Mariana Islands
    "3144096": "NOR",  # Norway
    "286963": "OMN",  # Oman
    "1168579": "PAK",  # Pakistan
    "1559582": "PLW",  # Palau
    "3703430": "PAN",  # Panama
    "2088628": "PNG",  # Papua New Guinea
    "3437598": "PRY",  # Paraguay
    "1814991": "CHN",  # People's Republic of China
    "3932488": "PER",  # Peru
    "1694008": "PHL",  # Philippines
    "798544": "POL",  # Poland
    "2264397": "PRT",  # Portugal
    "289688": "QAT",  # Qatar
    "2963597": "IRL",  # Republic of Ireland
    "2260494": "COG",  # Republic of the Congo
    "798549": "ROU",  # Romania
    "2017370": "RUS",  # Russia
    "49518": "RWA",  # Rwanda
    "3575174": "KNA",  # Saint Kitts and Nevis
    "3576468": "LCA",  # Saint Lucia
    "3577815": "VCT",  # Saint Vincent and the Grenadines
    "4034894": "WSM",  # Samoa
    "3168068": "SMR",  # San Marino
    "102358": "SAU",  # Saudi Arabia
    "2245662": "SEN",  # Senegal
    "6290252": "SRB",  # Serbia
    "8505033": "SCG",  # Serbia and Montenegro
    "241170": "SYC",  # Seychelles
    "2403846": "SLE",  # Sierra Leone
    "1880251": "SGP",  # Singapore
    "7609695": "SXM",  # Sint Maarten
    "3057568": "SVK",  # Slovakia
    "3190538": "SVN",  # Slovenia
    "2103350": "SLB",  # Solomon Islands
    "51537": "SOM",  # Somalia
    "953987": "ZAF",  # South Africa
    "1835841": "KOR",  # South Korea
    "7909807": "SSD",  # South Sudan
    "8354411": "SUN",  # Soviet Union
    "2510769": "ESP",  # Spain
    "1227603": "LKA",  # Sri Lanka
    "6254930": "PSE",  # State of Palestine
    "366755": "SDN",  # Sudan
    "3382998": "SUR",  # Suriname
    "2661886": "SWE",  # Sweden
    "2658434": "CHE",  # Switzerland
    "163843": "SYR",  # Syria
    "2410758": "STP",  # São Tomé and Príncipe
    "1668284": "TWN",  # Taiwan
    "1220409": "TJK",  # Tajikistan
    "149590": "TZA",  # Tanzania
    "1605651": "THA",  # Thailand
    "3572887": "BHS",  # The Bahamas
    "2413451": "GMB",  # The Gambia
    "2363686": "TGO",  # Togo
    "4032283": "TON",  # Tonga
    "3573591": "TTO",  # Trinidad and Tobago
    "2464461": "TUN",  # Tunisia
    "298795": "TUR",  # Turkey
    "1218197": "TKM",  # Turkmenistan
    "2110297": "TUV",  # Tuvalu
    "226074": "UGA",  # Uganda
    "690791": "UKR",  # Ukraine
    "290557": "ARE",  # United Arab Emirates
    "2635167": "GBR",  # United Kingdom
    "6252001": "USA",  # United States of America
    "3439705": "URY",  # Uruguay
    "1512440": "UZB",  # Uzbekistan
    "2134431": "VUT",  # Vanuatu
    "3164670": "VAT",  # Vatican City
    "3625428": "VEN",  # Venezuela
    "1562822": "VNM",  # Vietnam
    "69543": "YEM",  # Yemen
    "895949": "ZMB",  # Zambia
    "878675": "ZWE",  # Zimbabwe
    # added
    "1821275": "MAC",  # macau-special-administrative-region
}

# todo: omzetten naar lijst
qid_country = {
    "Q142": "FRA",  # France (Q142)
    "Q15180": "SUN",  # Soviet Union (Q15180)
    "Q159": "RUS",  # Russia (Q159)
    "Q170072": "NLD",  # Dutch Republic (Q170072)
    "Q172107": "Q172107",  # Polish–Lithuanian Commonwealth (Q172107)
    "Q212": "UKR",  # Ukraine (Q212)
    "Q215": "SVN",  # Slovenia (Q215)
    "Q218": "ROU",  # Romania (Q218)
    "Q28": "HUN",  # Hungary (Q28)
    "Q28513": "HUN",  # Austria-Hungary (Q28513)
    "Q29": "ESP",  # Spain (Q29)
    "Q30": "USA",  # United States of America (Q30)
    "Q34266": "RUS",  # Russian Empire (Q34266)
    "Q801": "ISR",  # Israel (Q801)
    "Q83286": "YUG",  # Socialist Federal Republic of Yugoslavia (Q83286)
    "Q36": "POL",  # Poland (Q36)
    # todo ; country + languages
    "Q191077": "",  # Kingdom of Yugoslavia (Q191077) 1929–1945
    "Q211": "LVA",  # Latvia (Q211)
    "Q403": "SRB",  # Serbia (Q403)
    "Q155": "BRA",  # Brazil (Q155)
    "Q822": "LBN",  # Lebanon (Q822)
    "Q174193": "GBR",  # United Kingdom of Great Britain and Ireland (Q174193)
    "Q40": "AUT",  # Austria (Q40)
    "Q756617": "DNK",  # Kingdom of Denmark (Q756617)
}
qid_language = {
    "Q1321": "spa",  # Spanish (Q1321)
    "Q150": "fra",  # French (Q150)
    "Q1860": "eng",  # English (Q1860)
    "Q6654": "hrv",  # Croatian (Q6654)
    "Q7411": "nld",  # Dutch (Q7411)
    "Q7737": "rus",  # Russian (Q7737)
    "Q809": "pol",  # Polish (Q809)
    "Q9056": "ces",  # Czech (Q9056)
    "Q9058": "slk",  # Slovak (Q9058)
    "Q9063": "slv",  # Slovene (Q9063)
    "Q9255": "kir",  # Kyrgyz (Q9255)
    "Q9299": "srp",  # Serbian (Q9299)
}

wikidata_language = {
    "ky": "kir",
    "fr": "fra",
    "nl": "nld",
}

# https://en.wikipedia.org/wiki/List_of_Wikipedias
# todo: talen gebruiken
wikidata_sitelink = {
    "cswiki": "CZE",
    "svwiki": "SWE",
    "trwiki": "TUR",
    "azwiki": "AZE",
    "bewiki": "BLR",
    "huwiki": "HUN",
    "jawiki": "JPN",
    "kywiki": "KGZ",
    "lvwiki": "LVA",
    "plwiki": "POL",
    "ruwiki": "RUS",
    "ukwiki": "UKR",
}
