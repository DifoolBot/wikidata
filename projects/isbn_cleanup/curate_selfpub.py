"""Interactive triage for self-published / KDP book items.

Walks the self-pub review pile (bibliographic items whose publisher is Amazon or
Kindle Direct Publishing) one at a time, shows the item's current state, asks only
the questions that item actually raises, and applies your answers. It is the
human-in-the-loop companion to `mark_selfpublished.py`: that bot auto-does the small
safe slice and routes everything ambiguous to review; this tool works that review
pile with you in the loop.

It reuses the bot's helpers and conventions (deprecated statements are invisible on
read via `live()`, the 979-8/978 split, the own-imprint check). Every item's proposed
edits are shown and must be confirmed before saving; nothing is written otherwise.

v1 handles the "core" edits: publisher (remove the platform value; set Independently
published / author+P3831 / a real publisher / CreateSpace), ISBN reformatting to
canonical hyphenation, adding an ASIN, distribution format (P437, migrating a stray
P2701 file-format), and moving an author mis-filed as publisher into P50. Deprecating
a wrong-edition ISBN (rank + P2241) is NOT done here yet -- it's flagged as a manual
step (do it in the UI: deprecate the P212 + P2241 = "refers to different subject"
Q28091153).

Dry-run by default (apply() simulates); pass --save to really edit.

    python projects/isbn_cleanup/curate_selfpub.py            # dry run, whole pile
    python projects/isbn_cleanup/curate_selfpub.py --qid Q123 # one item
    python projects/isbn_cleanup/curate_selfpub.py --file q.txt   # QIDs from a file
    python projects/isbn_cleanup/curate_selfpub.py --save     # really edit
"""

import argparse
import hashlib
import re
from datetime import date
from pathlib import Path

import pywikibot
from stdnum import isbn as stdnum_isbn

import shared_lib.change_wikidata as cwd
import shared_lib.constants as wd
import mark_selfpublished as msp  # reuse helpers/conventions (sibling module)

repo = msp.repo

QID_CREATESPACE = "Q15803989"      # CreateSpace Independent Publishing Platform
QID_EBOOK = "Q128093"              # ebook (P437 distribution format)
QID_PAPERBACK = "Q193934"          # paperback (P437 distribution format)
QID_HARDCOVER = "Q193955"          # hardcover (P437 distribution format)
QID_HUMAN = "Q5"
PID_FILE_FORMAT = "P2701"
PID_AMAZON_AUTHOR_ID = "P4862"
EDITION_TYPE = "Q3331189"   # version, edition or translation
# Properties that describe a physical/published EDITION, not the abstract work.
EDITION_PROPS = [wd.PID_PUBLISHER, wd.PID_ISBN_13, wd.PID_ISBN_10,
                 wd.PID_AMAZON_STANDARD_IDENTIFICATION_NUMBER, wd.PID_DISTRIBUTION_FORMAT]
# Identifiers must never be *deleted*: move them to the right edition, or (if they're a
# different version) deprecate -- never remove.
ID_PROPS = {wd.PID_AMAZON_STANDARD_IDENTIFICATION_NUMBER, wd.PID_ISBN_13, wd.PID_ISBN_10}
QID_DIFFERENT_VERSION = "Q51845721"  # P2241 reason: applies to a different version of this work

HERE = Path(__file__).parent
OUTPUT_DIR = HERE / "output"
DONE_FILE = OUTPUT_DIR / "curate_done.txt"

_cache: dict = {}


def entity(qid: str):
    """Cached, fetched ItemPage for a value item (for label / P31 lookups)."""
    if qid not in _cache:
        it = pywikibot.ItemPage(repo, qid)
        try:
            it.get()
        except Exception:
            pass
        _cache[qid] = it
    return _cache[qid]


def label(qid: str) -> str:
    return entity(qid).labels.get("en", qid) if hasattr(entity(qid), "labels") else qid


def is_human(qid: str) -> bool:
    it = entity(qid)
    return any((c.getTarget() and c.getTarget().getID() == QID_HUMAN)
               for c in it.claims.get("P31", [])) if hasattr(it, "claims") else False


def ask(prompt: str, default: str = "") -> str:
    hint = f" [{default}]" if default else ""
    try:
        v = input(f"  {prompt}{hint} > ").strip()
    except EOFError:
        return default
    return v or default


def confirm(prompt: str, default: bool = True) -> bool:
    d = "Y/n" if default else "y/N"
    v = ask(f"{prompt} [{d}]").lower()
    if not v:
        return default
    return v.startswith("y")


