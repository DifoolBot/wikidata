"""Page kinds the enwiki categories or the namespace state outright: disambiguation, set index, names, Template:, Category:, ... (2026-11-01).

  python pages.py [--wiki en] [--min-age-days 180]
  in:  output/items_<wiki>.tsv, output/cats_<wiki>.tsv, output/done_<wiki>.txt + output/qs_<wiki>*_all.txt + output/*/rejected.tsv (skipped)
  out: output/qs_<wiki>_pages_all.txt (QS v1) + pages_review.tsv (qid, why, kind, title, other sitelinks)

The class describes the enwiki page only. So other sitelinks are allowed only in the namespace kinds, and there only to
pages in a namespace too: an article next to it means the item may be a mix, which is a job for the sitelinks by hand.
"""
import argparse
import collections
import datetime as dt
import glob
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ.setdefault("PYWIKIBOT_DIR", os.path.dirname(os.path.dirname(HERE)))
import pywikibot  # noqa: E402
from pywikibot import config  # noqa: E402
from pywikibot.data import api  # noqa: E402

from make_qs import first_revision  # noqa: E402

OUT = os.path.join(HERE, "output")
NAMESPACE = {"Template": "Q11266439", "Category": "Q4167836", "Portal": "Q4663903", "Module": "Q15184295",
             "Help": "Q56005592", "Wikipedia": "Q14204246"}
CLASS = {"disambiguation": "Q4167410", "set index": "Q15623926", "surname": "Q101352", "male given name": "Q12308941",
         "female given name": "Q11879590", "unisex given name": "Q3409032", "given name": "Q202444", "nickname": "Q49614"}
# set index by category too, but 169 of 220 '(nickname)' pages have Q49614; a page can be nickname and more (Zizou)
MIXED_NICKNAME = re.compile(r"\bnickname (?:or|and) (?:an? )?(?:given|sur|family)", re.I)
SURNAME = re.compile(r"(?:^|_)[Ss]urnames$")
GIVEN = re.compile(r"(?:^|_)[Gg]iven_names$")
LISTLIKE = re.compile(r"\b(?:may|can|could) (?:also )?refer to\b|\brefers? to (?:several|various|either|any)\b|\bis the name of (?:several|two|three|many)\b|"
                      r"\bcommon name\b|\bnickname\b|\bbyname\b|\bepithet\b|\bset index\b", re.I)


def kind_of(title, cats):
    """The kind of a page, or (None, why) when its categories say two things."""
    space = title.split(":", 1)[0] if ":" in title else ""
    if space in NAMESPACE:
        return space, ""
    if "All_disambiguation_pages" in cats or title.endswith("(disambiguation)"):
        return "disambiguation", ""
    surname = any(SURNAME.search(c) for c in cats)
    given = [c for c in cats if GIVEN.search(c)]
    if surname and given:
        return None, "surname and given name"
    if surname:
        return "surname", ""
    if given:
        sex = {w for c in given for w in ("Masculine", "Feminine", "Unisex") if w in c}
        if len(sex) > 1 and "Unisex" not in sex:
            return "unisex given name", ""
        return {"Masculine": "male given name", "Feminine": "female given name", "Unisex": "unisex given name"}.get(
            min(sex) if len(sex) == 1 else "Unisex" if sex else "", "given name"), ""
    if any("et_index_articles" in c for c in cats):
        return "set index", ""
    return None, ""


def opening_agrees(kind, text):
    """Pages get filed under these categories by mistake too (Mukarakate is a place, Brancaccio family a family)."""
    s = text[:250]
    if kind == "set index":
        return bool(LISTLIKE.search(s))
    if kind == "surname":
        return bool(re.search(r"\b(?:sur|family |last |)name\b", s)) and not re.search(r"\bname of an?\b|\blexeme\b|\btribe\b|\bclan\b|\bcaste\b", s)
    if kind.endswith("given name"):
        return bool(re.search(r"\bname\b", s)) and not re.search(r"\bsurname\b|\bfamily name\b|\blexeme\b|\bcharacter\b", s)
    return True


