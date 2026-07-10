import json
import os.path
import re
from typing import Dict, List
from addlabel.paths import DATA_DIR
from addlabel.wdqs_client import query_wdqs_simple

QID_AFGHANISTAN = "Q889"
QID_ALBANIA = "Q222"
QID_ALGERIA = "Q262"
QID_ANDORRA = "Q228"
QID_ANGOLA = "Q916"
QID_ANTIGUA_AND_BARBUDA = "Q781"
QID_ARGENTINA = "Q414"
QID_ARMENIA = "Q399"
QID_ARUBA = "Q21203"
QID_AUSTRALIA = "Q408"
QID_AUSTRIA = "Q40"
QID_AZERBAIJAN = "Q227"
QID_BAHRAIN = "Q398"
QID_BANGLADESH = "Q902"
QID_BARBADOS = "Q244"
QID_BELARUS = "Q184"
QID_BELGIUM = "Q31"
QID_BELIZE = "Q242"
QID_BENIN = "Q962"
QID_BHUTAN = "Q917"
QID_BOLIVIA = "Q750"
QID_BOSNIA_AND_HERZEGOVINA = "Q225"
QID_BOTSWANA = "Q963"
QID_BRAZIL = "Q155"
QID_BRUNEI_DARUSSALAM = "Q921"
QID_BULGARIA = "Q219"
QID_BURKINA_FASO = "Q965"
QID_BURUNDI = "Q967"
QID_BYELORUSSIAN_SOVIET_SOCIALIST_REPUBLIC = "Q2895"
QID_CAMBODIA = "Q424"
QID_CAMEROON = "Q1009"
QID_CANADA = "Q16"
QID_CAPE_VERDE = "Q1011"
QID_CENTRAL_AFRICAN_REPUBLIC = "Q929"
QID_CHAD = "Q657"
QID_CHILE = "Q298"
QID_COLOMBIA = "Q739"
QID_COMOROS = "Q970"
QID_COOK_ISLANDS = "Q26988"
QID_COSTA_RICA = "Q800"
QID_CROATIA = "Q224"
QID_CUBA = "Q241"
QID_CURACAO = "Q25279"
QID_CYPRUS = "Q229"
QID_CZECH_REPUBLIC = "Q213"
QID_CZECHOSLOVAKIA = "Q33946"
QID_DEMOCRATIC_REPUBLIC_OF_THE_CONGO = "Q974"
QID_DENMARK = "Q35"
QID_DJIBOUTI = "Q977"
QID_DOMINICA = "Q784"
QID_DOMINICAN_REPUBLIC = "Q786"
QID_EAST_TIMOR = "Q574"
QID_ECUADOR = "Q736"
QID_EGYPT = "Q79"
QID_EL_SALVADOR = "Q792"
QID_EQUATORIAL_GUINEA = "Q983"
QID_ERITREA = "Q986"
QID_ESTONIA = "Q191"
QID_ESWATINI = "Q1050"
QID_ETHIOPIA = "Q115"
QID_FAROE_ISLANDS = "Q4628"
QID_FEDERAL_REPUBLIC_OF_YUGOSLAVIA = "Q838261"
QID_FEDERATED_STATES_OF_MICRONESIA = "Q702"
QID_FIJI = "Q712"
QID_FINLAND = "Q33"
QID_FRANCE = "Q142"
QID_GABON = "Q1000"
QID_GEORGIA = "Q230"
QID_GERMAN_DEMOCRATIC_REPUBLIC = "Q16957"
QID_GERMANY = "Q183"
QID_GHANA = "Q117"
QID_GIBRALTAR = "Q1410"
QID_GREECE = "Q41"
QID_GREENLAND = "Q223"
QID_GRENADA = "Q769"
QID_GUATEMALA = "Q774"
QID_GUINEA = "Q1006"
QID_GUINEA_BISSAU = "Q1007"
QID_GUYANA = "Q734"
QID_HAITI = "Q790"
QID_HONDURAS = "Q783"
QID_HUNGARY = "Q28"
QID_ICELAND = "Q189"
QID_INDIA = "Q668"
QID_INDONESIA = "Q252"
QID_IRAN = "Q794"
QID_IRAQ = "Q796"
QID_ISRAEL = "Q801"
QID_ITALY = "Q38"
QID_IVORY_COAST = "Q1008"
QID_JAMAICA = "Q766"
QID_JAPAN = "Q17"
QID_JORDAN = "Q810"
QID_KAZAKHSTAN = "Q232"
QID_KENYA = "Q114"
QID_KINGDOM_OF_THE_NETHERLANDS = "Q29999"
QID_KIRIBATI = "Q710"
QID_KUWAIT = "Q817"
QID_KYRGYZSTAN = "Q813"
QID_LAOS = "Q819"
QID_LATVIA = "Q211"
QID_LEBANON = "Q822"
QID_LESOTHO = "Q1013"
QID_LIBERIA = "Q1014"
QID_LIBYA = "Q1016"
QID_LIECHTENSTEIN = "Q347"
QID_LITHUANIA = "Q37"
QID_LUXEMBOURG = "Q32"
QID_MADAGASCAR = "Q1019"
QID_MALAWI = "Q1020"
QID_MALAYSIA = "Q833"
QID_MALDIVES = "Q826"
QID_MALI = "Q912"
QID_MALTA = "Q233"
QID_MARSHALL_ISLANDS = "Q709"
QID_MAURITANIA = "Q1025"
QID_MAURITIUS = "Q1027"
QID_MEXICO = "Q96"
QID_MOLDOVA = "Q217"
QID_MONACO = "Q235"
QID_MONGOLIA = "Q711"
QID_MONTENEGRO = "Q236"
QID_MOROCCO = "Q1028"
QID_MOZAMBIQUE = "Q1029"
QID_MYANMAR = "Q836"
QID_NAMIBIA = "Q1030"
QID_NAURU = "Q697"
QID_NEPAL = "Q837"
QID_NETHERLANDS = "Q55"
QID_NETHERLANDS_ANTILLES = "Q25227"
QID_NEW_HEBRIDES = "Q752431"
QID_NEW_ZEALAND = "Q664"
QID_NICARAGUA = "Q811"
QID_NIGER = "Q1032"
QID_NIGERIA = "Q1033"
QID_NIUE = "Q34020"
QID_NORTH_KOREA = "Q423"
QID_NORTH_MACEDONIA = "Q221"
QID_NORTHERN_MARIANA_ISLANDS = "Q16644"
QID_NORWAY = "Q20"
QID_OMAN = "Q842"
QID_PAKISTAN = "Q843"
QID_PALAU = "Q695"
QID_PANAMA = "Q804"
QID_PAPUA_NEW_GUINEA = "Q691"
QID_PARAGUAY = "Q733"
QID_CHINA = "Q148"
QID_PERU = "Q419"
QID_PHILIPPINES = "Q928"
QID_POLAND = "Q36"
QID_PORTUGAL = "Q45"
QID_QATAR = "Q846"
QID_REPUBLIC_OF_DAHOMEY = "Q798431"
QID_REPUBLIC_OF_IRELAND = "Q27"
QID_REPUBLIC_OF_UPPER_VOLTA = "Q797422"
QID_REPUBLIC_OF_THE_CONGO = "Q971"
QID_ROMANIA = "Q218"
QID_RUSSIA = "Q159"
QID_RWANDA = "Q1037"
QID_SAINT_KITTS_AND_NEVIS = "Q763"
QID_SAINT_LUCIA = "Q760"
QID_SAINT_VINCENT_AND_THE_GRENADINES = "Q757"
QID_SAMOA = "Q683"
QID_SAN_MARINO = "Q238"
QID_SAUDI_ARABIA = "Q851"
QID_SENEGAL = "Q1041"
QID_SERBIA = "Q403"
QID_SERBIA_AND_MONTENEGRO = "Q37024"
QID_SEYCHELLES = "Q1042"
QID_SIERRA_LEONE = "Q1044"
QID_SINGAPORE = "Q334"
QID_SINT_MAARTEN = "Q26273"
QID_SLOVAKIA = "Q214"
QID_SLOVENIA = "Q215"
QID_SOCIALIST_FEDERAL_REPUBLIC_OF_YUGOSLAVIA = "Q83286"
QID_SOLOMON_ISLANDS = "Q685"
QID_SOMALIA = "Q1045"
QID_SOUTH_AFRICA = "Q258"
QID_SOUTH_KOREA = "Q884"
QID_SOUTH_SUDAN = "Q958"
QID_SOVIET_UNION = "Q15180"
QID_SPAIN = "Q29"
QID_SRI_LANKA = "Q854"
QID_STATE_OF_PALESTINE = "Q219060"
QID_SUDAN = "Q1049"
QID_SURINAME = "Q730"
QID_SWEDEN = "Q34"
QID_SWITZERLAND = "Q39"
QID_SYRIA = "Q858"
QID_SAO_TOME_AND_PRINCIPE = "Q1039"
QID_TAIWAN = "Q865"
QID_TAJIKISTAN = "Q863"
QID_TANZANIA = "Q924"
QID_THAILAND = "Q869"
QID_THE_BAHAMAS = "Q778"
QID_CAYMAN_ISLANDS = "Q5785"
QID_REUNION = "Q17070"
QID_THE_GAMBIA = "Q1005"
QID_TOGO = "Q945"
QID_TONGA = "Q678"
QID_TRINIDAD_AND_TOBAGO = "Q754"
QID_TUNISIA = "Q948"
QID_TURKEY = "Q43"
QID_TURKMENISTAN = "Q874"
QID_TUVALU = "Q672"
QID_UGANDA = "Q1036"
QID_UKRAINE = "Q212"
QID_UNITED_ARAB_EMIRATES = "Q878"
QID_UNITED_KINGDOM = "Q145"
QID_USA = "Q30"
QID_URUGUAY = "Q77"
QID_UZBEKISTAN = "Q265"
QID_VANUATU = "Q686"
QID_VATICAN_CITY = "Q237"
QID_VENEZUELA = "Q717"
QID_VIETNAM = "Q881"
QID_YEMEN = "Q805"
QID_ZAMBIA = "Q953"
QID_ZIMBABWE = "Q954"
# added
QID_HONG_KONG = "Q8646"
QID_TIBET_AUTONOMOUS_REGION = "Q17269"
QID_GUERNSEY = "Q25230"  # qid changed
QID_ISLE_OF_MAN = "Q9676"
QID_AMERICAN_SAMOA = "Q16641"
QID_MARTINIQUE = "Q17054"
QID_MAYOTTE = "Q17063"
QID_KOSOVO = "Q1246"
QID_MACAU = "Q14773"
QID_PALESTINIAN_NATIONAL_AUTHORITY = "Q219060"  # qid changed
QID_PUERTO_RICO = "Q1183"
QID_EAST_TIMOR = "Q574"
QID_KINGDOM_OF_HUNGARY = "Q171150"
QID_KINGDOM_OF_ITALY = "Q172579"
QID_JERSEY = "Q785"
QID_PITCAIRN_ISLANDS = "Q35672"
QID_BYZANTINE_EMPIRE = "Q12544"
QID_ROMAN_EMPIRE = "Q2277"
QID_OTTOMAN_EMPIRE = "Q12560"
QID_RUSSIAN_SOVIET_FEDERATIVE_SOCIALIST_REPUBLIC = "Q2184"
QID_MADEIRA = "Q26253"
QID_FRENCH_INDOCHINA = "Q185682"
QID_CANARY_ISLANDS = "Q5813"
QID_WEST_GERMANY = "Q713750"
QID_GUADELOUPE = "Q17012"
QID_NEW_CALEDONIA = "Q33788"
QID_ELECTORATE_OF_MAINZ = "Q284667"
QID_CROWN_OF_CASTILE = "Q217196"
QID_ANCIENT_GREECE = "Q11772"
QID_SAINT_BARTHELEMY = "Q25362"
QID_MIDDLE_EAST = "Q7204"
QID_CISLEITHANIA = "Q533534"
QID_KOREA_UNDER_JAPANESE_RULE = "Q503585"
QID_MANDATORY_PALESTINE = "Q193714"
QID_KIRGHIZ_SOVIET_SOCIALIST_REPUBLIC = "Q130276"
QID_WEST_BANK = "Q36678"
QID_GUAM = "Q16635"
QID_FRENCH_GUIANA = "Q3769"
QID_ASIA = "Q48"
QID_ANTARCTICA = "Q51"
QID_CARIBBEAN = "Q664609"
QID_AFRICA = "Q15"
#QID_THE_BAHAMAS = "Q778"
QID_CANADIAN_PRAIRIES = "Q1364746"
#QID_CAPE_VERDE = "Q1011"
QID_LATIN_AMERICA = "Q12585"
QID_KOREA = "Q18097"
QID_FRENCH_POLYNESIA = "Q30971"
QID_GERMAN_REICH = "Q1206012"
QID_ZAIRE = "Q6500954"
QID_SOUTH_YEMEN = "Q199841"
QID_REPUBLIC_OF_THE_CONGO = "Q971"
QID_DEMOCRATIC_REPUBLIC_OF_THE_CONGO = "Q974"
QID_THIRTEEN_COLONIES = "Q179997"
QID_TIBET = "Q17252"
QID_NEW_KINGDOM_OF_GRANADA = "Q2077264"
QID_BRITISH_NORTH_AMERICA = "Q248452"
QID_PROVINCE_OF_QUEBEC = "Q251668"
QID_NORTHERN_LOW_COUNTRIES = "Q27996474"
QID_OTTOMAN_PALESTINE = "Q2909425"
QID_REPUBLIC_OF_ABKHAZIA = "Q31354462"
QID_SWEDEN_FINLAND = "Q3279296"
QID_KOREA_UNDER_JAPANESE_RULE = "Q503585"
QID_CISLEITHANIA = "Q533534"
QID_IRELAND = "Q57695350"
QID_CLASSICAL_ATHENS = "Q844930"


