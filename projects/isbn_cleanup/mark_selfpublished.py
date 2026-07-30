"""Mark self-published books: replace a self-pub-platform publisher (P123) correctly.

Someone entering a KDP / Amazon self-published book often puts the *publisher* as
Amazon's self-publishing operation -- **Amazon (Q3884)** or **Kindle Direct
Publishing (Q15823534)** -- but neither is the publisher-of-record. This bot removes
that wrong value and sets the correct self-publishing publisher. **Only one case is
auto-edited** (the rest go to review): a **979-8 ISBN present in Wikidata** is a free
KDP ISBN, which Bowker registers as the imprint **"Independently published"
(Q135060696)** -- that item is literally the publisher-of-record, so **P123 =
Q135060696** (no author needed; a public-domain reprinter who used KDP is still the
self-publisher).

The **no-ISBN case is deliberately NOT auto-edited.** In theory a Kindle / eBook with
no registered imprint is self-published *by the author* (P123 = author, qualified
**object of statement has role (P3831) = self-publishing (Q1568650)** -- the form on
Q113134471). But "no ISBN in Wikidata" isn't proof there is no ISBN: a 979-8 free-KDP
ISBN often sits on Amazon or a paperback sibling while the WD item has neither the
ISBN nor the ASIN (Q136323745: Amazon shows 979-8-3083-0028-1, shared by its Kindle
and paperback, but WD has nothing) -- and then the publisher is Independently
published, not the author. We can't tell the two apart from WD data, so no-ISBN items
go to review for a manual Amazon check.

Guards that send items to review:
  * a **non-979-8 ISBN** (outside the KDP block) -> may be CreateSpace / an author's
    own ISBN / a real publisher (undecidable from WD; manual check);
  * a **work/edition (FRBR) split** (P747) -> publisher belongs on the edition;
  * a **real (non-platform) publisher already present** -> it has a real publisher;
  * a **referenced** platform publisher, or **sitelinks** (notable);
  * **no ISBN in WD** -> possible hidden 979-8 (see above).

Only a self-pub-platform P123 (see SELFPUB_PLATFORMS) on a bibliographic P31 is
considered; non-books with such a publisher (Kindle Store, the Kindle app, AWS
blogs) are filtered out by the discovery query. Broader self-pub signals (979-8
ISBN, ASIN, no publisher) are a separate future pass.

Dry-run by default. A dry run writes a fresh preview of every item's disposition
(EDIT / REVIEW / SKIP) to output/selfpub_dryrun.txt, rewritten each run and never
touched by --save. Candidates come back in a deterministic order (ORDER BY ?item), so
a `--limit N` dry run and a following `--save` cover the same slice. Pass --save to
actually edit (requires pywikibot auth).

    python projects/isbn_cleanup/mark_selfpublished.py                # dry run, whole list
    python projects/isbn_cleanup/mark_selfpublished.py --limit 5      # dry run, 5 items -> preview file
    python projects/isbn_cleanup/mark_selfpublished.py --qid Q123     # one item, even if done
    python projects/isbn_cleanup/mark_selfpublished.py --recheck-review  # re-examine reviewed items
    python projects/isbn_cleanup/mark_selfpublished.py --save         # really edit
"""

import argparse
import hashlib
from datetime import date
from pathlib import Path

import pywikibot
import requests
from stdnum import isbn as stdnum_isbn

import shared_lib.change_wikidata as cwd
import shared_lib.constants as wd

QLEVER_URL = "https://qlever.dev/api/wikidata"
USER_AGENT = "DifoolBot/1.0 (https://www.wikidata.org/wiki/User:DifoolBot)"

# P31 types for which a self-pub-platform publisher means a self-published book.
BIBLIOGRAPHIC_TYPES = [
    "Q571",       # book
    "Q7725634",   # literary work
    "Q47461344",  # written work
    "Q3331189",   # version, edition or translation
    "Q193495",    # monograph
    "Q732577",    # publication
    "Q87167",     # manuscript
]

# P123 values that name Amazon's self-publishing operation rather than a real
# publisher-of-record. Any of these on a bibliographic item is the self-pub tell we
# replace with the correct model (Independently published, or author + P3831).
SELFPUB_PLATFORMS = [
    wd.QID_AMAZON,                   # Amazon (Q3884)
    wd.QID_KINDLE_DIRECT_PUBLISHING, # Kindle Direct Publishing (Q15823534)
]

