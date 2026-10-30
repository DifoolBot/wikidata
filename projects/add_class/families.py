"""Title families ('Outline of X', 'Foreign relations of X' ...) -> the P31 their classified enwiki siblings have.

  python families.py [--wiki en] [--min-age-days 180] [--round N]
  in:  output/items_<wiki>.tsv, output/opening_<wiki>.tsv, output/done_<wiki>.txt (skipped)
  out: output/qs_<wiki>_family<N>_all.txt (QS v1, P31 only; round 1 without N)
       + skipped_families.tsv (qid, reason, family, title, sentence)

Class per family = the majority P31 among enwiki articles with the same title pattern that already have one (QLever,
2026-10-30; share among the top 4 classes in brackets). Only families with a clear majority; 'Politics of' (political
system 264 / politics by country 234), 'Military ranks of', 'Women in', 'National symbols of' and 'Gun laws in' are
split or thin, 'Parish of' / 'Electoral district of' need a per-state class. The title decides, not the opening:
'Foreign relations of Kiribati' opens with 'Kiribati is a full member of the Commonwealth'.
Year families (round 2) were counted on the enwiki replica titles + a 2,000 sample: '<year> ... – Singles/Doubles' are
tennis events (1,842/2,000) when the parent tournament ('2026 Pune Challenger') has sport (P641) tennis; badminton
events share the pattern. Not used: '<year> ... football team' (ours are All-Conference selections, not team seasons),
'<year> ... Council election' and '<year> ... Cup final' (split).
Round 3: 'Parish of' / 'Electoral district of' have a per-state class among the siblings, but our items are nearly all
one state (New South Wales, Victoria); IN_SENTENCE keeps that state's only.
"""
import argparse
import collections
import datetime as dt
import glob
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from history import enwiki_items  # noqa: E402
from make_qs import first_revision  # noqa: E402
from stub_table import qlever  # noqa: E402
from verify_stub import first_sentence  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "output")
FAMILY = {  # title prefix (or name) -> (class, siblings with it of the top 4[, title regex])
    "Outline of ": ("Q26884324", "792/897"),  # Wikimedia outline article
    "Foreign relations of ": ("Q610018", "171/181"),  # foreign relations
    "Bibliography of ": ("Q1631107", "258/310"),  # bibliography
    "Time in ": ("Q22676729", "121/143"),  # time by area
    "Judiciary of ": ("Q105985", "44/53"),  # judiciary
    "Glossary of ": ("Q63254493", "250/324"),  # Wikimedia glossary list article
    "Coat of arms of ": ("Q14659", "393/617"),  # coat of arms; national/local coat of arms are its subclasses
    "Murder of ": ("Q132821", "1127/1559"),  # murder; most of the rest is P31 human, which is wrong
    "Anglican Diocese of ": ("Q18917976", "70/104"),  # Anglican diocese; the rest are other diocese classes
    "Index of ": ("Q13406463", "392/412"),  # Wikimedia list article
    "Parish of ": ("Q28931760", "152/169"),  # parish of New South Wales, see IN_SENTENCE
    "Electoral district of ": ("Q5356187", "234/814"),  # electoral district of Victoria: ours are all Victorian
    # round 4, shares of the classified siblings in a sample of at most 1,000 replica titles
    "<...> statistical leaders": ("Q13406463", "247/251", r".+ statistical leaders$"),  # Wikimedia list article
    "Billboard Year-End Hot ": ("Q98645843", "67/68"),  # Wikimedia music-related list
    "Sun Odyssey ": ("Q106179098", "8/8"),  # sailboat class
    "Military history of ": ("Q17524420", "63/88"),  # aspect of history
    "Orders, decorations, and medals of ": ("Q13406463", "108/129"),  # Wikimedia list article
    "<year> ... gubernatorial election": ("Q15261477", "748/988", r"^\d{4}.* gubernatorial election$"),
    "<year> ... leadership election": ("Q6508670", "762/956", r"^\d{4}.* leadership election$"),
    "<year> ... mayoral election": ("Q15280243", "705/990", r"^\d{4}.* mayoral election$"),
    # round 5, the user's model Men's long jump world record progression (Q60748521), with EXTRA below
    "<...> world record progression": ("Q13406463", "38/59", r".+ world record progression$"),
    # round 6, models 2024 Democratic / Republican National Convention (Q104844259, Q104844263): the party's series
    # (PARTY_SERIES), else their parent 'United States presidential nominating convention'
    "<year> ... National Convention": ("Q1413715", "125/238", r"^\d{4}.* National Convention$"),
    "Immediate Geographic Region ": ("Q61707934", "2/3"),  # round 7, Brazil; the user's model Uberaba (Q22065012)
    # round 8: the country's own class (BUDGET_SERIES; the user's model United States federal budget Q7883083), else
    # government budget (user: not budget Q41263, which isn't linked to it)
    "<year> ... federal budget": ("Q271855", "user", r"^\d{4}.* federal budget$"),
    # round 9: P279 like the user's model vehicle registration plates of the Netherlands (Q1269379), see PLATE_PARENT
    "Vehicle registration plates of ": ("Q22706", "user"),
    # round 10: the user's new class honorary sports team: '1955 All-Southern Conference football team consists of
    # American football players chosen by the AP'; all-star (Q1654577) takes part in an all-star game, so no
    "<year> All-... team": ("Q141927695", "user", r"^\d{4}(?:[–-]\d{2,4})? (?:.*\bAll-|Little All-).*\b[Tt]eams?$"),
    "<year> ... – Singles/Doubles": ("Q46190676", "1842/2000",  # tennis event, if the parent is tennis
                                     r"^\d{4}(?:–\d{2,4})? .+ – [\w' ]*?(?:[Ss]ingles|[Dd]oubles)$"),
}
EXTRA = {"<...> world record progression": [("P360", "Q688615")]}  # family -> more statements: is a list of world record
TENNIS_EVENTS = "<year> ... – Singles/Doubles"
CONVENTIONS = "<year> ... National Convention"
PARTY_SERIES = {"Democratic": "Q1185865", "Republican": "Q361909", "Libertarian": "Q6541336"}
NO_NOMINATING = re.compile(r"Bolivian|PDP|Students for a Democratic Society|Colored|Emergency|Mormon")  # no US party's
# presidential ticket: a constituent assembly, a Nigerian party, the Colored Conventions Movement; 1844 Mormon: unsure