hungarian_name_order_countries_list = [QID_HUNGARY]
# China, Japan, Korea, and Vietnam
eastern_name_order_countries_list = [
    QID_CHINA,
    QID_JAPAN,
    QID_NORTH_KOREA,
    QID_SOUTH_KOREA,
    QID_VIETNAM,
    QID_MACAU,
]

loc_locale_dict = {
    "Aberdeen (S.D.)": QID_USA,  # south dakota
    "Adelaide (S.A.)": QID_AUSTRALIA,  # south australia
    "Africa": "",
    "Alabama": QID_USA,
    "Alaska": QID_USA,
    "Albania": QID_CANADA,
    "Alberta": QID_CANADA,
    "Algeria": QID_ALGERIA,
    "Alon-Shevut": QID_ISRAEL,
    "Angola": QID_ANGOLA,
    "Argentina": QID_ARGENTINA,
    "Arizona": QID_USA,
    "Armenia (Republic)": QID_ARMENIA,
    "Armenia": QID_ARMENIA,
    "Auckland (N.Z.)": QID_NEW_ZEALAND,
    "Austraila": QID_AUSTRALIA,  # typo
    "Australia": QID_AUSTRALIA,
    "Austria": QID_AUSTRIA,
    "Azerbaijan": QID_AZERBAIJAN,
    "Bahia (Brazil : State)": QID_BRAZIL,
    "Bahrain": QID_BAHRAIN,
    "Baltimore, MD": QID_USA,
    "Bangladesh": QID_BANGLADESH,
    "Belarus": QID_BELARUS,
    "Belgium": QID_BELGIUM,
    "Bella Vista, Ark.": QID_USA,
    "Bene Beraḳ": QID_ISRAEL,
    "Benin": QID_BENIN,
    "Bhutan": QID_BHUTAN,
    "Bolivia": QID_BOLIVIA,
    "Bordeaux (France : Généralité)": QID_FRANCE,
    "Bosnia and Herzegovina": QID_BOSNIA_AND_HERZEGOVINA,
    "Brazil": QID_BRAZIL,
    "Brisbane (Qld.)": QID_AUSTRALIA,
    "Brisbane (Qld)": QID_AUSTRALIA,
    "British Columbia": QID_CANADA,
    "Bulgaria": QID_BULGARIA,
    "Bundoora (Vic.)": QID_AUSTRALIA,
    "Burkina Faso": QID_BURKINA_FASO,
    "Burma": QID_MYANMAR,
    "Burundi": QID_BURUNDI,
    "Burwood (Vic.)": QID_AUSTRALIA,
    "Cabo Verde": QID_CAPE_VERDE,
    "California, Northern": QID_USA,
    "California, Southern": QID_USA,
    "California": QID_USA,
    "Cameroon": QID_CAMEROON,
    "Canada, Northern": QID_CANADA,
    "Canada": QID_CANADA,
    "Canary Islands": QID_CANARY_ISLANDS,
    "Canberra (A.C.T.)": QID_AUSTRALIA,
    "Central Andes region": "",
    "Cephalonia (Greece : Municipality)": QID_GREECE,
    "Charlottetown (P.E.I.)": QID_CANADA,  # prince edward island
    "Chicago": QID_USA,
    "Chile": QID_CHILE,
    "China": QID_CHINA,
    "Colombia": QID_COLOMBIA,
    "Colorado": QID_USA,
    "Confederated Tribes and Bands of the Yakama Nation": QID_USA,
    "Congo (Brazzaville)": QID_REPUBLIC_OF_THE_CONGO,
    "Congo (Democratic Republic)": QID_DEMOCRATIC_REPUBLIC_OF_THE_CONGO,
    "Connecticut": QID_USA,
    "Côte d'Ivoire": QID_IVORY_COAST,
    "Croatia": QID_CROATIA,
    "Cuba": QID_CUBA,
    "Cundinamarca (Colombia : Department)": QID_COLOMBIA,
    "Cyprus": QID_CYPRUS,
    "Czech Republic": QID_CZECH_REPUBLIC,
    "Czechoslovakia": QID_CZECHOSLOVAKIA,
    "Dalmatia": QID_CROATIA,
    "Darwin (N.T.)": QID_AUSTRALIA,
    "Denmark": QID_DENMARK,
    "Djibouti": QID_DJIBOUTI,
    "Dominican Republic": QID_DOMINICAN_REPUBLIC,
    "Down (Northern Ireland : County)": QID_UNITED_KINGDOM,
    "East Asia": "",
    "Ecuador": QID_ECUADOR,
    "Edmonton (Alta.)": QID_USA,
    "Egypt": QID_EGYPT,
    "England, Southern": QID_UNITED_KINGDOM,
    "England": QID_UNITED_KINGDOM,
    "Eritrea": QID_ERITREA,
    "Estonia": QID_ESTONIA,
    "Europe": "",
    "European Union countries": "",
    "Even Shemuʼel": QID_ISRAEL,
    "Finland": QID_FINLAND,
    "Florida": QID_USA,
    "Framce": QID_FRANCE,
    "France": QID_FRANCE,
    "Frankfurt am Main": QID_GERMANY,
    "French Indochina": QID_FRENCH_INDOCHINA,
    "Georgia (Republic)": QID_GEORGIA,
    "Georgia": QID_USA,
    "Germany (West)": QID_WEST_GERMANY,
    "Germany": QID_GERMANY,
    "Ghana": QID_GHANA,
    "Gorʹkiĭ (R.S.F.S.R.)": QID_RUSSIAN_SOVIET_FEDERATIVE_SOCIALIST_REPUBLIC,
    "Gran Chaco": "",
    "Great Britain": QID_UNITED_KINGDOM,
    "Great Britian": QID_UNITED_KINGDOM,
    "Great Lakes Region (North America)": QID_USA,
    "Greece": QID_GREECE,
    "Guatemala": QID_GUATEMALA,
    "Guinea": QID_GUINEA,
    "Haiti": QID_HAITI,
    "Halifax (N.S.)": QID_CANADA,
    "Hamburg": QID_GERMANY,
    "Har ha-Menuḥot (Cemetery : Jerusalem)": QID_ISRAEL,
    "Hawaii": QID_USA,
    "Hoa Lư (Vietnam : District)": QID_VIETNAM,
    "Hobart (Tas.)": QID_AUSTRALIA,
    "Honduras": QID_HONDURAS,
    "Hong Kong": QID_HONG_KONG,
    "Hungary": QID_HUNGARY,
    "Iceland": QID_ICELAND,
    "Idaho": QID_USA,
    "Illinois": QID_USA,
    "India": QID_INDIA,
    "Indiana": QID_USA,
    "Indonesia": QID_INDONESIA,
    "Iowa": QID_USA,
    "Iran": QID_IRAN,
    "Iraq": QID_IRAQ,
    "Ireland": QID_REPUBLIC_OF_IRELAND,
    "is": QID_ISRAEL,
    "Israel": QID_ISRAEL,
    "Italy": QID_ITALY,
    "Jackson (Miss.)": QID_USA,
    "Jamaica": QID_JAMAICA,
    "Japan": QID_JAPAN,
    "Jerusalem": QID_ISRAEL,
    "Jordan": QID_JORDAN,
    "Kansas": QID_USA,
    "Kazakhstan": QID_KAZAKHSTAN,
    "Kenya": QID_KENYA,
    "Korea (North)": QID_NORTH_KOREA,
    "Korea (South)": QID_SOUTH_KOREA,
    "Korea": QID_SOUTH_KOREA,
    "Kubanʹ (Russia : Region)": QID_RUSSIA,
    "Kumanovo (Macedonia)": QID_NORTH_MACEDONIA,
    "Kuwait": QID_KUWAIT,
    "Kyoto (Japan : Prefecture)": QID_JAPAN,
    "Kyrgyzstan": QID_KYRGYZSTAN,
    "Laos": QID_LAOS,
    "Laramie (Wyo.)": QID_USA,
    "Latin America": "",
    "Latvia": QID_LATVIA,
    "Lebanon": QID_LEBANON,
    "Leningrad (R.S.F.S.R.)": QID_RUSSIA,
    "Leningrad, R.S.F.S.R.": QID_RUSSIAN_SOVIET_FEDERATIVE_SOCIALIST_REPUBLIC,
    "Lesotho": QID_LESOTHO,
    "Lexington (Ky.)": QID_USA,
    "Lexington, Virginia": QID_USA,
    "Liberia": QID_LIBERIA,
    "Libya": QID_LIBYA,
    "Lincoln (N.Z.)": QID_NEW_ZEALAND,
    "Lithuania": QID_LITHUANIA,
    "Louisville, Ky.": QID_USA,
    "Lublin (Poland : Powiat)": QID_POLAND,
    "Luxembourg": QID_LUXEMBOURG,
    "Macedonia (Republic)": QID_NORTH_MACEDONIA,
    "Madagascar": QID_MADAGASCAR,
    "Madeira Islands": QID_MADEIRA,
    "Maine": QID_USA,
    "Mainz (Electorate)": QID_ELECTORATE_OF_MAINZ,
    "Mainz (Germany : Landkreis)": QID_GERMANY,
    "Malawi": QID_MALAWI,
    "Malaysia": QID_MALAYSIA,
    "Mali": QID_MALI,
    "Malta": QID_MALTA,
    "Martinique": QID_MARTINIQUE,
    "Maryland": QID_USA,
    "Massachusetts": QID_USA,
    "Mauritania": QID_MAURITANIA,
    "Mauritius": QID_MAURITIUS,
    "Mbandaka (Congo)": QID_DEMOCRATIC_REPUBLIC_OF_THE_CONGO,
    "Md.": QID_USA,  # maryland
    "Me.": QID_USA,  # Maine
    "Mecklenburg (Germany : Region)": QID_GERMANY,
    "Melbourne (Vi)": QID_AUSTRALIA,
    "Melbourne (Vic.)": QID_AUSTRALIA,
    "Melbourne, Vic.": QID_AUSTRALIA,
    "Meota (Sask.)": QID_CANADA,
    "Mexico": QID_MEXICO,
    "Michigan": QID_USA,
    "Middle East": QID_MIDDLE_EAST,
    "Moldova": QID_MOLDOVA,
    "Monaco": QID_MONACO,
    "Monaghan (Ireland : County)": QID_REPUBLIC_OF_IRELAND,
    "Mongolia": QID_MONGOLIA,
    "Montenegro": QID_MONTENEGRO,
    "Montréal (Québec)": QID_CANADA,
    "Morocco": QID_MOROCCO,
    "Moroni (Comoros)": QID_COMOROS,
    "Moscow (Russia : Oblast)": QID_RUSSIA,
    "Moscow": QID_RUSSIA,
    "Mozambique": QID_MOZAMBIQUE,
    "N.H.": QID_USA,  # New Hampshire
    "N.M.": QID_USA,  # new mexico
    "N.Z.": QID_NEW_ZEALAND,
    "Namibia": QID_NAMIBIA,
    "Neb.": QID_USA,
    "Nederlands": QID_NETHERLANDS,
    "Nepal": QID_NEPAL,
    "Neptune (N.J. : Township)": QID_USA,
    "Netherlands": QID_NETHERLANDS,
    "New Brunswick": QID_CANADA,
    "New Delhi": QID_INDIA,
    "New Jersey": QID_USA,
    "New Mexico": QID_USA,
    "New South Wales": QID_AUSTRALIA,
    "New York (State)": QID_USA,
    "New York Region": QID_USA,
    "New York, New York": QID_USA,
    "New York": QID_USA,
    "New Zealand": QID_NEW_ZEALAND,
    "Newark, Del.": QID_USA,
    "Newfoundland and Labrador": QID_CANADA,
    "Nicosia (Cyprus)": QID_CYPRUS,
    "Niger": QID_NIGER,
    "Nigeria": QID_NIGERIA,
    "North Carolina": QID_USA,
    "Northern Ireland": QID_UNITED_KINGDOM,
    "Northwest, Pacific": "",
    "Norway": QID_NORWAY,
    "Novyĭ Afon (Georgia)": QID_GEORGIA,
    "Okla.": QID_USA,
    "Oklahoma": QID_USA,
    "Oman": QID_OMAN,
    "Ont.": QID_CANADA,
    "Ontario": QID_USA,
    "Oregon": QID_USA,
    "Orem, Utah": QID_USA,
    "Pakistan": QID_PAKISTAN,
    "Palawan (Philippines : Province)": QID_PHILIPPINES,
    "Palestine": QID_STATE_OF_PALESTINE,
    "Panama": QID_PANAMA,
    "Paraguay": QID_PARAGUAY,
    "Paris": QID_FRANCE,
    "Pennsylvania": QID_USA,
    "Perth (W.A.)": QID_AUSTRALIA,
    "Peru": QID_PERU,
    "Philippines": QID_PHILIPPINES,
    "Poland": QID_POLAND,
    "Polar regions": "",
    "Portugal": QID_PORTUGAL,
    "Poznań": QID_POLAND,
    "Prince Edward Island": QID_CANADA,
    "Puerto Rico": QID_PUERTO_RICO,
    "Pyrenees": "",
    "Qatar": QID_QATAR,
    "Québec": QID_CANADA,
    "Queensland": QID_AUSTRALIA,
    "Rhode Island": QID_USA,
    "Richmond, VA": QID_USA,  # Virginia
    "Rockville, Md.": QID_USA,  # Maryland
    "Romania": QID_ROMANIA,
    "Russia (Federation)": QID_RUSSIA,
    "Russia (Federation0)": QID_RUSSIA, # typo
    "Russia": QID_RUSSIA,
    "Russian S.F.S.R.": QID_RUSSIA,
    "Rwanda": QID_RWANDA,
    "S.C.": QID_USA,  # south carolina
    "Saudi Arabia": QID_SAUDI_ARABIA,
    "Scarborough (Toronto, Ont.)": QID_CANADA,
    "Scotland": QID_UNITED_KINGDOM,
    "Selinus, Extinct city": "",
    "Senegal": QID_SENEGAL,
    "Serbia": QID_SERBIA,
    "Shangqiu": QID_CHINA,
    "Sheffield, UK": QID_UNITED_KINGDOM,
    "Sierra Leone": QID_SIERRA_LEONE,
    "Singapore": QID_SINGAPORE,
    "Skopje (North Macedonia)": QID_NORTH_MACEDONIA,
    "Slovakia": QID_SLOVAKIA,
    "Slovenia": QID_SLOVENIA,
    "Somalia": QID_SOMALIA,
    "Soquel, Calif": QID_USA,
    "South Africa": QID_SOUTH_AFRICA,
    "South Asia": "",
    "South Australia": QID_AUSTRALIA,
    "South Carolina": QID_USA,
    "Soviet Union": QID_SOVIET_UNION,
    "Spain": QID_SPAIN,
    "Sri Lanka": QID_SRI_LANKA,
    "Staunton, Va": QID_USA,  # virginia
    "Sudan": QID_SUDAN,
    "Suriname": QID_SURINAME,
    "Sweden": QID_SWEDEN,
    "Switzerland": QID_SWITZERLAND,
    "Syria": QID_SYRIA,
    "Taiwan": QID_TAIWAN,
    "Tanzania": QID_TANZANIA,
    "Tasmania": QID_AUSTRALIA,
    "Tennessee": QID_USA,
    "Texas": QID_USA,
    "Thailand": QID_THAILAND,
    "Tʻbilisi (Georgia)": QID_GEORGIA,
    "Timor-Leste": QID_EAST_TIMOR,
    "Toronto": QID_CANADA,
    "Trinidad and Tobago": QID_TRINIDAD_AND_TOBAGO,
    "Tunisia": QID_TUNISIA,
    "Turkey": QID_TURKEY,
    "U.K.": QID_UNITED_KINGDOM,
    "U.S.": QID_USA,
    "Udaipur (India : District)": QID_INDIA,
    "Uganda": QID_UGANDA,
    "Ukraine": QID_UKRAINE,
    "United Arab Emirates": QID_UNITED_ARAB_EMIRATES,
    "United Kingdom": QID_UNITED_KINGDOM,
    "United States of America": QID_USA,
    "United States": QID_USA,
    "Uruguay": QID_URUGUAY,
    "Uzbekistan": QID_UZBEKISTAN,
    "Vatican City": QID_VATICAN_CITY,
    "Venezuela": QID_VENEZUELA,
    "Vermont": QID_USA,
    "Vietnam (Associated State)": QID_VIETNAM,  # Q1193879
    "Vietnam (Republic)": QID_VIETNAM,
    "Vietnam": QID_VIETNAM,
    "Virginia": QID_USA,
    "Wales": QID_UNITED_KINGDOM,
    "Washington (State)": QID_USA,
    "Wellington, N.Z.": QID_NEW_ZEALAND,
    "West Bank": QID_ISRAEL,
    "West, Virginia": QID_USA,
    "Western Australia": QID_AUSTRALIA,
    "Wisconsin": QID_USA,
    "Wyoming": QID_USA,
    "Yemen (Republic)": QID_YEMEN,
    "Yemen": QID_YEMEN,
    "Yugoslavia": QID_FEDERAL_REPUBLIC_OF_YUGOSLAVIA,
    "Zambia": QID_ZAMBIA,
    "Zimbabwe": QID_ZIMBABWE,

    # USA states
    "Ala.": QID_USA,
    "Alta.": QID_CANADA,  # Alberta, Canada
    "Ariz.": QID_USA,
    "B.C.": QID_CANADA,  # British Columbia, Canada
    "Calif.": QID_USA,
    "Colo.": QID_USA,
    "Conn.": QID_USA,
    "Conn.": QID_USA,
    "D.": QID_USA,
    "D.C.": QID_USA,
    "Fla.": QID_USA,
    "Ga.": QID_USA,  # Georgia
    "Ill.": QID_USA,
    "Ind.": QID_USA,
    "Kan.": QID_USA,
    "La.": QID_USA,
    "Mass.": QID_USA,
    "Mich.": QID_USA,
    "Minn.": QID_USA,
    "Minnesota": QID_USA,
    "Missouri": QID_USA,
    "Mo.": QID_USA,  # Missouri
    "N.C.": QID_USA,
    "N.J.": QID_USA,
    "N.S.W.": QID_AUSTRALIA,
    "N.Y.": QID_USA,
    "Nev.": QID_USA,
    "Ohio": QID_USA,
    "Or.": QID_USA,
    "P.R.": QID_PUERTO_RICO,
    "Pa.": QID_USA,
    "R.I.": QID_USA,  # Rhode island
    "Tenn.": QID_USA,
    "Tex.": QID_USA,
    "Utah": QID_USA,
    "Va.": QID_USA,  # Virginia
    "Vt.": QID_USA,
    "Wash.": QID_USA,
    "Wis.": QID_USA,
}


