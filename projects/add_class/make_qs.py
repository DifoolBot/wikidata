"""Decided stub classes -> QuickStatements files, one per class (READ-ONLY: writes files, no edits).

  python projects/add_class/make_qs.py [--wiki en] [--min-age-days 180] [--ref]
  -> output/qs_<wiki>/<prop>_<class>.txt (QS v1: Qitem<TAB>P31<TAB>Qclass) + output/qs_<wiki>/skipped.tsv

An item gets the class of its decided stub categories (review_<wiki>.tsv, decision column) when they all agree;
different decisions -> skipped (conflict). Items whose Wikidata page is younger than --min-age-days (first revision,
wikidatawiki replica) are skipped: template-importing bots get the first go. Right before writing, QLever re-checks
that the item still has no P31/P279 and still exists (not merged into a redirect). --ref adds
'imported from Wikimedia project' (S143) = the wiki.
"""
import argparse
import collections
import csv
import datetime as dt
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from replica_cats import BATCH, run  # noqa: E402
from review import typed  # noqa: E402
from stub_table import QBATCH, is_stub, qlever  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "output")
WIKI_ITEM = {"en": "Q328"}  # English Wikipedia
# catch-all classes of the place stubs ('Nigerian_building_and_structure_stubs', 'Scottish_organisation_stubs'):
# a more specific decided stub on the same item wins
GENERIC = {"Q811979", "Q41176", "Q43229", "Q4830453", "Q783794", "Q6881511"}
# an article in 'Types_of_saints' / 'Lists_of_books' is about a kind of thing or is a list, not an instance
# ('Saint Companions' is no human, user 2026-10-28) -> skipped, unless the class is itself a class of types
TYPE_OR_LIST = re.compile(r"(^|_)(Types|Kinds|Forms|Classes|Varieties|Styles|Genres|Lists|Glossaries)_of_")
METACLASS = {"Q2235308"}  # ship type ('Types_of_fishing_vessels')
# enwiki short description (output/shortdesc_<wiki>.tsv, from the replica): 'Type of mace' on a P31 row = a kind
# -> types list; 'Astrophysical process' / 'Database theory' = a concept -> skipped, unless the word is in the
# class label ('2D-art technique' for artistic technique)
KIND_DESC = re.compile(r"\b(type|types|kind|kinds|form|forms|class|classes|category|variety|varieties) of\b", re.I)
CONCEPT_DESC = re.compile(r"\b(process|phenomenon|phenomena|concept|theory|theorem|method|technique|principle|term|"
                          r"terminology|practice|study of|field of|branch of|hypothesis|mechanism|effect|problem|"
                          r"list of|lists of)\b", re.I)
# head noun of the short description naming another kind of thing ('Organisation looking for sunken submarines' on
# a submarine row, user 2026-10-28; 'Brand of Russian vodka' on liquor; 'Book series' on written work) -> skipped
STRONG_HEAD = {"organization", "association", "society", "foundation", "charity", "agency", "institute", "union",
               "federation", "council", "committee", "trust", "club", "party", "movement", "group", "network",
               "company", "business", "firm", "corporation", "bank", "publisher", "press", "studio", "school",
               "university", "college", "academy", "magazine", "newspaper", "journal", "series", "class", "league",
               "team", "account", "brand", "person", "people", "family", "dynasty", "project", "programme", "program",
               "film", "album", "song", "band", "software", "website", "event", "festival", "award", "prize",
               "competition", "tournament", "championship"}
ORG_HEAD = {"organization", "association", "society", "foundation", "charity", "agency", "institute", "union",
            "federation", "council", "committee", "trust", "club", "party", "movement", "group", "network", "company",
            "business", "firm", "corporation", "bank", "publisher", "press", "studio", "school", "university",
            "college", "academy"}
ORG_CLASS = re.compile(r"organi[sz]ation|association|society|company|business|enterprise|institution|agency|union|"
                       r"party|bank|publishing|manufacturer|studio|school|university|college|seminary|club|team|"
                       r"press|denomination|station|developer|line", re.I)
