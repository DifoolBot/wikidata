"""Low-hanging fruit from the article openings: lists, surnames, given names, disambiguation pages.

  python easy_patterns.py [--wiki en] [--min-age-days 180] [--ref] [--round N]
  in:  output/items_<wiki>.tsv, output/opening_<wiki>.tsv (first_sentence.py on Toolforge),
       output/done_<wiki>.txt (QIDs already in an uploaded batch: skipped)
  out: output/qs_<wiki>_easy[N]/<kind>.txt (QS v1; round N gets its own folder, so a run batch is never overwritten) + samples.tsv (qid, kind, title, opening) for a spot check
       + sitelinks_review.tsv: items with sitelinks on other wikis too (no QS; the item may be a mix)

Only the first sentence counts, and (lists aside) it must start with the title itself, without a '(name)' qualifier
("Szoboszlai is a surname."); an opening about something else ('The Clash on film' -> the band) is never used.
A sentence naming both a surname and a given name is skipped (Wikidata keeps those as separate items).
'may refer to' is only taken when the replica marks the page as a disambiguation page (set-index articles
look the same but are not).
"""
import argparse
import datetime as dt
import os
import random
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from make_qs import first_revision, still_unclassified  # noqa: E402
from verify_stub import first_sentence  # noqa: E402  (not at ':' -- 'Dyakonova (masculine: Dyakonov) is a ...')
from replica_cats import BATCH, lit, run  # noqa: E402
from stub_table import QBATCH, qlever  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "output")
WIKI_ITEM = {"en": "Q328"}

KINDS = {  # kind -> (property, class, label)
    "list": ("P31", "Q13406463", "Wikimedia list article"),
    "disambiguation": ("P31", "Q4167410", "Wikimedia disambiguation page"),
    "surname": ("P31", "Q101352", "family name"),
    "male_given_name": ("P31", "Q12308941", "male given name"),
    "female_given_name": ("P31", "Q11879590", "female given name"),
    "unisex_given_name": ("P31", "Q3409032", "unisex given name"),
    "given_name": ("P31", "Q202444", "given name"),
}
LIST_START = re.compile(r"^(This is an? (?:\w+ )?list of|The following is an? (?:\w+ )?list of|This list of|"
                        r"This article lists)\b")
ADJ = r"(?:(?:[\w'-]+|and|or),? ){0,4}?"  # 'a Hungarian', 'an English and Scottish', 'a common Dutch-language'
SUBJECT = r"^[^.]{0,80}?\b(?:is|was) (?:an?|the) "
PART = r"(?! (?:lexeme|element|component|suffix|prefix|ending|root|particle)s?\b)"  # '-drag is a given name lexeme'
SURNAME = re.compile(SUBJECT + ADJ + r"(?:surname|family name)\b" + PART)
GIVEN = re.compile(SUBJECT + ADJ + r"given name\b" + PART)


def outside_brackets(s, m):
    """The 'is a' of the match is not inside brackets: 'Carlislehoekspruit Pass (English: Carlisle is a surname, ...)
    is a mountain pass'."""
    before = s[:re.search(r"\b(?:is|was) (?:an?|the) ", s).start()] if m else ""
    return m and before.count("(") == before.count(")")
NAME_WORD = re.compile(r"\b(surname|family name|given name|first name|forename)\b")


def classify(title, text):
    s = first_sentence(text)
    if title.startswith(("List of ", "Lists of ")) or LIST_START.match(s):
        return "list"
    if re.match(r"^[^.]{0,100}? (?:may|can) (?:also )?refer to\b", s):
        return "disambiguation"
    base = re.sub(r"\s*\([^)]*\)$", "", title).casefold()
    if not s.casefold().startswith(base):  # the opening is about something else ('The Clash on film': the band)
        return None
    names = set(NAME_WORD.findall(s))
    if outside_brackets(s, SURNAME.match(s)) and not names & {"given name", "first name", "forename"}:
        return "surname"
    if outside_brackets(s, GIVEN.match(s)) and not names & {"surname", "family name"}:
        m = GIVEN.match(s)
        head = s[re.search(r"\b(?:is|was) (?:an?|the) ", s).start():m.end()]  # not '(Nhlanhla unisex) is a feminine'
        if re.search(r"\bunisex\b|\bgender-neutral\b", head):
            return "unisex_given_name"
        male, female = re.search(r"\b(masculine|male)\b", head), re.search(r"\b(feminine|female)\b", head)
        if male and not female:
            return "male_given_name"
        if female and not male:
            return "female_given_name"
        return "given_name"
    return None


def disambig_titles(wiki, titles):
    """The titles the replica marks as disambiguation pages."""
    sql = ""
    for i in range(0, len(titles), BATCH):
        part = ",".join(lit(t) for t in titles[i:i + BATCH])
        sql += (f"SELECT page_title FROM page JOIN page_props ON pp_page = page_id AND pp_propname = 'disambiguation' "
                f"WHERE page_namespace = 0 AND page_title IN ({part});\n")
    return {r[0].replace("_", " ") for r in run(wiki, sql)} if sql else set()