HERE = Path(__file__).parent
OUTPUT_DIR = HERE / "output"
DONE_FILE = OUTPUT_DIR / "selfpub_done.txt"
FAILED_FILE = OUTPUT_DIR / "selfpub_failed.txt"
REVIEW_FILE = OUTPUT_DIR / "selfpub_review.txt"
# Preview of a dry run, rewritten fresh each run (never touched during --save).
REPORT_FILE = OUTPUT_DIR / "selfpub_dryrun.txt"

site = pywikibot.Site("wikidata", "wikidata")
repo = site.data_repository()


def fetch_candidates() -> list[str]:
    """QIDs of bibliographic items whose publisher (P123) is a self-pub platform
    (Amazon or Kindle Direct Publishing)."""
    types = " ".join(f"wd:{t}" for t in BIBLIOGRAPHIC_TYPES)
    pubs = " ".join(f"wd:{q}" for q in SELFPUB_PLATFORMS)
    query = f"""PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX wd: <http://www.wikidata.org/entity/>
SELECT DISTINCT ?item WHERE {{
  VALUES ?pub {{ {pubs} }}
  ?item wdt:{wd.PID_PUBLISHER} ?pub .
  ?item wdt:P31 ?type .
  VALUES ?type {{ {types} }}
}}
ORDER BY ?item"""
    r = requests.post(QLEVER_URL, data={"query": query},
                      headers={"User-Agent": USER_AGENT, "Accept": "text/tab-separated-values"},
                      timeout=180)
    r.raise_for_status()
    qids = []
    for line in r.text.splitlines()[1:]:
        qid = line.strip().rsplit("/", 1)[-1].rstrip(">")
        if qid.startswith("Q"):
            qids.append(qid)
    return qids


def author_owns_publisher(author_qid: str) -> str | None:
    """If the author founded or owns a publisher (modeled in Wikidata), return
    'QID (label)'. Per KDP's own docs, an author can either take a *free* KDP ISBN
    (Bowker registers it as the imprint "Independently published") OR buy their *own*
    ISBN under a registered imprint (Amazon then shows that imprint). Both land in the
    979-8 block, so a 979-8 ISBN alone can't tell them apart -- but an author who runs
    their own press likely used the latter, making the publisher that press, not
    Independently published (found via Ys Goldt Q137692457 / Nachtljocht Press
    Q139787571). Catches only imprints that exist as WD items; a brand-new own-imprint
    with no item still slips through (keep the manual spot-check)."""
    query = f"""PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT DISTINCT ?p ?pl WHERE {{
  {{ ?p wdt:P112 wd:{author_qid} }} UNION {{ ?p wdt:P127 wd:{author_qid} }}
  UNION {{ wd:{author_qid} wdt:P1830 ?p }}
  ?p wdt:P31/wdt:P279* wd:{wd.QID_PUBLISHING_HOUSE} .
  OPTIONAL {{ ?p rdfs:label ?pl FILTER(LANG(?pl)="en") }}
}}"""
    r = requests.post(QLEVER_URL, data={"query": query},
                      headers={"User-Agent": USER_AGENT, "Accept": "text/tab-separated-values"},
                      timeout=60)
    r.raise_for_status()
    for line in r.text.splitlines()[1:]:
        parts = line.split("\t")
        if not parts or not parts[0].strip():
            continue
        pid = parts[0].strip().rsplit("/", 1)[-1].rstrip(">")
        # QLever returns RDF literals as "Label"@en -- take the quoted content.
        raw = parts[1].strip() if len(parts) > 1 else ""
        label = raw[1:raw.rindex('"')] if raw.startswith('"') and '"' in raw[1:] else raw
        return f"{pid} ({label})" if label else pid
    return None


def live(claims):
    """Non-deprecated claims. Per WD convention (see User:IagoQnsi/deprecation_reasons)
    deprecated statements are treated as invisible on read; the only place we consult
    them is the add-guard, which refuses to (re-)add a value that already exists as a
    deprecated statement (e.g. a Kindle edition's paperback ISBN, deprecated as
    "refers to different subject")."""
    return [c for c in claims if c.rank != "deprecated"]


def author_died_before_publication(page, author_qid: str) -> str | None:
    """If the author's death year precedes the item's (latest) publication year,
    they didn't self-publish it -- it's a posthumous reprint, so the self-publisher
    is someone else (a public-domain repackager), not the author."""
    pub_years = [t.year for c in live(page.claims.get("P577", [])) if (t := c.getTarget())]
    if not pub_years:
        return None
    author = pywikibot.ItemPage(repo, author_qid)
    author.get()
    death_years = [t.year for c in live(author.claims.get("P570", [])) if (t := c.getTarget())]
    if death_years and min(death_years) < max(pub_years):
        return f"author {author_qid} died {min(death_years)} < publication {max(pub_years)} -- reprint"
    return None


