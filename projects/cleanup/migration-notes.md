# RemoveWeakReferences.js → WDCaches migration

## Loading order

Add to `common.js` before `WikidataCleanup.js`:

```javascript
// [[User:Difool/WDCaches.js]]
importScript('User:Difool/WDCaches.js');
```

In `RemoveWeakReferences.js`, replace the `mw.loader.using(...).then(init)` entry point with:

```javascript
mw.hook('wdcaches.ready').add(() => {
  mw.loader.using(['mediawiki.util', 'oojs-ui-core', 'oojs-ui-widgets']).then(init);
});
```

---

## §01 Constants — what to remove

Remove the following cache-related constants entirely (they live in WDCaches now):

```
ONE_DAY, CHUNK_SIZE, MAX_TRAVERSAL_DEPTH, FETCH_BACKOFF_MS
WIKIPEDIA_EDITIONS_CACHE_KEY, WIKIPEDIA_EDITIONS_TTL_MS
LANG_NAMES_CACHE_KEY, LANG_NAMES_TTL_MS
OBSOLETE_IDS_CACHE_KEY, OBSOLETE_IDS_TTL_MS
REGEX_CACHE_KEY, REGEX_CACHE_TTL_MS
URL_PATTERNS_CACHE_KEY, URL_PATTERNS_TTL_MS
STATED_IN_CACHE_KEY, STATED_IN_TTL_MS
URL_STRIP_CACHE_KEY, URL_STRIP_CACHE_TTL_MS, URL_STRIP_PAGE
URL_BLOCKLIST_CACHE_KEY, URL_BLOCKLIST_CACHE_TTL_MS, URL_BLOCKLIST_PAGE
SOURCE_CATEGORIES_CACHE_KEY, SOURCE_CATEGORIES_TTL_MS, SOURCE_CATEGORIES_PAGE
FETCH_FAILURE_TIMES_KEY, INDEXEDDB_NAME, INDEXEDDB_VERSION
PID_GND_ID, PID_DEUTSCHE_BIOGRAPHIE_GND_ID  (only used by shouldIgnorePattern)
```

Keep `OCC_CACHE_KEY`, `OCC_CACHE_TTL_MS`, `P31_PARENTS_CACHE_KEY`,
`P31_PARENTS_CACHE_TTL_MS` — the traversal caches remain in WikidataCleanup.

---

## §03 Utilities — what to remove

Remove these functions (now in WDCaches, re-exported on `window.WDCaches`):

- `normalizeUrl` → `WDCaches.normalizeUrl`
- `removeTrailingSlash` → `WDCaches.removeTrailingSlash`
- `cleanUrl` → `WDCaches.cleanUrl`
- `validateUrlPattern` (internal to WDCaches, not needed externally)
- `validatePropertyRegex` (internal to WDCaches)
- `sanitizePattern` (internal to WDCaches)
- `convertWikidataRegexToJS` (internal to WDCaches)
- `isArchiveUrl` → `WDCaches.isArchiveUrl`
- `analyzeWikimediaUrl` → `WDCaches.analyzeWikimediaUrl`
- `isWikimediaImportUrl` → `WDCaches.isWikimediaImportUrl`
- `compileAnchoredRegex` → `WDCaches.compileAnchoredRegex`

Keep:
- `isQid` — re-exported as `WDCaches.isQid` but used so heavily in WikidataCleanup
  that keeping a local alias `const isQid = WDCaches.isQid;` at the top is cleaner
  than replacing every call site.
- `uniq` — same reasoning; keep as `const uniq = WDCaches.isQid
  ? (arr) => [...new Set(arr.filter(WDCaches.isQid))] : uniq;` or just keep locally.
- `normalizeText`, `visualizeInvisibleChars`, `formatUrlForDisplay`,
  `parseWikibaseTime` — cleanup-specific, stay.

---

## §04 In-memory caches — what to remove

Remove these declarations entirely:

```javascript
const urlStripCache = { always: {}, recognition: {} };
const wikipediaEditionsCache = new Map();
const wikipediaLangNamesCache = new Map();
const urlBlocklistCache = { rules: [], timestamp: 0 };
const obsoleteIdProps = new Set();
const propertyRegexCache = new Map();
const propertyUrlPatternsCache = new Map();
const propertyStatedInCache = new Map();
const sourceCategoryCache = { aggregator: new Set(), community: new Set(), redundant: [] };
let indexedDBReady = false;
let indexedDB_instance = null;
```

Keep:
```javascript
const occupationParentsCache = new Map();
const p31ParentsCache = new Map();
```

---

## §05-§06 IndexedDB and localStorage helpers — remove entirely

All of sections 05 and 06 move to WDCaches. Delete:
`initIndexedDB`, `getIndexedDBStore`, `getIndexedDBReadTx`, `getIndexedDBWriteTx`,
`cache_saveIndexedDB`, `cache_loadIndexedDB`, `cache_resetIndexedDB`,
`cache_getStatusIndexedDB`, `cache_saveLocalSt`, `cache_loadLocalSt`,
`cache_resetLocalSt`, `cache_getStatusLocalSt`, `cache_getStatus`, `cache_reset`.

---

## §07 Settings — remove `enableLargeBuffers`

```javascript
// Before:
const defaultSettings = {
  autoStartPreview: true,
  enableLargeBuffers: false,
  enableHeavyComputing: false,
  enabledDetectors: { ... },
};

// After:
const defaultSettings = {
  autoStartPreview: true,
  enableHeavyComputing: false,
  enabledDetectors: { ... },
};
```

---

## §08 API helpers — remove entirely

Delete: `api_fetchWikipediaEditions`, `api_fetchContentLanguages`,
`api_fetchEntities` → replace call sites with `WDCaches.fetchEntities(qids)`,
`api_fetchAllObsoleteIdProps`, `api_fetchPropertyRegexConstraints`,
`shouldIgnorePattern`, `api_fetchPropertyUrlMatchPatterns`,
`extractQID`, `api_fetchUrlStripRules`, `api_fetchUrlBlocklist`,
`api_fetchPropertyStatedInPreferences`, `api_fetchSourceCategoryRules`.

---

## §09 Cache registry — remove entirely

Delete the entire `caches` array. The settings UI's Cache & Buffers panel
replaces its iteration of `caches` with `WDCaches.getCacheRegistry()`.

---

## §10 Fetch-failure backoff — remove entirely

Delete: `loadFetchFailureTimes`, `saveFetchFailureTimes`, `fetchFailureTimes`,
`refreshCacheWithNotify`.

In `detectConvertWikipediaStatedIn` and `detectInvalidStatedInReference`, the
pattern:
```javascript
if (!wikipediaEditionsCache.size) {
  await refreshCacheWithNotify(caches.find((c) => c.key === WIKIPEDIA_EDITIONS_CACHE_KEY));
}
```
becomes:
```javascript
if (!WDCaches.isWikipediaEdition) {
  await WDCaches.refresh('wikipediaEditions');
}
```
or simply removed — `WDCaches.init()` guarantees caches are populated before
WikidataCleanup runs.

---

## §11 Cache init — remove entirely

Delete `initCaches`. The call `await initCaches(settings)` in `initCleanupTool`
is replaced by nothing — WDCaches has already initialised by the time
`wdcaches.ready` fires.

Remove the `initCaches(settings)` call from `initCleanupTool`.

---

## §12 Claim helpers — call-site replacements

