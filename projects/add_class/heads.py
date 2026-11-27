"""'The X is a <noun phrase>' -> the class of the head of that phrase, for hand-picked unambiguous heads (2026-10-31).

  python heads.py [--wiki en] [--min-age-days 180]
  in:  output/items_<wiki>.tsv, output/opening_<wiki>.tsv, output/done_<wiki>.txt + output/qs_<wiki>*_all.txt +
       output/*/rejected.tsv (all skipped)
  out: output/qs_<wiki>_heads_all.txt (QS v1) + heads_review.tsv (qid, why, head, title, opening)

The phrase runs up to the first stop word. A phrase ends in a head of RULES; 'only' lists the words allowed right before
the head ('' = none), 'block' the words that make it something else (car park, anti-tank mine). An opening with A/An names
a kind, not one thing, and is left out; so is a sentence whose subject is not the title, and 'X and Y' (two things).
"""
import argparse
import collections
import datetime as dt
import glob
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from groups import AROUND, KIND, LOOSE  # noqa: E402
from make_qs import first_revision  # noqa: E402
from nvc import classified  # noqa: E402
from stub_table import qlever  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "output")
STOP = set("""in of that which who located based from for by on at with to and or as where near between built founded
established designed published written produced created developed owned operated used held named known called made situated
under during about within run serving started formed issued released manufactured organized organised first originally
formerly consisting featuring than since while when after before whose it its has had but not through along across against
headquartered found living dwelling inhabiting playing appearing belonging played given presented promoted active contested
representing collected introduced launched dedicated focused specializing specialising recorded represented licensed celebrated
hosted operating originating set providing offering using covering containing including involving supporting dating currently commonly primarily widely often responsible being similar seen undertaken focusing working
available among amongst amid amidst over into toward towards upon per via around beyond behind inside outside throughout
sold worn practised practiced performed observed spoken aimed intended whereby wherein whereas thereby compiled""".split())
# 'a privately held company', 'an unaided government run medical college'; not 'a company owned by', 'a festival held annually'
OWNED = re.compile(r"\b[\w'-]+ (?:owned|held|traded|run|funded|operated|sponsored|backed|managed|led|dedicated) (?!(?:" + "|".join(sorted(STOP)) + r")\b|[\w-]+ly\b)", re.I)
ARTICLES = {"the", "a", "an", "his", "her", "their", "this", "these", "those", "its"}
SENT = re.compile(r"^(?:The )?(.{2,90}?)(?: \([^)]*\))?,? (is|was|are|were) an? ([^.;:()]{3,120})")
PLANNED = {"proposed", "planned", "fictional", "fictitious", "mythical", "mythological", "imaginary", "hypothetical", "legendary"}
PORTAL = re.compile(r"^(?:\w+ )+portal (?=[A-Z])")  # 'Christianity portal A house of hospitality ...'
FIELD = re.compile(r"^In [^,]{2,60}, ")  # 'In developmental psychology, thematic coherence is an organization of meanings'
# a title in common nouns is a concept, not a body with a name (computer memory organization, Thematic coherence)
BODY = {"organization", "organisation", "company", "brand", "manufacturer", "charity", "non-profit organization",
        "nonprofit organization", "not-for-profit organization", "non-profit organisation", "nonprofit organisation",
        "not-for-profit organisation", "non-governmental organization", "non-governmental organisation",
        "charitable organization", "charitable organisation"}
