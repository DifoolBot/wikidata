"""Title families whose opening states the class -> the class most classified siblings use (found 2026-10-31).

  python groups.py [--wiki en] [--min-age-days 180]
  in:  output/items_<wiki>.tsv, output/opening_<wiki>.tsv, output/done_<wiki>.txt + output/qs_<wiki>*_all.txt (skipped)
  out: output/qs_<wiki>_groups_all.txt (QS v1) + groups_review.tsv (qid, why, group, title, opening)

A title alone misleads (Fort Hood 43, Band of the Royal Irish Regiment), so the word must come after is/was/are/were in
the opening. The first group that matches decides. Class only: a family with a golden example of the user gets its own
script with the other statements. Namespace pages need no opening.
"""
import argparse
import collections
import datetime as dt
import glob
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from make_qs import first_revision  # noqa: E402
from nvc import classified  # noqa: E402
from stub_table import qlever  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "output")
LOOSE = re.compile(r"\b(?:may|can|could) refer to\b|\bset index\b", re.I)
UNIT = r"\b(?:army|infantry|cavalry|regiment|military|militia|artillery|air force|navy|naval|armou?red|national guard|royal air)\b"
# name, property, class, title, word after is/was in the opening ('' = no opening needed), title or opening not wanted
GROUPS = [
    ("Template:", "P31", "Q11266439", r"^Template:", "", ""),
    ("Category:", "P31", "Q4167836", r"^Category:", "", ""),
    ("Portal:", "P31", "Q4663903", r"^Portal:", "", ""),
    ("Wikipedia:", "P31", "Q14204246", r"^Wikipedia:", "", ""),
    ("Module:", "P31", "Q15184295", r"^Module:", "", ""),
    ("Billboard Year-End", "P31", "Q98645843", r"^Billboard Year-End ", r"\blist\b", ""),
    ("Lists of", "P31", "Q13406463", r"^Lists of ", r"\blists?\b", ""),
    ("ballot measures", "P31", "Q13406463", r"ballot measures$", "", ""),
    ("Bibliography of", "P31", "Q1631107", r"^Bibliography of | bibliography$", r"\b(?:bibliography|list)\b", ""),
    ("Regiment", "P31", "Q176799", r" Regiment$", r"\b(?:regiment|battery)\b", r"^Band of "),
    ("Battalion", "P31", "Q176799", r" Battalion$", r"\bbattalion\b", ""),
    ("Squadron", "P31", "Q176799", r" Squadron$", UNIT, ""),
    ("Brigade", "P31", "Q176799", r" Brigade$", UNIT, r"protest|militant|Ambulance"),
    ("Operation", "P31", "Q645883", r"^Operation ", r"\b(?:military operation|military offensive|offensive|naval operation|airborne operation|amphibious)\b", ""),
    ("naval battle", "P31", "Q1261499", r"^Battle of ", r"\bnaval (?:battle|engagement)\b", ""),
    ("Battle of", "P31", "Q178561", r"^Battle of ", r"^[^.]*?\b(?:fought|took place|occurred|engagement|conflict)\b|\b(?:is|was)\b[^.]*?\bbattle\b",
     r"order of battle|Golds|Begums|\bwrestling\b|\bcricket\b"),
    ("ministry", "P31", "Q640506", r" ministry$", r"\b(?:ministry|cabinet|council of ministers)\b", r"\bshadow\b|Christian|Catholic"),
    ("Presidency of", "P31", "Q15284636", r"^Presidency of (?!the |Strategy)", r"\b(?:presidency|president)\b", ""),
    ("Minister of", "P31", "Q4164871", r"^Minister of ", r"\b(?:minister|cabinet|office|position)\b", ""),
    ("Governor of", "P31", "Q4164871", r"^Governor of ", r"\b(?:governor|chief executive|officer)\b", ""),
    ("leadership election", "P31", "Q6508670", r"^\d{4} .* leadership election$", r"\belect\b|\bheld\b", ""),
    ("gubernatorial election", "P31", "Q15261477", r"^\d{4} .* gubernatorial election$", r"\belect\b|\bheld\b|\belection\b", ""),
    ("year election", "P31", "Q40231", r"^\d{4}(?:[–-]\d{2,4})? .* election$", r"\belect\b|\bheld\b|\belections?\b|\btook place\b", r"\bcandidates\b|opinion polling|Brotherhood"),
    ("state house district", "P31", "Q104146934", r"House of Representatives \d+[a-z]{2} district$", r"\bdistricts?\b", ""),
    ("District Council former", "P31", "Q64827141", r"^District Council of ", r"\blocal government area\b", r"\bis\b.{0,40}\blocal government area\b"),
    ("District Council", "P31", "Q55558027", r"^District Council of ", r"\blocal government area\b", ""),
    ("parish NSW", "P31", "Q28931760", r", New South Wales$", r"\bparish\b", ""),
    ("Irish act", "P31", "Q91586285", r" Act,? \d{4}$", r"\bOireachtas\b", ""),
    ("Indian act", "P31", "Q33283984", r" Act,? \d{4}$", r"\bParliament of India\b", ""),
    ("Constitution of", "P31", "Q7755", r"^Constitution of ", r"\bconstitution\b", r"Tribunal|Amendment|Committee"),
    ("Free Trade Agreement", "P31", "Q3536928", r"Free Trade Agreement$", r"\bfree trade agreement\b", r"^Proposed |\bproposed\b"),
    ("political scandal", "P31", "Q934744", r" scandal$", r"\bpolitical scandal\b", r"^Official "),
    ("scandal", "P31", "Q192909", r" scandal$", r"\bscandal\b", r"^Official "),
    ("controversy", "P31", "Q1255828", r" controversy$", r"\b(?:controversy|debate|dispute)\b", ""),
    ("protests", "P31", "Q273120", r" protests$", r"\b(?:protests?|demonstrations?)\b", ""),
    ("strike", "P31", "Q49776", r" strike$", r"\bstrike\b", r"missile|air|drone|^First-pitch|type of labor|form of "),
    ("COVID-19 in", "P31", "Q3241045", r"^COVID-19 pandemic in ", r"\bpandemic\b", ""),
    ("Demographics of", "P31", "Q23983664", r"^Demographics of (?!districts of|Jehovah|the Democratic Party|Generation|the Church of|the Victorian|Nair)", "", ""),
    ("ethnic group", "P31", "Q41710", r"^[\w'-]+(?: [\w'-]+)? people$", r"\b(?:ethnic|ethnolinguistic|tribe|tribal|indigenous|aboriginal|pastoral|community|subgroup)\b", r"\bby\b"),
    ("dialect", "P31", "Q33384", r" dialect$", r"\bdialect\b", ""),
    ("theorem", "P31", "Q65943", r" theorem$", r"\btheorem\b|\bstates\b", ""),
    ("conjecture", "P31", "Q319141", r" conjecture$", r"\b(?:conjecture|unsolved|proposed)\b", ""),
    ("equation", "P31", "Q11345", r" equation$", r"\bequation\b", ""),
    ("algorithm", "P31", "Q8366", r" algorithm$", r"\balgorithm\b", ""),
    ("former hospital", "P31", "Q64578911", r" Hospital$", r"^(?:(?!\bis\b)[^.])*?\bwas\b[^.]{0,60}\bhospital\b", ""),
    ("Hospital", "P31", "Q16917", r" Hospital$", r"\bhospital\b", r"\bveterinary\b"),
    ("High School", "P31", "Q9826", r" High School$", r"\bhigh school\b", ""),
    ("Museum", "P31", "Q33506", r" Museum$", r"\bmuseum\b", r"^Friends of "),
    ("public library", "P31", "Q28564", r" Library$", r"\bpublic library\b", r"^The Committee"),
    ("Hindu temple", "P31", "Q842402", r" Temple$", r"\bhindu\b", ""),
    ("Buddhist temple", "P31", "Q5393308", r" Temple$", r"\bbuddhist\b", ""),
    ("Stadium", "P31", "Q483110", r" Stadium$", r"\bstadium\b", ""),
    ("Mall", "P31", "Q11315", r" Mall$", r"\b(?:mall|shopping cent(?:er|re))\b", ""),
    ("Dam", "P31", "Q12323", r" Dam$", r"\bdam\b", r"\bproposed\b"),
    ("Statue of", "P31", "Q179700", r"^Statue of ", r"\bstatue\b", r"coins?|\bproposed\b"),
    ("bowl game", "P31", "Q2922711", r" Bowl$", r"\bbowl game\b", ""),
    ("Player of the Year", "P31", "Q618779", r"Player of the Year(?: Award)?$", r"\b(?:award|awarded|given|presented)\b", ""),
    ("women's national cricket team", "P31", "Q86255923", r"women's national cricket team$", r"\bcricket\b", ""),
    ("national cricket team", "P31", "Q86255944", r" national cricket team$", r"\bcricket\b", r"women|under"),
    ("cricket team", "P31", "Q17376093", r" cricket team$", r"\bcricket\b", r" in "),
]
PRED = r"\b(?:is|was|are|were)\b[^.]*?"
# 'An adjoint equation is ...' names a kind, 'The Fenske equation is ...' one thing: a kind is P279 (user 2026-10-31)
KIND = re.compile(r"^(?:In [^,]{3,40}, )?(?:An?|Any) ", re.I)
KIND_CLASSES = {"Q8366", "Q11345", "Q65943", "Q176799", "Q16917"}
TYPE_OF = re.compile(r"\b(?:is|was|are|were) (?:a|an) type of\b|\bname for a type of\b", re.I)
# an article about something around the family, not one of its members
AROUND = re.compile(r"^(?:Reactions|Illustration|Investigation|Social media|Death sentences|Timeline|Criticism|Aftermath|"
                    r"Effects|Locomotives) |solution to the ")


