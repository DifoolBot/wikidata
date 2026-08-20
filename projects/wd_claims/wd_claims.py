#!/usr/bin/env python3
"""
wd_claims.py — Pull Wikidata claim data (values, ranks, qualifiers) reliably
via pywikibot, instead of manually copying from the diff view. Optionally
cross-checks two items for identifier values that appear on both, so you can
spot rank/qualifier mismatches (e.g. an identifier live on one item and
missing/wrongly-ranked on the other after a conflation split).

For each item it also looks up its VIAF cluster ID(s) (P214) against viaf.org
and prints what the cluster groups together — the authority ids and any other
Wikidata items VIAF ties to the same person — each resolved to its Wikidata
property. That surfaces, next to the item's own claims, what an external source
believes belongs together (handy for the same conflation-split checks). A
deprecated VIAF ID is looked up only when it was deprecated *for conflation*
(P2241 = Q14946528) — that cluster is precisely the conflated blob you want to
inspect; one deprecated for any other reason (e.g. a withdrawn id) is noted and
skipped. The lookup reuses the sibling ``viaf`` project: its ``ViafApiClient``
for the API call and its ``AuthoritySources`` table to name VIAF's source codes
(VIAF calls GND ``DNB``, BNF ``BNF``, …). Pass ``--no-viaf`` to skip it
(offline/quiet runs).

All Wikidata communication goes through pywikibot (shared_lib.wikidata_site),
so it inherits the repo's User-Agent, maxlag handling and throttling. The VIAF
call is a plain HTTPS GET (rate-limited ~1000/day). Read-only: it never edits.

Usage (from the repo root, PYTHONPATH=projects;projects/shared_lib via .env):
    python projects/wd_claims/wd_claims.py Q81280957 Q139428957
    python projects/wd_claims/wd_claims.py --compare Q81280957 Q139428957
    python projects/wd_claims/wd_claims.py --no-viaf Q81280957
"""

import argparse
import io
import sys
from collections import defaultdict

import pywikibot
import requests
from pywikibot.exceptions import (
    InvalidTitleError,
    IsRedirectPageError,
    NoPageError,
)

import shared_lib.constants as wd
from shared_lib.wikidata_site import get_repo, get_site
from viaf.authority_sources import AuthoritySources
from viaf.viaf_api_client import ViafApiClient, ViafRateLimitExceeded, ViafStatus

# Datatypes whose target is another Wikibase entity (has an id + a label to
# resolve); everything else renders from the target value directly.
ENTITY_TYPES = {
    "wikibase-item",
    "wikibase-property",
    "wikibase-lexeme",
    "wikibase-sense",
    "wikibase-form",
}


def load_items(repo, qids):
    """Load each QID as an ItemPage, following redirects and skipping the
    missing. Returns an ordered dict {qid: ItemPage}."""
    items = {}
    for qid in qids:
        try:
            item = pywikibot.ItemPage(repo, qid)  # rejects malformed ids here
            item.get()
        except InvalidTitleError:
            print(f"{qid}: not a valid item id, skipping")
            continue
        except NoPageError:
            print(f"{qid}: no such item, skipping")
            continue
        except IsRedirectPageError:
            target = item.getRedirectTarget()
            print(f"{qid}: redirect -> {target.getID()}, using target")
            item = target
            item.get()
        items[qid] = item
    return items


def fetch_labels(site, ids):
    """Resolve property/item ids (P123, Q456) to labels in one batched
    wbgetentities request per 50 ids, routed through pywikibot.

    Prefers the English label, falling back to the language-agnostic ``mul``
    label -- since 2024 a proper name identical across languages is often stored
    only under ``mul`` (Wikidata drops the per-language copies), so an en-only
    lookup would come back empty and render the bare id."""
    labels = {}
    ids = sorted(set(ids))
    for i in range(0, len(ids), 50):  # API caps ids per request
        chunk = ids[i : i + 50]
        data = site.simple_request(
            action="wbgetentities",
            ids="|".join(chunk),
            props="labels",
            languages="en|mul",
        ).submit()
        for eid, edata in data["entities"].items():
            lbls = edata.get("labels", {})
            label = (lbls.get("en") or lbls.get("mul") or {}).get("value")
            labels[eid] = label or eid
    return labels


def item_label(item):
    """The item's own display label: its English label, or the ``mul``
    (language-agnostic) label as fallback, else empty."""
    return item.labels.get("en") or item.labels.get("mul") or ""