def isbn_lines(page) -> list[str]:
    out = []
    for pid in (wd.PID_ISBN_13, wd.PID_ISBN_10):
        for c in page.claims.get(pid, []):
            v = c.getTarget()
            if not isinstance(v, str):
                continue
            rank = "" if c.rank == "normal" else f" ({c.rank})"
            if stdnum_isbn.is_valid(v):
                canon = stdnum_isbn.format(v)
                blk = "979-8" if stdnum_isbn.compact(v).startswith("9798") else "978"
                note = "canonical" if canon == v else f"-> {canon}"
                out.append(f"{pid} = {v}{rank}  [{blk}, {note}]")
            else:
                out.append(f"{pid} = {v}{rank}  [INVALID]")
    return out


def show_state(qid: str, item, page) -> None:
    lab = item.labels.get("en", "(no label)")
    p31 = ", ".join(label(c.getTarget().getID()) for c in page.claims.get("P31", []) if c.getTarget())
    print(f"\n=== {qid}  \"{lab}\"  ({p31})")
    desc = item.descriptions.get("en")
    if desc:
        print(f"    {desc}")
    pubs = []
    for c in msp.live(page.claims.get(wd.PID_PUBLISHER, [])):
        t = c.getTarget()
        if not t:
            continue
        tid = t.getID()
        tag = "platform" if tid in msp.SELFPUB_PLATFORMS else ("person" if is_human(tid) else "org")
        pubs.append(f"{label(tid)} ({tid}, {tag})")
    print(f"  P123 publisher : {'; '.join(pubs) or '(none live)'}")
    authors = [c.getTarget().getID() for c in msp.live(page.claims.get(wd.PID_AUTHOR, [])) if c.getTarget()]
    print(f"  P50  author    : {', '.join(f'{label(a)} ({a})' for a in authors) or '(none)'}")
    for ln in isbn_lines(page):
        print(f"  {ln}")
    asins = [c.getTarget() for c in page.claims.get(wd.PID_AMAZON_STANDARD_IDENTIFICATION_NUMBER, [])]
    print(f"  P5749 ASIN     : {', '.join(a for a in asins if isinstance(a, str)) or '(none)'}")
    fmt = [label(c.getTarget().getID()) for c in page.claims.get(wd.PID_DISTRIBUTION_FORMAT, []) if c.getTarget()]
    ff = [label(c.getTarget().getID()) for c in page.claims.get(PID_FILE_FORMAT, []) if c.getTarget()]
    print(f"  P437 dist.fmt  : {', '.join(fmt) or '(none)'}"
          + (f"   |  P2701 file-format: {', '.join(ff)}" if ff else ""))
    if page.item.sitelinks:
        print(f"  sitelinks      : {len(page.item.sitelinks)}")


def suggest(page, editions) -> tuple[str, str]:
    """(default-letter, hint) for the publisher question, from the split model."""
    has_979_8, non_kdp = msp.classify_isbns(page, editions)
    if non_kdp:
        return "", f"non-979-8 ISBN {non_kdp} -> CreateSpace / own / real; CHECK Amazon"
    if has_979_8:
        for a in [c.getTarget().getID() for c in msp.live(page.claims.get(wd.PID_AUTHOR, [])) if c.getTarget()]:
            press = msp.author_owns_publisher(a)
            if press:
                return "", f"979-8 ISBN but author owns publisher {press} -> likely own imprint"
        return "i", "979-8 free-KDP ISBN -> Independently published"
    return "a", "no ISBN in WD -> author+self-pub (but verify no hidden 979-8 on Amazon!)"