def get_loc_geographic_areas_country(area_code: str) -> str:
    area_mapping = {
        "a------": QID_ASIA,
        "t------": QID_ANTARCTICA,
        "a-af": QID_AFGHANISTAN,
        "a-ai": QID_ARMENIA,
        "a-aj": QID_AZERBAIJAN,
        "a-ba": QID_BAHRAIN,
        "a-bg": QID_BANGLADESH,
        #"a-bn": QID_BORNEO,
        #"a-br": QID_BURMA,
        "a-bt": QID_BHUTAN,
        #"a-bx": QID_BRUNEI,
        "a-cb": QID_CAMBODIA,
        "a-cc": QID_CHINA,
        "a-ce": QID_SRI_LANKA,
        "a-ch": QID_TAIWAN,
        "a-cy": QID_CYPRUS,
        #"a-em": QID_TIMOR-LESTE,
        #"a-gs": QID_GEORGIA_(REPUBLIC),
        "-a-hk": QID_HONG_KONG,
        "a-ii": QID_INDIA,
        "a-io": QID_INDONESIA,
        "a-iq": QID_IRAQ,
        "a-ir": QID_IRAN,
        "a-is": QID_ISRAEL,
        "a-ja": QID_JAPAN,
        "a-jo": QID_JORDAN,
        "a-kg": QID_KYRGYZSTAN,
        "a-kn": QID_NORTH_KOREA,
        "a-ko": QID_SOUTH_KOREA,
        "a-kr": QID_KOREA,
        "a-ku": QID_KUWAIT,
        "a-kz": QID_KAZAKHSTAN,
        "a-le": QID_LEBANON,
        "a-ls": QID_LAOS,
        #"-a-mh": QID_MACAO,
        "a-mk": QID_OMAN,
        "a-mp": QID_MONGOLIA,
        "a-my": QID_MALAYSIA,
        "a-np": QID_NEPAL,
        #"a-nw": QID_NEW_GUINEA,
        #"-a-ok": QID_OKINAWA,
        "a-ph": QID_PHILIPPINES,
        "a-pk": QID_PAKISTAN,
        "a-pp": QID_PAPUA_NEW_GUINEA,
        #"-a-pt": QID_PORTUGUESE_TIMOR,
        "a-qa": QID_QATAR,
        "a-si": QID_SINGAPORE,
        #"-a-sk": QID_SIKKIM,
        "a-su": QID_SAUDI_ARABIA,
        "a-sy": QID_SYRIA,
        "a-ta": QID_TAJIKISTAN,
        "a-th": QID_THAILAND,
        "a-tk": QID_TURKMENISTAN,
        "a-ts": QID_UNITED_ARAB_EMIRATES,
        "a-tu": QID_TURKEY,
        "a-uz": QID_UZBEKISTAN,
        #"-a-vn": QID_VIET_NAM,_NORTH,
        #"-a-vs": QID_VIET_NAM,_SOUTH,
        "a-vt": QID_VIETNAM,
        "a-ye": QID_YEMEN,
        "-a-ys": QID_SOUTH_YEMEN,
        "aw": QID_MIDDLE_EAST,
        "awba": QID_WEST_BANK,
        #"awgz": QID_GAZA_STRIP,
        "e-aa": QID_ALBANIA,
        "e-an": QID_ANDORRA,
        "e-au": QID_AUSTRIA,
        "e-be": QID_BELGIUM,
        "e-bn": QID_BOSNIA_AND_HERZEGOVINA,
        "e-bu": QID_BULGARIA,
        "e-bw": QID_BELARUS,
        "e-ci": QID_CROATIA,
        "e-cs": QID_CZECHOSLOVAKIA,
        "e-dk": QID_DENMARK,
        "e-er": QID_ESTONIA,
        "e-fi": QID_FINLAND,
        "e-fr": QID_FRANCE,
        "e-ge": QID_GERMAN_DEMOCRATIC_REPUBLIC,
        "e-gg": QID_GUERNSEY,
        "e-gi": QID_GIBRALTAR,
        "e-gr": QID_GREECE,
        "e-gw": QID_WEST_GERMANY,
        "e-gx": QID_GERMANY,
        "e-hu": QID_HUNGARY,
        "e-ic": QID_ICELAND,
        "e-ie": QID_REPUBLIC_OF_IRELAND,
        "e-im": QID_ISLE_OF_MAN,
        "e-it": QID_ITALY,
        "e-je": QID_JERSEY,
        "e-kv": QID_KOSOVO,
        "e-lh": QID_LIECHTENSTEIN,
        "e-li": QID_LITHUANIA,
        "e-lu": QID_LUXEMBOURG,
        "e-lv": QID_LATVIA,
        "e-mc": QID_MONACO,
        "e-mm": QID_MALTA,
        "e-mo": QID_MONTENEGRO,
        "e-mv": QID_MOLDOVA,
        "e-ne": QID_NETHERLANDS,
        "e-no": QID_NORWAY,
        "e-pl": QID_POLAND,
        "e-po": QID_PORTUGAL,
        "e-rb": QID_SERBIA,
        "e-rm": QID_ROMANIA,
        "e-ru": QID_RUSSIA,
        "e-sm": QID_SAN_MARINO,
        "e-sp": QID_SPAIN,
        "e-sw": QID_SWEDEN,
        "e-sz": QID_SWITZERLAND,
        "e-uk": QID_UNITED_KINGDOM,
        #"-e-uk-ui": QID_GREAT_BRITAIN_MISCELLANEOUS_ISLAND_DEPENDENCIES,
        "e-un": QID_UKRAINE,
        "e-ur": QID_SOVIET_UNION,
        #"-e-ur-ai": QID_ARMENIA_(REPUBLIC),
        "-e-ur-aj": QID_AZERBAIJAN,
        "-e-ur-bw": QID_BELARUS,
        "-e-ur-er": QID_ESTONIA,
        #"-e-ur-gs": QID_GEORGIA_(REPUBLIC),
        "-e-ur-kg": QID_KYRGYZSTAN,
        "-e-ur-kz": QID_KAZAKHSTAN,
        "-e-ur-li": QID_LITHUANIA,
        "-e-ur-lv": QID_LATVIA,
        "-e-ur-mv": QID_MOLDOVA,
        #"-e-ur-ru": QID_RUSSIA_(FEDERATION),
        "-e-ur-ta": QID_TAJIKISTAN,
        "-e-ur-tk": QID_TURKMENISTAN,
        "-e-ur-un": QID_UKRAINE,
        "-e-ur-uz": QID_UZBEKISTAN,
        #"-e-url": QID_CENTRAL_REGION,_RSFSR,
        "e-vc": QID_VATICAN_CITY,
        "e-xn": QID_NORTH_MACEDONIA,
        "e-xo": QID_SLOVAKIA,
        "e-xr": QID_CZECH_REPUBLIC,
        "e-xv": QID_SLOVENIA,
        "e-yu": QID_FEDERAL_REPUBLIC_OF_YUGOSLAVIA,
        "f-ae": QID_ALGERIA,
        "f-ao": QID_ANGOLA,
        "f-bd": QID_BURUNDI,
        "f-bs": QID_BOTSWANA,
        #"-f-by": QID_BIAFRA,
        "f-cd": QID_CHAD,
        "f-cf": QID_REPUBLIC_OF_THE_CONGO,
        "f-cg": QID_DEMOCRATIC_REPUBLIC_OF_THE_CONGO,
        "f-cm": QID_CAMEROON,
        "f-cx": QID_CENTRAL_AFRICAN_REPUBLIC,
        "f-dm": QID_BENIN,
        "f-ea": QID_ERITREA,
        "f-eg": QID_EQUATORIAL_GUINEA,
        "f-et": QID_ETHIOPIA,
        "f-ft": QID_DJIBOUTI,
        "f-gh": QID_GHANA,
        "f-gm": QID_THE_GAMBIA,
        "f-go": QID_GABON,
        "f-gv": QID_GUINEA,
        #"-f-if": QID_IFNI,
        "f-iv": QID_IVORY_COAST,
        "f-ke": QID_KENYA,
        "f-lb": QID_LIBERIA,
        "f-lo": QID_LESOTHO,
        "f-ly": QID_LIBYA,
        "f-mg": QID_MADAGASCAR,
        "f-ml": QID_MALI,
        "f-mr": QID_MOROCCO,
        "f-mu": QID_MAURITANIA,
        "f-mw": QID_MALAWI,
        "f-mz": QID_MOZAMBIQUE,
        "f-ng": QID_NIGER,
        "f-nr": QID_NIGERIA,
        "f-pg": QID_GUINEA_BISSAU,
        "f-rh": QID_ZIMBABWE,
        "f-rw": QID_RWANDA,
        "f-sa": QID_SOUTH_AFRICA,
        "f-sd": QID_SOUTH_SUDAN,
        "f-sf": QID_SAO_TOME_AND_PRINCIPE,
        "f-sg": QID_SENEGAL,
        #"f-sh": QID_SPANISH_NORTH_AFRICA,
        "f-sj": QID_SUDAN,
        "f-sl": QID_SIERRA_LEONE,
        "f-so": QID_SOMALIA,
        "f-sq": QID_ESWATINI,
        #"f-ss": QID_WESTERN_SAHARA,
        "f-sx": QID_NAMIBIA,
        "f-tg": QID_TOGO,
        "f-ti": QID_TUNISIA,
        "f-tz": QID_TANZANIA,
        "f-ua": QID_EGYPT,
        "f-ug": QID_UGANDA,
        "f-uv": QID_BURKINA_FASO,
        "f-za": QID_ZAMBIA,
        "i-cq": QID_COMOROS,
        #"i-fs": QID_TERRES_AUSTRALES_ET_ANTARCTIQUES_FRANÇAISES,
        #"i-hm": QID_HEARD_AND_MCDONALD_ISLANDS,
        "i-mf": QID_MAURITIUS,
        "i-my": QID_MAYOTTE,
        "i-re": QID_REUNION,
        "i-se": QID_SEYCHELLES,
        #"i-xa": QID_CHRISTMAS_ISLAND_(INDIAN_OCEAN),
        #"i-xb": QID_COCOS_(KEELING)_ISLANDS,
        "i-xc": QID_MALDIVES,
        #"-i-xo": QID_SOCOTRA_ISLAND,
        # "l": QID_ATLANTIC_OCEAN,
        # "ln": QID_NORTH_ATLANTIC_OCEAN,
        # "lnaz": QID_AZORES,
        # "lnbm": QID_BERMUDA_ISLANDS,
        # "lnca": QID_CANARY_ISLANDS,
        # "lncv": QID_CABO_VERDE,
        # "lnfa": QID_FAROE_ISLANDS,
        # "lnjn": QID_JAN_MAYEN_ISLAND,
        # "lnma": QID_MADEIRA_ISLANDS,
        # "lnsb": QID_SVALBARD_(NORWAY),
        # "ls": QID_SOUTH_ATLANTIC_OCEAN,
        # "lsai": QID_ASCENSION_ISLAND_(ATLANTIC_OCEAN),
        # "lsbv": QID_BOUVET_ISLAND,
        # "lsfk": QID_FALKLAND_ISLANDS,
        # "lstd": QID_TRISTAN_DA_CUNHA,
        # "lsxj": QID_SAINT_HELENA,
        # "lsxs": QID_SOUTH_GEORGIA_AND_SOUTH_SANDWICH_ISLANDS,
        # "m": QID_INTERCONTINENTAL_AREAS_(EASTERN_HEMISPHERE),
        # "ma": QID_ARAB_COUNTRIES,
        # "mb": QID_BLACK_SEA,
        # "me": QID_EURASIA,
        # "mm": QID_MEDITERRANEAN_REGION;_MEDITERRANEAN_SEA,
        # "mr": QID_RED_SEA,
        # "n": QID_NORTH_AMERICA,
        "n-cn": QID_CANADA,
        "n-gl": QID_GREENLAND,
        "n-mx": QID_MEXICO,
        "n-us": QID_USA,
        "n-ust": QID_USA, #	Southwest, New
        # "n-xl": QID_SAINT_PIERRE_AND_MIQUELON,
        # "nc": QID_CENTRAL_AMERICA,
        "ncbh": QID_BELIZE,
        "nccr": QID_COSTA_RICA,
        # "nccz": QID_CANAL_ZONE,
        "nces": QID_EL_SALVADOR,
        "ncgt": QID_GUATEMALA,
        "ncho": QID_HONDURAS,
        "ncnq": QID_NICARAGUA,
        "ncpn": QID_PANAMA,
        "nwaq": QID_ANTIGUA_AND_BARBUDA,
        "nwaw": QID_ARUBA,
        "nwbb": QID_BARBADOS,
        # "-nwbc": QID_BARBUDA,
        # "nwbf": QID_BAHAMAS,
        # "nwbn": QID_BONAIRE,
        "nwcj": QID_CAYMAN_ISLANDS,
        "nwco": QID_CURACAO,
        "nwcu": QID_CUBA,
        "nwdq": QID_DOMINICA,
        "nwdr": QID_DOMINICAN_REPUBLIC,
        # "nweu": QID_SINT_EUSTATIUS,
        # "-nwga": QID_GREATER_ANTILLES,
        "nwgd": QID_GRENADA,
        "nwgp": QID_GUADELOUPE,
        # "-nwgs": QID_GRENADINES,
        # "nwhi": QID_HISPANIOLA,
        "nwht": QID_HAITI,
        "nwjm": QID_JAMAICA,
        # "nwla": QID_ANTILLES,_LESSER,
        # "nwli": QID_LEEWARD_ISLANDS_(WEST_INDIES),
        # "nwmj": QID_MONTSERRAT,
        "nwmq": QID_MARTINIQUE,
        "-nwna": QID_NETHERLANDS_ANTILLES,
        "nwpr": QID_PUERTO_RICO,
        # "-nwsb": QID_SAINT-BARTHÉLEMY,
        "nwsc": QID_SAINT_BARTHELEMY,
        # "nwsd": QID_SABA,
        "nwsn": QID_SINT_MAARTEN,
        # "nwst": QID_SAINT-MARTIN,
        # "nwsv": QID_SWAN_ISLANDS_(HONDURAS),
        # "nwtc": QID_TURKS_AND_CAICOS_ISLANDS,
        "nwtr": QID_TRINIDAD_AND_TOBAGO,
        # "nwuc": QID_UNITED_STATES_MISCELLANEOUS_CARIBBEAN_ISLANDS,
        # "nwvb": QID_BRITISH_VIRGIN_ISLANDS,
        # "nwvi": QID_VIRGIN_ISLANDS_OF_THE_UNITED_STATES,
        # "-nwvr": QID_VIRGIN_ISLANDS,
        # "nwwi": QID_WINDWARD_ISLANDS_(WEST_INDIES),
        # "nwxa": QID_ANGUILLA,
        "nwxi": QID_SAINT_KITTS_AND_NEVIS,
        "nwxk": QID_SAINT_LUCIA,
        "nwxm": QID_SAINT_VINCENT_AND_THE_GRENADINES,
        "poas": QID_AMERICAN_SAMOA,
        "pobp": QID_SOLOMON_ISLANDS,
        # "poci": QID_CAROLINE_ISLANDS,
        # "-pocp": QID_CANTON_AND_ENDERBURY_ISLANDS,
        "pocw": QID_COOK_ISLANDS,
        # "poea": QID_EASTER_ISLAND,
        "pofj": QID_FIJI,
        "pofp": QID_FRENCH_POLYNESIA,
        # "pogg": QID_GALAPAGOS_ISLANDS,
        # "-pogn": QID_GILBERT_AND_ELLICE_ISLANDS,
        "pogu": QID_GUAM,
        # "poji": QID_JOHNSTON_ISLAND,
        "pokb": QID_KIRIBATI,
        # "poki": QID_KERMADEC_ISLANDS,
        # "poln": QID_LINE_ISLANDS,
        # "pome": QID_MELANESIA,
        # "pomi": QID_MICRONESIA_(FEDERATED_STATES),
        "ponl": QID_NEW_CALEDONIA,
        "ponn": QID_VANUATU,
        "ponu": QID_NAURU,
        # "popc": QID_PITCAIRN_ISLAND,
        "popl": QID_PALAU,
        # "pops": QID_POLYNESIA,
        # "-pory": QID_RYUKYU_ISLANDS,_SOUTHERN,
        # "-posc": QID_SANTA_CRUZ_ISLANDS,
        # "posh": QID_SAMOAN_ISLANDS,
        "-posn": QID_SOLOMON_ISLANDS,
        # "potl": QID_TOKELAU,
        "poto": QID_TONGA,
        # "pott": QID_MICRONESIA,
        "potv": QID_TUVALU,
        # "poup": QID_UNITED_STATES_MISCELLANEOUS_PACIFIC_ISLANDS,
        # "powf": QID_WALLIS_AND_FUTUNA_ISLANDS,
        # "powk": QID_WAKE_ISLAND,
        "pows": QID_SAMOA,
        # "poxd": QID_MARIANA_ISLANDS,
        "poxe": QID_MARSHALL_ISLANDS,
        # "poxf": QID_MIDWAY_ISLANDS,
        "poxh": QID_NIUE,
        "s-ag": QID_ARGENTINA,
        "s-bl": QID_BRAZIL,
        "s-bo": QID_BOLIVIA,
        "s-ck": QID_COLOMBIA,
        "s-cl": QID_CHILE,
        "s-ec": QID_ECUADOR,
        "s-fg": QID_FRENCH_GUIANA,
        "s-gy": QID_GUYANA,
        "s-pe": QID_PERU,
        "s-py": QID_PARAGUAY,
        "s-sr": QID_SURINAME,
        "s-uy": QID_URUGUAY,
        "s-ve": QID_VENEZUELA,
        "u-at": QID_AUSTRALIA,
        "u-nz": QID_NEW_ZEALAND,
        "f------": QID_AFRICA,
        "nwbf": QID_THE_BAHAMAS,
        "n-cnp": QID_CANADIAN_PRAIRIES,
        "lncv":	QID_CAPE_VERDE,
        "cl": QID_LATIN_AMERICA,
    }

    # Check if the full code exists first, else move to broader matches
    if area_code in area_mapping:
        return area_mapping[area_code]

    # Split the code and search for the closest broader match
    parts = area_code.split('-')
    for i in range(len(parts) - 1, 0, -1):
        key = '-'.join(parts[:i])
        if key in area_mapping:
            return area_mapping[key]
    
    raise RuntimeError(f"get_loc_geographic_areas_country: Unknown code: {area_code}")

