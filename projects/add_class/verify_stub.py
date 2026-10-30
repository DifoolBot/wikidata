"""Check the stub-category statements (output/qs_<wiki>/*.txt from make_qs.py) against the article's first sentence.

  python verify_stub.py [--wiki en]
  in:  output/qs_<wiki>/*.txt, output/items_<wiki>.tsv, output/opening_<wiki>.tsv
  out: output/qs_<wiki>_checked/confirmed.txt  one QS file (QS takes one upload) with the confirmed statements
       output/qs_<wiki>_checked/review.tsv     the rest: qid, prop, class, label, reason, head, title, sentence

The head noun of the first 'is a/an ...' phrase must name the class: its label's or an alias's last word, a
synonym from SAME_KIND, or an item with that label that is a P279+ subclass of the class ('stadium' -> sports
venue). A label used as a modifier does not count ('a common database operation' is no database).
'X is a type of sword' confirms a P279 to sword. The sentence must be about the title ('The Clash on film' opens
with the band). Reasons in review.tsv: no opening, other subject, no head, kind article (P31 on 'a type of'),
mismatch (the sentence names another kind: 'Tidal stripping occurs when', 'Lost 52 Project is a private
organization').
"""
import argparse
import collections
import glob
import json
import os
import re
import sys

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from make_qs import TYPE_OR_LIST, norm_word  # noqa: E402
from stub_table import QBATCH, qlever  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "output")

COPULA = re.compile(r"\b(?:(?:is|was) (?:one of (?:the )?|an? |the )|(?:are|were) (?:one of (?:the )?|an? |the )?)",
                    re.I)  # 'Weavers' windows are large horizontal windows'
STOP = re.compile(r"\b(?:in|of|on|at|from|for|by|with|that|which|who|whose|where|located|situated|based|founded|"
                  r"built|near|and|or|to|between|known|named|called|designed|developed|produced|written|directed|"
                  r"released|published|made|owned|operated|run|used|since|during|serving|consisting|containing|"
                  r"featuring|starring|within|among|inside|under|across|outside|along|around|over|covering|"
                  r"throughout|representing|operating|offering|providing|connecting|linking|depicting|including|"
                  r"comprising|spanning|flowing|organizing|organising|promoting)\b|"
                  r"(?<![\w-])(?<!ly )(?:held|seen|found|set|sold|kept|led|grown|worn|taught|spoken|given|taken|"
                  r"shown|drawn|done|bought|brought)\b|"  # not 'horse-drawn', 'member-led', 'privately held'
                  r"\b\w+ed (?:in|to|by|on|at|for|from|as|with|between|under)\b|"
                  r"[,.](?=\s|$)|[;:()\[\]–—\"]", re.I)  # '33,800-acre ranch'; 'dedicated to', 'formed in'
KIND = {"type", "kind", "form", "variety", "style", "class", "family", "genre", "category", "breed", "cultivar"}
SAME_KIND = {  # class head word -> other head words that mean the same kind of thing (filled from review.tsv)
}


ABBREV = re.compile(r"(?:\b(?:Inc|Ltd|Co|Corp|Bros|St|Ste|Mt|Ft|Mr|Mrs|Ms|Dr|Prof|Jr|Sr|Rev|Gen|Col|Capt|Lt|"
                    r"Sgt|No|Nos|Vol|vs|ca|approx|U\.S|U\.K|D\.C|a\.k\.a|aka|e\.g|i\.e)|\b[A-Z])$")  # 'J. R. R.'


def first_sentence(text):
    """Up to the first sentence end, not after an abbreviation, inside brackets ('SALT (a.k.a. FindSALT) is') or
    before a '(' ('Hey Chicken! (叫了个鸡), also known as', 'Inc. (NENI) is')."""
    for m in re.finditer(r"[.!?](?:\s+[A-Z\"]|\s*$)", text):
        before = text[:m.start()]
        if before.count("(") > before.count(")"):
            continue
        if not (text[m.start()] == "." and ABBREV.search(before)):
            return text[:m.start() + 1]
    return text


def noun_phrase(phrase):
    """The words up to the first stop, the last one (the head) singular: 'historic railway stations in' ->
    'historic railway station'."""
    words = re.findall(r"[A-Za-z][A-Za-z'-]*", STOP.split(phrase, 1)[0])
    return " ".join([w.lower() for w in words[:-1]] + [norm_word(words[-1])]) if words else ""


MEASURE = re.compile(r"\b\d[\d.,]*[- ]?(?:mi|km|m|ft|foot|feet|miles?|kilomet(?:re|er)s?|met(?:re|er)s?|acres?|"
                     r"hectares?|ha|inch(?:es)?|in|cm)\b(?: (?:long|tall|high|wide|deep))?", re.I)


