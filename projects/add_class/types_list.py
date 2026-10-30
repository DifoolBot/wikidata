"""Type / list articles skipped by make_qs.py -> output/qs_<wiki>/types_review.tsv, for review (READ-ONLY).

  python projects/add_class/types_list.py [--wiki en]

Rows: 'type/list article' (a Types_of_/Lists_of_ category) and 'type article' (a P31 row whose short description
says 'Type of ...': proposed P279 of the same class). An article in 'Types_of_saints' is a kind of saint ('Saint Companions', user 2026-10-28): proposed P279 = the
main topic (P301) of that Types_of_ category, else its P4224. A 'List of ...' article: P31 Wikimedia list article.
Other rows (a list category on a non-list title) get no proposal. Columns: qid, title, category, proposal, label.
The file is .tsv on purpose: make_qs.py rewrites the *.txt batches, this list stays a hand check.
"""
import argparse
import csv
import os
import sys
import urllib.parse as u

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "nl_books"))
from wd_api import api_get  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "output")
LIST_ARTICLE = "Q13406463"


def entities(ids, props):
    out = {}
    ids = sorted(set(ids))
    for i in range(0, len(ids), 50):
        r = api_get("https://www.wikidata.org/w/api.php?" + u.urlencode(
            {"action": "wbgetentities", "ids": "|".join(ids[i:i + 50]), "props": props, "languages": "en|mul",
             "format": "json"}))
        out.update(r["entities"])
    return out


def label(e):
    labels = e.get("labels", {})
    return (labels.get("en") or labels.get("mul") or {}).get("value", "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wiki", default="en")
    args = ap.parse_args()
    qs_dir = os.path.join(OUT, f"qs_{args.wiki}")
    with open(os.path.join(qs_dir, "skipped.tsv"), encoding="utf-8") as fh:
        rows = [r.rstrip("\n").split("\t") for r in fh if "\ttype/list article\t" in r or "\ttype article\t" in r]
    with open(os.path.join(OUT, f"items_{args.wiki}.tsv"), encoding="utf-8") as fh:
        title = dict(line.rstrip("\n").split("\t", 1) for line in fh)
    cats = sorted({c for _, why, c in rows if why == "type/list article"})
    cat_item = {}
    for i in range(0, len(cats), 50):
        r = api_get(f"https://{args.wiki}.wikipedia.org/w/api.php?" + u.urlencode(
            {"action": "query", "prop": "pageprops", "ppprop": "wikibase_item", "format": "json",
             "titles": "|".join("Category:" + c.replace("_", " ") for c in cats[i:i + 50])}))
        for p in r["query"]["pages"].values():
            if "pageprops" in p:
                cat_item[p["title"].split(":", 1)[1].replace(" ", "_")] = p["pageprops"]["wikibase_item"]
    cat_e = entities(cat_item.values(), "claims")

    def topic(c):
        claims = cat_e.get(cat_item.get(c), {}).get("claims", {})
        for p in ("P301", "P4224"):
            for st in claims.get(p, []):
                v = st["mainsnak"].get("datavalue", {}).get("value", {}).get("id")
                if v and not st.get("qualifiers"):
                    return v
        return ""

    out = []
    for q, why, c in rows:
        t = title.get(q, "")
        if why == "type article":  # from the short description: 'P279 Qclass | Type of mace ...'
            proposal, desc = c.split(" | ", 1)
            out.append([q, t, desc, proposal])
        elif t.startswith("List of ") or t.startswith("Lists of "):
            out.append([q, t, c, f"P31 {LIST_ARTICLE}"])
        elif not c.startswith("Lists_of_") and topic(c):
            out.append([q, t, c, f"P279 {topic(c)}"])
        else:
            out.append([q, t, c, ""])
    labels = entities([p.split()[1] for *_, p in out if p], "labels")
    path = os.path.join(qs_dir, "types_review.tsv")
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter="\t", lineterminator="\n")
        w.writerow(["qid", "title", "category", "proposal", "label"])
        for q, t, c, p in out:
            w.writerow([q, t, c, p, label(labels.get(p.split()[1], {})) if p else ""])
    print(f"{len(out)} rows, {sum(1 for r in out if r[3])} with a proposal -> {path}")


if __name__ == "__main__":
    main()