def get_loc_url_country(url: str) -> str:
    url_mapping = {
        "https://id.loc.gov/authorities/subjects/sh85020279": QID_CARIBBEAN,
        "https://id.loc.gov/rwo/agents/n78086438": QID_USA, # Chicago (Ill.) 
        "https://id.loc.gov/rwo/agents/n78089021": QID_JAPAN, # Japan
        "https://id.loc.gov/rwo/agents/n78089046": QID_SPAIN, # Madrid (Spain)
        "https://id.loc.gov/rwo/agents/n78095330": QID_USA,
        "https://id.loc.gov/rwo/agents/n78095520": QID_USA, # Philadelphia (Pa.)
        "https://id.loc.gov/rwo/agents/n78095779": QID_USA, # Memphis (Tenn.)
        "https://id.loc.gov/rwo/agents/n78095801": QID_USA, # Nashville (Tenn.)
        "https://id.loc.gov/rwo/agents/n79003285": QID_ISRAEL,
        "https://id.loc.gov/rwo/agents/n79005665": QID_UNITED_KINGDOM, # London (England)
        "https://id.loc.gov/rwo/agents/n79006404": QID_FRANCE,
        "https://id.loc.gov/rwo/agents/n79006530": QID_USA, # Baltimore (Md.)
        "https://id.loc.gov/rwo/agents/n79006971": QID_SPAIN,
        "https://id.loc.gov/rwo/agents/n79007500": QID_USA, # Portland (Or.)
        "https://id.loc.gov/rwo/agents/n79018143": QID_GREECE, # Athens (Greece)
        "https://id.loc.gov/rwo/agents/n79018452": QID_USA, # San Francisco (Calif.)
        "https://id.loc.gov/rwo/agents/n79018782": QID_USA, # Santa Monica (Calif.)
        "https://id.loc.gov/rwo/agents/n79018873": QID_SWEDEN, # Stockholm (Sweden)
        "https://id.loc.gov/rwo/agents/n79021184": QID_SWEDEN,
        "https://id.loc.gov/rwo/agents/n79021240": QID_USA, # Los Angeles (Calif.)
        "https://id.loc.gov/rwo/agents/n79021326": QID_AUSTRALIA,
        "https://id.loc.gov/rwo/agents/n79021597": QID_DENMARK,
        "https://id.loc.gov/rwo/agents/n79021783": QID_ITALY,
        "https://id.loc.gov/rwo/agents/n79021855": QID_USA, # Sydney (N.S.W.)
        "https://id.loc.gov/rwo/agents/n79022918": QID_USA, # Louisville (Ky.)
        "https://id.loc.gov/rwo/agents/n79023147": QID_UNITED_KINGDOM,
        "https://id.loc.gov/rwo/agents/n79023321": QID_USA, # Dallas (Tex.)
        "https://id.loc.gov/rwo/agents/n79041717": QID_USA, # California
        "https://id.loc.gov/rwo/agents/n79041965": QID_USA, # Seattle (Wash.)
        "https://id.loc.gov/rwo/agents/n79049218": QID_USA, # Columbus (Ohio)
        "https://id.loc.gov/rwo/agents/n79049234": QID_USA, # Houston (Tex.)
        "https://id.loc.gov/rwo/agents/n79053090": QID_HUNGARY,
        "https://id.loc.gov/rwo/agents/n79055130": QID_PERU,
        "https://id.loc.gov/rwo/agents/n79056139": QID_NICARAGUA, # Managua (Nicaragua)
        "https://id.loc.gov/rwo/agents/n79056672": QID_USA, # Hayward (Wis.)
        "https://id.loc.gov/rwo/agents/n79061242": QID_CHILE,
        "https://id.loc.gov/rwo/agents/n79062978": QID_SWITZERLAND, 
        "https://id.loc.gov/rwo/agents/n79064631": QID_USA, # Tucson (Ariz.)
        "https://id.loc.gov/rwo/agents/n79076156": QID_RUSSIA, # Moscow (Russia)
        "https://id.loc.gov/rwo/agents/n79079328": QID_CANADA, # Toronto (Ont.)
        "https://id.loc.gov/rwo/agents/n79086824": QID_USA, # Kent (Ohio)
        "https://id.loc.gov/rwo/agents/n79088885": QID_GUINEA,
        "https://id.loc.gov/rwo/agents/n79089577": QID_USA, # Marin County (Calif.)
        "https://id.loc.gov/rwo/agents/n79089624": QID_SPAIN, # Catalonia (Spain)
        "https://id.loc.gov/rwo/agents/n79089785": QID_FRANCE, # Villefranche-sur-Mer (France)
        "https://id.loc.gov/rwo/agents/n79091151": QID_CHINA,
        "https://id.loc.gov/rwo/agents/n79091691": QID_HUNGARY, # Budapest (Hungary)
        "https://id.loc.gov/rwo/agents/n79100735": QID_POLAND, # Toruń (Poland)
        "https://id.loc.gov/rwo/agents/n79100830": QID_USA, # Storrs (Conn.)
        "https://id.loc.gov/rwo/agents/n79108998": QID_USA, # Lexington (Ky.)
        "https://id.loc.gov/rwo/agents/n79109786": QID_USA, # Knoxville (Tenn.)
        "https://id.loc.gov/rwo/agents/n79118971": QID_USA, # Oakland (Calif.)
        "https://id.loc.gov/rwo/agents/n79145770": QID_MALTA,
        "https://id.loc.gov/rwo/agents/n80001203": QID_RUSSIA,
        "https://id.loc.gov/rwo/agents/n80006269": QID_USA, # Hartford (Conn.)
        "https://id.loc.gov/rwo/agents/n80009698": QID_NICARAGUA,
        "https://id.loc.gov/rwo/agents/n80017896": QID_SERBIA, # Belgrade (Serbia)
        "https://id.loc.gov/rwo/agents/n80034915": QID_USA, # York (England)
        "https://id.loc.gov/rwo/agents/n80040311": QID_USA, # Brooklyn (New York, N.Y.)
        "https://id.loc.gov/rwo/agents/n80040493": QID_USA, # Athens (Ga.)
        "https://id.loc.gov/rwo/agents/n80046126": QID_USA, # Michigan
        "https://id.loc.gov/rwo/agents/n80049716": QID_PORTUGAL,
        "https://id.loc.gov/rwo/agents/n80076227": QID_GERMANY, # Dortmund (Germany)
        "https://id.loc.gov/rwo/agents/n80084495": QID_USA, # Carmel (Calif.)
        "https://id.loc.gov/rwo/agents/n80089997": QID_ZAMBIA,
        "https://id.loc.gov/rwo/agents/n80094259": QID_RUSSIA, # Novgorod (Russia)
        "https://id.loc.gov/rwo/agents/n80118393": QID_USA, # Manhattan (New York, N.Y.)
        "https://id.loc.gov/rwo/agents/n80121275": QID_TANZANIA,
        "https://id.loc.gov/rwo/agents/n80123283": QID_FINLAND, # Helsinki (Finland)
        "https://id.loc.gov/rwo/agents/n80125931": QID_GERMANY,
        "https://id.loc.gov/rwo/agents/n80125948": QID_INDIA,
        "https://id.loc.gov/rwo/agents/n80126293": QID_USA, # New York (State)
        "https://id.loc.gov/rwo/agents/n80126312": QID_SOVIET_UNION, 
        "https://id.loc.gov/rwo/agents/n81001722": QID_HONG_KONG, # Hong Kong
        "https://id.loc.gov/rwo/agents/n81018615": QID_USA, # Naperville (Ill.)
        "https://id.loc.gov/rwo/agents/n81019983": QID_USA, # Farmington (Conn.)
        "https://id.loc.gov/rwo/agents/n81039599": QID_RUSSIA, # Saint Petersburg (Russia)
        "https://id.loc.gov/rwo/agents/n81063207": QID_BANGLADESH,
        "https://id.loc.gov/rwo/agents/n81129565": QID_USA, # Lima (Ohio)
        "https://id.loc.gov/rwo/agents/n81136956": QID_USA, # Gulfport (Fla.)
        "https://id.loc.gov/rwo/agents/n82052561": QID_FRANCE, # Le Puy (Haute-Loire, France)
        "https://id.loc.gov/rwo/agents/n82054987": QID_USA, # Fairfield (Conn.)
        "https://id.loc.gov/rwo/agents/n82082899": QID_USA, # Ambridge (Pa.)
        "https://id.loc.gov/rwo/agents/n82134265": QID_ITALY, # Chiavari (Italy)
        "https://id.loc.gov/rwo/agents/n82227642": QID_USA, # Dickson County (Tenn.)
        "https://id.loc.gov/rwo/agents/n82253985": QID_ESTONIA,
        "https://id.loc.gov/rwo/agents/n83023590": QID_USA, # Riegelsville (Pa.)
        "https://id.loc.gov/rwo/agents/n91128701": QID_BELARUS,
        "https://id.loc.gov/rwo/agents/n91129869": QID_UZBEKISTAN,
        "https://id.loc.gov/rwo/agents/n92000010": QID_AZERBAIJAN,
        "https://id.loc.gov/rwo/agents/n92056007": QID_RUSSIA, # Russia (Federation)
        "https://id.loc.gov/rwo/agents/no2007082207": QID_NEW_ZEALAND, # Kapiti Coast District (N.Z.)
        "https://id.loc.gov/rwo/agents/no2010165638": QID_GUINEA, # Labé (Guinea)
    }

    if url in url_mapping:
        return url_mapping[url]
    else:
        raise RuntimeError(f"get_loc_url_country: Unknown url: {url}")
    #"http://www.wikidata.org/entity/Q18438')

