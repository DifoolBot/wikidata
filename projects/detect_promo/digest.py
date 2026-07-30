#!/usr/bin/env python3
"""Render the accumulated observatory corpus (data/*.json from
collect_new_items.py) into the two products: a per-day CENSUS trend and a
deduplicated, ranked SHORTLIST.

The collector snapshots one day per file; this reads back any range of them,
dedupes the shortlist by QID (windows overlap at the daily boundary), and prints
a human triage view. READ-ONLY -- reads local JSON, makes no API calls.

Usage (from repo root):
    python projects/detect_promo/digest.py                     # all files, score>=4
    python projects/detect_promo/digest.py --days 30 --md      # last 30 days, markdown
    python projects/detect_promo/digest.py --min-score 7       # the promo core only
    python projects/detect_promo/digest.py --mixed             # mixed-modality clusters only
"""

import argparse
import datetime as dt
import glob
import io
import json
import os
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")


def load_days(data_dir: str, days: int | None) -> list[dict]:
    """Parse every <date>.json, newest first, optionally only the last N days."""
    cutoff = None
    if days is not None:
        cutoff = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    out = []
    for path in sorted(glob.glob(os.path.join(data_dir, "*.json"))):
        try:
            d = json.load(open(path, encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            print(f"  (skipped unreadable {os.path.basename(path)})", file=sys.stderr)
            continue
        if cutoff and d.get("date", "") < cutoff:
            continue
        out.append(d)
    out.sort(key=lambda d: d.get("date", ""), reverse=True)
    return out


def tells(r: dict) -> str:
    """The compact 'why look' string for one shortlist row."""
    t = []
    if r.get("username_match"):
        t.append("user=" + r["username_match"])
    if r.get("circular_strong"):
        t.append("circ_strong")
    if r.get("circular_weak"):
        t.append("circ_weak(%d)" % len(r["circular_weak"]))
    if r.get("has_promo_site"):
        t.append("promo:" + (r.get("domain") or "?"))
    if r.get("has_self_id") and not r.get("has_editorial_id"):
        t.append("self_id")
    if r.get("has_editorial_id"):
        t.append("editorial_id")
    if r.get("cluster_modality") == "mixed":
        t.append("MIXED-mod")
    n = r.get("cluster_n_created") or 0
    if n > 1:
        t.append("cluster=%d/%gm" % (n, r.get("cluster_span_min") or 0))
    if (r.get("refs_on_fresh_item") or 0) >= 3:
        t.append("refs=%d" % r["refs_on_fresh_item"])
    if r.get("has_sitelink"):
        t.append("SHIELDED")
    return "; ".join(t)


def print_census(days: list[dict]) -> None:
    print("=== CENSUS (per day, newest first) ===")
    tot_items = tot_new = tot_flagged = 0
    for d in days:
        c = d.get("census", {})
        age = c.get("creators_by_account_age", {})
        print(
            f"{d.get('date')}: {c.get('total_items', 0):>6} items | "
            f"{c.get('unique_creators', 0):>4} creators "
            f"(new<30d={age.get('new_lt30d', 0)}, est={age.get('established_ge120d', 0)}) | "
            f"bot={c.get('bot_created_items', 0)} | "
            f"new-acct items={c.get('new_account_items', 0)} "
            f"(flagged>=2: {c.get('flagged_ge2', 0)}, shielded: {c.get('shielded_by_sitelink', 0)})"
        )
        tot_items += c.get("total_items", 0)
        tot_new += c.get("new_account_items", 0)
        tot_flagged += c.get("flagged_ge2", 0)
    if len(days) > 1:
        print(
            f"--- {len(days)} days: {tot_items} items, "
            f"{tot_new} new-account creations, {tot_flagged} flagged>=2 ---"
        )


def collect_shortlist(days: list[dict], min_score: int, mixed_only: bool) -> list[dict]:
    """Union of every day's shortlist, deduped by QID (keep highest score)."""
    by_qid: dict[str, dict] = {}
    for d in days:
        day = d.get("date")
        for r in d.get("shortlist", []):
            if r.get("score", 0) < min_score:
                continue
            if mixed_only and r.get("cluster_modality") != "mixed":
                continue
            r = {**r, "date": day}
            prev = by_qid.get(r["qid"])
            if prev is None or r["score"] > prev["score"]:
                by_qid[r["qid"]] = r
    return sorted(by_qid.values(), key=lambda r: (-r["score"], r["qid"]))


def print_shortlist(rows: list[dict], top: int, md: bool) -> None:
    shown = rows[:top]
    print(f"\n=== SHORTLIST ({len(rows)} items; showing {len(shown)}) ===")
    if md:
        print("\n| Score | Date | Item | Creator | Subject | Tells |")
        print("|---|---|---|---|---|---|")
        for r in shown:
            subj = (r.get("label") or "(no label)").replace("|", "/")[:34]
            print(
                f"| {r['score']} | {r.get('date')} | {r['qid']} | "
                f"{r['user'].replace('|', '/')[:22]} | {subj} | {tells(r).replace('|', '/')} |"
            )
    else:
        for r in shown:
            subj = (r.get("label") or "(no label)")[:32]
            print(f"{r['score']:>2} | {r['qid']} | {r['user'][:20]:<20} | {subj:<32} | {tells(r)}")

    # The dominant vanity signature, so the "feel" is one number not 100 rows.
    sig = sum(
        1
        for r in rows
        if r.get("username_match") and r.get("has_promo_site") and r.get("has_self_id")
    )
    mixed = sum(1 for r in rows if r.get("cluster_modality") == "mixed")
    circ = sum(1 for r in rows if r.get("circular_strong"))
    print(
        f"\nof {len(rows)}: {sig} match the user=subject + own-site + self-id vanity shape; "
        f"{circ} have a founder<->company circular link; {mixed} are mixed-modality clusters."
    )


def main() -> None:
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-dir", default=DATA_DIR)
    ap.add_argument("--days", type=int, default=None, help="only the last N days")
    ap.add_argument("--min-score", type=int, default=4, help="shortlist floor (default 4)")
    ap.add_argument("--top", type=int, default=40, help="max shortlist rows to show")
    ap.add_argument("--mixed", action="store_true", help="only mixed-modality clusters")
    ap.add_argument("--md", action="store_true", help="markdown table output")
    args = ap.parse_args()

    days = load_days(args.data_dir, args.days)
    if not days:
        print(f"No day files in {args.data_dir} (run collect_new_items.py first).")
        return
    print_census(days)
    rows = collect_shortlist(days, args.min_score, args.mixed)
    print_shortlist(rows, args.top, args.md)


if __name__ == "__main__":
    main()
