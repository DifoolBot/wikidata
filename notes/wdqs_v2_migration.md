# WDQS v2 migration (2026-11-24)

WDQS is moving to v2 (QLever backend), `https://query-next.wikidata.org/sparql`.
v1 (`query.wikidata.org`, Blazegraph) may degrade from February 2027 and ends in June 2027.
v2 does not support `bd:slice`, `bd:sample`, `wikibase:mwapi`, `decodeURI` or query hints.
See https://www.wikidata.org/wiki/Wikidata:SPARQL_query_service/WDQS_backend_update/Migrate

## Changed

| Script | Before | After |
|---|---|---|
| `projects/addlabel/wdqs_client.py` | query.wikidata.org; pywikibot default endpoint | `WDQS_ENDPOINT` = query-next; pywikibot `SparqlQuery(endpoint=…, entity_url=…)`; `query_wdqs_simple` now sends the DifoolBot User-Agent and raises on HTTP errors |
| `projects/addlabel/addlabel_bot.py` `scan_slice` | `SERVICE bd:slice` over `?item wdt:{pid} ?authid` | ordered subquery `ORDER BY ?item ?authid LIMIT 100000 OFFSET index`; filters (P214, Q5, rank, no en/mul label) outside it, as before. Same result shape (`?item ?authid`). An empty window no longer ends the scan unless a 1-row probe shows the offset is past the end |
| `projects/addlabel/languages.py` (language list query) | `BIND(COALESCE(..., ?languageLabel) AS ?c)` with the label from `SERVICE wikibase:label` | en label via `OPTIONAL rdfs:label` + QID fallback, then the BIND |
| `projects/viaf_deconflate/prime_cache.py` `--fetch` | `bd:slice` on query-main, 200k windows, Q5 filter outside the slice | ordered subquery with the Q5 filter inside, 100k pages on query-next, 5 s apart; a short page is checked with a 1-row probe at the next offset |
| `projects/add_class/stub_table.py` (tracked), `plural.py`, `navbox_check.py`, `navbox_rows.py` (untracked, main checkout only) | query.wikidata.org fallback | query-next.wikidata.org, queries unchanged |

## Test results (read-only, 2026-11-24)

- addlabel scan windows on v2: GND P227 offset 0 → 3062 candidate rows (5.5 s); offset 1,000,000 → 1415 (4.8 s); LoC P244 offset 500,000 → 187 (3.8 s); GND offset 50,000,000 → 0 rows, probe says past the end → scan stops.
- addlabel lookup queries (languages.py / countries.py), v1 vs v2:
  identical for 6 of 9; the language-list query is identical after the fix (17,095 rows each; before the fix `?c` was unbound for 4,686 languages on v2);
  countries.py:1650 times out on v1, answers on v2 (11,296 rows);
  non-Latin scripts list: v2 serves astral-plane characters (CJK Ext-B etc.) as U+FFFD (server-side), so ~105 single-CJK-character labels differ. Harmless: they never match a language's script name.
- add_class query shapes (VALUES+UNION+labels, COUNT GROUP BY, label lookup, skos:altLabel, qualifier query, navbox classes): identical results on v1 and v2; the class-usage COUNT timed out on v1 (empty 200) and answered on v2 in 0.4 s.
- prime_cache `--fetch` full run on v2 (no cache written): 43 pages in 794 s, 4,284,309 (item, VIAF) pairs on 4,200,962 humans, no truncated page; `multi` = 67,776 items, `long` = 911,830. The 2026-09-14 dump gave multi 71,741 / long 903,085; 65,246 multi items are in both. The drop fits two months of deconflation work on exactly these items, plus the dump having been a different source.

## v2 quirks found

- `COUNT(*)` gives HTTP 500 (`{"details":"Error id …"}`); `COUNT(?var)` works.
- A response that runs past ~60 s is cut off but still answers HTTP 200 (a 500k-row CSV page came back with 373k rows). Keep pages small (100k rows ≈ 7–15 s) and check short pages.
- Astral-plane characters come back as U+FFFD.
- `SERVICE wikibase:label` works, but its variables are bound only after the rest of the group, so a `BIND` that uses `?xLabel` sees nothing.
- The standard Wikidata prefixes are predeclared, as on v1.

## Follow-ups

- The addlabel scan offset stored per property (`get_index`/`set_index`) was a position in Blazegraph's slice order; the new order is `ORDER BY ?item ?authid`, so an old stored offset points somewhere else in the list. Reset it to 0 for a full pass, or accept that some items are skipped or repeated once.

## viaf_bot (daily Toolforge job), 2026-11-24

- Work list (`_execute_qlever_query`): WDQS v2 first, qlever.dev as fallback; each endpoint keeps the
  old retry policy; `QleverQueryError` (run stops, same source next day) only when both fail. Requests
  now carry the DifoolBot User-Agent.
  Comparison of the work-list query: P691 62,929 rows in 4.8 s on v2 vs 62,934 in 17.5 s on qlever.dev;
  P227 30,096 vs 30,097; P244 1,563 vs 1,560; qlever.dev returned 429 twice during the test.
- Duplicate check (`get_duplicate_qids` via `viaf/wdqs_client.py`): v1 → v2.
- The unused `bd:slice` scan (`iterate` / `iterate_index`) is removed.
- Tested read-only: normal fetch (v2), v2 failing → qlever.dev, both failing → `QleverQueryError`,
  duplicate check on VIAF 113230702 (finds Q42 when excluding Q1, nothing when excluding Q42).
- Deploy: merge to main, push, then on Toolforge `become difoolbot; cd ~/wikidata; git pull`.
  No `jobs.yaml` change.
