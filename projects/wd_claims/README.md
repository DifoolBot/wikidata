# wd_claims

Pulls Wikidata claim data — values, ranks, and qualifiers — via pywikibot
instead of hand-copying it out of the diff view. For each QID it prints one line
per statement with the property and value both resolved to English labels, the
rank, and any qualifiers indented underneath.

`--compare` cross-checks **exactly two** items for values that appear on both
and lists them side by side, so a rank/qualifier mismatch is easy to spot —
e.g. an identifier left live on one item and missing or wrongly-ranked on the
other after a conflation split.

For each item it then looks up its **VIAF cluster ID(s) (P214)** against
viaf.org and prints what that cluster groups together — every authority id and
any sibling Wikidata items VIAF ties to the same person — each resolved to its
Wikidata property. Printed right under the item's own claims, that makes it easy
to see what an external source believes belongs together: which authority ids
VIAF has that the item is missing, or which other QIDs VIAF still conflates into
one cluster.

A **deprecated** VIAF ID is looked up only when its *reason for deprecated rank*
(P2241) is **conflation** (Q14946528) — that cluster is exactly the conflated
blob a split is meant to untangle, so its contents are what you want to see; the
line is flagged `deprecated: conflation`. A VIAF ID deprecated for any other
reason (e.g. a *withdrawn identifier value*) is genuinely wrong rather than
merely shared, so it is noted and *not* looked up:
`--- VIAF <id>: skipping deprecated id (reason: withdrawn identifier value) ---`.
`--no-viaf` skips the VIAF lookup entirely (offline or quiet runs).

The VIAF call reuses the sibling `viaf` project (reached via `PYTHONPATH`):
`viaf.viaf_api_client.ViafApiClient` makes the request, and
`viaf.authority_sources.AuthoritySources` names VIAF's source codes by their
Wikidata property — VIAF's own codes are cryptic (`DNB` = GND, `SUDOC` = IdRef,
`WKP` = Wikidata). Codes this repo doesn't model, and Wikidata, print as-is.
The client also emits one `Remaining: day=… month=…` budget line per call (the
VIAF API is rate-limited to ~1000/day); abandoned-record redirects are followed
to the surviving cluster and shown as `cluster A -> B`.

All communication with Wikidata goes through pywikibot
(`shared_lib.wikidata_site`): item reads use `ItemPage.get()`, and labels are
resolved in one batched `wbgetentities` request per 50 ids via
`site.simple_request`. That means it inherits the repo's User-Agent, maxlag
handling and throttling. **Read-only — it never edits.**

Dates render at their stored precision rather than padding out to a full
`YYYY-MM-DD` that reads as a spurious 1 January: a year-precision value prints as
`1945`, and coarser ones as `1940s`, `20th century` or `2nd millennium`. That
keeps a precision mismatch visible in `--compare` (e.g. one item born `1945`, a
wrongly-split twin born `20th century`).

Labels prefer the English (`en`) value and fall back to the language-agnostic
`mul` label. Since 2024, a proper name that is identical across languages
(e.g. *Douglas Adams*) is often stored only under `mul`, with the per-language
copies dropped — so an en-only lookup would come back empty and print the bare
QID instead of a name.

## Run

```bash
# from the repo root (VS Code sets PYTHONPATH=projects;projects/shared_lib via .env)
python projects/wd_claims/wd_claims.py Q81280957 Q139428957
python projects/wd_claims/wd_claims.py --compare Q81280957 Q139428957
python projects/wd_claims/wd_claims.py --no-viaf Q81280957   # skip the VIAF lookup
```

Any number of QIDs may be listed for a plain dump; `--compare` requires exactly
two. Missing items are skipped with a note; redirects are followed to their
target.

## Output

Plain text to stdout. Per item:

```
=== Q5582 (Vincent van Gogh) ===
[Q5582] VIAF cluster ID: 9854560  (normal)
[Q5582] date of birth: 1853-03-30  (normal)
[Q5582] occupation: painter (Q1028181)  (normal)
Remaining: day=996 month=0
    --- VIAF cluster 9854560 (found) ---
        Bibliothèque nationale de France ID (P268): FRBNF119275919  [content: 11927591]
        GND ID (P227): http://d-nb.info/gnd/118540416  [content: 118540416]
        Library of Congress authority ID (P244): n79022935  [content: n  79022935]
        IdRef ID (P269): 027176207
        Wikidata (WKP): Q5582
```

The VIAF block prints one line per authority id in the cluster, resolved to its
Wikidata property; `[content: …]` appears only when VIAF's record notation
differs from the raw id (BNF checksum/prefix, LC spacing, RISM old/new style).
An item with no VIAF ID (or only ones deprecated for reasons other than
conflation) prints `--- VIAF: no VIAF ID (P214) on this item ---` or a
per-id `skipping deprecated id` note instead.

With `--compare`, an extra `Shared identifier values …` block groups each
`(property, value)` pair found on both items, one line per item, so differing
ranks or qualifiers line up for inspection.