IS_ONLY = {"village", "town", "hamlet", "suburb", "locality", "neighborhood", "neighbourhood"}  # 'was' = a former place
PLACE = {"", "small", "large", "coastal", "fishing", "major", "residential", "rural", "suburban", "urban", "remote"}
NO_PLAN = {"proposed", "planned", "fictional", "mythical", "legendary", "former", "defunct"}
# head, class, only, block
RULES = [
    ("non-profit organization", "Q163740", None, set()), ("nonprofit organization", "Q163740", None, set()),
    ("not-for-profit organization", "Q163740", None, set()), ("non-profit organisation", "Q163740", None, set()),
    ("nonprofit organisation", "Q163740", None, set()), ("not-for-profit organisation", "Q163740", None, set()),
    ("non-governmental organization", "Q79913", None, set()), ("non-governmental organisation", "Q79913", None, set()),
    ("charitable organization", "Q708676", None, set()), ("charitable organisation", "Q708676", None, set()),
    ("charity", "Q708676", None, set()),
    ("organization", "Q43229", None, {"terrorist", "militant", "crime", "criminal", "paramilitary", "guerrilla"}),
    ("organisation", "Q43229", None, {"terrorist", "militant", "crime", "criminal", "paramilitary", "guerrilla"}),
    ("theatre company", "Q742421", None, set()), ("theater company", "Q742421", None, set()),
    ("company", "Q783794", None, {"opera", "dance", "ballet", "military", "infantry", "artillery", "rifle", "tank", "engineer",
                                  "independent", "sister", "repertory", "touring", "puppet", "circus", "marine", "improvisational", "improv",
                                  "comedy", "performing", "performance", "ensemble", "arts", "theatre", "theater", "theatrical",
                                  "spanish-dance", "stage", "acting", "drama", "storytelling", "shakespeare"}),
    ("manufacturer", "Q13235160", None, set()), ("law firm", "Q613142", None, set()), ("record label", "Q18127", None, set()),
    ("airline", "Q46970", None, NO_PLAN), ("brewery", "Q131734", None, NO_PLAN), ("winery", "Q156362", None, NO_PLAN),
    ("distillery", "Q1251750", None, NO_PLAN), ("brand", "Q431289", None, set()),
    ("restaurant", "Q11707", None, set()), ("hotel", "Q27686", None, NO_PLAN | {"heritage-listed"}),
    ("magazine", "Q41298", None, {"gunpowder", "powder"}), ("newspaper", "Q11032", None, set()),
    ("bank", "Q22687", {"commercial", "investment", "savings", "community", "private", "state-owned", "central"}, set()),
    ("golf tournament", "Q2990946", None, {"disc", "snow"}), ("card game", "Q142714", None, set()),
    ("board game", "Q131436", None, set()), ("athletic conference", "Q2992826", None, set()),
    ("music festival", "Q868557", None, set()), ("film festival", "Q220505", None, set()), ("festival", "Q132241", None, set()),
    ("rugby league football club", "Q15221215", None, set()), ("rugby league club", "Q15221215", None, set()),
    ("rugby union football club", "Q43009164", None, set()), ("rugby union club", "Q43009164", None, set()),
    ("australian football club", "Q17374546", None, set()), ("australian rules football club", "Q17374546", None, set()),
    ("football club", "Q476028", None, {"rules", "gaelic", "american", "canadian", "rugby", "gridiron", "supporting", "fan", "touch"}),
    ("political party", "Q7278", None, set()),
    ("trade union", "Q178790", None, set()), ("noble family", "Q13417114", None, set()), ("clan", "Q211503", None, {"camorra", "mafia", "crime"}),
    ("denomination", "Q13414953", None, {"banknote", "currency", "coin"}),
    ("government agency", "Q327333", None, set()), ("law enforcement agency", "Q732717", None, set()),
    ("school district", "Q398141", None, {"former"}), ("historic district", "Q15243209", None, set()),
    ("archaeological site", "Q839954", None, set()), ("radio station", "Q14350", None, {"pirate", "clandestine"}),
    ("television channel", "Q2001305", None, set()), ("website", "Q35127", None, set()),
    ("keelboat", "Q106179098", None, set()), ("sailboat", "Q106179098", None, set()),
    ("song", "Q7366", None, {"fight"}), ("sculpture", "Q860861", None, NO_PLAN), ("statue", "Q179700", None, NO_PLAN),
    ("monument", "Q4989906", None, {"natural", "geological", "national"} | NO_PLAN),
    ("park", "Q22698", {"", "public", "urban", "municipal", "city", "county", "regional", "recreational", "large", "small", "historic"}, set()),
    ("museum", "Q33506", None, NO_PLAN), ("cemetery", "Q39614", None, set()), ("castle", "Q23413", None, NO_PLAN),
    ("palace", "Q16560", None, {"movie", "former"} | NO_PLAN), ("mosque", "Q32815", None, set()), ("cathedral", "Q2977", None, set()),
    ("synagogue", "Q34627", None, {"former"}), ("monastery", "Q44613", None, set()), ("abbey", "Q160742", None, set()),
    ("theatre", "Q24354", {"", "historic", "broadway"}, set()), ("university", "Q3918", None, NO_PLAN | {"failed", "militant", "unaccredited", "the", "union"}),
    ("college", "Q189004", {"", "private", "women's", "junior", "medical", "small", "liberal", "business"}, set()),
    ("stadium", "Q483110", None, NO_PLAN), ("arena", "Q641226", None, NO_PLAN), ("hospital", "Q16917", {"", "public", "general", "teaching", "military"}, set()),
    ("shopping mall", "Q31374404", None, NO_PLAN), ("shopping centre", "Q11315", None, NO_PLAN),
    ("mine", "Q820477", {"coal", "gold", "copper", "iron", "silver", "tin", "diamond", "open-pit"}, set()),
    ("river", "Q4022", {""}, set()), ("lake", "Q23397", {"", "freshwater", "small", "salt", "natural", "glacial"}, set()),
    ("mountain", "Q8502", {""}, set()), ("hill", "Q54050", {"", "small"}, set()), ("peninsula", "Q34763", {"", "small"}, set()),
    ("bay", "Q39594", {"", "small", "large"}, set()), ("beach", "Q40080", {"", "small", "coastal"}, set()),
    ("island", "Q23442", {"", "small", "uninhabited", "barrier", "undeveloped", "granite", "river", "private"}, set()),
    ("village", "Q532", PLACE, set()), ("town", "Q3957", PLACE, set()), ("hamlet", "Q5084", PLACE, set()),
    ("suburb", "Q188509", PLACE, set()), ("locality", "Q3257686", PLACE, set()),
    ("neighborhood", "Q123705", PLACE | {"historic"}, set()), ("neighbourhood", "Q123705", PLACE | {"historic"}, set()),
    ("treaty", "Q131569", None, {"unimplemented"}),
    # round 2 (2026-11-01)
    ("think tank", "Q155271", None, set()), ("advocacy group", "Q431603", None, set()), ("research institute", "Q31855", None, set()),
    ("research center", "Q7315155", None, set()), ("research centre", "Q7315155", None, set()), ("trade association", "Q2178147", None, set()),
    ("professional association", "Q829080", None, set()), ("educational institution", "Q2385804", None, set()),
    ("publishing house", "Q2085381", None, set()), ("book publisher", "Q2085381", None, set()), ("wrestling promotion", "Q721067", None, set()),
    ("opera company", "Q20819922", None, set()), ("ballet company", "Q805233", None, set()), ("television station", "Q1616075", None, NO_PLAN),
    ("television network", "Q1254874", None, NO_PLAN), ("radio network", "Q1061197", None, {"mobile"}), ("television channel", "Q2001305", None, set()),
    ("tv channel", "Q2001305", None, set()), ("specialty channel", "Q561068", None, set()), ("religious order", "Q2061186", None, set()),
    ("political alliance", "Q60170135", None, set()), ("political movement", "Q2738074", None, set()), ("statutory body", "Q43108199", None, set()),
    ("nightclub", "Q622425", None, {"virtual"}), ("tambon", "Q1077097", None, set()), ("unincorporated community", "Q17343829", None, set()),
    ("ghost town", "Q74047", None, set()), ("historic building", "Q35112127", None, set()), ("historic house", "Q5773747", None, set()),
    ("art gallery", "Q1007870", None, set()), ("protected area", "Q473972", None, NO_PLAN), ("nature reserve", "Q179049", None, NO_PLAN),
    ("golf course", "Q1048525", None, NO_PLAN), ("golf club", "Q2022036", None, set()), ("waterfall", "Q34038", None, set()),
    ("hindu temple", "Q842402", None, set()), ("buddhist temple", "Q5393308", None, set()), ("catholic church", "Q1088552", None, set()),
    ("fort", "Q1785071", {"", "former", "historic", "military", "colonial", "british", "french", "spanish", "dutch", "portuguese", "roman", "hill", "small", "old"}, set()),
    ("housing estate", "Q12104567", None, set()), ("residential area", "Q674950", None, set()), ("beauty pageant", "Q2658935", None, set()),
    ("tennis tournament", "Q13219666", None, set()), ("basketball tournament", "Q4867756", None, set()), ("art exhibition", "Q667276", None, set()),
    ("wrestling event", "Q17317604", {"professional"}, set()), ("concert tour", "Q1573906", None, set()), ("constitutional amendment", "Q53463", None, {"proposed"}),
    ("political scandal", "Q934744", None, set()), ("radio galaxy", "Q217012", None, set()), ("board wargame", "Q4931403", None, set()),
    ("play-by-mail game", "Q1129581", None, set()), ("infantry division", "Q9248092", None, set()), ("infantry battalion", "Q15704239", None, set()),
    ("infantry regiment", "Q10358588", None, set()), ("artillery battery", "Q240313", None, set()), ("military unit", "Q176799", None, set()),
    ("express train", "Q67454740", None, set()), ("deity", "Q178885", None, set()), ("god", "Q178885", None, set()), ("goddess", "Q178885", None, set()),
    ("dynasty", "Q164950", {"", "ruling", "royal", "imperial", "hasidic", "chinese", "persian", "indian", "muslim", "local", "small", "minor"}, set()),
    ("tribe", "Q133311", None, {"apprenticeship", "musical"}), ("caste", "Q484416", None, set()), ("ethnic group", "Q41710", None, set()),
    ("hasidic dynasty", "Q2591905", None, set()), ("comic book series", "Q14406742", None, set()), ("book series", "Q277759", None, set()), ("graphic novel", "Q725377", None, set()), ("comic strip", "Q838795", None, set()),
    ("manga series", "Q21198342", None, set()), ("web series", "Q526877", None, set()), ("television series", "Q5398426", None, NO_PLAN),
    ("fairy tale", "Q699", None, set()), ("academic journal", "Q737498", None, set()), ("scientific journal", "Q5633421", None, set()),
    ("ice hockey team", "Q4498974", None, set()), ("hockey team", "Q4498974", {"ice", "junior", "professional", "league", "minor", "senior", "amateur"}, set()),
    ("baseball team", "Q13027888", None, set()), ("basketball team", "Q13393265", None, set()), ("cricket team", "Q17376093", None, set()),
    ("volleyball team", "Q15720476", None, set()), ("softball team", "Q82969709", None, set()), ("lacrosse team", "Q116431233", None, set()),
    ("netball team", "Q134468953", None, set()), ("racing team", "Q20074337", None, {"cycling", "bicycle", "horse", "dragon", "boat", "yacht", "motorcycle", "motocross"}),
    ("american football team", "Q17156793", None, set()), ("rugby league team", "Q15221215", None, set()),
    ("association football team", "Q15944511", None, set()), ("rock band", "Q5741069", None, set()), ("sports club", "Q847017", None, set()),
    ("constituency", "Q192611", None, set()), ("electoral district", "Q192611", None, set()), ("electoral division", "Q192611", None, set()),
    # round 3 (2026-11-01): the class of pages opening the same way; sports classes stay generic, 'football' can be any code
    # a Camorra clan is a crime group, a 'natural geological formation' a landform, a 'third-level education award' a qualification
    ("cricket ground", "Q682943", None, NO_PLAN), ("civil parish", "Q1115575", None, set()), ("music venue", "Q8719053", None, NO_PLAN),
    ("commercial building", "Q655686", None, NO_PLAN), ("office building", "Q1021645", None, NO_PLAN), ("papal bull", "Q189867", None, set()),
    ("geologic formation", "Q736917", None, {"natural", "anticline"}), ("geological formation", "Q736917", None, {"natural", "anticline"}), ("secondary school", "Q159334", None, NO_PLAN),
    ("high school", "Q9826", None, NO_PLAN), ("learned society", "Q955824", None, set()), ("government ministry", "Q192350", None, set()),
    ("princely state", "Q1336152", None, set()), ("settlement", "Q486972", PLACE, set()), ("award", "Q618779", None, {"education"}),
    ("football competition", "Q13406554", None, set()), ("cup competition", "Q13406554", None, set()), ("league competition", "Q13406554", None, set()),
    ("club competition", "Q13406554", None, set()), ("cricket competition", "Q13406554", None, set()), ("football tournament", "Q13406554", None, set()),
    ("cricket tournament", "Q13406554", None, set()), ("hockey tournament", "Q13406554", None, set()), ("curling tournament", "Q13406554", None, set()),
    ("football league", "Q623109", None, set()), ("hockey league", "Q623109", None, set()), ("basketball league", "Q623109", None, set()),
    ("baseball league", "Q623109", None, set()), ("cricket league", "Q623109", None, set()),
]
BY_LEN = sorted(RULES, key=lambda r: -len(r[0]))
# 'The Mangarla are an Aboriginal people', 'The Barrie Blizzard were a lacrosse team': a plural subject is one thing only for these
PLURAL = {"tribe", "caste", "ethnic group", "ice hockey team", "hockey team", "baseball team", "basketball team", "cricket team", "volleyball team",
          "softball team", "lacrosse team", "netball team", "racing team", "american football team", "rugby league team",
          "rugby league football club", "rugby league club", "association football team", "football club", "rock band", "noble family", "clan", "dynasty"}
