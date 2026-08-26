# viaf_deconflate

Revisits VIAF IDs (`P214`) that were **deprecated for conflation**
(`P2241` = `Q14946528`) and works out what should happen once VIAF has split
the cluster on their side. Sibling of the `viaf` add-bot, which never touches
these (it skips any item that already has a `P214`).

**Status: dry-run by default; `--apply` performs all the edit outcomes.**
`deconflate.py` selects candidates, queries VIAF, classifies each item, and
prints a report. With `--apply` it makes the edits — add a de-conflated cluster,
relabel to `Q35773207`, un-deprecate a now-correct cluster, and stamp
`retrieved` — previewing unless `--save` is given. Review outcomes are never
auto-edited.

## Outcomes

| Outcome | Meaning | Intended edit (not yet implemented) |
|---|---|---|
| `ADD_AND_RELABEL` | de-conflated: the item's ids moved to a new, unused cluster | add the cluster at normal rank (full VIAF reference) **and** relabel the old statement `Q14946528` → `Q35773207` + stamp |
| `RELABEL_ONLY` | de-conflated: the item's ids moved to a cluster already on the item | relabel the old statement `Q14946528` → `Q35773207` + stamp |
| `CORRECT_AS_OF_NOW` | every id in the old cluster is now a non-deprecated id on this item — VIAF resolved it | **un-deprecate** (normal rank, drop the `P2241` qualifier) + stamp |
| `STILL_CONFLATED` | a second party is still in the cluster: the cluster carries a source the item also has but with a *different* value (item GND ≠ cluster GND), or a `P1889`/`P4070`/same-VIAF partner still has one of its ids in the cluster, or VIAF links ≥2 items | keep deprecated (conflation) + stamp |
| `PROBABLY_CONFLATED` | a foreign id isn't on this item and isn't tied to another item — unclear | review list |
| `LIST_REDIRECT` | old cluster now redirects | manual review list |
| `LIST_ABANDONED` | old cluster abandoned / gone | manual review list (list-first; removal is OK'd but deferred) |
| `INCONSISTENT` | IDs split across >1 *substantial* cluster, or a live VIAF disagrees — benign unmerged own-fragments (e.g. a lone RERO singleton) are ignored | manual review — the item may itself conflate two people |
| `INSUFFICIENT` | no authority ID resolved anywhere | skip (not enough evidence) |
| `ERROR` | item could not be read/evaluated | — |

*Stamp* = remove any reference that is retrieved-only, then add `retrieved` = today
(so "update, or add if absent" falls out and old bare-retrieved refs don't pile up).

Every conclusion is scoped to the subject item: the old cluster may still
conflate two *other* people, and the tool asserts nothing about that.

## Run

Dry run (read-only):

```bash
python projects/viaf_deconflate/deconflate.py --out report.txt
```

Preview the edits it would make, then commit a small batch:

```bash
python projects/viaf_deconflate/deconflate.py --max-items 30 --apply
python projects/viaf_deconflate/deconflate.py --max-items 30 --apply --save
```

`PYTHONPATH` must include `projects` and `projects/shared_lib` (the repo `.env`
already sets this).

Flags: `--pid P244` (source to start from), `--max-items`, `--max-viaf-calls`
(default 900), `--min-day-remaining` (default 100 — stop when VIAF reports this
many daily calls left, leaving headroom for the daily cron and the manual UI
tool), `--min-age-days`, `--no-dup-check`, and `--apply` / `--save` /
`--apply-limit` (default 5).

## Reuse and known simplifications (for review)

- Per-source search keys / matching come from `viaf.authority_sources`; the VIAF
  calls and the redirect/abandoned status come from `viaf.viaf_api_client`;
  selection is `shared_lib.qlever`, the duplicate check is `viaf.wdqs_client`.
- The **budget** optimization the reviewer suggested is applied: once a fetched
  cluster already lists one of the item's other IDs, that ID is not re-queried.
- Unreliable sources are **skipped** for resolution (ISNI/FAST/… from the
  add-bot's ignore config), and the classifier knows the item's existing live
  VIAF(s), so a cluster already live on the item is never proposed as an add.
  A live id still resolving to the old cluster *is* the "still holds this person"
  signal, so forward resolution subsumes the reverse check.
- `STILL_CONFLATED` fires when a live id still resolves to the old cluster **and**
  a second party is confirmed present: query-free when the cluster carries a
  source the item also has but with a different value (item GND ≠ cluster GND) or
  VIAF links ≥2 items, otherwise via a `P1889`/`P4070`/same-VIAF partner whose own
  id is checked against the live cluster. Without any such confirmation the item
  is `PROBABLY_CONFLATED` (review), never auto-stamped.
- The duplicate check prefers VIAF's own `WKP` siblings (already in hand) and
  falls back to WDQS; a WDQS outage degrades it to WKP-only (noted, not fatal).
- `Q14946528` / `Q35773207` are local constants here; promote to
  `shared_lib.constants` when the edit step is built.

## Next

- `STAMP_RETRIEVED` (add a `retrieved` date to a still-conflated statement) is
  not wired yet — ~zero volume in practice, deferred (it needs a new reference
  block).
- Emit the review outcomes (`PROBABLY_CONFLATED`, `LIST_*`, `INCONSISTENT`) as
  wikitext for a review page.
- Make the item read sleep-and-retry on maxlag (the dry run currently marks
  those `ERROR`).
- Promote `Q14946528` / `Q35773207` to `shared_lib.constants`.
