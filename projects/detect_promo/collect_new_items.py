#!/usr/bin/env python3
"""Daily collector for the new-item "observatory".

Companion to detect_promo_accounts.py. That tool is a live triage over the most
recent slice of the firehose (it truncates newest-first at --limit, so it cannot
cover a full day -- Wikidata creates ~15k new items/24h). This collector instead
snapshots the WHOLE 24h window once a day and appends a dated JSON file, so a
month of daily runs accumulates into a corpus you can look back over.

Fetching the raw 24h creation list is cheap (~30 paginated calls). Only per-
account SCORING is expensive, so we score just the new-account slice (where the
promo payload lives) and leave the rest as a cheap census. Scoring at collection
time also SNAPSHOTS the payload before it can be speed-deleted -- the deleted-
payload blind spot that makes retrospective analysis lie.

Two products come out of each day file:
  * census   -- "what is getting shot into Wikidata": volume, account-age mix,
                bot share, size mix, tool mix, top creators, new-account P31 mix.
  * shortlist -- new-account creations scored payload-first (the RfD candidates
                and, rarely, the warm-up "unicorns").

READ-ONLY. Fetches from the public API, writes local JSON, makes no edits.

Usage (from repo root):
    python projects/detect_promo/collect_new_items.py               # last 24h -> data/<date>.json
    python projects/detect_promo/collect_new_items.py --hours 24 --slim
    python projects/detect_promo/collect_new_items.py --hours 1     # quick smoke test
"""

import argparse
import datetime as dt
import io
import json
import os
import sys
from collections import Counter, defaultdict

# Same-directory import: reuse the scorer's API plumbing and payload logic so the
# two tools stay in lockstep. sys.path[0] is this script's dir when run directly.
import detect_promo.detect_promo_accounts as dp

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")