def get_loc_locale_country(locale: str) -> str:
    if locale in loc_locale_dict:
        return loc_locale_dict[locale]

    # extract the part between parentheses
    match = re.search(r"\(([^)]+)\)", locale)
    if match:
        # parentheses text can be country, region, Federation/Republic
        parentheses_text = match.group(1)
        if parentheses_text in loc_locale_dict:
            return loc_locale_dict[parentheses_text]

    after = locale.split(",")[-1]
    if after:
        if after.endswith(")"):
            after = after[:-1]
        after = after.strip()
        if after in loc_locale_dict:
            return loc_locale_dict[after]

    raise RuntimeError(f"Loc: Unknown locale: {locale}")


# https://d-nb.info/standards/vocab/gnd/geographic-area-code.html
gnd_country_dict = {
    "XA-AD": QID_ANDORRA,
    "XA-AL": QID_ALBANIA,
    "XA-AT": QID_AUSTRIA,
    "XA-BA": QID_BOSNIA_AND_HERZEGOVINA,
    "XA-BE": QID_BELGIUM,
    "XA-BG": QID_BULGARIA,
    "XA-BY": QID_BELARUS,
    "XA-CH": QID_SWITZERLAND,
    "XA-CSHH": QID_CZECHOSLOVAKIA,
    "XA-CY": QID_CYPRUS,
    "XA-CZ": QID_CZECH_REPUBLIC,
    "XA-DDDE": QID_GERMAN_DEMOCRATIC_REPUBLIC,
    "XA-DE": QID_GERMANY,
    "XA-DK": QID_DENMARK,
    "XA-EE": QID_ESTONIA,
    "XA-ES": QID_SPAIN,
    "XA-FI": QID_FINLAND,
    "XA-FR": QID_FRANCE,
    "XA-GB": QID_UNITED_KINGDOM,
    "XA-GG": QID_GUERNSEY,
    "XA-GI": QID_GIBRALTAR,
    "XA-GR": QID_GREECE,
    "XA-HR": QID_CROATIA,
    "XA-HU": QID_HUNGARY,
    "XA-IE": QID_REPUBLIC_OF_IRELAND,
    "XA-IM": QID_ISLE_OF_MAN,
    "XA-IS": QID_ICELAND,
    "XA-IT": QID_ITALY,
    "XA-JE": QID_JERSEY,
    "XA-LI": QID_LIECHTENSTEIN,
    "XA-LT": QID_LITHUANIA,
    "XA-LU": QID_LUXEMBOURG,
    "XA-LV": QID_LATVIA,
    "XA-MC": QID_MONACO,
    "XA-MD": QID_MOLDOVA,
    "XA-ME": QID_MONTENEGRO,
    "XA-MK": QID_NORTH_MACEDONIA,
    "XA-MT": QID_MALTA,
    "XA-NL": QID_NETHERLANDS,
    "XA-NO": QID_NORWAY,
    "XA-PL": QID_POLAND,
    "XA-PT": QID_PORTUGAL,
    "XA-QV": QID_KOSOVO,
    "XA-RO": QID_ROMANIA,
    "XA-RS": QID_SERBIA,
    "XA-RU": QID_RUSSIA,
    "XA-SE": QID_SWEDEN,
    "XA-SI": QID_SLOVENIA,
    "XA-SK": QID_SLOVAKIA,
    "XA-SM": QID_SAN_MARINO,
    "XA-SUHH": QID_SOVIET_UNION,
    "XA-UA": QID_UKRAINE,
    "XA-VA": QID_VATICAN_CITY,
    "XA-YUCS": QID_FEDERAL_REPUBLIC_OF_YUGOSLAVIA,  # Yugoslavia
    "XB-AE": QID_UNITED_ARAB_EMIRATES,
    "XB-AF": QID_AFGHANISTAN,
    "XB-AM": QID_ARMENIA,
    "XB-AZ": QID_AZERBAIJAN,
    "XB-BD": QID_BANGLADESH,
    "XB-BH": QID_BAHRAIN,
    "XB-BN": QID_BRUNEI_DARUSSALAM,
    "XB-BT": QID_BHUTAN,
    "XB-CN-54": QID_TIBET_AUTONOMOUS_REGION,  # Tibet (China)
    "XB-CN": QID_CHINA,
    "XB-GE": QID_GEORGIA,  # Georgia (Republic)
    "XB-HK": QID_HONG_KONG,
    "XB-ID": QID_INDONESIA,
    "XB-IL": QID_ISRAEL,
    "XB-IN": QID_INDIA,
    "XB-IQ": QID_IRAQ,
    "XB-IR": QID_IRAN,
    "XB-JO": QID_JORDAN,
    "XB-JP": QID_JAPAN,
    "XB-KG": QID_KYRGYZSTAN,
    "XB-KH": QID_CAMBODIA,
    "XB-KP": QID_NORTH_KOREA,
    "XB-KR": QID_SOUTH_KOREA,
    "XB-KW": QID_KUWAIT,
    "XB-KZ": QID_KAZAKHSTAN,
    "XB-LA": QID_LAOS,
    "XB-LB": QID_LEBANON,
    "XB-LK": QID_SRI_LANKA,
    "XB-MM": QID_MYANMAR,
    "XB-MN": QID_MONGOLIA,
    "XB-MO": QID_MACAU,
    "XB-MV": QID_MALDIVES,
    "XB-MY": QID_MALAYSIA,
    "XB-NP": QID_NEPAL,
    "XB-OM": QID_OMAN,
    "XB-PH": QID_PHILIPPINES,
    "XB-PK": QID_PAKISTAN,
    "XB-QA": QID_QATAR,
    "XB-SA": QID_SAUDI_ARABIA,
    "XB-SG": QID_SINGAPORE,
    "XB-SY": QID_SYRIA,
    "XB-TH": QID_THAILAND,
    "XB-TJ": QID_TAJIKISTAN,
    "XB-TM": QID_TURKMENISTAN,
    "XB-TR": QID_TURKEY,
    "XB-TW": QID_TAIWAN,
    "XB-UZ": QID_UZBEKISTAN,
    "XB-VN": QID_VIETNAM,
    "XB-YE": QID_YEMEN,
    "XC-AO": QID_ANGOLA,
    "XC-BF": QID_BURKINA_FASO,
    "XC-BI": QID_BURUNDI,
    "XC-BJ": QID_BENIN,
    "XC-BW": QID_BOTSWANA,
    "XC-CD": QID_DEMOCRATIC_REPUBLIC_OF_THE_CONGO,
    "XC-CF": QID_CENTRAL_AFRICAN_REPUBLIC,
    "XC-CG": QID_REPUBLIC_OF_THE_CONGO,
    "XC-CI": QID_IVORY_COAST,
    "XC-CM": QID_CAMEROON,
    "XC-CV": QID_CAPE_VERDE,
    "XC-DJ": QID_DJIBOUTI,
    "XC-DZ": QID_ALGERIA,
    "XC-EG": QID_EGYPT,
    "XC-ER": QID_ERITREA,
    "XC-ET": QID_ETHIOPIA,
    "XC-GA": QID_GABON,
    "XC-GH": QID_GHANA,
    "XC-GN": QID_GUINEA,
    "XC-GQ": QID_EQUATORIAL_GUINEA,
    "XC-GW": QID_GUINEA_BISSAU,
    "XC-HVBF": QID_BURKINA_FASO,
    "XC-KE": QID_KENYA,
    "XC-KM": QID_COMOROS,
    "XC-LR": QID_LIBERIA,
    "XC-LS": QID_LESOTHO,
    "XC-LY": QID_LIBYA,
    "XC-MA": QID_MOROCCO,
    "XC-MG": QID_MADAGASCAR,
    "XC-ML": QID_MALI,
    "XC-MR": QID_MAURITANIA,
    "XC-MU": QID_MAURITIUS,
    "XC-MW": QID_MALAWI,
    "XC-MZ": QID_MOZAMBIQUE,
    "XC-NA": QID_NAMIBIA,
    "XC-NE": QID_NIGER,
    "XC-NG": QID_NIGERIA,
    "XC-RW": QID_RWANDA,
    "XC-SC": QID_SEYCHELLES,
    "XC-SD": QID_SUDAN,
    "XC-SL": QID_SIERRA_LEONE,
    "XC-SN": QID_SENEGAL,
    "XC-SO": QID_SOMALIA,
    "XC-SS": QID_SOUTH_SUDAN,
    "XC-SZ": QID_ESWATINI,
    "XC-TD": QID_CHAD,
    "XC-TG": QID_TOGO,
    "XC-TN": QID_TUNISIA,
    "XC-TZ": QID_TANZANIA,
    "XC-UG": QID_UGANDA,
    "XC-ZA": QID_SOUTH_AFRICA,
    "XC-ZM": QID_ZAMBIA,
    "XC-ZW": QID_ZIMBABWE,
    "XC": "",  # Africa
    "XD-AG": QID_ANTIGUA_AND_BARBUDA,
    "XD-AR": QID_ARGENTINA,
    "XD-AW": QID_ARUBA,
    "XD-BB": QID_BARBADOS,
    "XD-BO": QID_BOLIVIA,
    "XD-BR": QID_BRAZIL,
    "XD-BS": QID_THE_BAHAMAS,
    "XD-BZ": QID_BELIZE,
    "XD-CA": QID_CANADA,
    "XD-CL": QID_CHILE,
    "XD-CO": QID_COLOMBIA,
    "XD-CR": QID_COSTA_RICA,
    "XD-CU": QID_CUBA,
    "XD-DM": QID_DOMINICA,
    "XD-DO": QID_DOMINICAN_REPUBLIC,
    "XD-EC": QID_ECUADOR,
    "XD-GD": QID_GRENADA,
    "XD-GP": QID_GUADELOUPE,
    "XD-GT": QID_GUATEMALA,
    "XD-GY": QID_GUYANA,
    "XD-HN": QID_HONDURAS,
    "XD-HT": QID_HAITI,
    "XD-JM": QID_JAMAICA,
    "XD-KN": QID_SAINT_KITTS_AND_NEVIS,
    "XD-KY": QID_CAYMAN_ISLANDS,
    "XD-LC": QID_SAINT_LUCIA,
    "XD-MQ": QID_MARTINIQUE,
    "XD-MX": QID_MEXICO,
    "XD-NI": QID_NICARAGUA,
    "XD-PA": QID_PANAMA,
    "XD-PE": QID_PERU,
    "XD-PR": QID_PUERTO_RICO,
    "XD-PY": QID_PARAGUAY,
    "XD-SR": QID_SURINAME,
    "XD-SV": QID_EL_SALVADOR,
    "XD-TT": QID_TRINIDAD_AND_TOBAGO,
    "XD-US": QID_USA,
    "XD-UY": QID_URUGUAY,
    "XD-VC": QID_SAINT_VINCENT_AND_THE_GRENADINES,
    "XD-VE": QID_VENEZUELA,
    "XD": "",  # America
    "XE-AU": QID_AUSTRALIA,
    "XE-CK": QID_COOK_ISLANDS,
    "XE-FJ": QID_FIJI,
    "XE-FM": QID_FEDERATED_STATES_OF_MICRONESIA,
    "XE-KI": QID_KIRIBATI,
    "XE-MH": QID_MARSHALL_ISLANDS,
    "XE-MP": QID_NORTHERN_MARIANA_ISLANDS,
    "XE-NC": QID_NEW_CALEDONIA,
    "XE-NR": QID_NAURU,
    "XE-NZ": QID_NEW_ZEALAND,
    "XE-PG": QID_PAPUA_NEW_GUINEA,
    "XE-PW": QID_PALAU,
    "XE-SB": QID_SOLOMON_ISLANDS,
    "XE-TO": QID_TONGA,
    "XE-TV": QID_TUVALU,
    "XE-VU": QID_VANUATU,
    "XE-WS": QID_SAMOA,
    "XE": "",  # Australia, Oceania
    "XK-FO": QID_FAROE_ISLANDS,
    "XK-GL": QID_GREENLAND,
    "XL-RE": QID_REUNION,
    "XM-NU": QID_NIUE,
    "XM-PN": QID_PITCAIRN_ISLANDS,
    "XQ": "",  # World
    "XR": QID_CHINA,  # Orient -> chinese
    "XS": QID_ANCIENT_GREECE,
    "XT": QID_ROMAN_EMPIRE,
    "XU": QID_BYZANTINE_EMPIRE,
    "XV": QID_OTTOMAN_EMPIRE,  # Ottoman Empire; skip/arabic
    "XW": QID_SAUDI_ARABIA,  # Palestinian; skip/arabic
    "XX": QID_SAUDI_ARABIA,  # Arab Countries; skip/arabic
    "XY": QID_ISRAEL,  # Jews -> hebrew
    "ZZ": "",  # Country unknown
    "XD_BL": QID_SAINT_BARTHELEMY,
    "XA": "", # Europe
    "XA-DXDE": QID_GERMAN_REICH,
    "XB": QID_ASIA,
    "XC-ZRCD": QID_ZAIRE, # Congo (Democratic Republic)
    "XD-BL": QID_SAINT_BARTHELEMY,
    "XE-GU": QID_GUAM,
    # "XZ": "", #Imaginary places -> raise error
}