def do_publisher(page, editions, descs) -> None:
    live_pub = msp.live(page.claims.get(wd.PID_PUBLISHER, []))
    platform = [c for c in live_pub if c.getTarget() and c.getTarget().getID() in msp.SELFPUB_PLATFORMS]
    persons = [c for c in live_pub if c.getTarget() and c.getTarget().getID() not in msp.SELFPUB_PLATFORMS
               and is_human(c.getTarget().getID())]
    live_authors = [c.getTarget().getID() for c in msp.live(page.claims.get(wd.PID_AUTHOR, [])) if c.getTarget()]

    default, hint = suggest(page, editions)
    print(f"  -- Publisher --   (suggestion: {hint})")

    if platform:
        ids = [c.getTarget().getID() for c in platform]
        if confirm(f"remove platform publisher(s) {ids}?", True):
            for c in platform:
                page.remove_property(wd.PID_PUBLISHER, c)
            descs.append(f"- remove P123 = {', '.join(ids)} (platform)")

    # A person in P123 is the author, either mis-filed as publisher (remove) or the
    # self-publisher (keep, qualified P3831). Offer to add them as P50 first.
    published_set = False
    for c in persons:
        pid_ = c.getTarget().getID()
        if pid_ not in live_authors and confirm(f"add {label(pid_)} ({pid_}) as author (P50)?", True):
            _add_item(page, wd.PID_AUTHOR, pid_, descs, label(pid_))
            live_authors.append(pid_)
        r = ask(f"{label(pid_)} in P123: [s]elf-pub role (+P3831) / [r]emove / [k]eep", "s").lower()
        if r == "s":
            page.remove_property(wd.PID_PUBLISHER, c)
            _add_author_publisher(page, pid_, descs)
            published_set = True
        elif r == "r":
            page.remove_property(wd.PID_PUBLISHER, c)
            descs.append(f"- remove P123 = {pid_} ({label(pid_)}, mis-filed)")

    if published_set:
        return
    choice = ask("publisher? [i]ndependently  [a]uthor+selfpub  [Q<qid>] real  [c]reatespace  [enter]=none",
                 default).lower()
    if choice == "i":
        _add_item(page, wd.PID_PUBLISHER, wd.QID_INDEPENDENTLY_PUBLISHED, descs, "Independently published")
    elif choice == "c":
        _add_item(page, wd.PID_PUBLISHER, QID_CREATESPACE, descs, "CreateSpace")
    elif choice == "a":
        author = live_authors[0] if len(live_authors) == 1 else ask("author QID for publisher=author?").strip()
        if author.startswith("Q"):
            _add_author_publisher(page, author, descs)
    elif choice.startswith("Q"):
        _add_item(page, wd.PID_PUBLISHER, choice.strip(), descs, label(choice.strip()))


def _add_author_publisher(page, author_qid: str, descs) -> None:
    """Add P123 = author, qualified object-has-role = self-publishing."""
    new = pywikibot.Claim(repo, wd.PID_PUBLISHER)
    new.setTarget(pywikibot.ItemPage(repo, author_qid))
    role = pywikibot.Claim(repo, wd.PID_OBJECT_HAS_ROLE, is_qualifier=True)
    role.setTarget(pywikibot.ItemPage(repo, wd.QID_SELF_PUBLISHING))
    new.qualifiers.setdefault(wd.PID_OBJECT_HAS_ROLE, []).append(role)
    page.add_claim(wd.PID_PUBLISHER, new)
    descs.append(f"+ P123 = {author_qid} ({label(author_qid)}) [P3831 = self-publishing]")


def _add_item(page, pid, qid, descs, human) -> None:
    existing = {_value_str(c.getTarget()) for c in msp.live(page.claims.get(pid, [])) if c.getTarget()}
    if qid in existing:
        print(f"  ({pid} = {qid} ({human}) already present -- skipping)")
        return
    claim = pywikibot.Claim(repo, pid)
    claim.setTarget(pywikibot.ItemPage(repo, qid))
    page.add_claim(pid, claim)
    descs.append(f"+ {pid} = {qid} ({human})")


def _add_author_name_string(page, name, descs) -> None:
    """Record an author with no Wikidata item as P2093 (author name string) -- the
    mainstream way to note an author who has (or should have) no item. Per the property
    docs, don't use P2093 together with P50, so if the item carries a P50=unknown-value
    placeholder, offer to drop it."""
    existing = {_value_str(c.getTarget()) for c in msp.live(page.claims.get(wd.PID_AUTHOR_NAME_STRING, []))
                if c.getTarget()}
    if name in existing:
        print(f"  (P2093 = '{name}' already present -- skipping)")
    else:
        claim = pywikibot.Claim(repo, wd.PID_AUTHOR_NAME_STRING)
        claim.setTarget(name)
        page.add_claim(wd.PID_AUTHOR_NAME_STRING, claim)
        descs.append(f"+ P2093 (author name string) = '{name}'")
    somevalue = [c for c in msp.live(page.claims.get(wd.PID_AUTHOR, [])) if c.snaktype == "somevalue"]
    if somevalue and confirm("remove the P50 = unknown-value placeholder (don't use P50 + P2093 together)?", True):
        for c in somevalue:
            page.remove_property(wd.PID_AUTHOR, c)
        descs.append("- remove P50 = unknown value (replaced by P2093)")


