"""Villages, towns, hamlets, neighbourhoods and suburbs from the article openings, with a country-specific class.

  python villages.py [--wiki en] [--min-age-days 180]
  in:  output/items_<wiki>.tsv, output/opening_<wiki>.tsv, output/done_<wiki>.txt (skipped)
  out: output/qs_<wiki>_village_all.txt (QS v1, P31 only) + skipped_villages.tsv (qid, reason, title, sentence)

'X is a (small, fishing ...) village in A, B, Country' -> kind 'village', country = the last country name in the
place text (before any 'that/which/who' clause), else the last capitalised first-level unit (Uttar Pradesh ->
India). Class = the P31 most used among items with that P17 that are P279* the kind (share >= 60%); a specific class
only when its label names the country ('village in India', 'town of China'), else the generic one (village Q532).
Skipped: ghost/former/ancient places, Hong Kong/Macau/Taiwan, border mentions, settlement/locality (too vague).
Errors the user caught (2026-10-30): 'by the river' = Belarus (ISO code alias), 'North Goa' = Cameroon's North
Region, 'near the CAR-Cameroon border', 'in Labuan, Malaysia, that is inhabited by Brunei Malays'.
"""
import argparse
import collections
import datetime as dt
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from make_qs import first_revision  # noqa: E402
from stub_table import qlever  # noqa: E402
from verify_stub import first_sentence  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "output")
PREFIX = """PREFIX wd: <http://www.wikidata.org/entity/> PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#> PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
"""
BASE = {"village": "Q532", "town": "Q3957", "hamlet": "Q5084", "neighbourhood": "Q123705", "suburb": "Q188509"}
MIN_SHARE = 0.6
EXTRA = {"china": "Q148", "england": "Q145", "scotland": "Q145", "wales": "Q145", "northern ireland": "Q145"}
COMPASS = re.compile(r"^(?:(?:North|South|East|West|Central|Centre|Center|Upper|Lower|Middle|Inner|Outer|Coast|"
                     r"Littoral|Far)[ -]?)+(?:Region|Province|District)?$")  # 'North Goa' is no Cameroonian region
ADJ = (r"(?:(?:small|large|tiny|rural|coastal|mountain|fishing|farming|model|planned|new|old|hill|remote|border|"
       r"island|riverside|agricultural|census)[ -])*")
OPENING = re.compile(r"\bis an? " + ADJ + r"(?:(?-i:[A-Z][\w'-]+) )?(village|town|hamlet|neighbourhood|neighborhood|"
                     r"suburb)\b(?: (?:located|situated))? (?:in|of|on|near|within) (.+)", re.I)
FORMER = re.compile(r"\b(?:former|abandoned|deserted|depopulated|ruined|extinct|lost|ghost|historic(?:al)?|ancient)\b",
                    re.I)
CLAUSE = re.compile(r"(?<![A-Z])\.(?:\s|$)|;|\[|,? (?:that|which|who|whose|where|and is|it is|with a|known for)\b")


def name_tables():
    """(country names, first-level unit names) -> country QID. Short aliases ('by', 'to', 'in': ISO codes) only in
    capitals ('USA', 'DRC'); unit names only capitalised and unique to one country."""
    country = dict(EXTRA)
    q = PREFIX + """SELECT ?c ?name WHERE { VALUES ?t { wd:Q6256 wd:Q3624078 } ?c wdt:P31 ?t .
  { ?c rdfs:label ?name } UNION { ?c skos:altLabel ?name } FILTER(LANG(?name) = "en") }"""
    for r in qlever(q):
        n = r["name"]
        key = n if len(n) < 4 else n.casefold()
        if len(n) >= 4 or n.isupper():
            country.setdefault(key, r["c"])
    q = PREFIX + """SELECT ?a ?name ?c WHERE { VALUES ?t { wd:Q6256 wd:Q3624078 } ?c wdt:P31 ?t ; wdt:P150 ?a .
  ?a rdfs:label ?name FILTER(LANG(?name) = "en") }"""
    units = collections.defaultdict(set)
    for r in qlever(q):
        n = r["name"]
        if n.casefold() not in country and len(n) >= 3 and n[0].isupper() and not COMPASS.match(n):  # 'Goa'
            units[n].add(r["c"])
    return country, {n: next(iter(c)) for n, c in units.items() if len(c) == 1}


def find_country(place, country, units):
    long_ = re.compile(r"\b(?:" + "|".join(re.escape(n) for n in sorted((k for k in country if len(k) >= 4),
                                                                          key=len, reverse=True)) + r")\b", re.I)
    short = re.compile(r"\b(?:" + "|".join(re.escape(n) for n in country if len(n) < 4) + r")\b")
    hits = sorted([(m.start(), country[m.group(0).casefold()]) for m in long_.finditer(place)]
                  + [(m.start(), country[m.group(0)]) for m in short.finditer(place)])
    if hits:
        return hits[-1][1]
    unit = re.compile(r"\b(?:" + "|".join(re.escape(n) for n in sorted(units, key=len, reverse=True)) + r")\b")
    found = [m.group(0) for m in unit.finditer(place)]
    return units[found[-1]] if found else None