def other_sitelinks(qids, wiki):
    """QID -> the item's sitelinks other than <wiki>wiki, as 'xxwiki:Title' (QLever)."""
    own = f"{wiki}.wikipedia.org"
    links = {}
    for i in range(0, len(qids), QBATCH):
        vals = " ".join("wd:" + q for q in qids[i:i + QBATCH])
        # qlever() keeps only what follows the last '/', so no URLs: the host and the title come separately
        q = f"""PREFIX wd: <http://www.wikidata.org/entity/> PREFIX schema: <http://schema.org/>
SELECT ?item (STRBEFORE(STRAFTER(STR(?site), "://"), "/") AS ?host) ?name WHERE {{ VALUES ?item {{ {vals} }}
  ?page schema:about ?item ; schema:isPartOf ?site ; schema:name ?name . }}"""
        for r in qlever(q):
            if r["host"] != own:
                links.setdefault(r["item"], []).append(f"{r['host'].removesuffix('.org')}:{r['name']}")
    return links


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wiki", default="en")
    ap.add_argument("--min-age-days", type=int, default=180)
    ap.add_argument("--ref", action="store_true")
    ap.add_argument("--round", type=int, default=1, help="output folder qs_<wiki>_easy<N> (round 1: qs_<wiki>_easy)")
    ap.add_argument("--recheck", action="store_true",
                    help="ask QLever which items got a P31/P279 meanwhile (hardly any: 2 of ~6,500; a double one is harmless)")
    args = ap.parse_args()
    with open(os.path.join(OUT, f"items_{args.wiki}.tsv"), encoding="utf-8") as fh:
        title = dict(line.rstrip("\n").split("\t", 1) for line in fh if "\t" in line)
    done = set()
    try:
        with open(os.path.join(OUT, f"done_{args.wiki}.txt"), encoding="utf-8") as fh:
            done = {line.split("\t")[0].strip() for line in fh if line.strip()}
    except FileNotFoundError:
        pass
    found = {}
    with open(os.path.join(OUT, f"opening_{args.wiki}.tsv"), encoding="utf-8") as fh:
        for line in fh:
            q, text = line.rstrip("\n").split("\t", 1)
            kind = q in title and q not in done and classify(title[q], text)
            if kind:
                found[q] = (kind, text)
    print(f"{len(found)} pattern matches ({len(done)} done items skipped)")
    dis = [q for q, (k, _) in found.items() if k == "disambiguation"]
    marked = disambig_titles(args.wiki, [title[q] for q in dis])
    for q in dis:
        if title[q] not in marked:
            del found[q]
    print(f"   disambiguation: {len(marked)} of {len(dis)} marked as such on the wiki")
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=args.min_age_days)).strftime("%Y%m%d%H%M%S")
    first = first_revision(list(found))
    old = [q for q in found if first.get(q, "9") <= cutoff]
    keep = still_unclassified(old) if args.recheck else set(old)
    print(f"   {len(found) - len(old)} too new, {len(old) - len(keep)} classified meanwhile")
    qs_dir = os.path.join(OUT, f"qs_{args.wiki}_easy" + (str(args.round) if args.round > 1 else ""))
    os.makedirs(qs_dir, exist_ok=True)
    # the class describes the enwiki page only: with other sitelinks the item may be a mix (an enwiki
    # disambiguation page linked to articles elsewhere) -> fix the sitelinks by hand first
    others = other_sitelinks(sorted(keep), args.wiki)
    with open(os.path.join(qs_dir, "sitelinks_review.tsv"), "w", encoding="utf-8", newline="\n") as out:
        out.write("qid\tkind\ttitle\tother sitelinks\n")
        for q in sorted(others, key=lambda x: (found[x][0], int(x[1:]))):
            out.write(f"{q}\t{found[q][0]}\t{title[q]}\t{' | '.join(sorted(others[q]))}\n")
    keep -= set(others)
    print(f"   {len(others)} with other sitelinks -> sitelinks_review.tsv")
    ref = f"\tS143\t{WIKI_ITEM[args.wiki]}" if args.ref else ""
    by_kind = {}
    for q in sorted(keep, key=lambda x: int(x[1:])):
        by_kind.setdefault(found[q][0], []).append(q)
    for kind, qids in sorted(by_kind.items()):
        prop, cls, label = KINDS[kind]
        with open(os.path.join(qs_dir, f"{kind}.txt"), "w", encoding="utf-8", newline="\n") as out:
            out.writelines(f"{q}\t{prop}\t{cls}{ref}\n" for q in qids)
        print(f"   {kind:18} {prop} {cls} ({label}): {len(qids)}")
    random.seed(1)
    with open(os.path.join(qs_dir, "samples.tsv"), "w", encoding="utf-8", newline="\n") as out:
        for kind, qids in sorted(by_kind.items()):
            for q in random.sample(qids, min(15, len(qids))):
                out.write(f"{q}\t{kind}\t{title[q]}\t{first_sentence(found[q][1])[:200]}\n")
    print(f"{sum(map(len, by_kind.values()))} statements -> {qs_dir}")


if __name__ == "__main__":
    main()