def compile_groups():
    out = []
    for name, prop, cls, t, word, no in GROUPS:
        whole = word if word.startswith("^") else PRED + word  # '^' = the pattern brings its own is/was
        out.append((name, prop, cls, re.compile(t), re.compile(whole, re.I) if word else None,
                    re.compile(no) if no else None))
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
    this = os.path.join(OUT, f"qs_{args.wiki}_groups_all.txt")
    for path in glob.glob(os.path.join(OUT, f"qs_{args.wiki}*_all.txt")):
        if os.path.abspath(path) != os.path.abspath(this):  # waiting for upload, or uploaded
            with open(path, encoding="utf-8") as fh:
                done.update(line.split("\t", 1)[0] for line in fh if line.startswith("Q"))
    opening = {}
    with open(os.path.join(OUT, f"opening_{args.wiki}.tsv"), encoding="utf-8") as fh:
        for line in fh:
            q, text = line.rstrip("\n").split("\t", 1)
            opening[q] = text
    with open(os.path.join(OUT, "qs_en_numbered", "rejected.tsv"), encoding="utf-8") as fh:
        wrong = {line.split("\t", 1)[0] for line in fh if line.startswith("Q")}
    groups = compile_groups()
    pick, notes, found = {}, [], collections.Counter()
    for q, t in title.items():
        if q in done or q in wrong or AROUND.search(t):
            continue
        s = opening.get(q, "")[:400]
        family = None
        for g in groups:
            name, _, _, rx, word, no = g
            if not rx.search(t):
                continue
            family = family or name
            if no and (no.search(t) or (word and no.search(s))):
                continue
            if word and not word.search(s):
                continue
            pick[q] = g
            break
        if family and q not in pick:
            found[family] += 1
            notes.append((q, "opening does not state it", family, t, s[:150]))
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=args.min_age_days)).strftime("%Y%m%d%H%M%S")
    first = first_revision(list(pick))
    have = classified(sorted(pick))
    lines, count = [], collections.Counter()
    for q in sorted(pick, key=lambda x: int(x[1:])):
        name, prop, cls = pick[q][:3]
        s = opening.get(q, "")
        if cls in KIND_CLASSES and (KIND.match(s) or TYPE_OF.search(s[:200])):
            prop = "P279"
        if first.get(q, "9") > cutoff:
            notes.append((q, "too new", name, title[q], s[:150]))
        elif q in have:
            notes.append((q, "has a class by now", name, title[q], s[:150]))
        elif LOOSE.search(s[:300]):
            notes.append((q, "may refer to / set index", name, title[q], s[:150]))
        else:
            lines.append(f"{q}\t{prop}\t{cls}\n")
            count[name] += 1
    with open(this, "w", encoding="utf-8", newline="\n") as fh:
        fh.writelines(lines)
    with open(os.path.join(OUT, "groups_review.tsv"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write("qid\twhy\tgroup\ttitle\topening\n")
        fh.writelines("\t".join(n) + "\n" for n in sorted(notes, key=lambda n: (n[2], n[1])))
    print(f"{len(lines)} QS lines -> {os.path.basename(this)}; {len(notes)} in review")
    classes = sorted({g[2] for g in GROUPS})
    label = {}
    for r in qlever("PREFIX wd: <http://www.wikidata.org/entity/> PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#> "
                    f"SELECT ?c ?l WHERE {{ VALUES ?c {{ {' '.join('wd:' + c for c in classes)} }} ?c rdfs:label ?l "
                    'FILTER(LANG(?l) = "en") }'):
        label[r["c"]] = r["l"]
    for name, _, cls, *_ in GROUPS:
        print(f"{count[name]}\t{found[name]}\t{name}\t{cls}\t{label.get(cls, '?')}")


if __name__ == "__main__":
    main()