def linked_editions(page) -> list:
    """Edition/translation items linked from this (work) item via P747.

    In the work/edition (FRBR) split -- e.g. Iamcarbon's written-work + version pairs
    -- the ISBN, format and true publisher belong on the *edition*, while a stray
    platform publisher may sit on the *work*. These are fetched so their ISBNs are
    readable across the link; the list is empty for the common single-item case
    (no P747), so no extra network fetch happens there."""
    out = []
    for c in live(page.claims.get(wd.PID_HAS_EDITION_OR_TRANSLATION, [])):
        t = c.getTarget()
        if t:
            t.get()
            out.append(t)
    return out


def classify_isbns(page, editions=()) -> tuple[bool, list[str]]:
    """Split the valid ISBNs of the item -- and its linked editions -- into buckets.

    Returns (has_979_8, non_kdp). ``has_979_8`` is True when a valid 979-8 ISBN is
    present -- the free-KDP block, which Bowker registers as the imprint
    "Independently published", so the publisher-of-record is literally that item.
    ``non_kdp`` lists valid ISBNs outside 979-8: a signal it may be a real publisher
    edition (e.g. a work with country-registered ISBNs) where marking it
    self-published would be wrong. 979 has no ISBN-10, so P957 is always 978-*.

    ``editions`` are the P747-linked edition items. In a work/edition split the ISBN
    lives on the edition, not the work being processed, so we must read across the
    link -- otherwise the non-979-8 guard goes blind (e.g. Q111585457's work carries
    no ISBN while its paperback edition carries the 978 one)."""
    has_979_8 = False
    non_kdp = []
    for claims in [page.claims, *(e.claims for e in editions)]:
        for pid in (wd.PID_ISBN_13, wd.PID_ISBN_10):
            for c in live(claims.get(pid, [])):
                v = c.getTarget()
                if isinstance(v, str) and stdnum_isbn.is_valid(v):
                    comp = stdnum_isbn.compact(v)
                    if comp.startswith("9798"):
                        has_979_8 = True
                    else:
                        non_kdp.append(v)
    return has_979_8, non_kdp