# https://data.bnf.fr/vocabulary/countrycodes/x
bnf_country_dict = {
    "aa": "",  # aire géographique ancienne
    "am": QID_ARMENIA,  # Armenia
    "an": QID_NETHERLANDS_ANTILLES,  # Antilles néerlandaises
    "anhh": QID_NETHERLANDS_ANTILLES,  # Antille néerlandaises (1954-2010à
    "ba": QID_BOSNIA_AND_HERZEGOVINA,  # Bosnia and Herzegovina
    "bn": QID_BRUNEI_DARUSSALAM,  # Brunei
    "bo": QID_BOLIVIA,  # Bolivie
    "cd": QID_DEMOCRATIC_REPUBLIC_OF_THE_CONGO,  # Congo (République démocratique)
    "cg": QID_REPUBLIC_OF_THE_CONGO,  # Congo
    "cshh": QID_CZECHOSLOVAKIA,  # Tchécoslovaquie (1918-1992)
    "csxx": QID_SERBIA_AND_MONTENEGRO,  # Serbie-et-Monténegro (2003-2006)
    "cv": QID_CAPE_VERDE,  # Cap-Vert
    "ddde": QID_GERMAN_DEMOCRATIC_REPUBLIC,  # Allemagne (République démocratique) (1949-1990)
    "hk": QID_HONG_KONG,
    "ir": QID_IRAN,  # Iran
    "kp": QID_NORTH_KOREA,  # Corée (République populaire démocratique)
    "kr": QID_SOUTH_KOREA,  # Corée (République)s
    "la": QID_LAOS,
    "ly": QID_LIBYA,  # Libye
    "md": QID_MOLDOVA,  # Moldavie
    "mk": QID_NORTH_MACEDONIA,  # Macédoine (République)
    "mm": QID_MYANMAR,  # Myanmar
    "ps": QID_PALESTINIAN_NATIONAL_AUTHORITY,  # Autorité palestinienne
    "ru": QID_RUSSIA,  # Russia
    "sr": QID_SURINAME,  # Suriname
    "suhh": QID_SOVIET_UNION,  # Soviet Union (1922-1991)
    "sy": QID_SYRIA,  # Syrie
    "tw": QID_TAIWAN,  # Chine (République)
    "tz": QID_TANZANIA,  # Tanzanie
    "ve": QID_VENEZUELA,  # Venezuela
    "vn": QID_VIETNAM,  # Viet Nam
    "xdhh": QID_GERMANY,  # Allemagne avant 1945
    "xkhh": QID_SOUTH_KOREA,  # Corée avant 1948
    "xnhh": QID_NETHERLANDS,  # Belgique et Pays-Bas avant 1830
    "yucs": QID_FEDERAL_REPUBLIC_OF_YUGOSLAVIA,  # Yougoslavie (1918-2006)
    "..": ""
}