PAGE_CAT = {"All_disambiguation_pages", "All_set_index_articles", "Surnames", "Given_names"}  # the page is a list of things, whatever its opening says


def phrase(s):
    """Words of the noun phrase after is/was a(n), or None; 'hotel and casino' is two things and gives None."""
    m = SENT.match(s)
    if not m:
        return None
    words = []
    tokens = OWNED.sub("", re.sub(r"\[[^\]]*\]", "", m.group(3))).replace(",", " , ").split()  # 'company[where?] developing'
    for i, w in enumerate(tokens):
        if w == ",":
            continue
        # a second noun phrase begins: 'an emerging field concerning the quantum technology of ...'
        if w.casefold() in ARTICLES or (w.casefold().endswith("ing") and i + 1 < len(tokens) and tokens[i + 1].casefold() in ARTICLES):
            break
        if w.casefold() in ("and", "or"):
            return None
        if w.casefold() in STOP or not re.fullmatch(r"[A-Za-z'-]+", w):
            break
        words.append(w.casefold())
    return words or None


CLAUSE = re.compile(r"\b(?:is|was|are|were|which|who|that|has|had|where|whose)\b|[.!?] ", re.I)


def key(text):
    return re.sub(r"[\W_]+", "", re.sub(r"^the ", "", text.casefold()))