def process_item(qid: str, edit_group: str, test: bool) -> tuple[bool, str | None, str | None]:
    """Replace a self-pub-platform publisher (Amazon / KDP) with the correct model.

    Only one case is auto-edited: a **979-8 ISBN present in Wikidata** is a free KDP
    ISBN, which Bowker registers as the imprint "Independently published" (Q135060696)
    -- so P123 = that item. Everything else routes to review. In particular the
    **no-ISBN case is NOT auto-edited**: "no ISBN in WD" isn't proof there is no ISBN
    (a 979-8 free-KDP ISBN often sits on Amazon / a paperback sibling but is missing
    from the WD item), so author + P3831 self-publishing can't be told from a hidden
    979-8 and needs a manual Amazon check.

    Returns (changed, review_reason, action). ``review_reason`` is set (nothing
    edited) when a guard trips: a non-979-8 ISBN (may be a real edition, including one
    on a linked edition item), a **work/edition split** (publisher belongs on the
    edition), a real (non-platform) publisher already present, or a **no-ISBN** item
    (possible hidden 979-8). ``action`` is a short label of the edit made/attempted, or
    None when a guard tripped or the item isn't a candidate; it feeds the dry-run
    report so a preview shows *what* would change.
    """
    item = pywikibot.ItemPage(repo, qid)
    page = cwd.WikiDataPage(item, test=test)
    page.edit_group = edit_group

    # A book notable enough for a Wikipedia article isn't an anonymous self-pub;
    # a self-pub-platform publisher there is a data artifact, not a self-pub tell.
    if page.item.sitelinks:
        return False, f"has {len(page.item.sitelinks)} sitelink(s) -- notable, review", None

    # Read ISBNs across the P747 link too: in a work/edition split the ISBN sits on
    # the edition, so a per-item check would miss it and wrongly auto-edit the work.
    editions = linked_editions(page)
    has_979_8, real_isbns = classify_isbns(page, editions)
    if real_isbns:
        # A non-979-8 ISBN is not a free-KDP-ISBN, so we can't apply the
        # Independently-published model -- but it is NOT necessarily a real
        # publisher: it may be CreateSpace (Q15803989, whose many 978-1-4xxx/5xxx
        # registrant blocks aren't enumerable from WD -- P3035 records only one),
        # an author's own bought ISBN, or a genuine publisher. Undecidable from WD
        # data; needs the manual Amazon / Google-Books publisher check.
        return False, f"non-979-8 ISBN(s) -- check publisher (CreateSpace/self-pub vs real): {', '.join(real_isbns)}", None

    publishers = live(page.claims.get(wd.PID_PUBLISHER, []))
    platform = [c for c in publishers if c.getTarget() and c.getTarget().getID() in SELFPUB_PLATFORMS]
    other = [c for c in publishers if c.getTarget() and c.getTarget().getID() not in SELFPUB_PLATFORMS]
    if not platform:
        return False, None, None
    if other:
        return False, f"also has a real publisher ({[c.getTarget().getID() for c in other]})", None
    # A referenced platform publisher is deliberate (someone sourced it) -- don't
    # silently override; a careless self-pub entry is unreferenced.
    if any(c.sources for c in platform):
        return False, "P123 self-pub platform is referenced (deliberate) -- review", None

    # Work/edition (FRBR) split: the platform publisher sits on this work, but the
    # publisher belongs on the edition (which carries the ISBN/format). Don't
    # auto-edit the work -- route to review for manual placement on the edition.
    # (A non-979-8 edition ISBN would already have exited above; what remains here
    # is a split with only 979-8 / no-ISBN editions.)
    if editions:
        eds = "; ".join(e.getID() for e in editions)
        return False, f"work/edition split: move publisher to edition(s) {eds}", None

    removed = ", ".join(sorted({c.getTarget().getID() for c in platform}))

    if has_979_8:
        # 979-8 is the current ISBN block, dominated by -- but not exclusive to -- the
        # free-KDP pool that Bowker registers as "Independently published". An author
        # who bought their *own* ISBN under a registered imprint also gets 979-8, and
        # Amazon then shows that imprint. If an author here runs their own press, the
        # book is likely that press's, not the free-KDP pool -> review, not auto-edit.
        for a in [c.getTarget().getID() for c in live(page.claims.get("P50", [])) if c.getTarget()]:
            press = author_owns_publisher(a)
            if press:
                return False, (f"979-8 ISBN but author {a} owns publisher {press} -- "
                               "may be own imprint / a republication (older free-KDP edition "
                               "+ newer own-imprint edition); check editions & ISBNs"), None

        # Add-guard: don't (re-)add Independently published if it already exists as a
        # deprecated statement -- it was deprecated deliberately, and re-adding would
        # undo that. Note it for review instead. (This reads deprecated ranks on
        # purpose -- the one place we do.)
        if any(c.rank == "deprecated" and c.getTarget()
               and c.getTarget().getID() == wd.QID_INDEPENDENTLY_PUBLISHED
               for c in page.claims.get(wd.PID_PUBLISHER, [])):
            return False, ("P123 = Independently published exists as a deprecated "
                           "statement -- not re-adding"), None

        # Free-KDP paperback: the Bowker imprint of record is "Independently
        # published" regardless of who the author is (a public-domain reprinter
        # who used KDP is still the self-publisher here), so no author is needed.
        print(f"  P123: {removed} -> Independently published {wd.QID_INDEPENDENTLY_PUBLISHED} (979-8 KDP ISBN)",
              flush=True)
        for c in platform:
            page.remove_property(wd.PID_PUBLISHER, c)
        new = pywikibot.Claim(repo, wd.PID_PUBLISHER)
        new.setTarget(pywikibot.ItemPage(repo, wd.QID_INDEPENDENTLY_PUBLISHED))
        page.add_claim(wd.PID_PUBLISHER, new)
        page.summary = "mark self-published: publisher = Independently published (979-8 KDP ISBN)"
        return page.apply(), None, f"P123 = Independently published ({wd.QID_INDEPENDENTLY_PUBLISHED})"

    # No 979-8 ISBN *in Wikidata* -- but that is NOT proof the book has no ISBN. These
    # self-pub items are under-catalogued, and a 979-8 free-KDP ISBN (which would make
    # the publisher Independently published, not the author) often sits on Amazon or a
    # paperback sibling while the WD item has neither the ISBN nor the ASIN (found on
    # Q136323745: Amazon 979-8-3083-0028-1 shared by its Kindle+paperback, absent from
    # WD). author+P3831 (a true no-ISBN Kindle) can't be told from a missing 979-8 from
    # WD data alone, so this is a manual-check case, not an auto-edit -> route to review.
    # The author / dead-author context is appended only to inform the reviewer.
    reason = "no ISBN in WD -- check Amazon for a 979-8 ISBN (-> Independently published) vs author+P3831"
    authors = [c.getTarget().getID() for c in page.claims.get("P50", []) if c.getTarget()]
    if len(authors) != 1:
        reason += f"; no single author (P50={authors or 'none'})"
    elif (reprint := author_died_before_publication(page, authors[0])):
        reason += f"; {reprint}"
    return False, reason, None