COUNTRIES_FILE = DATA_DIR / "countries.json"
COUNTRIES_ISO_FILE = DATA_DIR / "countries_iso.json"
COUNTRIES_GEO_FILE = DATA_DIR / "countries_geo.json"
COUNTRIES_LOC_FILE = DATA_DIR / "countries_loc.json"
WD = "http://www.wikidata.org/entity/"


class Country:
    def __init__(
        self,
        qid: str,
        description: str,
        iso2: List[str] = None,
        iso3: List[str] = None,
        iso3166_2: List[str] = None,
        geo: List[str] = None,
        loc: List[str] = None,
        languages=None,
    ):

        self.qid = qid
        self.description = description
        self.iso2 = iso2 if iso2 is not None else []
        self.iso3 = iso3 if iso3 is not None else []
        self.iso3166_2 = iso3166_2 if iso3166_2 is not None else []
        self.geo = geo if geo is not None else []
        self.loc = loc if loc is not None else []
        self.languages = languages if languages is not None else []

    def add_property(self, property_name, value):
        if value and value not in getattr(self, property_name, []):
            getattr(self, property_name).append(value)

    def get_code(self):
        # Return the first string found from iso3, iso2, iso3166_2, or fallback to description
        return next(
            (code for code in (self.iso3 + self.iso2 + self.iso3166_2) if code),
            self.description,
        )

    def add_language(self, language_qid: str):
        language_obj = {
            "qid": language_qid,
        }
        self.languages.append(language_obj)

    def get_languages(self):
        lan = []
        for l in self.languages:
            qid = l["qid"]
            lan.append(qid)
        return lan

    # Method to serialize selected properties
    def to_dict(self):
        properties = [
            "description",
            "iso2",
            "iso3",
            "iso3166_2",
            "geo",
            "loc",
            "languages",
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
            iso2=data.get("iso2"),
            iso3=data.get("iso3"),
            iso3166_2=data.get("iso3166_2"),
            geo=data.get("geo"),
            loc=data.get("loc"),
            languages=data.get("languages"),
        )


