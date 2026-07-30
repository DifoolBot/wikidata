# detect_promo

Read-only detector for the **"warm-up gnome + promo payload"** account
signature (the Johnpacklamber1 pattern): an operator warms up an account with
lots of formulaic *"Added missing description"* term edits to build a
non-single-purpose history, then drops a small self-referential promo cluster
(a founder + their company, interlinked, no editorial identifier).

It **makes no edits and nominates nothing** — it prints a ranked review list
for a human. The point is to catch the *operator/network*, not the item (RfD
already catches items); an operator invests in a reusable account, so the win
is spotting the repetition and the siblings.

## Usage

Run as modules with `projects/` on `PYTHONPATH` (VS Code sets this via
`.vscode/settings.json`; a plain shell or the daily cron must export it:
`export PYTHONPATH=projects` from the repo root — required because the collector
imports `detect_promo.detect_promo_accounts`).

```bash
# from repo root
python -m detect_promo.detect_promo_accounts --hours 24        # live window scan
python -m detect_promo.detect_promo_accounts --hours 72 --max-accounts 80
python -m detect_promo.detect_promo_accounts --user Johnpacklamber1  # score one account
```

Uses only the public Wikidata API (no Toolforge DB). `quarry.sql` is the bulk
companion for scanning all recent accounts at once (network detection).

## Observatory (daily census + shortlist)

`detect_promo_accounts.py --hours N` is a *live triage* of the most recent slice
only: it fetches newest-first and truncates at `--limit`, and Wikidata creates
~15k new items/24h, so **`--limit` — not `--hours` — is the real window bound**.
A bigger `--limit` never covers a full day cheaply; the highest-scoring promo
accounts sit earlier in the window than a 500-item pull ever reaches.

For full-day coverage, two collectors accumulate a corpus instead:

```bash
# 1. collect: snapshot the WHOLE prior 24h -> data/<date>.json (run daily via cron)
python -m detect_promo.collect_new_items            # add --slim to drop raw items

# 2. digest: render the accumulated data/*.json (READ-ONLY, no API)
python -m detect_promo.digest --days 30 --md        # census trend + ranked shortlist
python -m detect_promo.digest --min-score 7         # the promo core
python -m detect_promo.digest --mixed               # mixed-modality clusters only
```

Each day file holds two products:

- **census** — "what is getting shot into Wikidata": item volume, creators by
  account age (new <30d / recent / established), bot share, size/tool mix, top
  creators, new-account P31 mix. Fetching this is cheap (~30 paginated calls).
- **shortlist** — new-account (registered < 120d) creations, **payload-scored
  and snapshotted at collection time** (so a speed-deleted payload is still in
  the corpus — the deleted-payload blind spot, closed). Scoring the whole day is
  what's expensive, so it is bounded to the new-account slice where promo lives.

**Empirically the common actionable find is payload-only**, not the warm-up
conjunction: fresh single-purpose accounts whose signature is
`user=subject + own-website + self-issued-id` (SEO/COI vanity items). The
warm-up "unicorn" is rare (and partly *invisible* — see limitation 1 below).
Non-scored **display tells** aid triage: `cluster_modality` (mixed = hand-seed
the anchor via UI, then script the rest via API), `cluster_span_min` (scripted
burst), and `refs_on_fresh_item` (notability laundering). Sleeper/farming
accounts (old registration, recent first edit) are *not* caught by the 120-day
cutoff — feed the collected creators to `--users-file` for the heavier pass.

The daily snapshot is a local scheduled task (`collect_new_items.py`, writes to
`data/`, gitignored). Note: the web-UI edit tag is `wikidata-ui`, not the
human-readable "Wikidata user interface" — matching the display name silently
zeroes every `via_ui`/`ui_frac` signal.

### Tracking deletions (validation loop)

```bash
python -m detect_promo.track_deletions     # cross-ref corpus vs the deletion log
```