def _ordinal(n):
    """1 -> '1st', 2 -> '2nd', 11 -> '11th', 21 -> '21st'."""
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def format_wbtime(t):
    """Render a WbTime at its actual precision, the way Wikidata displays it,
    instead of padding everything out to a full YYYY-MM-DD that reads as a
    spurious 1 January. Precision codes match shared_lib.date_value
    (11=day ... 6=millennium); the century/decade/millennium arithmetic follows
    the same conventions (e.g. year 2000 century precision -> 20th century)."""
    p = t.precision
    year = t.year
    if p >= 11:  # day
        return f"{year:04d}-{t.month:02d}-{t.day:02d}"
    if p == 10:  # month
        return f"{year:04d}-{t.month:02d}"
    if p == 9:  # year
        return f"{year}"
    if year > 0:  # coarser buckets are only well-defined for CE years
        if p == 8:  # decade
            return f"{year // 10 * 10}s"
        if p == 7:  # century
            return f"{_ordinal((year - 1) // 100 + 1)} century"
        if p == 6:  # millennium
            return f"{_ordinal((year - 1) // 1000 + 1)} millennium"
    # Coarser than a millennium, or BCE at a coarse precision: keep the year and
    # name the raw precision so nothing is silently misrepresented.
    return f"{year} (precision {p})"


def render_target(claim, labels):
    """Render a claim's (or qualifier's) target as a readable string."""
    if claim.getSnakType() != "value":
        return f"[{claim.getSnakType()}]"
    target = claim.getTarget()
    if claim.type in ENTITY_TYPES:
        eid = target.getID()
        return f"{labels.get(eid, eid)} ({eid})"
    if claim.type == "time":
        return format_wbtime(target)
    if claim.type == "monolingualtext":
        return target.text
    if claim.type == "quantity":
        return str(target.amount)
    if claim.type == "globe-coordinate":
        return f"{target.lat}, {target.lon}"
    return str(target)


def _target_entity_id(claim):
    """The id a claim's target refers to, if it is a Wikibase entity."""
    if claim.getSnakType() == "value" and claim.type in ENTITY_TYPES:
        return claim.getTarget().getID()
    return None


def collect_ids_to_resolve(item):
    """Walk all claims and gather every P/Q id that will need a label."""
    ids = set()
    for prop, claims in item.claims.items():
        ids.add(prop)
        for claim in claims:
            sid = _target_entity_id(claim)
            if sid:
                ids.add(sid)
            for qprop, qsnaks in claim.qualifiers.items():
                ids.add(qprop)
                for qs in qsnaks:
                    qsid = _target_entity_id(qs)
                    if qsid:
                        ids.add(qsid)
    return ids


def parse_item(qid, item, labels):
    """Return a list of dicts: one per statement, with resolved text."""
    rows = []
    for prop, claims in item.claims.items():
        pname = labels.get(prop, prop)
        for claim in claims:
            row = {
                "qid": qid,
                "prop_id": prop,
                "prop": pname,
                "value": render_target(claim, labels),
                "rank": claim.getRank(),
                "qualifiers": {},
            }
            for qprop, qsnaks in claim.qualifiers.items():
                qname = labels.get(qprop, qprop)
                row["qualifiers"][qname] = [render_target(qs, labels) for qs in qsnaks]
            rows.append(row)
    return rows


def print_rows(rows):
    for r in rows:
        print(f"[{r['qid']}] {r['prop']}: {r['value']}  ({r['rank']})")
        for qname, qvals in r["qualifiers"].items():
            print(f"    {qname}: {', '.join(qvals)}")


def compare(qid_a, qid_b, rows_a, rows_b):
    """Flag identifier values that appear on both items, side by side."""
    by_value_a = defaultdict(list)
    by_value_b = defaultdict(list)
    for r in rows_a:
        by_value_a[(r["prop_id"], r["value"])].append(r)
    for r in rows_b:
        by_value_b[(r["prop_id"], r["value"])].append(r)

    shared = set(by_value_a) & set(by_value_b)
    if not shared:
        print("No identical (property, value) pairs found on both items.")
        return

    print(f"Shared identifier values between {qid_a} and {qid_b}:\n")
    for prop, value in sorted(shared):
        for r in by_value_a[(prop, value)]:
            quals = f" {r['qualifiers']}" if r["qualifiers"] else ""
            print(f"  [{qid_a}] {r['prop']}: {value} — {r['rank']}{quals}")
        for r in by_value_b[(prop, value)]:
            quals = f" {r['qualifiers']}" if r["qualifiers"] else ""
            print(f"  [{qid_b}] {r['prop']}: {value} — {r['rank']}{quals}")
        print()