class Countries:
    def __init__(self):
        self.qid_dict, self.iso_dict, self.geo_dict, self.loc_dict = (
            self.load_countries()
        )

    def get_country(self, country_qid: str) -> Country:
        if country_qid not in self.qid_dict:
            raise RuntimeError(f"Unknown qid country  {country_qid}")
        return self.qid_dict[country_qid]

    def get_country_from_geo(self, geo: str) -> str:
        if geo not in self.geo_dict:
            raise RuntimeError(f"Unknown geo country {geo}")

        # todo ; anders
        return self.geo_dict[geo][0]

    def get_country_from_loc(self, loc: str) -> str:
        if loc not in self.loc_dict:
            raise RuntimeError(f"Unknown loc country {loc}")

        # todo ; anders
        return self.loc_dict[loc][0]

    def is_hungarian_name_order_country(self, country_qid: str) -> bool:
        return country_qid in hungarian_name_order_countries_list

    def is_hungarian_name_order_language(self, language_qid: str) -> bool:
        for country_qid in hungarian_name_order_countries_list:
            if language_qid in self.get_country(country_qid).get_languages():
                return True
        return False

    def is_eastern_name_order_country(self, country: str) -> bool:
        return country in eastern_name_order_countries_list

    def is_eastern_name_order_language(self, language_qid: str) -> bool:
        for country_qid in eastern_name_order_countries_list:
            if language_qid in self.get_country(country_qid).get_languages():
                return True
        return False

    def load_countries(self):
        if os.path.exists(COUNTRIES_FILE):
            with open(COUNTRIES_FILE, "r") as file:
                data = json.load(file)

            qid_dict = {key: Country.from_dict(key, value) for key, value in data.items()}
        else:
            qid_dict = self.construct_language_dict(self.construct_country_dict())
            self.save(qid_dict)

        qid_dict[QID_MIDDLE_EAST] = Country(QID_MIDDLE_EAST, 'Middle East')
        qid_dict[QID_MIDDLE_EAST].add_language("Q13955") # arabic
        qid_dict[QID_AFRICA] = Country(QID_AFRICA, 'Africa')
        qid_dict[QID_ANCIENT_GREECE] = Country(QID_ANCIENT_GREECE, 'Ancient Greece')
        qid_dict[QID_ANTARCTICA] = Country(QID_ANTARCTICA, 'Antarctica ')
        qid_dict[QID_ASIA] = Country(QID_ASIA, 'Asia')
        qid_dict[QID_BRITISH_NORTH_AMERICA] = Country(QID_BRITISH_NORTH_AMERICA, 'British North America')
        qid_dict[QID_CANADIAN_PRAIRIES] = Country(QID_CANADIAN_PRAIRIES, 'Canadian Prairies')
        qid_dict[QID_CARIBBEAN] = Country(QID_CARIBBEAN, 'Caribbean')
        qid_dict[QID_CISLEITHANIA] = Country(QID_CISLEITHANIA, 'Cisleithania')
        qid_dict[QID_CLASSICAL_ATHENS] = Country(QID_CLASSICAL_ATHENS, 'Classical Athens')
        qid_dict[QID_IRELAND] = Country(QID_IRELAND, 'Ireland')
        qid_dict[QID_KIRGHIZ_SOVIET_SOCIALIST_REPUBLIC] = Country(QID_KIRGHIZ_SOVIET_SOCIALIST_REPUBLIC, 'Kirghiz Soviet Socialist Republic')
        qid_dict[QID_KOREA_UNDER_JAPANESE_RULE] = Country(QID_KOREA_UNDER_JAPANESE_RULE, 'Korea under Japanese rule')
        qid_dict[QID_LATIN_AMERICA] = Country(QID_LATIN_AMERICA, 'Latin America')
        qid_dict[QID_MANDATORY_PALESTINE] = Country(QID_MANDATORY_PALESTINE, 'Mandatory Palestine')
        qid_dict[QID_NEW_KINGDOM_OF_GRANADA] = Country(QID_NEW_KINGDOM_OF_GRANADA, 'New Kingdom of Granada')
        qid_dict[QID_NORTHERN_LOW_COUNTRIES] = Country(QID_NORTHERN_LOW_COUNTRIES, 'Northern Low Countries')
        qid_dict[QID_OTTOMAN_PALESTINE] = Country(QID_OTTOMAN_PALESTINE, 'Ottoman Palestine')
        qid_dict[QID_PROVINCE_OF_QUEBEC] = Country(QID_PROVINCE_OF_QUEBEC, 'Province of Quebec')
        qid_dict[QID_REPUBLIC_OF_ABKHAZIA] = Country(QID_REPUBLIC_OF_ABKHAZIA, 'Republic of Abkhazia')
        qid_dict[QID_SWEDEN_FINLAND] = Country(QID_SWEDEN_FINLAND, 'Sweden-Finland')
        qid_dict[QID_THIRTEEN_COLONIES] = Country(QID_THIRTEEN_COLONIES, 'Thirteen Colonies')
        qid_dict[QID_TIBET] = Country(QID_TIBET, 'Tibet')
        qid_dict[QID_WEST_BANK] = Country(QID_WEST_BANK, 'West Bank')


        iso_dict = {}
        geo_dict = {}
        loc_dict = {}

        for qid, country in qid_dict.items():
            for key, d in [
                ("iso2", iso_dict),
                ("iso3", iso_dict),
                ("iso3166_2", iso_dict),
                ("geo", geo_dict),
                ("loc", loc_dict),
            ]:
                # Use the country attribute directly, which is a list in the Country class
                items = getattr(country, key, [])
                if items:
                    for item in items:
                        if item not in d:
                            d[item] = []
                        if qid not in d[item]:
                            d[item].append(qid)

        return qid_dict, iso_dict, geo_dict, loc_dict

    def construct_country_dict(self) -> Dict[str, Country]:
        print("Loading countries")

        qry = """SELECT DISTINCT ?item ?itemLabel ?iso2 ?iso3 ?iso3166_2 ?geo (REPLACE(STR(?loc_value), "countries/", "") AS ?loc) WHERE {
                    {
                        ?item p:P31 ?statement0.
                        ?statement0 (ps:P31/(wdt:P279*)) wd:Q6256.
                    }
                    UNION
                    {
                        ?item p:P31 ?statement0.
                        ?statement0 (ps:P31/(wdt:P279*)) wd:Q3024240.
                    }
                    UNION
                    {
                        ?item p:P297 ?statement0.
                        ?statement0 ps:P297 _:anyValueP297.
                    }
                    UNION
                    {
                        ?item p:P298 ?statement1.
                        ?statement1 ps:P298 _:anyValueP298.
                    }
                    UNION
                    {
                        ?item p:P299 ?statement2.
                        ?statement2 ps:P299 _:anyValueP299.
                    }
                    UNION
                    {
                        ?item p:P300 ?statement3.
                        ?statement3 ps:P300 _:anyValueP300.
                    }
                    OPTIONAL { ?item wdt:P297 ?iso2. }
                    OPTIONAL { ?item wdt:P298 ?iso3. }
                    OPTIONAL { ?item wdt:P300 ?iso3166_2. }
                    OPTIONAL { ?item wdt:P1566 ?geo. }
                    OPTIONAL {
                        ?item wdt:P4801 ?loc_value.
                        FILTER(CONTAINS(LCASE(STR(?loc_value)), "countries/"))
                    }
                    SERVICE wikibase:label {
                        bd:serviceParam wikibase:language "en".
                        ?item rdfs:label ?itemLabel.
                    }
                    }"""

        result_dict = {}

        for row in query_wdqs_simple(qry):
            qid = row.get("item", {}).get("value", "").replace(WD, "")
            description = row.get("itemLabel", {}).get("value", "").replace(WD, "")
            keys_values = {
                "iso2": row.get("iso2", {}).get("value", "").replace(WD, ""),
                "iso3": row.get("iso3", {}).get("value", "").replace(WD, ""),
                "iso3166_2": row.get("iso3166_2", {}).get("value", "").replace(WD, ""),
                "geo": row.get("geo", {}).get("value", "").replace(WD, ""),
                "loc": row.get("loc", {}).get("value", "").replace(WD, ""),
            }

            if not qid.startswith("Q"):
                # unknown value
                continue

            # Check if the Country object already exists, or create a new one
            if qid not in result_dict:
                result_dict[qid] = Country(qid, description)

            country = result_dict[qid]

            # Add properties to the Country object
            for key, value in keys_values.items():
                country.add_property(key, value)

        return result_dict

    def construct_language_dict(self, result_dict: Dict[str, Country]) -> Dict[str, Country]:
        print("Loading languages of countries")

        qry = """SELECT DISTINCT ?item ?language ?languageLabel WHERE {
            {
                ?item p:P31 ?statement0.
                ?statement0 (ps:P31/(wdt:P279*)) wd:Q6256.
            }
            UNION
            {
                ?item p:P31 ?statement0.
                ?statement0 (ps:P31/(wdt:P279*)) wd:Q3024240.
            }
            UNION
            {
                ?item p:P297 ?statement0.
                ?statement0 ps:P297 _:anyValueP297.
            }
            UNION
            {
                ?item p:P298 ?statement1.
                ?statement1 ps:P298 _:anyValueP298.
            }
            UNION
            {
                ?item p:P299 ?statement2.
                ?statement2 ps:P299 _:anyValueP299.
            }
            UNION
            {
                ?item p:P300 ?statement3.
                ?statement3 ps:P300 _:anyValueP300.
            }
            ?item wdt:P37 ?language.
            FILTER(NOT EXISTS { ?language wdt:P31 wd:Q34228. })
            SERVICE wikibase:label {
                bd:serviceParam wikibase:language "en".
                ?language rdfs:label ?languageLabel.
            }
            }"""
        for row in query_wdqs_simple(qry):
            qid = row.get("item", {}).get("value", "").replace(WD, "")
            language_qid = row.get("language", {}).get("value", "").replace(WD, "")
            language = row.get("languageLabel", {}).get("value", "").replace(WD, "")
            if not qid.startswith("Q"):
                # unknown value
                continue
            if not language_qid.startswith("Q"):
                # unknown value
                continue

            if qid in result_dict:
                language_obj = {
                    "qid": language_qid,
                    "description": language,
                }
                result_dict[qid].languages.append(language_obj)

        return result_dict

    # def examine_dict(self, result_dict: Dict[str, Country]) -> Dict[str, Country]:
    #     for country in result_dict.values():
    #         code = (
    #             country.get("iso3", [None])[0]
    #             or country.get("iso2", [None])[0]
    #             or country.get("iso3166_2", [None])[0]
    #             or country.get("description")
    #         )
    #         country["code"] = code
    #         lan = []
    #         for l in country.get("languages", []):
    #             qid = l["qid"]
    #             lan.append(qid)
    #         country["lan"] = lan
    #     return result_dict

    def save(self, qid_dict):
        with open(COUNTRIES_FILE, "w") as file:
            json.dump({key: obj.to_dict() for key, obj in qid_dict.items()}, file, indent=4)


    def save_dicts(self):
        with open(COUNTRIES_ISO_FILE, "w") as outfile:
            json.dump(self.iso_dict, outfile, indent=4)
        with open(COUNTRIES_GEO_FILE, "w") as outfile:
            json.dump(self.geo_dict, outfile, indent=4)
        with open(COUNTRIES_LOC_FILE, "w") as outfile:
            json.dump(self.loc_dict, outfile, indent=4)


def main() -> None:
    c = Countries()
    #qid_dict[Q7204')
    c.get_country(QID_MIDDLE_EAST)
    c.get_country(QID_CISLEITHANIA)
    c.get_country(QID_KOREA_UNDER_JAPANESE_RULE)
    c.get_country(QID_MANDATORY_PALESTINE)
    c.get_country(QID_KIRGHIZ_SOVIET_SOCIALIST_REPUBLIC)
    c.get_country(QID_ANCIENT_GREECE)


if __name__ == "__main__":
    main()
