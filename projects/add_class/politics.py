"""'Politics of X' articles -> the model of the user's golden examples.

  python politics.py [--wiki en] [--min-age-days 180]
  in:  output/items_<wiki>.tsv, output/opening_<wiki>.tsv, output/done_<wiki>.txt (skipped)
  out: output/qs_<wiki>_politics_all.txt (QS v1) + politics_review.tsv (qid, note, title, main item, label, opening)

Model (user 2026-10-30):
- X is a country: politics of the Netherlands (Q877631), P31 political system + P31 politics by country + P17 X.
- X is part of a country: politics of Georgia (Q7225245), P279 politics of <its country> + P1269 (facet of) X.
X = the item of the enwiki article named by the rest of the title (see history.py). Its country = its one P17; the
parent = the item of the enwiki article 'Politics of <country>'. Anything else goes to the review file, no statement:
a topic (no matching X: resentment, Star Trek), a period, several or no P17, no parent.
"""
import argparse
import datetime as dt
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from history import PREFIX, enwiki_items, key, names_of  # noqa: E402
from make_qs import first_revision  # noqa: E402
from stub_table import qlever  # noqa: E402
from verify_stub import first_sentence  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "output")
TITLE = re.compile(r"^Politics of (.+)$")
SYSTEM, BY_COUNTRY = "Q28108", "Q12332021"
# about one issue there, not the politics of the place
ISSUE = {"the Oak Ridges Moraine", "the Barents Sea"}
PERIOD = re.compile(r" (?:before|during|in the) ")


def places(items):
    """item -> (kind 'country' or '', its P17 items, enwiki title of each P17, disambiguation?)."""
    out = {x: ["", [], False] for x in items}
    for i in range(0, len(items), 300):
        values = " ".join("wd:" + x for x in items[i:i + 300])
        q = PREFIX + f"""SELECT ?m ?c WHERE {{ VALUES ?m {{ {values} }} ?m wdt:P17 ?c }}"""
        for r in qlever(q):
            out[r["m"]][1].append(r["c"])
        q = PREFIX + f"""SELECT DISTINCT ?m ?t WHERE {{ VALUES ?m {{ {values} }} VALUES ?t {{ wd:Q6256 wd:Q3624078
  wd:Q3024240 wd:Q4167410 }} ?m wdt:P31 ?t }}"""
        for r in qlever(q):
            if r["t"] == "Q4167410":
                out[r["m"]][2] = True
            else:
                out[r["m"]][0] = "country"
    return out


def enwiki_titles(items):
    """item -> enwiki article title."""
    out = {}
    for i in range(0, len(items), 300):
        q = PREFIX + f"""SELECT ?m ?t WHERE {{ VALUES ?m {{ {" ".join("wd:" + x for x in items[i:i + 300])} }}
  ?a schema:about ?m ; schema:isPartOf <https://en.wikipedia.org/> ; schema:name ?t }}"""
        out.update((r["m"], r["t"]) for r in qlever(q))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wiki", default="en")
    ap.add_argument("--min-age-days", type=int, default=180)
    args = ap.parse_args()
    with open(os.path.join(OUT, f"items_{args.wiki}.tsv"), encoding="utf-8") as fh:
        title = dict(line.rstrip("\n").split("\t", 1) for line in fh if "\t" in line)
    with open(os.path.join(OUT, f"done_{args.wiki}.txt"), encoding="utf-8") as fh:
        done = {line.strip() for line in fh if line.strip()}
    cand = {q: TITLE.match(t).group(1) for q, t in title.items() if TITLE.match(t) and q not in done}
    opening = {}
    with open(os.path.join(OUT, f"opening_{args.wiki}.tsv"), encoding="utf-8") as fh:
        for line in fh:
            q, text = line.rstrip("\n").split("\t", 1)
            if q in cand:
                opening[q] = first_sentence(text)
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=args.min_age_days)).strftime("%Y%m%d%H%M%S")
    first = first_revision(list(cand))
    too_new = [q for q in cand if first.get(q, "9") > cutoff]
    for q in too_new:
        del cand[q]
    variants = {q: [v[0].upper() + v[1:] for v in dict.fromkeys([re.sub(r"^the ", "", r, flags=re.I), r])]
                for q, r in cand.items()}
    target = enwiki_items(sorted({v for vs in variants.values() for v in vs}))
    main_items = sorted({item for _, item in target.values()})
    info = places(main_items)
    alias = names_of(main_items)
    countries = sorted({c for _, cs, _ in info.values() for c in cs})
    country_title = enwiki_titles(countries)
    tries = {c: [f"Politics of {t}", f"Politics of the {t}"] for c, t in country_title.items()}
    parent_of = enwiki_items(sorted({t for ts in tries.values() for t in ts}))
    parent = {}
    for c, ts in tries.items():
        hit = next((parent_of[t] for t in ts if t in parent_of and parent_of[t][0].startswith("Politics of ")), None)
        if hit:
            parent[c] = hit[1]
    named = names_of(sorted(set(parent.values())))  # 'Politics of Nigeria' = the item federal government of Nigeria
    parent = {c: p for c, p in parent.items() if any("politics" in n.casefold() for n in named.get(p, ()))}
    lines, notes, count = [], [], {"country": 0, "part": 0}
    for q in sorted(cand, key=lambda x: int(x[1:])):
        rest, s = cand[q], opening.get(q, "")
        art, item = next((target[v] for v in variants[q] if v in target), ("", ""))
        kind, cs, disambig = info.get(item, ("", [], False))
        keys = {key(n) for n in alias.get(item, set())} - {""}

        def note(why):
            notes.append((q, why, title[q], item, art, s))

        if rest in ISSUE or PERIOD.search(rest):
            note("an issue or period: skipped")
        elif not item:
            note("no main article (a topic?): skipped")
        elif item == q or disambig:
            note("redirects to itself or a disambiguation page: skipped")
        elif not any(k in key(rest) or key(rest) in k for k in keys):  # 'Kanagawa' = Kanagawa Prefecture
            note("main item label differs (a topic?): skipped")
        elif kind == "country" or cs == [item]:
            lines += [f"{q}\tP31\t{SYSTEM}\n", f"{q}\tP31\t{BY_COUNTRY}\n", f"{q}\tP17\t{item}\n"]
            count["country"] += 1
        elif len(set(cs)) != 1:
            note(f"{len(set(cs))} countries on the main item: skipped")
        elif cs[0] not in parent:
            note(f"no 'Politics of' article for its country {cs[0]}: skipped")
        elif parent[cs[0]] == q:
            note("the parent is the item itself: skipped")
        else:
            lines += [f"{q}\tP279\t{parent[cs[0]]}\n", f"{q}\tP1269\t{item}\n"]
            count["part"] += 1
    with open(os.path.join(OUT, f"qs_{args.wiki}_politics_all.txt"), "w", encoding="utf-8", newline="\n") as fh:
        fh.writelines(lines)
    with open(os.path.join(OUT, "politics_review.tsv"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write("qid\tnote\ttitle\tmain item\tmain article\topening\n")
        fh.writelines("\t".join(map(str, n)) + "\n" for n in sorted(notes, key=lambda n: n[1]))
    print(f"{len(cand) + len(too_new)} politics titles, {len(too_new)} too new; {count['country']} countries, "
          f"{count['part']} parts; {len(notes)} skipped; {len(lines)} QS lines -> qs_{args.wiki}_politics_all.txt")
    print(json.dumps({n: sum(1 for x in notes if x[1] == n) for n in sorted({x[1] for x in notes})}))


if __name__ == "__main__":
    main()