def about_title(t, s):
    """The sentence is about the page itself: subject and title contain each other (not 'Liverpool F.C. league record')."""
    m = SENT.match(s)
    name = re.sub(r" \(.*\)$", "", re.sub(r",.*$", "", t))
    title_key, subject = key(name), key(m.group(1)) if m else ""
    if not subject or not title_key:
        return False
    # the class is in a side clause or a later sentence: 'Mayurbhanj Palace was the royal palace of ..., which was a princely state'
    if CLAUSE.search(m.group(1).casefold().replace(name.casefold(), "")):
        return False
    # the subject stops inside a title word and the title goes on: 'Goa is a tiny region' on the page 'Goans in sports' (not 'Portland Western')
    at = name.casefold().find(m.group(1).casefold())
    rest = name[at + len(m.group(1)):] if at >= 0 else ""
    if rest[:1].isalpha() and " " in rest:
        return False
    # a title may add a word to the subject (Tatka Village), not a phrase (Paksi FC in European football)
    return title_key in subject or (subject in title_key and len(title_key) - len(subject) <= 12)


EVENT = {"golf tournament", "festival", "music festival", "film festival", "tennis tournament", "basketball tournament", "beauty pageant",
         "award", "football competition", "cup competition", "league competition", "club competition", "cricket competition", "football tournament",
         "cricket tournament", "hockey tournament", "curling tournament", "football league", "hockey league", "basketball league", "baseball league",
         "cricket league"}