# --------------------------------------------------------------------------- #
# VIAF cluster lookup                                                          #
#                                                                              #
# For each item's VIAF cluster ID (P214) we ask viaf.org what that cluster     #
# contains and print it beneath the item's own claims. The API call and the    #
# code->property table both come from the sibling ``viaf`` project, so this    #
# stays in step with the VIAF bot instead of hard-coding VIAF's source codes.  #
# --------------------------------------------------------------------------- #

WIKIDATA_VIAF_CODE = "WKP"  # VIAF's authority-source code for Wikidata itself
# "conflation": the reason-for-deprecated-rank (P2241) value meaning a single
# identifier was found to cover two people and split across items. Matches
# viaf_score.py's Q_CONFLATION.
QID_CONFLATION = "Q14946528"


def build_viaf_code_map():
    """Map each VIAF authority-source code to the Wikidata property it stands
    for, as ``code -> [(pid, description), ...]``.

    Built from viaf.authority_sources.AuthoritySources -- the same table the
    VIAF bot uses -- so the codes stay in sync with that project and cryptic
    VIAF codes are shown by their Wikidata property (VIAF calls GND ``DNB``,
    IdRef ``SUDOC`` ...). A few codes map to more than one property (e.g.
    ``NSZL``), hence the list."""
    sources = AuthoritySources()
    code_map = {}
    for pid in sources.all_pids():
        src = sources.get(pid)
        code_map.setdefault(src.viaf_code, []).append((src.pid, src.description))
    return code_map


def label_viaf_code(code, code_map):
    """Human-readable label for a VIAF source code, e.g. ``GND ID (P227)``.
    Falls back to a plain 'Wikidata' for ``WKP`` and to the bare code for any
    source this repo does not model."""
    if code == WIKIDATA_VIAF_CODE:
        return "Wikidata (WKP)"
    entries = code_map.get(code)
    if not entries:
        return code
    return ", ".join(f"{desc} ({pid})" for pid, desc in entries)


def _deprecation_reason(claim):
    """The item id given as reason for deprecated rank (P2241) on a claim, or
    None when the claim carries no such qualifier value."""
    for qs in claim.qualifiers.get(wd.PID_REASON_FOR_DEPRECATED_RANK, []):
        if qs.getSnakType() == "value":
            return qs.getTarget().getID()
    return None


def collect_viaf_ids(item):
    """Classify the item's VIAF cluster IDs (P214) for lookup, in order and with
    duplicate ids dropped. Returns ``[(viaf_id, kind, reason_qid), ...]`` where
    kind is one of:

      - ``"live"``        a normal/preferred-rank id -> look it up (reason None);
      - ``"conflation"``  a *deprecated* id whose reason for deprecated rank
                          (P2241) is conflation (Q14946528) -> still look it up.
                          A cluster deprecated *for conflation* is the very blob
                          this tool exists to help untangle, so its contents are
                          exactly what you want to see; reason_qid is the
                          conflation id;
      - ``"skipped"``     deprecated for some other reason (e.g. a withdrawn
                          identifier value) -> not looked up, only noted, since
                          the id is genuinely wrong rather than merely shared;
                          reason_qid is that reason, or None if none was given.

    somevalue/novalue snaks carry no id and are dropped entirely."""
    out = []
    seen = set()
    for claim in item.claims.get(wd.PID_VIAF_ID, []):
        if claim.getSnakType() != "value":
            continue
        viaf_id = claim.getTarget()
        if not viaf_id or viaf_id in seen:
            continue
        if claim.getRank() == "deprecated":
            reason = _deprecation_reason(claim)
            kind = "conflation" if reason == QID_CONFLATION else "skipped"
        else:
            kind, reason = "live", None
        seen.add(viaf_id)
        out.append((viaf_id, kind, reason))
    return out


def fetch_viaf(client, viaf_id, max_redirects=3):
    """Query VIAF for a cluster id, following an abandoned-record redirect to
    the surviving cluster (up to ``max_redirects`` hops). Returns
    ``(final_id, result, chain)`` where ``chain`` is the ids redirected through
    (empty when the first lookup already resolved)."""
    chain = []
    current = str(viaf_id)
    result = None
    for _ in range(max_redirects + 1):
        result = client.query_viaf_id(current)
        if result.status == ViafStatus.REDIRECT and result.redirect_to:
            chain.append(current)
            current = str(result.redirect_to)
            continue
        break
    return current, result, chain


