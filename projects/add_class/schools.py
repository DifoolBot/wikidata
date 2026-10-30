"""Schools and colleges from the article openings, the class from the compound ('public high school' -> high school).

  python schools.py [--wiki en] [--min-age-days 180]
  in:  output/items_<wiki>.tsv, output/opening_<wiki>.tsv, output/done_<wiki>.txt (skipped)
  out: output/qs_<wiki>_school_all.txt (QS v1, P31 only) + skipped_schools.tsv (qid, reason, compound, title, sentence)

'X is a public co-educational high school located in ...' -> the longest tail of the words before the school word
that is the en label (or alias) of a subclass of educational institution (Q2385804), with the fixed choices in
OVERRIDE; otherwise plain school / college. The school word must end the phrase ('school district', 'school
athletic conference', 'school of thought', 'college football rivalry' are no schools) and be the sentence's first
verb (not 'X is situated in Y, which is a school'); heritage-listed schools are register entries for buildings.
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
from villages import names_title  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "output")
HEAD = r"school|college|academy|gymnasium|lyceum|madrasa|madrasah|seminary|kindergarten"
OPENING = re.compile(r"\bis an? ((?:[\w'&-]+,? ){0,6}?)(" + HEAD + r")\b(?=,|\.|;| \(| (?:located |situated |based |"
                     r"founded )?(?:in|at|on|near|for)\b| (?:located|situated|based|serving|founded|established)\b)",
                     re.I)
FUNC = {"for", "and", "of", "by", "the", "a", "an", "or", "in", "to", "with", "which"}
OVERRIDE = {  # compound -> class, where the label lookup picks the wrong sense or a thin duplicate
    "public school": "Q3914",  # UK: an independent school; US: a state school
    "state school": "Q3914",
    "academy": "Q3914",  # Q162633 is the learned academy; an English 'academy' is a school
    "senior high school": "Q9826", "senior secondary school": "Q159334", "higher secondary school": "Q159334",
    "elementary school": "Q9842", "private college": "Q189004", "madrasah": "Q132834",
    "residential school": "Q3914",  # not 'Canadian Indian residential school' (Columbus Developmental Center)
    "islamic seminary": "Q132834",  # not 'hawza', the Shia seminary (Mazahir Uloom Jadeed is Deobandi)
    "martial art school": "Q135495953", "martial arts school": "Q135495953",  # not 'art school' (Rhee Taekwon-Do)
}
MIN_SITELINKS = 5  # thinner classes are often one country's type: 'government school' (Hong Kong), 'junior high
#                    school' (Taiwan), 'free school' (England); the shorter tail is used instead
NOT_IN_PHRASE = re.compile(r"^(?:for|of|by|in|at|on|to|with|which|that|who|from|named|called|known|\w+ed)$", re.I)
FORMER = re.compile(r"\bheritage-listed\b|\bheritage register\b", re.I)


def class_names():
    """Lowercased en label/alias -> class (a label beats an alias, then the most sitelinks)."""
    q = """PREFIX wd: <http://www.wikidata.org/entity/> PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#> PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX wikibase: <http://wikiba.se/ontology#>
SELECT ?c ?name ?n ?kind WHERE { ?c wdt:P279* wd:Q2385804 ; wikibase:sitelinks ?n .
  { ?c rdfs:label ?name BIND("l" AS ?kind) } UNION { ?c skos:altLabel ?name BIND("a" AS ?kind) }
  FILTER(LANG(?name) = "en") }"""
    names = collections.defaultdict(set)
    for r in qlever(q):
        names[r["name"].lower()].add((r["kind"] == "l", int(r["n"]), r["c"]))
    best = {k: max(x for x in v if x[1] >= MIN_SITELINKS)[2] for k, v in names.items()
            if any(x[1] >= MIN_SITELINKS for x in v)}
    best.update(OVERRIDE)
    return best


def compound_class(words, head, names):
    """The longest tail of 'public co-educational high' + head that names a class: 'high school' -> Q9826."""
    w = [x.strip(",").lower() for x in words] + [head.lower()]
    while len(w) > 1 and w[0] in FUNC:
        w = w[1:]
    for k in range(min(4, len(w)), 0, -1):
        if " ".join(w[-k:]) in names:
            return " ".join(w[-k:]), names[" ".join(w[-k:])]
    return head.lower(), names.get(head.lower())


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
    names = class_names()
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
                continue
            comp, cls = compound_class(m.group(1).split(), m.group(2), names)
            after = re.sub(r"^\s*\([^)]*\)", "", s[m.end():])
            if any(NOT_IN_PHRASE.match(w.strip(",")) for w in m.group(1).split()):
                continue  # 'The Granby roll is a wrestling reversal named for Granby High School'
            if (re.search(r",[^,]*\b(?:and|or)\s*$", m.group(1))
                    or re.search(r"\b(?:" + HEAD + r"),? (?:and|or)\b", m.group(1), re.I)
                    or re.match(r"(?:,(?: [\w'-]+){0,3},?)? (?:and|or) ", s[m.end():])):
                continue  # a mix: 'an area, hill and school' (Q10984336); 'a pre-school, kindergarten, and
                #           international school' (Q48775212); 'a military academy and flight school' (Q136346001)
            if re.match(r"\s*of\b", after):
                reason = "'school of' (a tradition?)"  # 'a traditional school (koryu) of Japanese martial arts'
            elif "(disambiguation)" in title[q] or re.search(r"\b(?:may|can) (?:also )?refer to\b", text):
                reason = "disambiguation"
            elif FORMER.search(s[:m.end()]):
                reason = "heritage-listed (a building)"
            elif not cls:
                reason = "no class"
            else:
                found[q] = (cls, comp)
                continue
            skipped.append((q, reason, comp, title[q], s[:200]))
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=args.min_age_days)).strftime("%Y%m%d%H%M%S")
    first = first_revision(list(found))
    for q in [q for q in found if first.get(q, "9") > cutoff]:
        skipped.append((q, "too new", found[q][1], title[q], ""))
        del found[q]
    with open(os.path.join(OUT, f"qs_{args.wiki}_school_all.txt"), "w", encoding="utf-8", newline="\n") as fh:
        fh.writelines(f"{q}\tP31\t{c}\n" for q, (c, _) in sorted(found.items(), key=lambda x: (x[1][0], int(x[0][1:]))))
    with open(os.path.join(OUT, "skipped_schools.tsv"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write("qid\treason\tcompound\ttitle\tsentence\n")
        fh.writelines("\t".join(r) + "\n" for r in sorted(skipped, key=lambda r: r[1]))
    for reason, n in collections.Counter(r[1] for r in skipped).most_common():
        print(f"   {reason:30} {n}")
    for (comp, c), n in collections.Counter((comp, c) for c, comp in found.values()).most_common(40):
        print(f"   {n:5} {comp:28} {c}")
    print(f"{len(found)} statements -> qs_{args.wiki}_school_all.txt")


if __name__ == "__main__":
    main()