def class_per_country():
    """(kind, country) -> class: the most used P31 among the kind's items in that country, if >= MIN_SHARE."""
    best, label = {}, {}
    for kind, base in BASE.items():
        q = PREFIX + f"""SELECT ?c ?k (COUNT(?x) AS ?n) WHERE {{ ?k wdt:P279* wd:{base} . ?x wdt:P31 ?k ; wdt:P17 ?c . }}
GROUP BY ?c ?k HAVING (COUNT(?x) >= 20)"""
        per = collections.defaultdict(list)
        for r in qlever(q):
            per[r["c"]].append((int(r["n"]), r["k"]))
        for c, uses in per.items():
            n, k = max(uses)
            if n / sum(x for x, _ in uses) >= MIN_SHARE:
                best[kind, c] = k
    ids = sorted({k for k in best.values()} | {c for _, c in best})
    for i in range(0, len(ids), 300):
        q = PREFIX + f"""SELECT ?i ?l WHERE {{ VALUES ?i {{ {" ".join("wd:" + x for x in ids[i:i + 300])} }}
  ?i rdfs:label ?l FILTER(LANG(?l) = "en") }}"""
        label.update((r["i"], r["l"]) for r in qlever(q))
    # 'church town of Sweden' for Norway, 'Zaścianek' for Belarus, 'ward of Nepal' for a village -> generic
    for (kind, c), k in best.items():
        lab = label.get(k, "").casefold()
        if k != BASE[kind] and (label.get(c, "~").split()[-1].casefold() not in lab
                                or kind.replace("neighbourhood", "neighbo") not in lab):
            best[kind, c] = BASE[kind]
    return best


TOPIC = re.compile(r"^(?:history|culture|cultural|violence|riots?|massacre|incident|attack|bombing|earthquake|floods?|"
                   r"election|range|forest|reserve|temple|school|college|park|station|airport|dam|fort|mosque|church|"
                   r"railway|geography|economy|demographics|people|tourism|\d{4})$")


def names_title(title, subject):
    """The subject shares a word with the title, and no title word missing from the subject names a topic: not
    'Vatoli communal violence 2008' or 'History and culture of Kaviyoor' for 'Vatoli/Kaviyoor is a village'
    (Q16930481, Q28182913). Spelling variants pass ('Nakkah Afghan' ~ 'Nakka Afghan')."""
    words = lambda t: set(re.findall(r"\w+", t.casefold()))  # noqa: E731
    base = words(re.sub(r"\s*\([^)]*\)", "", title).split(",")[0])
    return bool(base & words(subject)) and not any(TOPIC.match(w) for w in base - words(subject))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wiki", default="en")
    ap.add_argument("--min-age-days", type=int, default=180)
    args = ap.parse_args()
    with open(os.path.join(OUT, f"items_{args.wiki}.tsv"), encoding="utf-8") as fh:
        title = dict(line.rstrip("\n").split("\t", 1) for line in fh if "\t" in line)
    try:
        with open(os.path.join(OUT, f"done_{args.wiki}.txt"), encoding="utf-8") as fh:
            done = {line.strip() for line in fh if line.strip()}
    except FileNotFoundError:
        done = set()
    country, units = name_tables()
    best = class_per_country()
    print(f"{len(country)} country names, {len(units)} units, {len(best)} kind/country classes")
    found, skipped = {}, []
    with open(os.path.join(OUT, f"opening_{args.wiki}.tsv"), encoding="utf-8") as fh:
        for line in fh:
            q, text = line.rstrip("\n").split("\t", 1)
            if q in done or q not in title:
                continue
            s = first_sentence(text)
            m = OPENING.search(s[:300])
            before = s[:m.start()] if m else ""
            if (not m or not names_title(title[q], before) or before.count("(") != before.count(")")
                    or re.search(r"\b(?:is|was|are|were|which|that|where)\b", re.sub(r"\([^)]*\)", "", before))):
                continue  # 'X School is situated in Nagyszelmenc, which is a small village' (Q5286999)
            kind = m.group(1).lower().replace("neighborhood", "neighbourhood")
            place = CLAUSE.split(m.group(2), 1)[0]
            if "(disambiguation)" in title[q] or re.search(r"\b(?:may|can) (?:also )?refer to\b|disambiguation page",
                                                           text):
                reason = "disambiguation"  # 'Tambun is a town in Perak ... Tambun may also refer to' (Q130387624)
            elif FORMER.search(s[:m.end()]) or re.search(r"\bantiquity\b|mentioned by", place, re.I):
                reason = "former/ancient"
            elif re.search(r"Hong Kong|Macau|Macao|Taiwan", place):
                reason = "Hong Kong/Macau/Taiwan"
            elif re.search(r"\bborders?\b", place, re.I):
                reason = "border"
            else:
                c = find_country(place, country, units)
                reason = "no country" if not c else "no class for kind/country" if (kind, c) not in best else ""
                if not reason:
                    found[q] = best[kind, c]
                    continue
            skipped.append((q, reason, title[q], s[:200]))
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=args.min_age_days)).strftime("%Y%m%d%H%M%S")
    first = first_revision(list(found))
    for q in [q for q in found if first.get(q, "9") > cutoff]:
        skipped.append((q, "too new", title[q], ""))
        del found[q]
    with open(os.path.join(OUT, f"qs_{args.wiki}_village_all.txt"), "w", encoding="utf-8", newline="\n") as fh:
        fh.writelines(f"{q}\tP31\t{c}\n" for q, c in sorted(found.items(), key=lambda x: (x[1], int(x[0][1:]))))
    with open(os.path.join(OUT, "skipped_villages.tsv"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write("qid\treason\ttitle\tsentence\n")
        fh.writelines("\t".join(r) + "\n" for r in sorted(skipped, key=lambda r: r[1]))
    for reason, n in collections.Counter(r[1] for r in skipped).most_common():
        print(f"   {reason:26} {n}")
    for c, n in collections.Counter(found.values()).most_common():
        print(f"   {c:12} {n}")
    print(f"{len(found)} statements -> qs_{args.wiki}_village_all.txt")


if __name__ == "__main__":
    main()
