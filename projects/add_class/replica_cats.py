"""Categories of the articles in output/items_<wiki>.tsv, from the Toolforge wiki replica over SSH (READ-ONLY).

  python projects/add_class/replica_cats.py [--wiki en] [--limit N]
  -> output/cats_<wiki>.tsv  (qid, category)        article categories (main namespace, no redirects)
  -> output/catinfo_<wiki>.tsv (category, item, hidden, parents)  per distinct category: its Wikidata item,
     hiddencat flag and its own parent categories ('|'-joined)

Lookup is by page title (indexed), batched; one mariadb session per step reads all batches from stdin.
"""
import argparse
import os
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "output")
SSH_HOST = "difool@login.toolforge.org"
BATCH = 2000


def replica_cmd(wiki):
    return (f'become difoolbot bash -c "mariadb --defaults-file=\\$HOME/replica.my.cnf '
            f'-h {wiki}wiki.analytics.db.svc.wikimedia.cloud -N --raw {wiki}wiki_p"')


def lit(title):
    return "'" + title.replace(" ", "_").replace("\\", "\\\\").replace("'", "\\'") + "'"


def run(wiki, sql):
    p = subprocess.run(["ssh", "-o", "BatchMode=yes", SSH_HOST, replica_cmd(wiki)], input=sql.encode("utf-8"),
                       capture_output=True, timeout=7200)
    if p.returncode:
        raise SystemExit(p.stderr.decode("utf-8", "replace")[-2000:])
    return [line.split("\t") for line in p.stdout.decode("utf-8").split("\n") if line]


def article_cats(titles, ns):
    """SQL: (page title, category title) for pages in namespace ns."""
    return (f"SELECT page_title, lt_title FROM page JOIN categorylinks ON cl_from = page_id "
            f"JOIN linktarget ON lt_id = cl_target_id AND lt_namespace = 14 "
            f"WHERE page_namespace = {ns} AND page_is_redirect = 0 AND page_title IN ({','.join(map(lit, titles))});\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wiki", default="en")
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()
    with open(os.path.join(OUT, f"items_{args.wiki}.tsv"), encoding="utf-8") as fh:
        items = [line.rstrip("\n").split("\t") for line in fh if line.strip()]
    items = items[:args.limit] if args.limit else items
    qid = {t.replace(" ", "_"): q for q, t in items}

    # 1. article -> categories
    titles = list(qid)
    sql = "".join(article_cats(titles[i:i + BATCH], 0) for i in range(0, len(titles), BATCH))
    rows = run(args.wiki, sql)
    with open(os.path.join(OUT, f"cats_{args.wiki}.tsv"), "w", encoding="utf-8", newline="\n") as fh:
        for t, c in rows:
            fh.write(f"{qid.get(t, '?')}\t{c}\n")
    cats = sorted({c for _, c in rows})
    print(f"{len(rows)} article-category links, {len(cats)} distinct categories")

    # 2. category -> item, hidden flag, parents
    info = {c: ["", "0", []] for c in cats}
    sql = ""
    for i in range(0, len(cats), BATCH):
        part = ",".join(map(lit, cats[i:i + BATCH]))
        sql += (f"SELECT 'I', page_title, pp_propname, pp_value FROM page JOIN page_props ON pp_page = page_id "
                f"AND pp_propname IN ('wikibase_item', 'hiddencat') WHERE page_namespace = 14 AND page_title IN ({part});\n")
        sql += "SELECT 'P', p.* FROM (" + article_cats(cats[i:i + BATCH], 14).rstrip(";\n") + ") p;\n"
    for r in run(args.wiki, sql):
        if r[0] == "I" and r[1] in info:
            info[r[1]][0 if r[2] == "wikibase_item" else 1] = r[3] if r[2] == "wikibase_item" else "1"
        elif r[0] == "P" and r[1] in info:
            info[r[1]][2].append(r[2])
    with open(os.path.join(OUT, f"catinfo_{args.wiki}.tsv"), "w", encoding="utf-8", newline="\n") as fh:
        for c, (item, hidden, parents) in info.items():
            fh.write(f"{c}\t{item}\t{hidden}\t{'|'.join(parents)}\n")
    print(f"category info -> catinfo_{args.wiki}.tsv")


if __name__ == "__main__":
    main()
