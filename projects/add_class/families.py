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
"""
import argparse
import collections
import datetime as dt
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
    "<year> ... – Singles/Doubles": ("Q46190676", "1842/2000",  # tennis event, if the parent is tennis
                                     r"^\d{4}(?:–\d{2,4})? .+ – [\w' ]*?(?:[Ss]ingles|[Dd]oubles)$"),
}
TENNIS_EVENTS = "<year> ... – Singles/Doubles"


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
        if "(disambiguation)" in title[q] or re.search(r"\b(?:may|can) (?:also )?refer to\b", text):
            reason = "disambiguation"
        elif not text:
            reason = "no opening"
        elif re.search(r"\bat the end of the Cold War$", title[q]):
            reason = "order of battle"  # 'Outline of the British Army at the end of the Cold War': a structure
        elif fam == TENNIS_EVENTS and not tennis[title[q]]:
            reason = "parent tournament not tennis"  # or no parent article
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
        fh.writelines(f"{q}\tP31\t{FAMILY[f][0]}\n" for q, f in sorted(found.items(), key=lambda x: (x[1], int(x[0][1:]))))
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