BUDGET_SERIES = {"Canadian": "Q5030766", "Australian": "Q4825004", "United States": "Q7883083", "Malaysian": "Q24935390"}
PROPERTY = {"Vehicle registration plates of ": "P279"}  # family -> the property, when not P31
PLATES = "Vehicle registration plates of "
PLATE_PARENT = {  # place -> its country's plates, or the European class as on the country items
    "Q1740451": "Alabama|Alaska|American Samoa|Arizona|Arkansas|Colorado|Connecticut|Delaware|Florida|Georgia (U.S. "
                "state)|Guam|Hawaii|Idaho|Illinois|Indiana|Iowa|Kansas|Kentucky|Louisiana|Maine|Maryland|Massachusetts|"
                "Michigan|Minnesota|Mississippi|Missouri|Montana|Native American tribes in the United States|Nebraska|"
                "Nevada|New Hampshire|New Jersey|New Mexico|New York|North Carolina|North Dakota|Oklahoma|Oregon|"
                "Pennsylvania|Puerto Rico|Rhode Island|South Carolina|South Dakota|Tennessee|Texas|the Northern Mariana "
                "Islands|the territories of the United States|the United States for 1942|the United States for 1960|"
                "the United States Virgin Islands|Utah|Vermont|Virginia|"
                "Washington (state)|Washington, D.C.|West Virginia|Wisconsin|Wyoming",
    "Q39079": "Alberta|British Columbia|Manitoba|New Brunswick|Nova Scotia|Nunavut|Prince Edward Island|Quebec|"
              "Saskatchewan|the Northwest Territories|Yukon",
    "Q1740385": "Christmas Island|New South Wales|Norfolk Island|Queensland|South Australia|the Australian Capital "
                "Territory|the Cocos (Keeling) Islands|the Northern Territory|Western Australia",
    "Q1131620": "Fars|Gilan|Golestan|Hamedan|Hormozgan|Ilam|Isfahan|Kerman|Kermanshah|Khuzestan|Kurdistan|Kohgiluyeh and "
                "Boyer-Ahmad|Lorestan|Mazandaran|North Khorasan|Qazvin|Qom|Sistan and Baluchistan|Zanjan",
    "Q17089282": "Jersey|South Ossetia|the German Democratic Republic|the Isle of Man|the Luhansk People's Republic",
}
PLATE_PARENT = {place: parent for parent, places in PLATE_PARENT.items() for place in places.split("|")}