YEAR = re.compile(r"\b(?:1[0-9]|20)\d\d\b")  # '1994 Senior British Open' = one edition, P31 is the series there
CURRENCY = re.compile(r"\bcurrency\b|\bcoin(?:age)?\b|\bbanknote\b|\bnote\b", re.I)  # the 'denomination' rule means religion
# 'a French restaurant with two locations' is a small chain, not one restaurant (user 2026-11-01)
LOCATIONS = re.compile(r"\b(?:with|has|have|operates?) (?:[\w-]+ ){0,4}locations\b|\b\w+-location\b|\bchain\b|"
                       r"\b(?:second|third|other|additional) locations?\b|\bhas operated in\b", re.I)


# 'The Clash on film', 'FC Kremin Kremenchuk statistics', 'Cooking Papa (volumes 1–100)': the opening names the subject of the page, not the page
ASPECT_TAIL = re.compile(r"\bon film\b|\bstatistics\b|\brecords?\b|\bseasons?\b|\bdraft\b|\bpicks\b|\bHall of Fame\b|\bresults\b|"
                         r"\baccomplishments\b|\bcheerleading\b|\bsquads?\b|\bplayers\b|\bhistory\b|\broster\b|\bopponent\b|\(volumes\b", re.I)
ANOTHER_VIEW = re.compile(r"^(?:According to|As |For |Under )")  # 'According to the Swaminarayan philosophy, a Dev Mandir is ...' = a kind
TAXON = re.compile(r"\b(?:sub)?famil(?:y|ies)\b|\bgenus\b|\bgenera\b")  # 'Mydini is a tribe of flies in the family Mydidae'
TEAM_HEAD = re.compile(r"\b(?:team|club)$")
OUTSIDE_US = re.compile(r"\b(?:Canada|Alberta|Quebec|Ontario|British Columbia|Manitoba|Saskatchewan|Newfoundland|Nova Scotia|New Brunswick|Yukon|Philippines|Australia)\b")