def do_isbn_format(page, descs) -> None:
    for pid in (wd.PID_ISBN_13, wd.PID_ISBN_10):
        for c in msp.live(page.claims.get(pid, [])):
            v = c.getTarget()
            if not isinstance(v, str) or not stdnum_isbn.is_valid(v):
                continue
            canon = stdnum_isbn.format(v)
            if canon != v and confirm(f"reformat {pid} {v} -> {canon}?", True):
                page.change_claim(pid, c, canon)
                descs.append(f"~ {pid}: {v} -> {canon}")


def do_asin(page, descs) -> None:
    if page.claims.get(wd.PID_AMAZON_STANDARD_IDENTIFICATION_NUMBER):
        return
    v = ask("add ASIN? (paste B0..., enter=skip)").strip()
    if v:
        claim = pywikibot.Claim(repo, wd.PID_AMAZON_STANDARD_IDENTIFICATION_NUMBER)
        claim.setTarget(v)
        page.add_claim(wd.PID_AMAZON_STANDARD_IDENTIFICATION_NUMBER, claim)
        descs.append(f"+ P5749 (ASIN) = {v}")


def do_format(page, descs) -> None:
    has_437 = bool(page.claims.get(wd.PID_DISTRIBUTION_FORMAT))
    ff = page.claims.get(PID_FILE_FORMAT, [])
    if has_437 and not ff:
        return
    choice = ask("distribution format? [e]book  [p]aperback  [Q<qid>]  enter=skip").lower()
    target = {"e": QID_EBOOK, "p": QID_PAPERBACK}.get(choice, choice if choice.startswith("q") else None)
    if target:
        target = target if target.startswith("Q") else target.upper()
        _add_item(page, wd.PID_DISTRIBUTION_FORMAT, target, descs, label(target))
    if ff and confirm(f"remove stray P2701 file-format ({', '.join(label(c.getTarget().getID()) for c in ff if c.getTarget())})?", True):
        for c in ff:
            page.remove_property(PID_FILE_FORMAT, c)
        descs.append("- remove P2701 (file format; use P437 distribution format)")


def classify_structure(page):
    """Return (variant, editions) where variant is 'work' | 'edition' | 'mix'.

    Per the FRBR split (mostly done by Iamcarbon): a **work** has 'has edition or
    translation' (P747) and must NOT carry edition properties (publisher/ISBN/…); an
    **edition** is typed 'version, edition or translation' (Q3331189) or has 'edition
    or translation of' (P629); a **mix** is neither -- a single item conflating both,
    typical of a beginner or a self-publishing author. ``editions`` are the P747
    targets (fetched), used to move a work's misplaced properties to the right item."""
    editions = msp.linked_editions(page)
    if editions:
        return "work", editions
    p31 = {c.getTarget().getID() for c in msp.live(page.claims.get("P31", [])) if c.getTarget()}
    if EDITION_TYPE in p31 or msp.live(page.claims.get(wd.PID_EDITION_OR_TRANSLATION_OF, [])):
        return "edition", editions
    return "mix", editions


def _value_str(target):
    return target.getID() if hasattr(target, "getID") else target


def edition_with(editions, pid: str, vstr: str):
    """QID of a linked edition that already carries pid=vstr (else None)."""
    for e in editions:
        for c in msp.live(e.claims.get(pid, [])):
            if _value_str(c.getTarget()) == vstr:
                return e.getID()
    return None


def page_for(edit_pages, qid, dry_run, edit_group):
    """A cached WikiDataPage for a *related* item we also edit (a linked edition, or
    an author whose Amazon author ID we add) -- applied alongside the main page."""
    if qid not in edit_pages:
        p = cwd.WikiDataPage(pywikibot.ItemPage(repo, qid), test=dry_run)
        p.edit_group = edit_group
        edit_pages[qid] = p
    return edit_pages[qid]


def asin_edition_conflict(vstr: str, ed_item) -> str | None:
    """Reason a B0 ASIN cannot be the target edition's (else None).

    You CANNOT infer a B0 ASIN's format from the string -- paperbacks (esp. newer KDP
    print) get B0 ASINs too, *alongside* an ISBN (found on Q115682585: paperback ASIN
    B0BN7PD6QC + ISBN 979-8-3652-3067-5). So format/ISBN-10 signals do NOT prove it's a
    Kindle. The only hard signal is that one edition holds one ASIN: if the edition
    already has a *different* ASIN, this one is a different product. Otherwise it's
    undecidable from WD -> ask the user (who's on Amazon)."""
    ed_asins = {_value_str(c.getTarget()) for c in
                msp.live(ed_item.claims.get(wd.PID_AMAZON_STANDARD_IDENTIFICATION_NUMBER, []))}
    if ed_asins and vstr not in ed_asins:
        return f"edition already has a different ASIN {sorted(ed_asins)}"
    return None