def class_of(fam, t):
    if fam == PLATES:
        return PLATE_PARENT.get(t[len(PLATES):], FAMILY[fam][0])
    m = re.match(r"\d{4} (\w+) National Convention$", t) if fam == CONVENTIONS else None
    if m:
        return PARTY_SERIES.get(m.group(1), FAMILY[fam][0])
    m = re.match(r"[\d–-]+ (.+) federal budget$", t)
    return BUDGET_SERIES.get(m.group(1), FAMILY[fam][0]) if m else FAMILY[fam][0]


def nominating(t, s):
    """A presidential convention by its opening, or held in an election year or the year before it (Prohibition met
    in 1951 for 1952); not the '1950 Progressive National Convention'."""
    return not NO_NOMINATING.search(t) and (int(t[:4]) % 4 in (0, 3) or "presidential" in s.lower())
IN_SENTENCE = {  # family -> the first sentence must say this, the title doesn't count: 'Peppora is a station' (Q55628929)
    "Parish of ": re.compile(r"\b(?:civil|cadastral) parish\b|\bparish\b.*\b(?:New South Wales|NSW)\b", re.I),
    # not the old Legislative Council (Q14935115), the Tasmanian House of Assembly (Q5355239) or a hatnote (Q5355948)
    "Electoral district of ": re.compile(r"(?=.*electoral district)(?=.*Victoria)(?=.*Legislative Assembly)", re.I),
}


def family_of(t):
    return next((f for f, v in FAMILY.items() if (re.match(v[2], t) if len(v) > 2 else t.startswith(f))), None)


def tennis_parents(titles):
    """Event title -> True when its parent tournament ('2026 Pune Challenger' for '2026 Pune Challenger – Doubles')
    has sport (P641) tennis; the 'All England Open' events are badminton."""
    parent = {t: t.rsplit(" – ", 1)[0] for t in titles}  # '2025 US Open' is a disambiguation: '... (tennis)' too
    tried = sorted({v for p in parent.values() for v in (p, p + " (tennis)")})
    item = {p: i for p, (_, i) in enwiki_items(tried).items()}
    ids, tennis = sorted(set(item.values())), set()
    for i in range(0, len(ids), 300):
        q = f"""PREFIX wd: <http://www.wikidata.org/entity/> PREFIX wdt: <http://www.wikidata.org/prop/direct/>
SELECT ?i WHERE {{ VALUES ?i {{ {" ".join("wd:" + x for x in ids[i:i + 300])} }} ?i wdt:P641 wd:Q847 }}"""
        tennis.update(r["i"] for r in qlever(q))
    return {t: item.get(p) in tennis or item.get(p + " (tennis)") in tennis for t, p in parent.items()}