def aspect_title(t, s):
    """The title is about something around the subject: Pre-colonial Timor, Capture of Fricourt, USAID in Bangladesh, IndiGo fleet."""
    m = SENT.match(s)
    title = re.sub(r" \(.*\)$", "", re.sub(r",.*$", "", t))
    at = title.casefold().find(m.group(1).casefold()) if m else -1
    if at < 0:
        return False
    before, after = title[:at].strip(), title[at + len(m.group(1)):].strip()
    return bool(re.search(r"(?:^|[\s-])[a-z]+$", before)) or after.startswith("in ") or after in ("fleet", "mascots", "tehsil")


ONE_OFF = re.compile(r"\bone-(?:off|time)\b|\bheld (?:only )?once\b|\bonly (?:once|edition)\b|\bsingle edition\b", re.I)
RECURS = re.compile(r"\b(?:annual(?:ly)?|yearly|biennial(?:ly)?|bi-annual|every (?:\w+ )?years?|each (?:year|season)|seasons?|editions?|inaugural|first held|"
                    r"winners?|champions|since \d{4}|from \d{4} (?:to|until)|between \d{4} and)\b", re.I)
A_LEAGUE = re.compile(r"\b(?:League|Liga|Division|Premiership|Football Association)\b")
NOT_A_LEAGUE = re.compile(r"\b(?:Cup|Trophy|Shield|Nations|Challenge|Series|Championship|Tournament|Bowl|Vase|Plate|Classic|Knock-?out)\b", re.I)
NAMED_EVENT = re.compile(r"\b(?:Cup|Trophy|Shield|Championship|Bowl|Vase|Plate|Series|Classic|Open|Invitational)\b")
SPORTS_COMPETITION = "Q13406554"


