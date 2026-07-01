"""
call_bot.py

Debug entry point for the remove_import_ref bot.

Runs the full per-item pipeline (find the target user's wbsetreference-add
revisions → diff rev/parent → match P143 import refs with no sitelink now or at
add-time) against a single Wikidata item, reusing the bot's real
``process_item`` so there is no logic drift from a normal run.  Set a breakpoint
anywhere in reference_checker.py / wikidata_api.py and step through one item.

How to use:
  1. Edit the constants in the CONFIG block below (at minimum, ITEM).
  2. Run / debug this file.  In VS Code the bundled "Python Debugger: Current
     File" config works as-is (the .env file puts ``projects`` on PYTHONPATH).
     From a terminal:  ``cd projects && python -m remove_import_ref.call_bot``

Notes:
  - DRY_RUN=True never submits an edit; it reports every reference it *would*
    remove.  Flip to False to actually remove them from the live item.
  - Reads are anonymous, but importing the shared session logs in, so DRY_RUN
    runs are ready to flip to a real edit without re-auth.
"""

import os
import uuid

from shared_lib.wikidata_site import SITE as site

from remove_import_ref.bot import HERE, load_config, process_item
from remove_import_ref.project_map import ProjectMap
from remove_import_ref.wikidata_api import WikidataAPI

# ── CONFIG: edit these ───────────────────────────────────────────────────────
ITEM = "Q55836906"  # the Wikidata item to debug (this one matches twice)
DRY_RUN = False  # True = detect only, never submit an edit
# ─────────────────────────────────────────────────────────────────────────────

# Known matches in the starting list:
#   Q7160034  → P1559 + P1412, both P143 Spanish Wikipedia, no eswiki sitelink
#   Q61044817 → P1412
# Known non-matches: Q107293092, Q107302731, Q7175059, Q7145947, Q7139416, Q71312037


def main() -> None:
    cfg = load_config()
    batch_id = uuid.uuid4().hex[:12]

    api = WikidataAPI(site)
    pmap = ProjectMap(
        os.path.join(HERE, cfg["dbcode_cache_file"]), resolver=api.entity_claim_p1800
    )

    print(f"Debugging {ITEM} | dry_run={DRY_RUN} | editgroup={batch_id}")

    # ↓↓↓ Set a breakpoint here, or inside process_item / added_import_refs ↓↓↓
    matches = process_item(ITEM, api, pmap, cfg)

    if not matches:
        print("  no match")
    for m in matches:
        print(
            f"  {m['action']}: {m['qid']} {m['claim_property']} "
            f"{m['project_qid']}/{m['dbcode']} ref={m['ref_hash']} rev={m['revid']}"
        )
        if m["action"] == "remove" and not DRY_RUN:
            from remove_import_ref.remover import remove_reference

            remove_reference(
                site, m["qid"], m["claim_id"], m["ref_hash"], m["dbcode"], batch_id
            )


if __name__ == "__main__":
    main()