def fetch(site, ids):
    """QID -> (other sitelinks, has P31/P279, redirect or deleted), through the API."""
    info = {}
    for i in range(0, len(ids), 200):
        part = ids[i:i + 200]
        data = api.Request(site=site, parameters={"action": "wbgetentities", "ids": "|".join(part), "props": "claims|sitelinks|info",
                                                  "maxlag": 5}).submit()
        for q, e in data["entities"].items():
            links = {w: s["title"] for w, s in e.get("sitelinks", {}).items()}
            info[q] = (links, bool(e.get("claims", {}).get("P31") or e.get("claims", {}).get("P279")), "missing" in e or "redirects" in e)
        for q in part:
            info.setdefault(q, ({}, False, True))  # a redirect comes back under its target's id
        time.sleep(1)
        print(min(i + 200, len(ids)), flush=True)
    return info


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wiki", default="en")
    ap.add_argument("--min-age-days", type=int, default=180)
    args = ap.parse_args()
    with open(os.path.join(OUT, f"items_{args.wiki}.tsv"), encoding="utf-8") as fh:
        title = dict(line.rstrip("\n").split("\t", 1) for line in fh if "\t" in line)
    with open(os.path.join(OUT, f"done_{args.wiki}.txt"), encoding="utf-8") as fh:
        done = {line.strip() for line in fh if line.strip()}
    this = os.path.join(OUT, f"qs_{args.wiki}_pages_all.txt")
    for path in glob.glob(os.path.join(OUT, f"qs_{args.wiki}*_all.txt")) + glob.glob(os.path.join(OUT, "*", "rejected.tsv")):
        if os.path.abspath(path) != os.path.abspath(this):
            with open(path, encoding="utf-8") as fh:
                done.update(line.split("\t", 1)[0] for line in fh if line.startswith("Q"))
    cats = collections.defaultdict(set)
    opening = {}
    with open(os.path.join(OUT, f"opening_{args.wiki}.tsv"), encoding="utf-8") as fh:
        for line in fh:
            q, text = line.rstrip("\n").split("\t", 1)
            opening[q] = re.sub(r"\s+", " ", text)
    with open(os.path.join(OUT, f"cats_{args.wiki}.tsv"), encoding="utf-8") as fh:
        for line in fh:
            q, cat = line.rstrip("\n").split("\t", 1)
            cats[q].add(cat)
    found, notes = {}, []
    for q, t in title.items():
        if q in done:
            continue
        kind, why = kind_of(t, cats.get(q, set()))
        if kind == "set index" and any("icknam" in c for c in cats.get(q, ())) and not MIXED_NICKNAME.search(opening.get(q, "")[:150]):
            kind = "nickname"
        if kind:
            found[q] = kind
        elif why:
            notes.append((q, why, "", t, ""))
    print(len(found), "pages:", collections.Counter(found.values()).most_common(), flush=True)
    config.maxlag = 5
    config.max_retries = 60
    site = pywikibot.Site("wikidata", "wikidata")
    site.login()
    assert site.user() == "DifoolBot", site.user()
    info = fetch(site, sorted(found))
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=args.min_age_days)).strftime("%Y%m%d%H%M%S")
    first = first_revision(list(found))
    lines, count = [], collections.Counter()
    own = f"{args.wiki}wiki"
    for q in sorted(found, key=lambda x: int(x[1:])):
        kind, t = found[q], title[q]
        links, classed, gone = info[q]
        others = {w: s for w, s in links.items() if w != own}
        if gone:
            notes.append((q, "redirect or deleted", kind, t, ""))
        elif classed:
            notes.append((q, "has a class by now", kind, t, ""))
        elif first.get(q, "9") > cutoff:
            notes.append((q, "too new", kind, t, ""))
        elif not opening_agrees(kind, opening.get(q, "")):
            notes.append((q, "opening does not say so", kind, t, opening.get(q, "")[:200]))
        elif kind in NAMESPACE and all(":" in s for s in others.values()):
            lines.append(f"{q}\tP31\t{NAMESPACE[kind]}\n")
            count[kind] += 1
        elif kind not in NAMESPACE and not others:
            lines.append(f"{q}\tP31\t{CLASS[kind]}\n")
            count[kind] += 1
        else:
            notes.append((q, "other sitelinks", kind, t, " | ".join(f"{w}:{s}" for w, s in sorted(others.items()))[:300]))
    with open(this, "w", encoding="utf-8", newline="\n") as fh:
        fh.writelines(lines)
    with open(os.path.join(OUT, "pages_review.tsv"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write("qid\twhy\tkind\ttitle\tother sitelinks\n")
        fh.writelines("\t".join(n) + "\n" for n in sorted(notes, key=lambda n: (n[2], n[1])))
    print(f"{len(lines)} QS lines -> {os.path.basename(this)}; {len(notes)} in review")
    print(count.most_common())
    print(collections.Counter((n[2], n[1]) for n in notes).most_common())
    labels = sorted(set(NAMESPACE.values()) | set(CLASS.values()))
    data = api.Request(site=site, parameters={"action": "wbgetentities", "ids": "|".join(labels), "props": "labels", "languages": "en", "maxlag": 5}).submit()
    for c in labels:
        print(c, data["entities"][c]["labels"]["en"]["value"])


if __name__ == "__main__":
    main()