def print_viaf(item, code_map, client, labels):
    """Look up each of the item's VIAF IDs and print the cluster's contents --
    the authority ids (and sibling Wikidata items) VIAF groups together --
    resolved to their Wikidata property. A deprecated id is looked up only when
    it was deprecated *for conflation* (that cluster is the thing worth
    inspecting); one deprecated for any other reason is noted and skipped.
    Read-only; costs one VIAF API call per id looked up (plus one per redirect
    followed)."""
    entries = collect_viaf_ids(item)
    if not entries:
        print("    --- VIAF: no VIAF ID (P214) on this item ---")
        return

    for viaf_id, kind, reason in entries:
        if kind == "skipped":
            reason_txt = labels.get(reason, reason) if reason else "no reason given"
            print(
                f"    --- VIAF {viaf_id}: skipping deprecated id "
                f"(reason: {reason_txt}) ---"
            )
            continue

        try:
            final_id, result, chain = fetch_viaf(client, viaf_id)
        except ViafRateLimitExceeded as e:
            # Every further call would hit the same daily/monthly limit.
            print(f"    --- VIAF {viaf_id}: {e} ---")
            return
        except requests.RequestException as e:
            print(f"    --- VIAF {viaf_id}: request error ({e}) ---")
            continue
        except Exception as e:  # malformed payload etc. -- keep dumping the rest
            print(f"    --- VIAF {viaf_id}: lookup failed ({e}) ---")
            continue

        # Flag when the id we looked up was a conflation-deprecated one, so the
        # cluster below is read as "the blob that was split", not a live id.
        note = "; deprecated: conflation" if kind == "conflation" else ""
        header = f"    --- VIAF cluster {viaf_id}"
        if chain:  # chain[0] == viaf_id; show where it ended up
            header += " -> " + " -> ".join((chain + [final_id])[1:])
        header += f" ({result.status}{note}) ---"
        print(header)

        if result.status != ViafStatus.FOUND:
            continue
        if not result.source_mapping:
            print("        (cluster lists no source records)")
            continue

        for code in sorted(result.source_mapping):
            label = label_viaf_code(code, code_map)
            for nsid, content_id in result.source_mapping[code]:
                # nsid and content_id usually match; when they don't (e.g.
                # NUKAT lists a vtls* nsid against an n* content id) show both.
                extra = f"  [content: {content_id}]" if content_id != nsid else ""
                print(f"        {label}: {nsid}{extra}")


def main():
    # Labels and "subject named as" qualifiers are international (accents, bidi
    # marks, CJK...). Windows consoles and redirected stdout default to the
    # legacy code page (cp1252), which raises UnicodeEncodeError at print time --
    # after all the API work is already done. Force UTF-8 out. (reconfigure is
    # a TextIOWrapper method; isinstance both guards at runtime and narrows the
    # type for the checker, unlike hasattr.)
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    ap = argparse.ArgumentParser()
    ap.add_argument("qids", nargs="+", help="QIDs to fetch, e.g. Q81280957 Q139428957")
    ap.add_argument(
        "--compare",
        action="store_true",
        help="cross-check exactly two given items for shared identifier values",
    )
    ap.add_argument(
        "--no-viaf",
        action="store_true",
        help="skip the live VIAF lookup; by default each item's VIAF IDs (P214) "
        "are resolved against viaf.org and the cluster's contents printed",
    )
    args = ap.parse_args()

    repo = get_repo()
    site = get_site()

    # Build the VIAF code->property table and API client once, up front, so a
    # bad import surfaces before any network work rather than mid-dump.
    code_map = None if args.no_viaf else build_viaf_code_map()
    viaf_client = None if args.no_viaf else ViafApiClient()

    items = load_items(repo, args.qids)

    all_ids = set()
    for item in items.values():
        all_ids |= collect_ids_to_resolve(item)
    labels = fetch_labels(site, all_ids)

    all_rows = {}
    for qid, item in items.items():
        rows = parse_item(qid, item, labels)
        all_rows[qid] = rows
        print(f"=== {qid} ({item_label(item)}) ===")
        print_rows(rows)
        if not args.no_viaf:
            print_viaf(item, code_map, viaf_client, labels)
        print()

    if args.compare:
        if len(args.qids) != 2:
            print("--compare requires exactly two QIDs")
            return
        qa, qb = args.qids
        if qa not in all_rows or qb not in all_rows:
            print("--compare needs both items to load")
            return
        compare(qa, qb, all_rows[qa], all_rows[qb])


if __name__ == "__main__":
    main()