SYNONYM_HEADS = [  # class label word -> description heads that mean the same kind of thing
    (re.compile(r"competition|tournament|race|championship|cup|meeting|sporting event|bowl", re.I),
     {"tournament", "competition", "league", "championship", "event"}),
    (re.compile(r"festival|event|process|disaster|battle|massacre|flood|wildfire|epidemic", re.I), {"event"}),
    (re.compile(r"\btype\b|\bclass\b", re.I), {"class"}),
    (re.compile(r"award|prize|decoration", re.I), {"award", "prize"}),
]


def norm_word(w):
    w = w.lower().replace("organisation", "organization").replace("programme", "program")
    if w == "series":
        return w
    if w.endswith("ies"):
        return w[:-3] + "y"
    return w[:-1] if w.endswith("s") and not w.endswith("ss") else w


def desc_mismatch(desc, label):
    """The description's head noun when it names another kind of thing than the class label, else ''."""
    first = re.split(r"\b(?:in|of|for|from|based|by|at|on|with|to|that|which|and)\b", desc)[0]
    strong = [w for w in (norm_word(w) for w in first.split() if w.isalpha()) if w in STRONG_HEAD]
    if not strong:
        return ""
    head = strong[-1]  # 'Organisation looking for ...' -> organization
    if head in {norm_word(w) for w in re.findall(r"[A-Za-z]+", label)}:
        return ""
    if head in ORG_HEAD and ORG_CLASS.search(label):
        return ""
    if any(rx.search(label) and head in heads for rx, heads in SYNONYM_HEADS):
        return ""
    return head


def first_revision(qids):
    """QID -> first revision timestamp (YYYYMMDDhhmmss) from the wikidatawiki replica."""
    sql = ""
    for i in range(0, len(qids), BATCH):
        part = ",".join(f"'{q}'" for q in qids[i:i + BATCH])
        sql += (f"SELECT page_title, MIN(rev_timestamp) FROM page JOIN revision ON rev_page = page_id "
                f"WHERE page_namespace = 0 AND page_title IN ({part}) GROUP BY page_title;\n")
    return dict(run("wikidata", sql)) if sql else {}


