"""Orchestration: for each listed item, find P143 import references that the
target user added while the item had no sitelink to that wiki -- then (now and
historically), and remove them.

Dry-run by default. Pass --save to actually edit (requires pywikibot auth).

    python -m projects.remove_import_ref.bot                 # dry-run, whole list
    python -m projects.remove_import_ref.bot --limit 3       # dry-run, first 3
    python -m projects.remove_import_ref.bot --save          # really edit
"""

from __future__ import annotations

import argparse
import os
import time
import uuid
from typing import Dict, List, Set

import yaml

from .project_map import ProjectMap
from .reference_checker import (
    added_import_refs,
    has_sitelink,
    reference_present,
)
from .wikidata_api import WikidataAPI

HERE = os.path.dirname(os.path.abspath(__file__))


def load_config() -> Dict:
    with open(os.path.join(HERE, "config.yaml"), encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_items(path: str) -> List[str]:
    with open(path, encoding="utf-8") as fh:
        return [ln.strip() for ln in fh if ln.strip() and not ln.startswith("#")]


def load_done(path: str) -> Set[str]:
    if not os.path.exists(path):
        return set()
    with open(path, encoding="utf-8") as fh:
        return {ln.split("\t", 1)[0].strip() for ln in fh if ln.strip()}


def append_line(path: str, line: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def process_item(qid: str, api: WikidataAPI, pmap: ProjectMap, cfg: Dict) -> List[Dict]:
    """Return a list of match dicts (one per removable reference). A match means
    all three conditions hold; removal itself is handled by the caller."""
    matches: List[Dict] = []

    revisions = api.user_revisions(qid, cfg["target_user"])
    add_revs = [r for r in revisions if "wbsetreference-add" in (r.get("comment") or "")]
    if not add_revs:
        return matches

    current = api.current_entity(qid) or {}

    for rev in add_revs:
        revid, parentid = rev["revid"], rev.get("parentid")
        if not parentid:
            continue
        ents = api.entities_at_revisions([revid, parentid])  # one request
        entity_rev = ents.get(revid)
        entity_parent = ents.get(parentid)
        if entity_rev is None or entity_parent is None:
            continue

        for added in added_import_refs(entity_rev, entity_parent):
            dbcode = pmap.dbcode(added.project_qid)
            if not dbcode:
                continue  # unknown project; log separately in real run

            # Condition 3: no sitelink at the moment the ref was added.
            if has_sitelink(entity_rev, dbcode):
                continue
            # Condition 2: still no sitelink now.
            if has_sitelink(current, dbcode):
                continue
            # Reference must still be present (unchanged) on the live item.
            if not reference_present(current, added.claim_id, added.ref_hash):
                continue
            # Decision: never auto-remove a reference that carries other snaks
            # besides the P143 import -- log it for manual review instead.
            action = "remove" if added.sole_import else "REVIEW_multi_snak_ref"
            matches.append({**added.__dict__, "qid": qid, "dbcode": dbcode,
                            "revid": revid, "action": action})
    return matches


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--save", action="store_true", help="actually edit (default: dry-run)")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    cfg = load_config()
    dry_run = not args.save

    # One EditGroups batch id for the whole run, so every edit groups together
    # at editgroups.toolforge.org for one-click review/revert.
    batch_id = uuid.uuid4().hex[:12]

    import pywikibot
    site = pywikibot.Site("wikidata", "wikidata")  # one session for read + write
    api = WikidataAPI(site)
    pmap = ProjectMap(
        os.path.join(HERE, cfg["dbcode_cache_file"]),
        resolver=api.entity_claim_p1800,
    )

    items = load_items(os.path.join(HERE, cfg["input_file"]))
    done = load_done(os.path.join(HERE, cfg["done_file"]))
    if args.limit:
        items = items[: args.limit]

    print(f"{'DRY-RUN' if dry_run else 'SAVE'}: {len(items)} items "
          f"({len(done)} already done)  editgroup={batch_id}", flush=True)

    for qid in items:
        if qid in done:
            continue
        try:
            matches = process_item(qid, api, pmap, cfg)
        except Exception as exc:  # noqa: BLE001 -- keep the batch alive
            print(f"  {qid}: ERROR {exc}")
            append_line(os.path.join(HERE, cfg["log_file"]), f"{qid}\tERROR\t{exc}")
            continue

        if not matches:
            append_line(os.path.join(HERE, cfg["done_file"]), f"{qid}\tno-match")
        for m in matches:
            line = (f"{m['qid']},{m['claim_property']},{m['project_qid']},"
                    f"{m['dbcode']},{m['ref_hash']},{m['revid']},{m['action']}")
            if m["action"] == "remove":
                print(f"  MATCH {line}", flush=True)
                append_line(os.path.join(HERE, cfg["matched_file"]), line)
                if not dry_run:
                    from .remover import remove_reference
                    remove_reference(site, m["qid"], m["claim_id"], m["ref_hash"],
                                     m["dbcode"], batch_id)
            else:  # multi-snak ref: log for review, never edit
                print(f"  REVIEW {line}", flush=True)
                append_line(os.path.join(HERE, cfg["skipped_file"]), line)
            if not dry_run:
                append_line(os.path.join(HERE, cfg["done_file"]),
                            f"{m['qid']}\t{m['action']}")

        time.sleep(cfg.get("sleep_between_items_secs", 0.5))


if __name__ == "__main__":
    main()