def clean(rest):
    """Drop what hides the head: brackets ('river (brook)'), measurements ('48.88 mi (78.66 km) long tributary',
    '55-foot (17 m) sculpture') and the comma after a leading adjective ('a minor, 1.2-kilometre long river')."""
    rest = re.sub(r"\s*\([^()]*\)", "", rest)
    rest = re.sub(r"\s{2,}", " ", MEASURE.sub("", rest)).lstrip()
    # not 'a room, often in the attic', 'a missile, the payload of which'
    return re.sub(r"^(\w+), (?=\d|(?!(?:the|a|an|which|who|that|its|his|her|their|also|often|now|once|then|"
                  r"sometimes|usually|mainly|mostly|generally|typically)\b)[a-z]+(?<!ly)\b)", r"\1 ", rest)


def analyse(title, sentence):
    """(head, kind, noun phrase) of the first 'is a ...' phrase, or None when there is none. kind: '' for one
    thing, 'kind' for 'a type of sword', 'plural' for 'HCS were schools established ...' (a class, not one school;
    Q12485836, user 2026-10-29)."""
    m = COPULA.search(sentence[:300])
    if not m:
        return None
    rest = clean(sentence[m.end():])
    np = noun_phrase(rest)
    if np.split(" ")[-1] in KIND:  # 'a type of sword' -> sword
        k = re.search(r"\bof (?:an? |the )?", rest)
        if k and k.start() < 40:
            np = noun_phrase(rest[k.end():])
            return np.split(" ")[-1], "kind", np
    head_part = STOP.split(rest, 1)[0]
    words = re.findall(r"[A-Za-z][A-Za-z'-]*", head_part)
    plural = (re.match(r"(?:are|were) (?!an? |one of)", m.group(0) + rest[:6], re.I)  # 'Kharchi are the Gods of'
              and words and re.search(r"[^s]s$", words[-1]))
    if plural:
        return np.split(" ")[-1], "plural", np
    # 'a second floor bedroom in the White House': one place, not a kind of room (President's Bedroom Q7241121)
    located = re.match(r"\s*(?:located |situated )?(?:in|at|on) (?:the )?[A-Z]", rest[len(head_part):])
    return np.split(" ")[-1], "located" if located else "", np


def about_title(title, sentence):
    """The subject (before 'is a') shares a word with the title ('The Diocese of Tanga' / 'Anglican Diocese of
    Tanga'); 'In nuclear weaponry, insertion time is' passes too, its head 'interval' then decides."""
    m = COPULA.search(sentence[:300])
    subject = sentence[:m.start()] if m else sentence[:80]
    words = lambda t: {w for w in re.findall(r"\w+", t.casefold()) if len(w) > 3}  # noqa: E731
    return bool(words(re.sub(r"\s*\([^)]*\)$", "", title)) & words(subject))


class Cache:
    """SPARQL answers kept in a JSON file, so a rerun after a 429 stall only asks what is missing:
    main[head] = [up to SENSES items], sub["item|class"] = True/False. Failed lookups are not stored."""

    def __init__(self, path):
        self.path = path
        try:
            with open(path, encoding="utf-8") as fh:
                d = json.load(fh)
        except FileNotFoundError:
            d = {}
        if d.get("version") != 2:  # v1 kept one item per head and head|class keys
            d = {}
        self.main, self.sub = d.get("main", {}), d.get("sub", {})

    def save(self):
        with open(self.path + ".tmp", "w", encoding="utf-8") as fh:
            json.dump({"version": 2, "main": self.main, "sub": self.sub}, fh)
        os.replace(self.path + ".tmp", self.path)


SENSES = 3


def main_items(heads, cache):
    """head word -> the SENSES items with that en label and the most sitelinks: the common senses, not an obscure
    item whose P279 chain leads anywhere. One was too few: 'group' is first the mathematical group, 'club' the
    weapon, 'foundation' the building (2026-10-30)."""
    todo = sorted(h for h in heads if h not in cache.main)
    print(f"   main items: {len(heads) - len(todo)} cached, {len(todo)} to look up", flush=True)
    for i in range(0, len(todo), 100):
        best = collections.defaultdict(list)
        vals = " ".join(f'"{h}"@en' for h in todo[i:i + 100])
        q = f"""PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#> PREFIX wikibase: <http://wikiba.se/ontology#>
SELECT ?name ?h ?n WHERE {{ VALUES ?name {{ {vals} }} ?h rdfs:label ?name ; wikibase:sitelinks ?n }}"""
        for r in qlever(q):
            best[r["name"]].append((int(r["n"]), r["h"]))
        for h in todo[i:i + 100]:
            cache.main[h] = [x for _, x in sorted(best[h], reverse=True)[:SENSES]]
        cache.save()
        print(f"   main items {min(i + 100, len(todo))}/{len(todo)}", flush=True)
    return {h: cache.main[h] for h in heads if cache.main.get(h)}