def _deprecate(page, pid, claim, vstr, descs) -> None:
    """Deprecate an identifier that belongs to a different version -- keep it, mark it
    not-current (rank=deprecated + P2241 = Q51845721), never delete. Applied in the
    same batched edit via change_wikidata.deprecate_claim."""
    page.deprecate_claim(pid, claim, QID_DIFFERENT_VERSION)
    descs.append(f"⚑ deprecate {pid} = {vstr} (P2241 = {QID_DIFFERENT_VERSION}, different version)")


def _move(page, edit_pages, pid, claim, vstr, is_item, ed_qid, descs, dry_run, eg) -> None:
    newc = pywikibot.Claim(repo, pid)
    newc.setTarget(pywikibot.ItemPage(repo, vstr) if is_item else vstr)
    page_for(edit_pages, ed_qid, dry_run, eg).add_claim(pid, newc)
    page.remove_property(pid, claim)
    descs.append(f"→ move {pid} = {vstr} from work to edition {ed_qid}")


def do_work_cleanup(page, editions, edit_pages, descs, dry_run, edit_group) -> None:
    """A strict work shouldn't carry edition properties. For each misplaced one:
    drop a platform publisher; drop values the edition already has; else move it to the
    linked edition -- but only to the edition it actually belongs to. A Kindle ASIN in
    particular is a *different version* than a paperback edition, so before moving an
    ASIN we ask which ISBN Amazon shows for it and require that to match the target
    edition's ISBN (found via Q112076896: Kindle ASIN B00IUODHWG vs paperback
    Q132530085)."""
    print(f"  -- WORK cleanup --   edition(s): {', '.join(e.getID() for e in editions)}")
    for pid in EDITION_PROPS:
        for c in msp.live(page.claims.get(pid, [])):
            vstr = _value_str(c.getTarget())
            is_item = hasattr(c.getTarget(), "getID")
            vlabel = label(vstr) if is_item else vstr
            if pid == wd.PID_PUBLISHER and is_item and vstr in msp.SELFPUB_PLATFORMS:
                if confirm(f"remove misplaced platform P123 = {vstr} ({vlabel}) from work?", True):
                    page.remove_property(pid, c)
                    descs.append(f"- work P123 = {vstr} ({vlabel}, platform)")
                continue
            holder = edition_with(editions, pid, vstr)
            if holder:
                if confirm(f"remove {pid} = {vstr} from work (already on edition {holder})?", True):
                    page.remove_property(pid, c)
                    descs.append(f"- work {pid} = {vstr} (already on {holder})")
                continue

            if len(editions) == 1:
                ed_item = editions[0]
            else:
                eq = ask("target edition QID?").strip()
                ed_item = next((e for e in editions if e.getID() == eq), None)
                if ed_item is None:
                    print("  (unknown edition; keeping on work)")
                    continue
            ed = ed_item.getID()
            other = {_value_str(x.getTarget()) for x in msp.live(ed_item.claims.get(pid, []))}
            if other:
                print(f"  note: edition {ed} already has {pid} = {sorted(other)} (different value)")

            # ASIN: a B0 ASIN's format is indeterminate from the string, so let the user
            # (on Amazon) confirm which edition it belongs to; never delete it.
            if pid == wd.PID_AMAZON_STANDARD_IDENTIFICATION_NUMBER and str(vstr).upper().startswith("B0"):
                conflict = asin_edition_conflict(vstr, ed_item)
                belongs = False
                if conflict:
                    print(f"  -> ASIN {vstr} can't be edition {ed}'s: {conflict}.")
                else:
                    fmt = ", ".join(sorted(label(f) for f in {_value_str(x.getTarget())
                          for x in msp.live(ed_item.claims.get(wd.PID_DISTRIBUTION_FORMAT, []))})) or "?"
                    belongs = confirm(f"does ASIN {vstr} belong to edition {ed} (format: {fmt})?", False)
                if belongs:
                    _move(page, edit_pages, pid, c, vstr, is_item, ed, descs, dry_run, edit_group)
                else:
                    alt = ask("[Q<qid>] move to the right edition / [d]eprecate (different version) / [k]eep",
                              "d").lower()
                    if alt.startswith("q") and alt[1:].isdigit():
                        _move(page, edit_pages, pid, c, vstr, is_item, alt.upper(), descs, dry_run, edit_group)
                    elif alt == "k":
                        pass  # keep as-is
                    else:
                        _deprecate(page, pid, c, vstr, descs)
                continue

            if pid in ID_PROPS:
                # Never delete an identifier -- move it, deprecate it, or keep it.
                ch = ask(f"work has misplaced {pid} = {vstr}: [m]ove to {ed} / [Q<qid>] other / "
                         "[d]eprecate (different version) / [k]eep", "d" if other else "m").lower()
                if ch == "m":
                    _move(page, edit_pages, pid, c, vstr, is_item, ed, descs, dry_run, edit_group)
                elif ch.startswith("q") and ch[1:].isdigit():
                    _move(page, edit_pages, pid, c, vstr, is_item, ch.upper(), descs, dry_run, edit_group)
                elif ch == "d":
                    _deprecate(page, pid, c, vstr, descs)
            else:
                # non-identifier (e.g. distribution format) -- move / remove / keep.
                ch = ask(f"work has misplaced {pid} = {vstr} ({vlabel}): [m]ove to {ed} / [r]emove / [k]eep",
                         "k" if other else "m").lower()
                if ch == "m":
                    _move(page, edit_pages, pid, c, vstr, is_item, ed, descs, dry_run, edit_group)
                elif ch == "r":
                    page.remove_property(pid, c)
                    descs.append(f"- work {pid} = {vstr} ({vlabel})")


