#!/usr/bin/env python3
"""Close the loop: which snapshotted items later got DELETED, and why.

The collector (collect_new_items.py) snapshots new items daily. This scans the
public deletion log (Special:Log/delete via list=logevents, ns0) over the corpus
window and cross-references it against everything we tracked. That yields:

  * PRECISION -- of the items we flagged (shortlist, by score band), how many
    were deleted, and for what reason (RfD vs speedy promo/spam/empty). A high
    delete rate on high scores means the payload signals are picking real promo.
  * RECALL / MISSES -- items we tracked that got deleted but we did NOT flag
    (score < 2). These are the scorer's blind spots, worth reading.

Deletions accumulate into data/deletions.json (merged across runs, idempotent).
Note the natural lag: RfD runs ~a week, so this only gets meaningful once the
corpus is several days deep. READ-ONLY (log metadata is public; deleted *content*
is not touched).

Usage (from repo root):
    python projects/detect_promo/track_deletions.py            # scan corpus window
    python projects/detect_promo/track_deletions.py --days 14  # cap the log scan
"""

import argparse
import datetime as dt
import glob
import io
import json
import os
import sys
from collections import Counter

import detect_promo_accounts as dp

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")


def load_corpus(data_dir: str) -> tuple[set[str], dict[str, dict], str | None]:
    """Return (all tracked QIDs, shortlist index qid->best row, earliest date).

    'all tracked' needs the raw item list; a --slim day file has only its
    shortlist, so tracked coverage is best when the collector keeps raw items.
    """
    tracked: set[str] = set()
    shortlist: dict[str, dict] = {}
    earliest = None
    for path in sorted(glob.glob(os.path.join(data_dir, "*.json"))):
        if os.path.basename(path) == "deletions.json":
            continue
        try:
            d = json.load(open(path, encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        date = d.get("date")
        if date and (earliest is None or date < earliest):
            earliest = date
        for it in d.get("items", []):
            tracked.add(it["qid"])
        for r in d.get("shortlist", []):
            tracked.add(r["qid"])
            prev = shortlist.get(r["qid"])
            if prev is None or r.get("score", 0) > prev.get("score", 0):
                shortlist[r["qid"]] = {**r, "date": date}
    return tracked, shortlist, earliest


def scan_delete_log(since_date: str) -> dict[str, dict]:
    """Page ns0 page-deletion log entries from since_date to now."""
    end = f"{since_date}T00:00:00Z"
    params = {
        "action": "query",
        "list": "logevents",
        "leaction": "delete/delete",  # page deletions only (not restore/revdel)
        "lenamespace": "0",
        "leprop": "title|type|user|timestamp|comment",
        "lelimit": "500",
        "leend": end,  # older bound; default dir is older-first-from-now
    }
    out: dict[str, dict] = {}
    for e in dp.paginate(params, "logevents"):
        title = e.get("title", "")
        if not title.startswith("Q"):
            continue
        # keep the most recent deletion if a title appears more than once
        if title not in out:
            out[title] = {
                "deleted_ts": e.get("timestamp"),
                "admin": e.get("user"),
                "reason": e.get("comment", "") or "",
            }
    return out


def classify_reason(reason: str) -> str:
    r = reason.lower()
    if "rfd" in r or "requests for deletion" in r:
        return "RfD"
    if any(k in r for k in ("spam", "promo", "advert", "g11")):
        return "spam/promo"
    if any(k in r for k in ("empty", "no meaningful", "g1", "test")):
        return "empty/test"
    if "notab" in r:
        return "notability"
    if "copyright" in r or "g12" in r:
        return "copyright"
    return "other"


def main() -> None:
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-dir", default=DATA_DIR)
    ap.add_argument("--days", type=int, default=None, help="cap the log scan to last N days")
    args = ap.parse_args()

    tracked, shortlist, earliest = load_corpus(args.data_dir)
    if not tracked:
        print("No corpus found (run collect_new_items.py first).")
        return
    since = earliest or dt.date.today().isoformat()
    if args.days is not None:
        cap = (dt.date.today() - dt.timedelta(days=args.days)).isoformat()
        since = max(since, cap)
    print(f"Corpus: {len(tracked)} tracked items ({len(shortlist)} shortlisted), "
          f"since {earliest}. Scanning deletion log from {since} ...")

    log = scan_delete_log(since)
    # Cross-reference: tracked items that appear in the deletion log.
    deleted = {}
    for qid in tracked & set(log):
        row = shortlist.get(qid, {})
        deleted[qid] = {
            **log[qid],
            "score": row.get("score"),  # None if we never flagged it
            "subject": row.get("label"),
            "created_date": row.get("date"),
            "reason_class": classify_reason(log[qid]["reason"]),
        }

    # Persist (merge with prior runs).
    path = os.path.join(args.data_dir, "deletions.json")
    store = {}
    if os.path.exists(path):
        try:
            store = json.load(open(path, encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            store = {}
    store.update(deleted)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(store, fh, ensure_ascii=False, indent=1, sort_keys=True)

    # --- report ---
    print(f"\n{len(deleted)} tracked item(s) deleted (of {len(tracked)} tracked).")

    def band(lo, hi):
        ids = [q for q, r in shortlist.items() if lo <= r.get("score", 0) <= hi]
        d = sum(1 for q in ids if q in deleted)
        rate = f"{d/len(ids):.0%}" if ids else "-"
        return len(ids), d, rate

    print("\nshortlist delete rate by score band (precision proxy):")
    for label, (lo, hi) in [(">=7", (7, 99)), ("4-6", (4, 6)), ("2-3", (2, 3))]:
        n, d, rate = band(lo, hi)
        print(f"  score {label:<4}: {d}/{n} deleted ({rate})")

    rc = Counter(r["reason_class"] for r in deleted.values())
    if rc:
        print("\ndeletion reasons:", dict(rc.most_common()))

    flagged_del = sorted(
        (r for q, r in deleted.items() if r.get("score")),
        key=lambda r: -(r.get("score") or 0),
    )
    if flagged_del:
        print("\n=== flagged items that were deleted (score-descending) ===")
        for r in flagged_del[:40]:
            print(f"  [{r.get('score')}] {r.get('subject') or '?'} "
                  f"[{r['reason_class']}] by {r['admin']} @ {r['deleted_ts']} :: {r['reason'][:60]}")

    # Deleted but never flagged -- the scorer's misses.
    misses = [q for q in deleted if not deleted[q].get("score")]
    if misses:
        print(f"\n{len(misses)} deleted item(s) we tracked but did NOT flag (score<2) "
              f"-- scorer misses to review:")
        for q in misses[:20]:
            print(f"  {q} [{deleted[q]['reason_class']}] :: {deleted[q]['reason'][:60]}")

    print(f"\nWrote {path}")


if __name__ == "__main__":
    main()
