"""Titles with a year or number -> the class of the same title with another number (user's trick, 2026-10-31).

  python numbered.py [--wiki en] [--min-age-days 180]
  in:  output/items_<wiki>.tsv, output/opening_<wiki>.tsv, output/done_<wiki>.txt + output/qs_<wiki>*_all.txt (skipped)
  out: output/qs_<wiki>_numbered_all.txt (QS v1) + numbered_review.tsv (qid, why, title, class, opening)

Mask the numbers in a title; the other enwiki titles with that mask are siblings. The class is used when at least
MIN_SIBLINGS classified siblings exist (at most CAP looked up) and SHARE of them agree. One or two siblings decide
badly (a boat became a dramatico-musical work). Never from siblings: disambiguation pages, set index articles (their
molecular formula pages have the wrong class) and the genes, proteins and compounds the project skips. Spot check of
40: 1 wrong ('may refer to', now filtered), 2-3 debatable (sports season on a single event).
"""
import argparse
import collections
import datetime as dt
import glob
import os
import random
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from make_qs import first_revision  # noqa: E402
from nvc import classified  # noqa: E402
from replica_cats import run  # noqa: E402
from stub_table import qlever  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "output")
NUM = re.compile(r"\d+(?:st|nd|rd|th)?(?:[–-]\d+)?")
NAMESPACE = re.compile(r"^[A-Z][a-z]+:")
CAP, MIN_SIBLINGS, SHARE = 20, 3, 0.8
NEVER = {"Q4167410", "Q15623926", "Q7187", "Q8054", "Q11173", "Q11053", "Q3782045", "Q5630036", "Q5630163", "Q407693",
         "Q501128", "Q13442814", "Q16521"}
LOOSE = re.compile(r"\b(?:may|can|could) refer to\b|\bset index\b", re.I)
# siblings carry sports season on drafts, all-star games, torch relays, transactions: only titles that say it (user 2026-10-31)
SPORTS_SEASON = "Q27020041"
SEASON_TITLE = re.compile(r"(?:(?<![-\w])[Ss]easons?(?: \d+)?| (?:Circuit|Tour|Tour de las Américas|Tour Latinoamérica))$")
# read per class: the siblings agree, but on a class that does not describe these (planned event on wrestling shows,
# zone on Davis Cup editions, the race or the code itself as class) or the project skips it (chemicals)
HOLD_CLASS = {"Q1656682", "Q113145171", "Q55135234", "Q935429", "Q1065972", "Q84467700", "Q51081147", "Q5451988"}
HOLD_TITLE = re.compile(r"^\d+(?:\.\d+)? (?:AM|FM)$|United States ballot measures$|general convention of|"
                        r"^Congressional canvass|[Hh]onours\b|bravery awards| marketing$|^Planica \d|"
                        r"House of Representatives \(Nepal\)$")
# a bare '<word> #' title can share its mask with a boat by accident (Gloucester 4 = a rugby league, user 2026-10-31)
SAILBOAT = "Q106179098"
BOAT = re.compile(r"sail|yacht|boat|sloop|dinghy|keel|catamaran|ketch|cutter|schooner", re.I)
# and the other way round: Meridian 25 = a sailboat, its mask gave the satellite model Meridian (reverted, 2026-10-31)
SAILING = re.compile(r"sailboat|sailing|keelboat|yacht|dinghy", re.I)
REJECTED = os.path.join(OUT, "qs_en_numbered", "rejected.tsv")  # qid, title, wrong, correct class, note


def rejected():
    with open(REJECTED, encoding="utf-8") as fh:
        return {line.split("\t", 1)[0] for line in fh if line.startswith("Q")}