def parse_wbtime(s: str):
    s = s.strip()
    if re.fullmatch(r"\d{4}", s):
        return pywikibot.WbTime(year=int(s))
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return pywikibot.WbTime(year=int(m.group(1)), month=int(m.group(2)), day=int(m.group(3)))
    return None


def do_author_amazon_id(page, descs, edit_pages, dry_run, edit_group) -> None:
    """[e] For each author (P50) lacking Amazon author ID (P4862), ask for it and add
    it to the *author* item (from the same Amazon page you're on). Cross-item edit,
    validated against the B[0-9A-Z]+ format, applied alongside the book. Used by both
    edition and mix items that are on Amazon."""
    for aq in [c.getTarget().getID() for c in msp.live(page.claims.get(wd.PID_AUTHOR, [])) if c.getTarget()]:
        ai = entity(aq)
        if hasattr(ai, "claims") and msp.live(ai.claims.get(PID_AMAZON_AUTHOR_ID, [])):
            continue
        aid = ask(f"[e] Amazon author ID (P4862) for {label(aq)} ({aq})? (B..., enter=skip)").strip()
        if not aid:
            continue
        if not re.fullmatch(r"B[0-9A-Z]+", aid):
            print(f"  (warning: '{aid}' isn't a valid Amazon author ID (B[0-9A-Z]+) -- skipped)")
            continue
        claim = pywikibot.Claim(repo, PID_AMAZON_AUTHOR_ID)
        claim.setTarget(aid)
        page_for(edit_pages, aq, dry_run, edit_group).add_claim(PID_AMAZON_AUTHOR_ID, claim)
        descs.append(f"+ [author {aq} ({label(aq)})] P4862 (Amazon author ID) = {aid}")