Scans the public ns0 deletion log (`logevents letype=delete`) over the corpus
window and cross-references every tracked QID, accumulating into
`data/deletions.json`. Two products: **precision** — the delete rate of the
shortlist *by score band*, with the reason (RfD / spam-promo / empty / notability)
and closing admin; and **misses** — items we tracked that were deleted but
*scored < 2*, i.e. the scorer's blind spots to review. **Mind the lag:** RfD runs
~a week and admins batch-close, so early delete rates are low and undifferentiated
— the precision signal only firms up once the corpus is 1–2 weeks deep. Empty/test
deletions are not scorer failures (an empty item is not a promo payload); the
misses worth reading are the `spam/promo` and `notability` ones.

## Scoring (starter weights — tune on real output)

- **warmup_pts** is *gated on the boilerplate fraction* — generic "many small
  fast edits" describes every legit gnome/bot, so it must not drive the score.
  Boilerplate >= 0.8 -> 4, >= 0.5 -> 3, >= 0.3 -> 2, else 0; tool-speed bursts,
  a high revert rate (AI-description errors), and **never having used the web
  UI** (`ui_frac == 0`, i.e. raw-API/scripted from the first edit) only
  corroborate -- they add points only when the boilerplate gate is already
  open, so legit untagged bots/tools are never flagged on their own.
  `raw_api_frac` (edits with NO tag at all) further separates a hand-rolled
  script/OAuth (high, like Johnpacklamber1's 95%) from a recognised tool
  (tagged; raw_api ~0%).
- **autoconfirmed-farming** (+2): a *front-loaded, boilerplate-heavy opening
  burst* that trips autoconfirmed at the minimum. Per
  [Wikidata:Autoconfirmed_users](https://www.wikidata.org/wiki/Wikidata:Autoconfirmed_users)
  the gate is **>= 50 edits AND first edit >= 4 days old** (age from the *first
  edit*, not registration — so this also catches sleeper accounts). Reaching it
  is the point: autoconfirmed edits are **patrolled automatically** (they skip
  the patrol queue), mass-editing tools unlock, and the CAPTCHA drops. The
  signal requires BOTH front-loading (first 50 edits burned inside the 4-day
  window) AND boilerplate in those 50 — front-loading alone is a fast genuine
  newbie; boilerplate alone is a gradual gnome. Scores even when the *recent*
  sample has gone quiet (farmed then dormant). Validated: Johnpacklamber1 burned
  50 edits in 1.78 days at 96% boilerplate, autoconfirmed exactly 4 days after
  its first edit.
- **payload_pts** = self-referential cluster link (+3, the hard-to-fake tell),
  promo website P856 on a fresh person/org (+2), person/org type (+1),
  self-issued-only identifiers (+1). "No editorial identifier" is deliberately
  **not** scored: at creation time almost everything lacks one.

Flag = **warmup >= 2 AND payload >= 3** (the conjunction). Warm-up alone is not
flagged — adding missing descriptions is legitimate gnome work.

## What the first run showed (findings)

- **Fingerprint works:** Johnpacklamber1 scores warmup 6/6 (boilerplate 98%,
  15 edits/min bursts). After gating on boilerplate, every legit prolific
  editor/bot in a live sample scored 0 — false positives on legit accounts
  dropped to zero.
- **Two variants caught:** the warm-up operator (via boilerplate) and the crude
  single-purpose payload account (low edits + promo item).
- **Two real limitations, confirmed live:**
  1. **Deleted payloads are invisible.** `usercontribs` omits deleted edits, so
     scoring a *past* account whose payload was already deleted shows only the
     warm-up. Live-window detection (the item still exists) is where the payload
     half works; for history you need admin deleted-contribs or the deletion log.
  2. **Identifiers lag creation.** A brand-new item almost never has an editorial
     authority ID yet, so "no editorial ID" cannot gate at creation — the real
     payload tells are promo + circular + self-issued-only.

## Next steps

- Run `quarry.sql` on Quarry to list all boilerplate-dominant accounts in the
  last 30 days; **multiple accounts sharing the fingerprint = a network**, which
  is the high-value deliverable (one operator block vs. endless item RfDs).
- If the network is real, promote the live-window scan to an EventStreams
  watcher on Toolforge and persist scores; keep it read-only, feeding an admin.
- Tune weights/allowlists (`EDITORIAL_ID_PROPS`, the boilerplate regex) on the
  Quarry output before trusting thresholds.