| Old | New |
|---|---|
| `obsoleteIdProps.has(pid)` | `WDCaches.isObsoleteProperty(pid)` |
| `sourceCategoryCache.aggregator.has(pid)` | `WDCaches.isAggregatorProperty(pid)` |
| `sourceCategoryCache.community.has(pid)` | `WDCaches.isCommunityProperty(pid)` |
| `sourceCategoryCache.redundant` | `WDCaches.getRedundancyPairs()` |
| `propertyStatedInCache.get(pid)` | `WDCaches.getPropertyStatedIn(pid)` |
| `wikipediaEditionsCache.has(qid)` | `WDCaches.isWikipediaEdition(qid)` |
| `wikipediaEditionsCache.get(qid)` | `WDCaches.getWikipediaEditionLang(qid)` |
| `wikipediaLangNamesCache.get(code)` | `WDCaches.getLangName(code)` |
| `urlBlocklistCache.rules` | via `WDCaches.matchBlocklist(url)` |
| `isArchiveUrl(url)` | `WDCaches.isArchiveUrl(url)` |
| `isWikimediaImportUrl(url)` | `WDCaches.isWikimediaImportUrl(url)` |
| `analyzeWikimediaUrl(url)` | `WDCaches.analyzeWikimediaUrl(url)` |
| `normalizeUrl(url)` | `WDCaches.normalizeUrl(url)` |
| `removeTrailingSlash(url)` | `WDCaches.removeTrailingSlash(url)` |
| `cleanUrl(url, opts)` | `WDCaches.cleanUrl(url, opts)` |
| `compileAnchoredRegex(p)` | `WDCaches.compileAnchoredRegex(p)` |

---

## §13 Occupation helpers — `api_fetchEntities` → `WDCaches.fetchEntities`

In `buildOccupationParents` and `buildP31Parents`, replace:
```javascript
const entities = await api_fetchEntities(toFetch);
```
with:
```javascript
const entities = await WDCaches.fetchEntities(toFetch);
```

The `caches.find(...)` + `cache_saveLocalSt(entry)` calls at the end of each
BFS loop become straightforward localStorage writes using the unchanged
`OCC_CACHE_KEY` / `P31_PARENTS_CACHE_KEY`. These two caches are still managed
entirely within WikidataCleanup; replace the `cache_saveLocalSt(occEntry)` calls
with a local helper:

```javascript
function _saveTraversalCache(key, map) {
  try {
    const entries = Array.from(map.entries()).map(([k, v]) => [k, Array.from(v)]);
    localStorage.setItem(key, JSON.stringify({
      timestamp: Date.now(), kind: "map", valueKind: "set", entries,
    }));
  } catch (e) {
    console.warn(`${TOOL_NAME}: failed to save traversal cache ${key}`, e);
  }
}
```

And a matching `_loadTraversalCache` for `initCleanupTool` startup.

---

## §14 External-ID validation — remove, replace with WDCaches call

Delete `validateExternalIdValue`. Replace all call sites with `WDCaches.validateExternalId(pid, value)`.

---

## §15 URL→property matching — remove, replace with WDCaches calls

Delete `extractId`, `matchUrlAgainstPatterns`, `matchUrlAgainstPatternsWithCleanup`.

Replace all call sites of `matchUrlAgainstPatternsWithCleanup(url)` with
`WDCaches.matchUrl(url)`. The return shape is identical.

---

## §17 detectBlocklistedUrlClaims — simplify

The inline blocklist-matching loop:
```javascript
const normUrl = normalizeUrlForBlocklist(rawVal);
for (const rule of rules) {
  if (!urlMatchesBlocklistRule(normUrl, rule)) continue;
  ...
}
```
collapses to:
```javascript
const match = WDCaches.matchBlocklist(rawVal);
if (!match) continue;
// use match.action, match.sectionLabel, match.deprecationReason
```

Delete `normalizeUrlForBlocklist` and `urlMatchesBlocklistRule`.

---

## Settings UI — Cache & Buffers panel

The panel currently iterates `caches` and calls `cache_getStatus` / `refreshCacheWithNotify` / `cache_reset`. Replace with:

```javascript
// Iterate
for (const entry of WDCaches.getCacheRegistry()) { ... }

// Status
await WDCaches.status(entry.id)

// Reload
await WDCaches.refresh(entry.id)

// Clear
await WDCaches.reset(entry.id)
```

Remove the `enableLargeBuffers` toggle from the settings dialog — it now appears
in a separate WDCaches settings dialog (or directly in the Cache & Buffers panel
as a top-level toggle that calls `WDCaches.saveSettings`).

---

## Debug helpers

Replace the `window.wd_cleanup_debug` object's cache-related entries with
delegations to `WDCaches.debug`:

```javascript
window.wd_cleanup_debug = {
  ...WDCaches.debug,
  // WikidataCleanup-specific additions remain here
};
```