def do_mix(page, descs, edit_pages, dry_run, edit_group) -> None:
    """A MIX item conflates work + edition, and may actually conflate *several*
    editions. Have the human verify the item's ISBN on Amazon: if that ISBN isn't a
    single Amazon product [a=no] or Amazon's date differs from the item's [c], it's a
    multi-version tangle -> skip. Otherwise use the answers to add ASIN / publisher /
    date / distribution-format statements."""
    isbns = [c.getTarget() for pid in (wd.PID_ISBN_13, wd.PID_ISBN_10)
             for c in msp.live(page.claims.get(pid, [])) if isinstance(c.getTarget(), str)]
    item_years = [t.year for c in msp.live(page.claims.get(wd.PID_PUBLICATION_DATE, [])) if (t := c.getTarget())]
    print(f"  -- MIX: verify on Amazon --  ISBN(s): {', '.join(isbns) or '(none)'}   item date: {item_years or '(none)'}")

    if isbns:
        found = confirm("[a] does that ISBN open THIS book as a single Amazon product?", True)
        asin = ask("    ASIN? (paste B0..., or enter if none / it's the print ISBN)") if found else ""
    else:
        asin = ask("[a] no ISBN on the item -- this book's Amazon ASIN? (paste B0..., or 'no' if not found)")
        found = bool(asin) and asin.lower() != "no"
    amdate = ask("[c] publication date shown on Amazon? (YYYY or YYYY-MM-DD, enter=skip)")

    problems = []
    if not found:
        problems.append("not found as a single Amazon product for this book")
    if amdate and (wt := parse_wbtime(amdate)) and item_years and wt.year not in item_years:
        problems.append(f"Amazon date {wt.year} != item date {item_years}")
    if problems:
        print("  -> " + "; ".join(problems)
              + "  ->  likely several versions conflated; SKIP for now (needs a manual work/edition split).")
        return

    # Consistent single version: turn [a/b/c/d] into statements.
    for c in msp.live(page.claims.get(wd.PID_PUBLISHER, [])):
        t = c.getTarget()
        if t and t.getID() in msp.SELFPUB_PLATFORMS:
            page.remove_property(wd.PID_PUBLISHER, c)
            descs.append(f"- remove P123 = {t.getID()} (platform)")

    pub = ask("[b] publisher? (1) CreateSpace  (2) Independently published  "
              "(3) author+self-pub (no publisher shown)  (4) other QID  (enter=none)")
    if pub == "1":
        _add_item(page, wd.PID_PUBLISHER, QID_CREATESPACE, descs, "CreateSpace")
    elif pub == "2":
        _add_item(page, wd.PID_PUBLISHER, wd.QID_INDEPENDENTLY_PUBLISHED, descs, "Independently published")
    elif pub == "3":
        authors = [c.getTarget().getID() for c in msp.live(page.claims.get(wd.PID_AUTHOR, [])) if c.getTarget()]
        if len(authors) == 1:
            _add_author_publisher(page, authors[0], descs)
        else:
            ans = ask("   author QID (-> P50 + P123 author+P3831), or a NAME (-> P2093 name string), "
                      "or enter=skip").strip()
            if ans.startswith("Q"):
                if ans not in authors:
                    _add_item(page, wd.PID_AUTHOR, ans, descs, label(ans))
                _add_author_publisher(page, ans, descs)
            elif ans:
                _add_author_name_string(page, ans, descs)
                print("  (author has no item -> recorded as P2093 name string; P123 left unset)")
    elif pub == "4":
        pq = ask("   publisher QID (Q...), or a name to note").strip()
        if pq.startswith("Q"):
            _add_item(page, wd.PID_PUBLISHER, pq, descs, label(pq))
        elif pq:
            print(f"  note: publisher = '{pq}' -- find/create its item and set P123 manually")

    book_on_amazon = found
    if asin:
        if asin.upper().startswith("B0"):
            if not page.claims.get(wd.PID_AMAZON_STANDARD_IDENTIFICATION_NUMBER):
                claim = pywikibot.Claim(repo, wd.PID_AMAZON_STANDARD_IDENTIFICATION_NUMBER)
                claim.setTarget(asin)
                page.add_claim(wd.PID_AMAZON_STANDARD_IDENTIFICATION_NUMBER, claim)
                descs.append(f"+ P5749 (ASIN) = {asin}")
        elif stdnum_isbn.is_valid(asin):
            print(f"  note: {asin} is the print ISBN-10 (Amazon shows it as the ASIN, but it "
                  "belongs in P957, not P5749) -- not adding to ASIN.")
        else:
            print(f"  note: '{asin}' isn't a Kindle ASIN (B0...) -- not adding to P5749.")

    if amdate and not item_years and (wt := parse_wbtime(amdate)):
        claim = pywikibot.Claim(repo, wd.PID_PUBLICATION_DATE)
        claim.setTarget(wt)
        page.add_claim(wd.PID_PUBLICATION_DATE, claim)
        descs.append(f"+ P577 (publication date) = {amdate}")

    fmt = ask("[d] format on Amazon? [k]indle / [p]aperback / [h]ardcover / enter=skip").lower()
    fmap = {"k": QID_EBOOK, "p": QID_PAPERBACK, "h": QID_HARDCOVER}
    if fmt in fmap and not page.claims.get(wd.PID_DISTRIBUTION_FORMAT):
        _add_item(page, wd.PID_DISTRIBUTION_FORMAT, fmap[fmt], descs, label(fmap[fmt]))

    do_isbn_format(page, descs)

    if book_on_amazon:
        do_author_amazon_id(page, descs, edit_pages, dry_run, edit_group)