def competition_class(words, t, s):
    """A sports competition line that is a league or a series gets that class; a one-off or an unclear one stays generic (user 2026-11-01)."""
    text = " ".join(words)
    if ONE_OFF.search(s[:500]):
        return SPORTS_COMPETITION
    if (A_LEAGUE.search(t) and not NOT_A_LEAGUE.search(t)) or (text.endswith("league competition") and not text.endswith("rugby league competition")):
        return "Q623109"  # sports league; 'rugby league competition' names the sport
    present = SENT.match(s).group(2) == "is" and NAMED_EVENT.search(t)
    if RECURS.search(s[:500]) or text.endswith(("cup competition", "club competition")) or present:
        return "Q18608583"  # recurring sporting event
    return SPORTS_COMPETITION


def common_title(t):
    """Several words, none capitalised after the first, no digit."""
    words = re.sub(r" \(.*\)$", "", t).split()
    return len(words) > 1 and not re.search(r"\d", t) and all(not w[:1].isupper() for w in words[1:])


def rule_for(words, verb="is"):
    text = " ".join(words)
    for rule in BY_LEN:
        head, _, only, block = rule
        if text == head or text.endswith(" " + head):
            before = text[:-len(head)].split()
            prev = before[-1] if before else ""
            if only is not None and prev not in only:
                return None, head
            if prev in block or set(before) & (block | PLANNED) or (head in IS_ONLY and verb != "is"):
                return None, head
            return rule, head
    return None, ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wiki", default="en")
    ap.add_argument("--min-age-days", type=int, default=180)
    ap.add_argument("--round", type=int, default=1, help="output qs_<wiki>_heads<N>_all.txt (round 1: qs_<wiki>_heads_all.txt)")
    ap.add_argument("--force", action="store_true", help="overwrite this round's output")
    args = ap.parse_args()
    suffix = str(args.round) if args.round > 1 else ""
    with open(os.path.join(OUT, f"items_{args.wiki}.tsv"), encoding="utf-8") as fh:
        title = dict(line.rstrip("\n").split("\t", 1) for line in fh if "\t" in line)
    with open(os.path.join(OUT, f"done_{args.wiki}.txt"), encoding="utf-8") as fh:
        done = {line.strip() for line in fh if line.strip()}
    this = os.path.join(OUT, f"qs_{args.wiki}_heads{suffix}_all.txt")
    if os.path.exists(this) and not args.force:  # a rerun after upload finds every item classed and would empty the record of the batch
        sys.exit(f"{os.path.basename(this)} exists; pick a new --round, or --force for a draft that has not been uploaded")
    page_cat = set()
    with open(os.path.join(OUT, f"cats_{args.wiki}.tsv"), encoding="utf-8") as fh:
        for line in fh:
            q, cat = line.rstrip("\n").split("\t", 1)
            if cat in PAGE_CAT:
                page_cat.add(q)
    paths = [p for p in glob.glob(os.path.join(OUT, f"qs_{args.wiki}*_all.txt")) if os.path.abspath(p) != os.path.abspath(this)]
    for path in paths + glob.glob(os.path.join(OUT, "*", "rejected.tsv")):
        with open(path, encoding="utf-8") as fh:
            done.update(line.split("\t", 1)[0] for line in fh if line.startswith("Q"))
    opening = {}
    with open(os.path.join(OUT, f"opening_{args.wiki}.tsv"), encoding="utf-8") as fh:
        for line in fh:
            q, text = line.rstrip("\n").split("\t", 1)
            opening[q] = text
    pick, notes = {}, []
    for q, t in title.items():
        s = PORTAL.sub("", opening.get(q, ""))
        if q in done or ":" in t or AROUND.search(t) or KIND.match(s):
            continue
        words = phrase(s)
        if not words:
            continue
        verb = SENT.match(s).group(2)
        rule, head = rule_for(words, verb)
        if verb in ("are", "were") and head not in PLURAL:
            continue
        if rule and (q in page_cat or t.endswith("(disambiguation)")):
            notes.append((q, "disambiguation, set index or name page", head, t, s[:150]))
        elif rule and (ASPECT_TAIL.search(t) or ANOTHER_VIEW.match(s)):
            notes.append((q, "the page is about something around the subject", head, t, s[:150]))
        elif rule and TEAM_HEAD.search(head) and YEAR.match(t):
            notes.append((q, "season of a team", head, t, s[:150]))
        elif rule and head == "tribe" and TAXON.search(s[:200]):
            notes.append((q, "taxonomic tribe", head, t, s[:150]))
        elif rule and head == "unincorporated community" and OUTSIDE_US.search(s[:200]):
            notes.append((q, "the class is for the United States", head, t, s[:150]))
        elif rule and re.search(rf"\b{head.split()[-1].capitalize()}\b", SENT.match(s).group(3)):
            notes.append((q, "capitalised head is a name", head, t, s[:150]))  # 'a National Football League (NFL) game'
        elif rule and head == "civil parish" and "England" not in s[:200]:
            notes.append((q, "the class is for England", head, t, s[:150]))
        elif rule and FIELD.match(s):
            notes.append((q, "opening starts with In <field>", head, t, s[:150]))
        elif rule and head in BODY and common_title(t):
            notes.append((q, "title in common nouns", head, t, s[:150]))
        elif rule and aspect_title(t, s):
            notes.append((q, "title is about something around the subject", head, t, s[:150]))
        elif rule and head in EVENT and YEAR.search(t):
            notes.append((q, "edition of a series", head, t, s[:150]))
        elif rule and head == "denomination" and CURRENCY.search(s[:200]):
            notes.append((q, "denomination of a currency", head, t, s[:150]))
        elif rule and head == "restaurant" and LOCATIONS.search(s[:400]):
            notes.append((q, "restaurant with several locations", head, t, s[:150]))
        elif rule and about_title(t, s):
            pick[q] = rule
        elif head:
            notes.append((q, "modifier or start not allowed", head, t, s[:150]))
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=args.min_age_days)).strftime("%Y%m%d%H%M%S")
    first = first_revision(list(pick))
    have = classified(sorted(pick))
    lines, count = [], collections.Counter()
    for q in sorted(pick, key=lambda x: int(x[1:])):
        head, cls = pick[q][:2]
        s = opening.get(q, "")
        if cls == SPORTS_COMPETITION:
            plain = PORTAL.sub("", s)
            cls = competition_class(phrase(plain), title[q], plain)
        if first.get(q, "9") > cutoff:
            notes.append((q, "too new", head, title[q], s[:150]))
        elif q in have:
            notes.append((q, "has a class by now", head, title[q], s[:150]))
        elif LOOSE.search(s[:300]):
            notes.append((q, "may refer to / set index", head, title[q], s[:150]))
        else:
            lines.append(f"{q}\tP31\t{cls}\n")
            count[head] += 1
    with open(this, "w", encoding="utf-8", newline="\n") as fh:
        fh.writelines(lines)
    with open(os.path.join(OUT, f"heads{suffix}_review.tsv"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write("qid\twhy\thead\ttitle\topening\n")
        fh.writelines("\t".join(n) + "\n" for n in sorted(notes, key=lambda n: (n[2], n[1])))
    print(f"{len(lines)} QS lines -> {os.path.basename(this)}; {len(notes)} in review")
    classes = sorted({r[1] for r in RULES})
    label = {}
    for i in range(0, len(classes), 100):
        for r in qlever("PREFIX wd: <http://www.wikidata.org/entity/> PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#> "
                        f"SELECT ?c ?l WHERE {{ VALUES ?c {{ {' '.join('wd:' + c for c in classes[i:i + 100])} }} ?c rdfs:label ?l "
                        'FILTER(LANG(?l) = "en") }'):
            label[r["c"]] = r["l"]
    for head, cls, *_ in RULES:
        print(f"{count[head]}\t{head}\t{cls}\t{label.get(cls, '?')}")


if __name__ == "__main__":
    main()