# Creators registered within this many days are "new accounts" -- the slice we
# score (fresh single-purpose promo accounts are the common actionable find).
# Sleeper/farming accounts (old registration, recent first edit) are NOT caught
# by a registration cutoff; run detect_promo_accounts.py --users-file over the
# collected creator list for the heavier warm-up/farming pass.
NEW_ACCOUNT_DAYS = 120


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def fetch_new_items(hours: int) -> list[dict]:
    """Every ns0 page creation by a registered user in the window (bots included
    on purpose -- they are a census category). Pages to the cutoff, no --limit
    truncation."""
    cutoff = (now_utc() - dt.timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    params = {
        "action": "query",
        "list": "recentchanges",
        "rcnamespace": "0",
        "rctype": "new",
        "rcshow": "!anon",
        "rcprop": "title|user|timestamp|comment|sizes|tags|flags",
        "rclimit": "500",
        "rcend": cutoff,
    }
    out = []
    for e in dp.paginate(params, "recentchanges"):
        out.append(
            {
                "qid": e.get("title"),
                "user": e.get("user"),
                "timestamp": e.get("timestamp"),
                "newlen": e.get("newlen", 0),
                "comment": e.get("comment", ""),
                "tags": e.get("tags", []) or [],
                "bot": bool(e.get("bot", False)),  # bot-FLAGGED edit
            }
        )
    return out


def fetch_creators(users: list[str]) -> dict:
    """Batch registration + editcount + groups (50 users/call)."""
    out = {}
    for i in range(0, len(users), 50):
        batch = users[i : i + 50]
        data = dp.api_get(
            {
                "action": "query",
                "list": "users",
                "ususers": "|".join(batch),
                "usprop": "registration|editcount|groups",
            }
        )
        for u in data.get("query", {}).get("users", []):
            out[u.get("name")] = {
                "registration": u.get("registration"),
                "editcount": u.get("editcount"),
                "groups": u.get("groups", []) or [],
            }
    return out


def age_days(registration: str | None, ref: dt.datetime) -> float | None:
    if not registration:
        return None
    try:
        return (ref - dp.parse_ts(registration)).total_seconds() / 86400
    except ValueError:
        return None


def size_bucket(n: int) -> str:
    n = abs(n or 0)
    if n < 150:
        return "lt150"
    if n < 1000:
        return "150_1k"
    if n < 10000:
        return "1k_10k"
    return "gt10k"


def compute_census(items: list[dict], creators: dict, ref: dt.datetime) -> dict:
    by_user = Counter(it["user"] for it in items)
    age_buckets = Counter()
    bot_accounts = set()
    for user, info in creators.items():
        if "bot" in info.get("groups", []):
            bot_accounts.add(user)
            continue
        a = age_days(info.get("registration"), ref)
        if a is None:
            age_buckets["unknown_reg"] += 1
        elif a < 30:
            age_buckets["new_lt30d"] += 1
        elif a < NEW_ACCOUNT_DAYS:
            age_buckets["recent_30_120d"] += 1
        else:
            age_buckets["established_ge120d"] += 1
    size_buckets = Counter(size_bucket(it["newlen"]) for it in items)
    via_ui = sum(1 for it in items if "wikidata-ui" in it["tags"])
    raw_api = sum(1 for it in items if not it["tags"])
    bot_items = sum(1 for it in items if it["bot"] or it["user"] in bot_accounts)
    return {
        "total_items": len(items),
        "unique_creators": len(by_user),
        "bot_flagged_accounts": len(bot_accounts),
        "bot_created_items": bot_items,
        "creators_by_account_age": dict(age_buckets),
        "item_size_buckets": dict(size_buckets),
        "items_via_ui": via_ui,
        "items_raw_api": raw_api,
        "top_creators": by_user.most_common(15),
    }


def score_new_accounts(
    items: list[dict], creators: dict, ref: dt.datetime
) -> tuple[list[dict], dict]:
    """Payload-score the creations by new (< NEW_ACCOUNT_DAYS) accounts, snapshot
    now. Returns (shortlist rows sorted by score desc, new-account P31 counter)."""
    new_users = {
        u
        for u, info in creators.items()
        if "bot" not in info.get("groups", [])
        and (a := age_days(info.get("registration"), ref)) is not None
        and a < NEW_ACCOUNT_DAYS
    }
    # Each new account's own created qids in the window -> circular-link detection.
    own_by_user: dict[str, set] = defaultdict(set)
    new_items = []
    for it in items:
        if it["user"] in new_users:
            own_by_user[it["user"]].add(it["qid"])
            new_items.append(it)
    if not new_items:
        return [], {}

    # Per-creator behavioural context (display tells, not scored):
    #   cluster_modality -- "mixed" when the account created some items via the
    #     web UI and others via raw API in the window. Inside an own-created
    #     linked cluster this is the "hand-seed the anchor, then script the rest"
    #     fingerprint (Roberto Manzi: person by UI, company + buildout by API).
    #     Noisy on its own -- legit editors mix too -- so it only earns attention
    #     next to a circular link or a low lexical score.
    #   span_min -- minutes between the account's first and last creation; a tight
    #     span + several items = a scripted burst.
    def _modality(it: dict) -> str:
        return "ui" if "wikidata-ui" in it["tags"] else "api"

    creator_items: dict[str, list] = defaultdict(list)
    for it in new_items:
        creator_items[it["user"]].append(it)
    cluster: dict[str, dict] = {}
    for u, its in creator_items.items():
        mods = {_modality(x) for x in its}
        ts = sorted(dp.parse_ts(x["timestamp"]) for x in its)
        cluster[u] = {
            "cluster_n_created": len(its),
            "cluster_modality": "mixed" if len(mods) > 1 else next(iter(mods)),
            "cluster_span_min": (
                round((ts[-1] - ts[0]).total_seconds() / 60, 1) if len(ts) > 1 else 0.0
            ),
        }

    def _count_refs(ent: dict) -> int:
        return sum(
            len(c.get("references", []) or [])
            for cl in (ent.get("claims", {}) or {}).values()
            for c in cl
        )

    ent_map = dp.get_entities([it["qid"] for it in new_items])
    p31 = Counter()
    shortlist = []
    n_shielded = n_zero = 0
    for it in new_items:
        ent = ent_map.get(it["qid"], {})
        user = it["user"]
        pay = dp.score_payload(it["qid"], ent, own_by_user[user], ent_map, user)
        pts = dp.payload_points(pay)
        for t in dp._claim_targets(ent.get("claims", {}) or {}, "P31"):
            p31[t] += 1
        if pay.get("has_sitelink"):
            n_shielded += 1
        elif pts == 0:
            n_zero += 1
        if pts >= 2:  # actionable floor, matches the triage table default
            info = creators.get(user, {})
            shortlist.append(
                {
                    "user": user,
                    "qid": it["qid"],
                    "score": pts,
                    "newlen": it["newlen"],
                    "registration": info.get("registration"),
                    "editcount": info.get("editcount"),
                    "label": pay.get("label"),
                    "description": pay.get("description"),
                    "domain": pay.get("domain"),
                    "is_payload_type": pay.get("is_payload_type"),
                    "has_promo_site": pay.get("has_promo_site"),
                    "has_self_id": pay.get("has_self_id"),
                    "has_editorial_id": pay.get("has_editorial_id"),
                    "username_match": pay.get("username_match"),
                    "has_sitelink": pay.get("has_sitelink"),
                    "sitelinks": pay.get("sitelinks"),
                    "circular_strong": pay.get("circular_strong"),
                    "circular_weak": pay.get("circular_weak"),
                    "n_claims": pay.get("n_claims"),
                    # display tells (not scored)
                    "created_via_ui": _modality(it) == "ui",
                    "refs_on_fresh_item": _count_refs(ent),
                    **cluster[user],
                }
            )
    shortlist.sort(key=lambda r: r["score"], reverse=True)
    stats = {
        "new_account_items": len(new_items),
        "new_account_creators": len(new_users),
        "shielded_by_sitelink": n_shielded,
        "scored_zero": n_zero,
        "flagged_ge2": len(shortlist),
        "new_account_p31": p31.most_common(20),
    }
    return shortlist, stats


def main() -> None:
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--hours", type=int, default=24, help="look-back window")
    ap.add_argument(
        "--slim",
        action="store_true",
        help="omit the raw item list from the day file (keeps census + shortlist "
        "only; much smaller, but no re-analysis later)",
    )
    ap.add_argument(
        "--out-dir",
        default=DATA_DIR,
        help="where to write <date>.json (default: data/)",
    )
    args = ap.parse_args()

    ref = now_utc()
    print(f"Collecting new items from the last {args.hours}h ...")
    items = fetch_new_items(args.hours)
    users = sorted({it["user"] for it in items})
    print(f"{len(items)} new items by {len(users)} accounts; fetching creator meta ...")
    creators = fetch_creators(users)
    print("Scoring new-account creations ...")
    shortlist, sl_stats = score_new_accounts(items, creators, ref)

    census = compute_census(items, creators, ref)
    census.update(sl_stats)

    day = {
        "date": ref.strftime("%Y-%m-%d"),
        "window_hours": args.hours,
        "window_start": (ref - dt.timedelta(hours=args.hours)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
        "generated": ref.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "census": census,
        "shortlist": shortlist,
    }
    if not args.slim:
        day["items"] = items
        day["creators"] = creators

    os.makedirs(args.out_dir, exist_ok=True)
    path = os.path.join(args.out_dir, f"{day['date']}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(day, fh, ensure_ascii=False, indent=1)

    print(f"\nWrote {path}")
    print(
        f"  census: {census['total_items']} items, "
        f"{census['unique_creators']} creators, "
        f"{census['bot_created_items']} bot-created; "
        f"new-account: {sl_stats.get('new_account_items', 0)} items, "
        f"{sl_stats.get('flagged_ge2', 0)} flagged (>=2), "
        f"{sl_stats.get('shielded_by_sitelink', 0)} shielded"
    )
    for r in shortlist[:10]:
        print(
            f"  [{r['score']}] {r['qid']} {r['user']} — {r.get('label') or '(no label)'}"
        )


if __name__ == "__main__":
    main()