def key(x, c):
    return f"{x}|{c}"


def p279(pairs, cache):
    """Fill cache.sub[x|c] for item pairs: is x a P279+ subclass of c? Batches of 50 (300 -> QLever 500)."""
    todo = sorted(p for p in pairs if key(*p) not in cache.sub)
    print(f"   subclass check: {len(todo)} (item, class) pairs to look up", flush=True)

    def check(part):
        vals = " ".join(f"(wd:{x} wd:{c})" for x, c in part)
        q = f"""PREFIX wd: <http://www.wikidata.org/entity/> PREFIX wdt: <http://www.wikidata.org/prop/direct/>
SELECT DISTINCT ?h ?c WHERE {{ VALUES (?h ?c) {{ {vals} }} ?h wdt:P279+ ?c }}"""
        try:
            found = {(r["h"], r["c"]) for r in qlever(q)}
            for x, c in part:
                cache.sub[key(x, c)] = (x, c) in found
            cache.save()
        except requests.HTTPError:  # a 500 on a heavy batch: halve it; a single pair that fails stays a mismatch
            if len(part) > 1:
                check(part[:len(part) // 2])
                check(part[len(part) // 2:])
            else:
                print(f"   SPARQL error on {part[0]}, skipped", flush=True)

    for i in range(0, len(todo), 50):
        check(todo[i:i + 50])
        print(f"   subclass check {min(i + 50, len(todo))}/{len(todo)}", flush=True)


def subclass_heads(pairs, cache):
    """The (head, class) pairs where one of the main items labelled head (en, singular) is a subclass of class
    (P279+), e.g. stadium -> sports venue, novel -> literary work; ecclesiastical province -> Anglican diocese is not."""
    pairs = sorted(p for p in pairs if re.fullmatch(r"[a-z][a-z' -]*", p[0]))  # 'stadium', 'card game'
    item = main_items({h for h, _ in pairs}, cache)
    p279({(x, c) for h, c in pairs for x in item.get(h, ())}, cache)
    return {(h, c) for h, c in pairs if any(x == c or cache.sub.get(key(x, c)) for x in item.get(h, ()))}


def class_names(classes):
    """class QID -> (label, set of label/alias strings, lowercased), en with mul fallback."""
    names, label = collections.defaultdict(set), {}
    for i in range(0, len(classes), QBATCH):
        vals = " ".join("wd:" + q for q in classes[i:i + QBATCH])
        q = f"""PREFIX wd: <http://www.wikidata.org/entity/> PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
SELECT ?c ?kind ?name (LANG(?name) AS ?lang) WHERE {{ VALUES ?c {{ {vals} }}
  {{ ?c rdfs:label ?name BIND("label" AS ?kind) }} UNION {{ ?c skos:altLabel ?name BIND("alias" AS ?kind) }}
  FILTER(LANG(?name) IN ("en", "mul")) }}"""
        for r in qlever(q):
            names[r["c"]].add(r["name"].lower())
            if r["kind"] == "label" and (r["lang"] == "en" or r["c"] not in label):
                label[r["c"]] = r["name"]
    return {c: (label.get(c, c), names[c]) for c in classes}


def confirms(head, phrase, names):
    heads = {norm_word(n.split()[-1]) for n in names if n.split()}
    # only the head counts: 'a common database operation' is no database (Q818943, user 2026-10-29)
    return head in heads or any(head in SAME_KIND.get(h, ()) for h in heads)


ONE_FIND = re.compile(r"\b(?:unearthed|excavated|discovered|recovered|year[- ]old)\b", re.I)  # not 'found in'
METACLASS = re.compile(r"\b(?:type|class|kind|rank|occupation|profession|position|title|genre|style|breed|variety|"
                       r"form|model|series|family)\b", re.I)  # 'A bago is a traditional boat' -> P31 ship type is right


def compounds(head, phrase, names):
    """The modifier+head compounds to test when the head only matches the last word of a longer class name with
    another modifier: 'a 1976 war video game' on a board game row -> 'video game', 'war video game' (Crete 1941,
    user 2026-10-30). [] when a one-word name or the full name matches ('a popular board game')."""
    words = phrase.split()
    multi = [n.split() for n in names if len(n.split()) > 1 and norm_word(n.split()[-1]) == head]
    if any(len(n.split()) == 1 and norm_word(n) == head for n in names) or not multi:
        return []
    if any(words[-len(n):-1] == n[:-1] for n in multi if len(words) >= len(n)):
        return []
    return [" ".join(words[-k:]) for k in (2, 3) if len(words) >= k]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wiki", default="en")
    args = ap.parse_args()
    rows = []
    for path in sorted(glob.glob(os.path.join(OUT, f"qs_{args.wiki}", "P*.txt"))):
        with open(path, encoding="utf-8") as fh:
            rows += [line.rstrip("\n").split("\t")[:3] for line in fh if line.strip()]
    with open(os.path.join(OUT, f"items_{args.wiki}.tsv"), encoding="utf-8") as fh:
        title = dict(line.rstrip("\n").split("\t", 1) for line in fh if "\t" in line)
    with open(os.path.join(OUT, f"opening_{args.wiki}.tsv"), encoding="utf-8") as fh:
        opening = dict(line.rstrip("\n").split("\t", 1) for line in fh)
    info = class_names(sorted({c for _, _, c in rows}))
    print(f"{len(rows)} statements, {len(info)} classes")
    out_dir = os.path.join(OUT, f"qs_{args.wiki}_checked")
    os.makedirs(out_dir, exist_ok=True)
    reasons, confirmed, review, results, compound = collections.Counter(), [], [], [], {}
    for q, prop, cls in rows:
        label, names = info[cls]
        s = first_sentence(opening.get(q, ""))
        a = analyse(title.get(q, ""), s) if s else None
        if not s:
            reason, head = "no opening", ""
        elif not about_title(title.get(q, ""), s):
            reason, head = "other subject", a[0] if a else ""
        elif not a or not a[0]:
            reason, head = "no head", ""
        else:
            head, kind, phrase = a
            if TYPE_OR_LIST.search(title.get(q, "").replace(" ", "_")):
                reason = "type/list title"  # 'Classes of metals' is a classification, no metal (Q5128053)
            elif kind in ("kind", "plural") and prop == "P31":
                reason = "kind article" if kind == "kind" else "plural (class?)"
            elif kind == "located" and prop == "P279":
                reason = "P279 on one place?"
            elif prop == "P279" and ONE_FIND.search(s):
                reason = "one object (P31?)"  # 'a 280,000 year old flint tool, discovered in 1926' (Q21042177)
            elif (prop == "P31" and re.match(r"(?:An?|One) ", s) and not METACLASS.search(label)
                  and not re.match(r"(?:an?|one) ", title.get(q, "").casefold())):
                reason = "generic subject (P279?)"  # 'A One-Act Play Festival is a festival of' (Q7092277)
            elif confirms(head, phrase, names):
                reason = "confirmed"
                compound[q, cls] = compounds(head, phrase, names)
            else:
                reason = "mismatch"
        results.append((q, prop, cls, label, reason, head, s))
    cache = Cache(os.path.join(out_dir, "qlever_cache.json"))
    narrower = subclass_heads({(h, c) for _, _, c, _, r, h, _ in results if r == "mismatch" and h}, cache)
    # a compound that is an item of its own must be the class or under it: 'card game' is no board game
    pairs = {(x, c) for (_, c), xs in compound.items() for x in xs}
    known = main_items({x for x, _ in pairs}, cache)
    fits = subclass_heads({(x, c) for x, c in pairs if x in known}, cache)
    # ... or broader than the class: 'a musical instrument' on a string instrument row says less, not otherwise
    p279({(c, i) for x, c in pairs for i in known.get(x, ())}, cache)
    broader = {(x, c) for x, c in pairs if any(cache.sub.get(key(c, i)) for i in known.get(x, ()))}
    for q, prop, cls, label, reason, head, s in results:
        if reason == "mismatch" and (head, cls) in narrower:
            reason = "confirmed"  # the sentence names a subclass: 'stadium' on a sports venue row
        elif reason == "confirmed":
            other = [x for x in compound.get((q, cls), ()) if x in known]
            if other and not any((x, cls) in fits or (x, cls) in broader for x in other):
                reason, head = "modifier names another kind", other[0]
        reasons[reason] += 1
        if reason == "confirmed":
            confirmed.append(f"{q}\t{prop}\t{cls}\n")
        else:
            review.append(f"{q}\t{prop}\t{cls}\t{label}\t{reason}\t{head}\t{title.get(q, '')}\t{s[:200]}\n")
    with open(os.path.join(out_dir, "confirmed.txt"), "w", encoding="utf-8", newline="\n") as fh:
        fh.writelines(confirmed)
    with open(os.path.join(out_dir, "review.tsv"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write("qid\tprop\tclass\tlabel\treason\thead\ttitle\tsentence\n")
        fh.writelines(sorted(review, key=lambda r: (r.split("\t")[4], r.split("\t")[3], r.split("\t")[5])))
    for r, n in reasons.most_common():
        print(f"   {r:14} {n}")
    print(f"{len(confirmed)} confirmed -> {out_dir}")


if __name__ == "__main__":
    main()