def still_unclassified(qids):
    """The QIDs that, per QLever, still have no P31/P279 and are not redirects."""
    keep = set()
    for i in range(0, len(qids), QBATCH):
        vals = " ".join("wd:" + q for q in qids[i:i + QBATCH])
        q = f"""PREFIX wd: <http://www.wikidata.org/entity/> PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX wikibase: <http://wikiba.se/ontology#>
SELECT ?item WHERE {{ VALUES ?item {{ {vals} }} ?item wikibase:sitelinks [] .
  MINUS {{ ?item wdt:P31 [] }} MINUS {{ ?item wdt:P279 [] }} }}"""
        keep.update(r["item"] for r in qlever(q))
        print(f"   re-check {min(i + QBATCH, len(qids))}/{len(qids)}", flush=True)
    return keep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wiki", default="en")
    ap.add_argument("--min-age-days", type=int, default=180)
    ap.add_argument("--ref", action="store_true")
    ap.add_argument("--recheck", action="store_true",
                    help="ask QLever which items got a P31/P279 meanwhile (hardly any: 2 of ~6,500; a double one is harmless)")
    args = ap.parse_args()
    with open(os.path.join(OUT, f"review_{args.wiki}.tsv"), encoding="utf-8") as fh:
        review = [r for r in csv.DictReader(fh, delimiter="\t") if r["decision"]]
    decision = {r["stub"]: tuple(r["decision"].split()) for r in review}
    class_label = {r["class"]: r["label"] for r in review}
    class_label.update({  # classes that only come in through prefill.py overrides
        "Q47461344": "written work", "Q7725634": "literary work", "Q33506": "museum", "Q27686": "hotel",
        "Q40357": "prison", "Q11315": "shopping center", "Q16560": "palace", "Q682943": "cricket field",
        "Q1076486": "sports venue", "Q3914": "school", "Q14660": "flag", "Q4830453": "business",
        "Q3918": "university", "Q40231": "public election", "Q5393308": "Buddhist temple"})
    shortdesc = {}
    sd_path = os.path.join(OUT, f"shortdesc_{args.wiki}.tsv")
    if os.path.exists(sd_path):
        with open(sd_path, encoding="utf-8") as fh:
            shortdesc = dict(line.rstrip("\n").split("\t", 1) for line in fh)
    else:
        print(f"   WARNING: no {sd_path}, short-description checks skipped")
    cats = collections.defaultdict(list)
    with open(os.path.join(OUT, f"cats_{args.wiki}.tsv"), encoding="utf-8") as fh:
        for q, c in (line.rstrip("\n").split("\t") for line in fh):
            cats[q].append(c)
    votes = collections.defaultdict(dict)  # qid -> {(prop, class): [stubs]}
    skipped = []
    for q, cs in cats.items():
        for c in cs:
            if c not in decision:
                continue
            # a stub alone is too weak (Food_stubs also holds 'Taste detection threshold'): the article must also
            # sit in a non-stub category naming the type in the plural ('Desserts', 'Organisations_based_in_X')
            if any(not is_stub(x) and typed(c, x) for x in cs):
                votes[q].setdefault(decision[c], []).append(c)
            elif not any(s in decision and any(not is_stub(x) and typed(s, x) for x in cs) for s in cs):
                skipped.append((q, "stub only", c))
    print(f"{len({s[0] for s in skipped})} items with a decided stub but no matching plural category")
    chosen = {}
    for q, v in votes.items():
        if len(v) > 1 and any(c not in GENERIC for _, c in v):  # 'built structure' + 'church building' -> church
            v = {k: s for k, s in v.items() if k[1] not in GENERIC}
        kind = next((x for x in cats[q] if TYPE_OR_LIST.search(x)), None)
        if len(v) > 1:
            skipped.append((q, "conflict", "; ".join(f"{p} {c} <- {','.join(s)}" for (p, c), s in v.items())))
        elif kind and next(iter(v))[1] not in METACLASS:
            skipped.append((q, "type/list article", kind))
        else:
            prop, cls = next(iter(v))
            desc = shortdesc.get(q, "")
            concept = CONCEPT_DESC.search(desc)
            if prop == "P31" and KIND_DESC.search(desc) and cls not in METACLASS:
                skipped.append((q, "type article", f"P279 {cls} | {desc}"))
            elif concept and concept.group(1).lower() not in class_label.get(cls, "").lower():
                skipped.append((q, "concept article", desc))
            elif desc and desc_mismatch(desc, class_label.get(cls, "")):
                skipped.append((q, "description names another kind", f"{class_label.get(cls, cls)} | {desc}"))
            else:
                chosen[q] = (prop, cls)
    print(f"{len(votes)} items in a decided stub: {len(chosen)} agree, {sum(s[1] == 'conflict' for s in skipped)} conflict")

    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=args.min_age_days)).strftime("%Y%m%d%H%M%S")
    born = first_revision(sorted(chosen))
    for q in sorted(chosen):
        if q not in born:
            skipped.append((q, "missing", "no page on the replica (deleted?)"))
            del chosen[q]
        elif born[q] > cutoff:
            skipped.append((q, "too new", born[q]))
            del chosen[q]
    keep = still_unclassified(sorted(chosen)) if args.recheck else set(chosen)
    for q in sorted(chosen):
        if q not in keep:
            skipped.append((q, "classified meanwhile", ""))
            del chosen[q]

    qs_dir = os.path.join(OUT, f"qs_{args.wiki}")
    os.makedirs(qs_dir, exist_ok=True)
    for f in os.listdir(qs_dir):  # a class that lost all its items must not keep last run's file
        if f.endswith(".txt"):
            os.remove(os.path.join(qs_dir, f))
    per = collections.defaultdict(list)
    for q, (prop, cls) in chosen.items():
        per[(prop, cls)].append(q)
    ref = f"\tS143\t{WIKI_ITEM[args.wiki]}" if args.ref else ""
    for (prop, cls), qs in per.items():
        with open(os.path.join(qs_dir, f"{prop}_{cls}.txt"), "w", encoding="utf-8", newline="\n") as fh:
            fh.writelines(f"{q}\t{prop}\t{cls}{ref}\n" for q in sorted(qs, key=lambda x: int(x[1:])))
    with open(os.path.join(qs_dir, "skipped.tsv"), "w", encoding="utf-8", newline="\n") as fh:
        fh.writelines("\t".join(r) + "\n" for r in skipped)
    reasons = collections.Counter(r[1] for r in skipped)
    print(f"{len(chosen)} statements in {len(per)} files -> {qs_dir}; skipped: {dict(reasons)}")


if __name__ == "__main__":
    main()
