"""'Women in X' articles -> the model of the user's golden example.

  python women.py [--wiki en] [--min-age-days 180]
  in:  output/items_<wiki>.tsv, output/done_<wiki>.txt (skipped)
  out: output/qs_<wiki>_women_all.txt (QS v1) + women_review.tsv (qid, why, title)

Model (user 2026-10-30): women in World War II (Q16969751), P31 female topic + P2348 (time period) the war or period.
The title alone can't tell a topic from an organisation, so REVIEW is picked by hand from the openings. P2348 only for
a named war, revolution or period (PERIOD), not for a polity or society (Joseon, Etruscan society).
A place (PLACE): women in Japan (Q8031453), women in the United States (Q17514041), P31 aspect in a geographic region +
P1269 women's history + P17 the P17 of the place (none when the place has not exactly one). A historical society
(HISTORIC, as Women in Maya society): the same without P17. A clear occupation
(WORKFORCE): also P1269 women in the workforce, as on Women in WWE (Q1205260).
"""
import argparse
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from history import enwiki_items  # noqa: E402
from make_qs import first_revision  # noqa: E402
from stub_table import qlever  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "output")
FEMALE_TOPIC, IN_REGION, WORKFORCE_ITEM, WOMENS_HISTORY = "Q107243694", "Q74817647", "Q8031587", "Q1279400"
PLACE = {"Q114415092": "Sri Lanka", "Q8031221": "Haiti", "Q139854489": "Malawi", "Q131198560": "Bermuda",
         "Q17018186": "British Virgin Islands", "Q137187414": "Western Sahara"}
HISTORIC = {"Q124619491", "Q132068758", "Q3068267", "Q4763684", "Q8031519"}  # place model without P17
WORKFORCE = {"Q22909799", "Q115804809", "Q60774877", "Q8031523", "Q22909800", "Q60776124", "Q30324151", "Q52694679"}
REVIEW = {
    "organisation": ["Q116814742", "Q139964183", "Q16930162", "Q17017683", "Q18395281", "Q55137849", "Q8031074",
                     "Q8031445", "Q85816091"],
    "work or legend": ["Q109849993", "Q136105254", "Q8031404"],
    "list": ["Q20716498", "Q21005936", "Q21005938", "Q21189893", "Q24190713", "Q85816099", "Q108822417",
             "Q134581470"],
    "theme in a work": ["Q8031490", "Q97585963", "Q8031549", "Q96419673"],
}
PERIOD = {
    "Q107740189": "Iran–Iraq War", "Q107740215": "War in Donbas", "Q107980656": "Cuban Revolution",
    "Q108486087": "Internal conflict in Peru", "Q108532505": "Gulf War", "Q123776206": "Mexican–American War",
    "Q131871773": "First Intifada", "Q131904615": "Sri Lankan Civil War",
    "Q131919580": "Myanmar civil war (2021–present)", "Q58061015": "Vietnam War",
    "Q3068288": "American Revolution", "Q8031548": "World War I", "Q96415486": "Mexican drug war",
    "Q115519806": "Spanish transition to democracy", "Q65080844": "Second Spanish Republic",
    "Q8031546": "Age of Enlightenment", "Q8031543": "California gold rush",
    "Q123685005": "Decolonisation of Africa", "Q64359127": "Bengali language movement",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wiki", default="en")
    ap.add_argument("--min-age-days", type=int, default=180)
    args = ap.parse_args()
    with open(os.path.join(OUT, f"items_{args.wiki}.tsv"), encoding="utf-8") as fh:
        title = dict(line.rstrip("\n").split("\t", 1) for line in fh if "\t" in line)
    with open(os.path.join(OUT, f"done_{args.wiki}.txt"), encoding="utf-8") as fh:
        done = {line.strip() for line in fh if line.strip()}
    cand = [q for q, t in title.items() if t.startswith("Women in ") and q not in done]
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=args.min_age_days)).strftime("%Y%m%d%H%M%S")
    first = first_revision(cand)
    why = {q: w for w, qs in REVIEW.items() for q in qs}
    why.update({q: "too new" for q in cand if first.get(q, "9") > cutoff})
    target = enwiki_items(sorted(set(PERIOD.values()) | set(PLACE.values())))
    place_items = " ".join("wd:" + target[t][1] for t in PLACE.values() if t in target)
    country = {}
    for r in qlever(f"""PREFIX wd: <http://www.wikidata.org/entity/> PREFIX wdt: <http://www.wikidata.org/prop/direct/>
SELECT ?m ?c WHERE {{ VALUES ?m {{ {place_items} }} ?m wdt:P17 ?c }}"""):
        country.setdefault(r["m"], set()).add(r["c"])
    lines, periods = [], 0
    for q in sorted(cand, key=lambda x: int(x[1:])):
        if q in why:
            continue
        lines.append(f"{q}\tP31\t{IN_REGION if q in PLACE or q in HISTORIC else FEMALE_TOPIC}\n")
        if q in HISTORIC:
            lines.append(f"{q}\tP1269\t{WOMENS_HISTORY}\n")
        if q in PLACE:
            lines.append(f"{q}\tP1269\t{WOMENS_HISTORY}\n")
            cs = country.get(target[PLACE[q]][1], set()) if PLACE[q] in target else set()
            if len(cs) == 1:
                lines.append(f"{q}\tP17\t{next(iter(cs))}\n")
            else:
                why[q] = f"no P17: {len(cs)} countries on {PLACE[q]}"
        if q in WORKFORCE:
            lines.append(f"{q}\tP1269\t{WORKFORCE_ITEM}\n")
        if PERIOD.get(q) in target:
            lines.append(f"{q}\tP2348\t{target[PERIOD[q]][1]}\n")
            periods += 1
        elif q in PERIOD:
            why[q] = f"P31 only, no article {PERIOD[q]}"
    with open(os.path.join(OUT, f"qs_{args.wiki}_women_all.txt"), "w", encoding="utf-8", newline="\n") as fh:
        fh.writelines(lines)
    with open(os.path.join(OUT, "women_review.tsv"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write("qid\twhy\ttitle\n")
        fh.writelines(f"{q}\t{w}\t{title[q]}\n" for q, w in sorted(why.items(), key=lambda x: x[1]) if q in title)
    print(f"{len(cand)} titles; {sum(x.split(chr(9))[1] == 'P31' for x in lines)} items,{periods} with P2348; "
          f"{len(lines)} QS lines -> qs_{args.wiki}_women_all.txt")
    for q in sorted(PERIOD):
        print(q, title.get(q), "->", target.get(PERIOD[q]), "SKIP" if why.get(q) else "")


if __name__ == "__main__":
    main()