def curate(qid: str, edit_group: str, dry_run: bool) -> str:
    """Interactively curate one item. Returns 'quit' to stop the session, else 'ok'."""
    item = pywikibot.ItemPage(repo, qid)
    page = cwd.WikiDataPage(item, test=dry_run)
    page.edit_group = edit_group
    show_state(qid, item, page)

    if page.item.sitelinks and not confirm("has sitelinks (notable) -- curate anyway?", False):
        return "ok"

    structure, editions = classify_structure(page)
    print(f"  structure: {structure.upper()}"
          + {"work": "  (P747 -> editions; must NOT hold publisher/ISBN)",
             "edition": "  (publisher/ISBN belong here)",
             "mix": "  (conflated work+edition -- clean in place)"}[structure])

    descs: list[str] = []
    edit_pages: dict = {}   # linked-edition pages that receive moved properties
    if structure == "work":
        do_work_cleanup(page, editions, edit_pages, descs, dry_run, edit_group)
    elif structure == "mix":
        do_mix(page, descs, edit_pages, dry_run, edit_group)
    else:  # edition
        do_publisher(page, editions, descs)
        do_isbn_format(page, descs)
        do_asin(page, descs)
        do_format(page, descs)
        has_ids = any(page.claims.get(p) for p in
                      (wd.PID_ISBN_13, wd.PID_ISBN_10, wd.PID_AMAZON_STANDARD_IDENTIFICATION_NUMBER))
        if has_ids:  # a published edition -> likely on Amazon
            do_author_amazon_id(page, descs, edit_pages, dry_run, edit_group)
        if msp.live(page.claims.get(wd.PID_ISBN_13, [])) or msp.live(page.claims.get(wd.PID_ISBN_10, [])):
            print("  (if an ISBN here is a sibling edition's, deprecate it manually: "
                  "rank + P2241 = Q28091153)")

    if not descs:
        print("  no changes.")
        return "ok"
    print("  -- proposed --")
    for d in descs:
        print(f"    {d}")
    ans = ask("apply? [y]es / [N]o / [q]uit").lower()
    if ans == "q":
        return "quit"
    if ans == "y":
        for p in [page, *edit_pages.values()]:
            ok = p.apply()
            print("  " + ("would save (dry run)." if dry_run else "saved." if ok else "no change / failed."))
    else:
        print("  discarded.")
    return "ok"


def load_done() -> set:
    if DONE_FILE.exists():
        with open(DONE_FILE, encoding="utf-8") as f:
            return {ln.split("\t", 1)[0].strip() for ln in f if ln.strip()}
    return set()


def daily_editgroup(tag: str) -> str:
    """A stable editgroups batch id for `tag` today, so the many restarts in one day
    land in a single reviewable/undoable batch instead of a new id each run. Derived
    from tag+date (per-tool, per-day), 12 hex chars to match the old format; unique per
    day and collision-free vs other tools/users."""
    return hashlib.sha1(f"{tag}:{date.today().isoformat()}".encode()).hexdigest()[:12]


def main() -> None:
    p = argparse.ArgumentParser(description="Interactive self-pub / KDP book curation.")
    p.add_argument("--save", action="store_true", help="really edit (default: dry run)")
    p.add_argument("--limit", type=int, metavar="N", help="stop after N items")
    p.add_argument("--qid", action="append", default=[], metavar="QID", help="only this QID (repeatable)")
    p.add_argument("--file", metavar="PATH", help="file of QIDs (first token per line)")
    p.add_argument("--editgroup", metavar="ID",
                   help="override the batch id (default: a stable per-day id)")
    args = p.parse_args()

    edit_group = args.editgroup or daily_editgroup("curate_selfpub")
    kind = "override" if args.editgroup else "daily; groups today's runs"
    print(f"editgroup={edit_group} ({kind}) ({'SAVE' if args.save else 'dry run'})", flush=True)

    if args.qid:
        items, force = args.qid, True
    elif args.file:
        with open(args.file, encoding="utf-8") as f:
            items = [ln.split()[0].split("\t")[0] for ln in f if ln.strip() and ln.lstrip()[0] == "Q"]
        force = True
    else:
        items = msp.fetch_candidates()
        print(f"{len(items)} candidate(s) in the self-pub pile", flush=True)
        force = False

    done = load_done()
    processed = 0
    for qid in items:
        if args.limit is not None and processed >= args.limit:
            break
        if not force and qid in done:
            continue
        processed += 1
        try:
            result = curate(qid, edit_group, dry_run=not args.save)
        except Exception as e:
            pywikibot.error(f"Error on {qid}: {e}")
            result = "ok"
        if args.save:
            OUTPUT_DIR.mkdir(exist_ok=True)
            with open(DONE_FILE, "a", encoding="utf-8") as f:
                f.write(qid + "\n")
        if result == "quit":
            print("stopped.")
            break
    print(f"Done: {processed} item(s).", flush=True)


if __name__ == "__main__":
    main()