def sibling_classes(keys, unclassified):
    """mask -> (classified siblings looked up, Counter of 'P31 Q..' / 'P279 Q..')."""
    rows = run("en", "SELECT page_title, pp_value FROM page JOIN page_props ON pp_page = page_id AND "
                     "pp_propname = 'wikibase_item' WHERE page_namespace = 0 AND page_is_redirect = 0 AND "
                     "page_title REGEXP '[0-9]';\n")
    sib = collections.defaultdict(list)
    for row in rows:
        if len(row) == 2:
            key = NUM.sub("#", row[0].replace("_", " "))
            if key in keys and row[1] not in unclassified:
                sib[key].append(row[1])
    random.seed(1)
    want = {q: key for key, qs in sib.items() for q in random.sample(qs, min(CAP, len(qs)))}
    qs = sorted(want)
    count, seen = collections.defaultdict(collections.Counter), collections.defaultdict(set)
    for i in range(0, len(qs), 300):
        q = f"""PREFIX wd: <http://www.wikidata.org/entity/> PREFIX wdt: <http://www.wikidata.org/prop/direct/>
SELECT ?i ?p ?c WHERE {{ VALUES ?i {{ {" ".join("wd:" + x for x in qs[i:i + 300])} }}
  VALUES ?p {{ wdt:P31 wdt:P279 }} ?i ?p ?c }}"""
        for r in qlever(q):
            count[want[r["i"]]][f"{r['p'].rsplit('/', 1)[-1]} {r['c']}"] += 1
            seen[want[r["i"]]].add(r["i"])
        time.sleep(1)
    return {k: (len(seen[k]), count[k]) for k in count}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wiki", default="en")
    ap.add_argument("--min-age-days", type=int, default=180)
    args = ap.parse_args()
    with open(os.path.join(OUT, f"items_{args.wiki}.tsv"), encoding="utf-8") as fh:
        title = dict(line.rstrip("\n").split("\t", 1) for line in fh if "\t" in line)
    with open(os.path.join(OUT, f"done_{args.wiki}.txt"), encoding="utf-8") as fh:
        done = {line.strip() for line in fh if line.strip()}
    this = os.path.join(OUT, f"qs_{args.wiki}_numbered_all.txt")
    for path in glob.glob(os.path.join(OUT, f"qs_{args.wiki}*_all.txt")):
        if os.path.abspath(path) != os.path.abspath(this):  # waiting for upload, or uploaded
            with open(path, encoding="utf-8") as fh:
                done.update(line.split("\t", 1)[0] for line in fh if line.startswith("Q"))
    masks = collections.defaultdict(list)
    for q, t in title.items():
        if q not in done and NUM.search(t) and not NAMESPACE.match(t):
            masks[NUM.sub("#", t)].append(q)
    print(f"{len(masks)} masks, {sum(map(len, masks.values()))} items", flush=True)
    classes = sibling_classes(set(masks), set(title))
    pick, notes = {}, []
    for key, qs in masks.items():
        n, count = classes.get(key, (0, collections.Counter()))
        if n < MIN_SIBLINGS or not count:
            continue
        top, votes = count.most_common(1)[0]
        if votes / n < SHARE:
            continue
        pick.update({q: top for q in qs})
    print(f"{len(pick)} items with agreeing siblings", flush=True)
    opening = {}
    with open(os.path.join(OUT, f"opening_{args.wiki}.tsv"), encoding="utf-8") as fh:
        for line in fh:
            q, text = line.rstrip("\n").split("\t", 1)
            if q in pick:
                opening[q] = text
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=args.min_age_days)).strftime("%Y%m%d%H%M%S")
    first = first_revision(list(pick))
    have = classified(sorted(pick))
    wrong = rejected()
    lines = []
    for q in sorted(pick, key=lambda x: int(x[1:])):
        prop, cls = pick[q].split()
        s = opening.get(q, "")

        def note(why):
            notes.append((q, why, title[q], pick[q], s[:150]))

        if cls in NEVER:
            note("class not taken from siblings")
        elif cls == SPORTS_SEASON and not SEASON_TITLE.search(title[q]):
            note("sports season, but the title is no season")
        elif cls in HOLD_CLASS or HOLD_TITLE.search(title[q]) or (cls == SAILBOAT and not BOAT.search(s[:300])) or (cls != SAILBOAT and SAILING.search(s[:150])):
            note("class does not describe these")
        elif q in wrong:
            note("rejected, see qs_en_numbered/rejected.tsv")
        elif first.get(q, "9") > cutoff:
            note("too new")
        elif q in have:
            note("has a class by now")
        elif not s.strip():
            note("no opening")
        elif LOOSE.search(s[:300]):
            note("may refer to / set index")
        else:
            lines.append(f"{q}\t{prop}\t{cls}\n")
    with open(this, "w", encoding="utf-8", newline="\n") as fh:
        fh.writelines(lines)
    with open(os.path.join(OUT, "numbered_review.tsv"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write("qid\twhy\ttitle\tclass\topening\n")
        fh.writelines("\t".join(n) + "\n" for n in sorted(notes, key=lambda n: n[1]))
    print(f"{len(lines)} QS lines -> {os.path.basename(this)}; {len(notes)} in review")
    print({w: sum(1 for n in notes if n[1] == w) for w in sorted({n[1] for n in notes})})


if __name__ == "__main__":
    main()