def load_processed(include_review: bool = True) -> set:
    """QIDs already handled, to skip on re-runs. Reviewed items count as processed by
    default (so they stop re-appearing and review.txt stops accumulating duplicates);
    pass include_review=False (--recheck-review) to re-examine them, e.g. after a
    manual fix."""
    processed = set()
    paths = [DONE_FILE, FAILED_FILE] + ([REVIEW_FILE] if include_review else [])
    for path in paths:
        if path.exists():
            with open(path, encoding="utf-8") as f:
                processed |= {line.split("\t", 1)[0].strip() for line in f if line.strip()}
    return processed


def append_line(path: Path, line: str) -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def daily_editgroup(tag: str) -> str:
    """Stable per-day editgroups batch id (tag+date), so repeated runs in a day group
    into one reviewable/undoable batch instead of a new random id per run."""
    return hashlib.sha1(f"{tag}:{date.today().isoformat()}".encode()).hexdigest()[:12]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Mark self-published books (publisher Amazon -> self-publishing)."
    )
    parser.add_argument("--save", action="store_true",
                        help="really edit Wikidata and record results (default: dry run)")
    parser.add_argument("--limit", type=int, metavar="N",
                        help="stop after processing N not-yet-done items")
    parser.add_argument("--qid", action="append", default=[], metavar="QID",
                        help="process only this QID, even if already processed (repeatable)")
    parser.add_argument("--recheck-review", action="store_true",
                        help="re-examine items previously sent to review (e.g. after a manual fix)")
    parser.add_argument("--editgroup", metavar="ID",
                        help="override the batch id (default: a stable per-day id)")
    args = parser.parse_args()

    edit_group = args.editgroup or daily_editgroup("mark_selfpublished")
    kind = "override" if args.editgroup else "daily; groups today's runs"
    print(f"editgroup={edit_group} ({kind}) ({'SAVE' if args.save else 'dry run'})", flush=True)

    force = bool(args.qid)
    items = args.qid if args.qid else fetch_candidates()
    if not args.qid:
        print(f"{len(items)} bibliographic item(s) with a self-pub-platform publisher", flush=True)
    done = load_processed(include_review=not args.recheck_review)

    # In a dry run, write a fresh preview report (rewritten each run, never during
    # --save) so the whole auto-edit/review split can be eyeballed as a file. Because
    # a dry run records nothing to the state files, a later --save covers the same
    # ordered slice (ORDER BY ?item makes the candidate order deterministic).
    report = None
    if not args.save:
        OUTPUT_DIR.mkdir(exist_ok=True)
        report = open(REPORT_FILE, "w", encoding="utf-8")
        report.write(f"# dry-run preview  editgroup={edit_group}  {len(items)} candidate(s)\n")

    processed = 0
    try:
        for qid in items:
            if args.limit is not None and processed >= args.limit:
                break
            if not force and qid in done:
                continue
            print(f"Processing {qid} ...", flush=True)
            processed += 1
            try:
                changed, review, action = process_item(qid, edit_group=edit_group, test=not args.save)
            except Exception as e:
                pywikibot.error(f"Error on {qid}: {e}")
                if args.save:
                    append_line(FAILED_FILE, f"{qid}\t{str(e)[:400]}")
                if report:
                    report.write(f"{qid}\tERROR\t{str(e)[:400]}\n")
                continue
            if review:
                print(f"  REVIEW {qid}: {review}", flush=True)
            if review:
                disposition, detail = "REVIEW", review
            elif action:
                disposition, detail = "EDIT", action
            else:
                disposition, detail = "SKIP", "not a candidate (no platform publisher)"
            if report:
                report.write(f"{qid}\t{disposition}\t{detail}\n")
            if args.save:
                if review:
                    append_line(REVIEW_FILE, f"{qid}\t{review}")
                else:
                    append_line(DONE_FILE, f"{qid}\t{'changed' if changed else 'no-change'}")
    finally:
        if report:
            report.close()
    print(f"Done: {processed} item(s) processed.", flush=True)
    if report is not None:
        print(f"Preview written to {REPORT_FILE}", flush=True)


if __name__ == "__main__":
    main()