SKIP = {  # family -> opening that is no member: 'The coat of arms of Kumanovo is actually an emblem' (Q30590156)
    # but 'The Yale University coat of arms is the primary emblem' is one; 'The coat of arms and the flag of Valais'
    "Coat of arms of ": re.compile(r"\b(?:actually|not) an? (?:emblem|seal|logo)\b|\bwas the emblem\b|"
                                   r"\barms and (?:the )?flag\b", re.I),
    "Murder of ": re.compile(r"\b(?:disappearance|suicide|accident(?:al|ally)?|manslaughter)\b", re.I),
    "<year> ... federal budget": re.compile(r"\balternative\b", re.I),  # an opposition's: Pakatan Harapan (Q21190347)
    # other parishes: 'a Church of England parish' (Q7137443), 'The Roman Catholic parish of St. Sylvanus' (Q18210370)
    "Parish of ": re.compile(r"\b(?:church|catholic|anglican|Queensland|Victoria|Tasmania|England|Ireland)\b", re.I),
}
NEED = {  # family -> title or opening must say this: 'Time in Tolkien's fiction' is a literary theme (Q106611193)
    "Time in ": re.compile(r"\bUTC|\bGMT\b|time zone|standard time|daylight saving", re.I),
    # 'Index of industrial production', 'Index of biological integrity', 'Index of a Lie algebra' are measures
    "Index of ": re.compile(r"\barticles?\b|\blist\b|alphabetical|topical guide|overview|\bContents\b", re.I),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wiki", default="en")
    ap.add_argument("--min-age-days", type=int, default=180)
    ap.add_argument("--round", type=int, default=1)
    args = ap.parse_args()
    name = f"qs_{args.wiki}_family{args.round if args.round > 1 else ''}_all.txt"
    with open(os.path.join(OUT, f"items_{args.wiki}.tsv"), encoding="utf-8") as fh:
        title = dict(line.rstrip("\n").split("\t", 1) for line in fh if "\t" in line)
    try:
        with open(os.path.join(OUT, f"done_{args.wiki}.txt"), encoding="utf-8") as fh:
            done = {line.strip() for line in fh if line.strip()}
    except FileNotFoundError:
        done = set()
    for path in glob.glob(os.path.join(OUT, f"qs_{args.wiki}_family*_all.txt")):  # a batch that isn't uploaded yet
        if os.path.basename(path) != name:
            with open(path, encoding="utf-8") as fh:
                done.update(line.split("\t")[0] for line in fh)
    cand = {q: family_of(t) for q, t in title.items() if q not in done and family_of(t)}
    tennis = tennis_parents([title[q] for q, f in cand.items() if f == TENNIS_EVENTS])
    opening = {}
    with open(os.path.join(OUT, f"opening_{args.wiki}.tsv"), encoding="utf-8") as fh:
        for line in fh:
            q, text = line.rstrip("\n").split("\t", 1)
            if q in cand:
                opening[q] = text
    found, skipped = {}, []
    for q, fam in cand.items():
        text = opening.get(q, "")
        s = first_sentence(text)
        if "(disambiguation)" in title[q] or re.search(r"\b(?:may|can|could) (?:also )?refer to\b|set index", text):
            reason = "disambiguation"
        elif not text:
            reason = "no opening"
        elif re.search(r"\bat the end of the Cold War$", title[q]):
            reason = "order of battle"  # 'Outline of the British Army at the end of the Cold War': a structure
        elif fam == TENNIS_EVENTS and not tennis[title[q]]:
            reason = "parent tournament not tennis"  # or no parent article
        elif fam == CONVENTIONS and not nominating(title[q], s):
            reason = "no presidential nominating convention"
        elif fam in IN_SENTENCE and not IN_SENTENCE[fam].search(s):
            reason = "sentence does not fit the family's class"
        elif fam in NEED and not NEED[fam].search(title[q] + " " + text[:400]):
            reason = "opening lacks the family's subject"
        elif fam == "Murder of " and re.match(r"Murder of (?!the )[a-z]", title[q]):
            reason = "victims are a group"  # 'Murder of youths in Ra'anana by British soldiers': a massacre (Q16129382)
        elif fam in SKIP and SKIP[fam].search(s):
            reason = "opening names something else"
        else:
            found[q] = fam
            continue
        skipped.append((q, reason, fam.strip(), title[q], s[:200]))
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=args.min_age_days)).strftime("%Y%m%d%H%M%S")
    first = first_revision(list(found))
    for q in [q for q in found if first.get(q, "9") > cutoff]:
        skipped.append((q, "too new", found[q].strip(), title[q], ""))
        del found[q]
    with open(os.path.join(OUT, name), "w", encoding="utf-8", newline="\n") as fh:
        for q, f in sorted(found.items(), key=lambda x: (x[1], int(x[0][1:]))):
            fh.write(f"{q}\t{PROPERTY.get(f, 'P31')}\t{class_of(f, title[q])}\n")
            fh.writelines(f"{q}\t{p}\t{v}\n" for p, v in EXTRA.get(f, []))
    with open(os.path.join(OUT, "skipped_families.tsv"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write("qid\treason\tfamily\ttitle\tsentence\n")
        fh.writelines("\t".join(r) + "\n" for r in sorted(skipped, key=lambda r: (r[1], r[2])))
    for reason, n in collections.Counter(r[1] for r in skipped).most_common():
        print(f"   {reason:30} {n}")
    for fam, n in collections.Counter(found.values()).most_common():
        print(f"   {n:5} {fam:24} {FAMILY[fam][0]}")
    print(f"{len(found)} statements -> {name}")


if __name__ == "__main__":
    main()
