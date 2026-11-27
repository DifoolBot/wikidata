# add_class TODO

- **Mixed disambiguation items - need to be split** (user, 2026-11-25): before any P31 Wikimedia disambiguation page
  (Q4167410), check that every sitelink is a disambiguation page (page_props 'disambiguation' on each wiki's replica).
  If not, the item mixes a disambiguation page with an article/redirect: no P31, put it here to be split.
  - Q138349292 Premiership of Shinzo Abe: enwiki = disambiguation; jawiki 安倍政権 = redirect to 安倍内閣 (Abe cabinet).
    Split: the enwiki disambiguation to its own item, or move the ja sitelink to the item of 安倍内閣.

- **Label check: Q3592878** (user, 2026-11-25, aspfam3 review): the Wikidata label 'Evolution of highest point of
  France' differs from the enwiki title 'History of the highest point in France'. Check the labels (en/mul, and
  whether the label follows another-language title), then one correction edit (DifoolBot, plan first). Idea: scan the
  other batch items for the same label/title mismatch.
  User 2026-11-25: 'titles in en wikipedia are normalized to generics format some time after page creation'. CONFIRMED
  on aspfam3 (210): 67 pages moved on enwiki (logging, log_type=move), 22 en labels != current title, 18 of them = an
  old enwiki title (e.g. Mapping California -> History of the mapping of California; United Kingdom local elections,
  2007/District councils -> Results of ...; Pakistani philosophy; The Troubles in Killeen -> Killean, a spelling fix;
  Candidates of the 2026 BC general election -> Results ... by riding). Plus 2 labels with double spaces (Q56412833,
  Q56415240): a trick (user 2026-11-25) - their en description is the single-spaced title, and Wikibase refuses a label
  equal to the description; no other item has the plain label (WDQS v2, so not a duplicate). Fix = plain label + a real
  en description in the same edit (precedent: qs_en_aspect_labels_fix.txt 'overview of ...'), never the label alone. Not stale: label without the enwiki disambiguator ('Electoral history of the Conservative Party' vs '(UK)')
  - fine. Method: en labels via WDQS v2 (the replica has no wbt_ term tables any more), moves via the enwiki replica
  (run("en", ...)). Plan: label = current title (drop disambiguator; lowercase common-noun head per the aspect-label
  rule), only when the label is an old title of the page; old label -> alias. Scope: all our booked items with a moved
  page, not only aspfam3.

- **Statements from {{Infobox TV advert}}** (user, 2026-11-19, from Go On Lad Q5574893): our 14 P31 television
  advertisement items (output/films_added.tsv) and other pages using the infobox carry structured fields: client
  (-> P859 sponsor / P1716 brand?), product (P1716 / P921?), agency, director (P57), production company (P272),
  producer (P162), music (P406 soundtrack?), released (P577), runtime (P2047), language (P407 / P364), starring
  (P161), budget (P2130). Map the fields (check how existing advert items model them first), only linked values ->
  QIDs, plain-text names held or P2093-style; reference S143 Q328 + P4656. Reviewed batch as usual.

- **Classes to create** (user, 2026-11-10): see CLASSES_TO_CREATE.md - class items that do not exist yet, with the open
  items waiting on them; the user creates the item, sends the QID, the waiting items get a reviewed batch.

- **P360 back-fill for our list items** (user, 2026-11-12: "not now; add it to the todo"). Since 2026-11-12 every P31
  Wikimedia list article line gets P360 (is a list of) in the same batch (RULES.md). Earlier batches gave ~1,138 items
  P31 Q13406463 without P360 (count: P31 Q13406463 lines in output/qs_en_*_torun.txt). Draft P360 per item, mostly from
  the title family ('Tourist attractions in X', '... post offices in ...', 'Landmarks in X' -> architectural landmark
  Q2319498); skip items that got a P360 meanwhile; unclear kinds stay out. Reviewed batch as usual. 2026-11-12: 1,138 items, 32 already had P360; tranche 1 = output/qs_en_p360_t1_all.txt (329 items, clear title families: armorials, draft history/members/candidates -> human, terrorist incidents, ranks, years, cantons, episodes, locomotive classes, NRHP listed place ...). Left: 777 (scratchpad p360_rest.tsv; rebuild from qs_en_*_torun P31 Q13406463 lines): sports results ~160, records ~115, league record by opponent 72, records and statistics 61, Comparison of 39 (per item), long tail. Tranche 2 (sports) = output/qs_en_p360_t2_all.txt (408: national football team results -> international association football match; other national/Olympic/unofficial results -> international match; league record by opponent, RFL, poker, Soling results -> sport result; national records in athletics etc. -> national record; records and statistics / accomplishments and records -> record; career statistics -> sports data). Left after t2: 369 (scratchpad p360_rest2.tsv; Major achievements by nation held). Tranches 1+2 run and verified 2026-11-13. Tranche 3 (long tail, per title) = output/qs_en_p360_t3_all.txt (238). Run and verified 2026-11-13; list-item en labels lowercased (432) the same day. Left after t3: 131 (scratchpad p360_rest3.tsv): 'Comparison of X and Y' pairs, Ukrainian 'Monuments of national significance', Major achievements by nation, ENnie Award winners (winners are products), prose 'X by country', transactions, indexes, performances, misc. prerun_replica.py now handles extras files (no 'classified' drop; drops items that already have the property).
- **Refine plain 'aspect in a geographic region' to its topic subclass** (user 2026-11-12 found transport by country or
  region Q98374631). Q74817647 has ~40 topic subclasses with 50+ uses each (sport in a geographic region Q29791211 3,366;
  demographics Q23983664; transport Q98374631 1,014; culture Q19958368; geography Q46865913; history of a city Q28747937;
  tourism Q98374854; religion Q66374263; climate Q46997958; education Q64801076; postage stamps and postal history
  Q74614691; art Q25679497; human rights Q69358181; politics Q12332021; healthcare Q64027602; media Q110812553; television
  Q55276680; women in a geographic region Q107244961; industry Q125150968; agriculture Q105897950; Freedom of religion
  Q6593141 ...; list: SPARQL '?c wdt:P279 wd:Q74817647'). Our batches gave ~1,215 items plain P31 Q74817647; by title
  ~105 match a subclass (transport/railways 42, sport 24, media 19, energy/industry 11, LGBTQ rights 5 ...). Our own
  unreferenced statement, so replacing the value is allowed (remove + add in one edit). From now on draft the subclass
  directly (RULES.md). 2026-11-13: of the 1,215 items, 762 are from aspects2 (output/qs_en_aspects2_all_torun.txt), which was checked 2026-11-06 but NEVER RUN (still unclassified, not in done_en); refined draft output/qs_en_aspects2_refined_all.txt (257 of its P31 aspect lines -> subclass; replica prerun 760 items / 829 lines in _torun). aspects2 labels (257 Len) also unrun (22 live). Live plain aspect: 453 items, 120 matched by title -> output/qs_en_aspect_refine_live_all.txt (value change of our own unreferenced P31, one edit per item). 2026-11-13: 56/120 changed (log output/qs_en_aspect_refine_live_all_done.tsv), 64 left. PAUSED by the user while the VIAF bot runs as DifoolBot on Toolforge; resume after it finishes: python projects/add_class/aspect_refine_live.py projects/add_class/output/qs_en_aspect_refine_live_all.txt --save (skips the done ones; new summary text).
- **Same-style descriptions for template-like list items.** Many list items have descriptions that follow a
  pattern but differ in style ('Hungarian records in track cycling', 'Papua New Guinean records in Olympic
  Weightlifting'). Sync them to one style per family (capitalisation, wording), e.g. the national-records lists
  (title 'List of <nationality> records in <sport>'). First count the families and their description variants,
  then pick the majority style. This is a description edit, so it needs a separate plan and approval.
- **Plural openings ('X are / were …')** (5,038 unclassified items, counted 2026-11-04; e.g. Spectral band
  Q2882278 'Spectral bands are regions of a given spectrum'): phrases.py skips them on purpose (SENT group 2 in
  are/were), so they never reached a picks batch. Two kinds mixed together: a single thing named in the plural
  ('X were a team / duo / band / family') → P31; a kind ('Spectral bands are regions', 'Abelian varieties are …')
  → P279. Top tails: series 615, group 491, people 307, type 280, class 230, team 189, family 138, community 117.
  A round of its own after part 2: split by 'are a/an <noun>' (P31) vs 'are <plural noun>' (P279).
  RUN 2026-11-08 (2,045 items / 2,124 lines live, + side batches draft history / state courts / league records); held rows in
  plural_review.tsv wait for a second pass and the aspect pass. Was: DRAFTED 2026-11-08: output/qs_en_plural_all.txt (2,145 lines, review page qs_en_plural_all_review.html) from 17,691
  open plural openings; the 15,546 left out (plural_review.tsv 'left: …') wait for a second pass (1,593 unresolved phrases,
  1,031 'are the …', 1,009 named sets, 145 low QIDs for the history check).
- **Future-state classes removed** (user, 2026-11-09, from Q112611297: TheaAlvaro removed P31 planned event from 36 past swimming
  events): items lose a 'future' class (planned event Q1656682, film project, proposed / under-construction building, planned …) once
  the thing happened and then become unclassified, after our to-do list was built (2026-10-28) and possibly with a low QID. Round:
  replica scan of recent wbremoveclaims of P31 to future-state classes on items now without P31/P279 + an enwiki sitelink -> draft the
  realized class (film project -> film, proposed building -> building, planned event -> the siblings' event class). Also: refresh
  items_en.tsv now and then (fetch_items.py) to catch newly unclassified items. History checks treat such removals as legitimate hints.
  RECHECK ON/AFTER 2026-11-16 (user, 2026-11-09): the 927 items TheaAlvaro took P31 planned event off (output/new1444_summary.tsv,
  output/items_en_new.tsv) - TheaAlvaro adds sporting event etc. in a second step; draft only what is still unclassified then (sibling
  event class), plus the ~500 other new items via the normal passes. Rerun fresh_items.py first.
- **Title-suffix / qualifier pass** (user, 2026-11-08, from the random 100): the class from the title's tail, checked on
  classified siblings (as aspect_pass: >= 4 siblings, >= 2/3 share it): bracket qualifiers ('Kapp (headcovering)'; 14,313 open
  titles carry one, 6,940 distinct: comics 104, play 74, company 66, mythology 63, software 54, card game 36, ship 25 …; place
  qualifiers like '(India)' are disambiguators, not classes) and head-noun suffixes ('… scandal', '… Foundation', '… results').
  First cases drafted by hand in finds.py.
- **'<holiday> in <country>' model** (user, 2026-11-08; after the import): Easter in Italy Q124252446 goes in with P31 holiday
  (aspects3, as 4 of 5 'Easter in X' siblings). Harmonise the 'Easter in X' / 'Christmas in X' country pages on the richer shape:
  P31 holiday (or annual event) + P279 <holiday> (as most clean 'Christmas in X' items: P279 Christmas + P31 annual event / holiday),
  plus P1269 <holiday> + P17 <country> (RULES.md aspect-template). Siblings now mixed: P1269 Easter ×2, P279 Easter ×1, P31 aspect in
  a geographic region ×2; Christmas side also 'observance of Christmas by country' and Christmas tradition. Count and draft as a
  reviewed batch; never change a referenced statement.
- **Capitalisation round 2: list + aspect labels** (user, 2026-11-08): the items classed since the first lowercase-label round
  (DECISIONS 2026-11-05 'Lowercase aspect labels': lowercase the first letter when the head matches the item's P1269 / P279 topic and
  that topic's label is lowercase, or the siblings' labels mostly start lowercase; never an acronym or a capitalised topic) — now
  also Wikimedia list articles ('List of …', 'Comparison of …', '<club> league record by opponent', '<team> draft history', records
  in athletics), aspects (P31 aspect / aspect in a geographic region / aspect of history: 'Theories of the Black Death', 'Property
  law in …', 'Occupational hazards in …'), ethnic group by residency ('Romani people in …'), state court tiers. Sources: the run
  files of 2026-11-08 (qs_en_plural / aspects3 / drafthistory / statecourts / leaguerecord / nl_residency _torun) and the older
  aspect / list items in done_en.txt. Check the en label vs the enwiki title (sentence case) and the siblings; keep proper names
  ('Kings of the Angles', 'Detroit Lions draft history': team name stays capitalised, only the common-noun head is lowered).
  Labels only (and description if it would equal the label); a reviewed QS batch as before.
- **Lead-reproduction measure** (user, 2026-11-05; after the import): for each done item, test whether the first lead
  sentence ('X is a <adj> <class> in <place>, founded in <year> by <founder>') can be reproduced from the item's own
  statements: P31/P279 class (label or a superclass), place (P131 / P17 / P276), time (P571 / P576 / P580), maker
  (P176 / P178 / P112 / P50), demonym (P495 / P17)... Score = share of the sentence's content words / slots covered.
  A low score points to (a) a missing statement (→ feed the RULES.md extractors), (b) a wrong class, or (c) a lead that
  is not encyclopedic: promotional wording ('leading', 'premier', 'world-class'), self-description ('describes
  itself as'), slogans — a review list for those (link to detect_promo / promo_cluster). Start with a sample, using
  opening_en.tsv and a wbgetentities read of the items; no edits.
- **Items whose enwiki article was deleted** (user, 2026-11-05): our to-do set (items_en.tsv, built 2026-10-28/29)
  was unclassified items with an enwiki sitelink; when the article is deleted the item is often left with no
  sitelink and no class — a candidate for Wikidata deletion. Collect them: prerun_filter's 'no enwiki sitelink'
  drops (_dropped.tsv, 3 so far), plus a periodic re-check of all of items_en.tsv. Re-check 2026-11-08 (refresh_open.py, replica):
  94 open items lost the enwiki sitelink (output/open_en_dropped.tsv 'no enwiki sitelink'); 364 more were already deleted on Wikidata. Per candidate check Wikidata
  notability first (other sitelinks = N1, identifiers / serious sources = N2, structural need = N3: used as a value
  or in a P279 chain, backlinks) and why the article went (AfD log). Only items failing all three go on a list for
  Wikidata:Requests for deletions — the user posts the nominations; no edits by the bot.
- **Refine the 486 left on P31 system Q58778** (after the none-of fix replaced 320; list: output/system_fix_remove.tsv) (user, 2026-11-06: fine for now, refine later). Families seen in the
  openings: navigation / control / camera / imaging / communication / monitoring systems, software and computer
  systems, schemes and programmes, forest 'ecological systems' (NatureServe), sound / audio technology, school
  networks. Method as for technique: group by the head before 'system' (scratchpad sy_open.txt / sy_map.py), golden
  siblings per family via WDQS, weapon and AN/ items as models (P31 <x> model / P279 type).
- **system Q58778 group (part 2, 963): sub-patterns spotted by the user (2026-11-05)** — the in-draft ones APPLIED
  2026-11-06 (DECISIONS.md 'system Q58778'); the no-draft siblings below remain for a later round. The opening 'is a system …' gathers unrelated kinds; apply the kind rule (too generic OK, wrong kind not):
  - 'Monarchy of X' (8 in part 2: Belize, Saint Lucia, St Vincent, Grenada, St Kitts, PNG, Tuvalu, Jamaica; Fiji,
    Italy, Pakistan, China, ancient India, Canada & Indigenous peoples in no draft): class from siblings (UK, Canada,
    Australia …; lookup mon_gold).
  - '<topic> in <place>' (Welfare in Puerto Rico, Auditing in India; also 'X (Country)' = Military retirement (United
    States), Chieftaincy institution (Ghana), Workfare in the United Kingdom Q16969624, Emergency medical services in
    the Netherlands, Reservation policy in Bihar, Foreigner registration in India, Interregional caravan trade in East
    Africa; full 'in/of <Place>' scan of the group: scratchpad sys_in.txt, 29 items; the non-topic ones there are
    names of other kinds: Florida Territorial Court of Appeals court, Tennessee Colleges of Applied Technology /
    University Center of Southern Oklahoma institutions, Handbook of Australian Soils, Coastal upwelling of the South
    Eastern Arabian Sea natural phenomenon, Washington Assessment of Student Learning test, BPA Classification of
    Diseases / Classification of Indian cities classification schemes) → P31 aspect in a geographic region Q74817647 like their aspects2
    siblings (Banking in …, Welfare in …). No-draft siblings for an aspects round: Insurance in Serbia / India / UK /
    Iraq / Pakistan, Accountancy in Luxembourg, Social security in Sweden / Sri Lanka / India, Social welfare in
    Luxembourg / Mexico.
  - 'Romanisation of <language>' (Sindhi in part 2; Wu Chinese, Telugu, Libyan placenames transliteration in no
    draft): siblings (QLever 2026-11-06) Greek / Persian / Korean P279 romanization Q976327; Ukrainian / Hebrew P31
    romanisation system Q108102018 + P279 romanization → Sindhi: P31 Q108102018 + P279 Q976327 (as Ukrainian).
  - Welfare siblings (QLever 2026-11-06): Welfare in Japan P31 Q74817647 + P279 welfare spending Q12002092; Social
    security in Australia P31 Q74817647 + P279 social security Q2483208 → '<topic> in <place>' = P31 Q74817647 +
    P279 <topic class> where one fits.
  - STILL TO LOOK UP (maxlag + QLever 429 on 2026-11-05 night): monarchy siblings (mon_gold.txt), land-reform
    siblings (ref_gold.txt), occurrence golden examples (oc_gold.txt) and classes (oc_cls.txt), all in the scratchpad;
    prerun_filter on parts 6 and 7 failed at login (maxlag), rerun.
  - 'Land reform in X' (Roman republic in part 2, 'was a system first attempted …' = wrong kind; 21 more in no
    draft: Ukraine, Rwanda, Pakistan, Philippines, Ethiopia, South Vietnam, South Africa, Athens, India, Austrian
    Empire, Habsburg monarchy, Sparta, Sicily, Bolivia, ancient Egypt, Zambia, Savoy, Scotland, Namibia, Romania)
    + ~12 'Reform(s) of …' (House of Lords, date of Easter, Bulgarian orthography …): class from siblings (ref_gold).
  - '(…)' disambiguators of other kinds: Alioth (Debian) forge website, Biff (Unix) software, Cornerstone Schools
    (Michigan) charter school network, Presidential Council (Benin) governing body, National Exam (Indonesia),
    Green Star (Australia) rating system, English version schools (Bangladesh) kind of school, Alternative Learning
    System (Philippines) education programme.
- **Six-digit round** (user, 2026-11-06; 3,163 open items with <= 6-digit QIDs): breakdown by the phrases.py filters:
  1,194 no class phrase found, 977 pass (phrase groups, output/six_digit_phrases.tsv), 485 kind openings ('X is a type of
  Y' → P279 Y), 303 field openings ('In <field>, …' → strip and parse), 99 not about the title, 62 plural, 43 small rest.
  Plan: (1) kind openings, (2) field openings, (3) phrase groups with goldens, (4) fix the parser for the 1,194, then
  rounds 1-3 again. Low QIDs: history check for removed classes first (see vandalism memory).
- **Low-QID history check** (user, 2026-11-06): for the 34 open 4-5 digit items and then the 3,136 six-digit ones,
  read the history (API, maxlag=5, when the lag clears) for edits that removed P31/P279; restore those by API undo (plan
  for the user's yes, list the vandal accounts); the rest go to a normal draft (output/qs_en_lowqid_all.txt on hold).
- **New item 'hyperthermal event'** (2026-11-06, later): P279 abrupt climate change Q2956049; for Late Lutetian Thermal
  Maximum Q132477754, Weissert Event Q123488417, Latest Danian Event Q133504097, Faraoni Thermal Excursion Q128483499 (now
  occurrence in part 2), and PETM Q55826 / Eocene Thermal Maximum 2 Q1346260 (now P31 climate change Q125928 = the
  current human-caused one: a misuse). Not anoxic event Q2030030: an OAE can follow a hyperthermal (Faraoni) but is a
  different kind. Similar thin spots: SPICE Q7611164 (carbon isotope excursion), Ungava magmatic event Q7884449
  (geological event Q109975697 has 3 uses). Creating items needs the user's go-ahead.
- **New item 'competitive speech event'** (user, 2026-11-06: later): P279 intellectual competition Q50843134, as the
  common class of the speech events (Original Oratory Q7102556, Duo / Humorous / Dramatic Interpretation, Extemporaneous
  speaking Q5421795, Oral interpretation …); then move their P279 Q50843134 to it. Creating the item needs the user's
  go-ahead (a Wikidata write).
- **Brand product models** (user, 2026-11-05; after the part-2 batch): to-do items with a brand in the en label are
  often product models that no picks batch reached. Count 2026-11-05 (items_en.tsv, word match, not in done_en.txt):
  Samsung 33 open (31 in no draft; ~22 product models: Galaxy / SGH phones, Galaxy Book, Buds, Gear, T9000),
  Honda 39 open (38 in no draft; ~25: F1 engines RA260E / HR35TT / JNC1, RC161–RC170 race bikes, CB900F, Nighthawk,
  ATC / TRX ATVs, BTC-T touring cars), Peugeot 4 (BTC-T 307 / 406 Coupé, UO-8). Model them by the product-model rule:
  P31 `<x> model` + P279 `<x>` (smartphone model Q19723451, cell phone model Q19723444, motorcycle model Q23866334,
  engine model Q15057021, car model Q3231690 ...). '… series' items need their own choice (model series Q811701?), as
  RULES.md model-1 notes; skip non-products (lawsuits, events, awards, teams, dealerships). Then widen to other brands:
  count labels starting with a manufacturer name (P176 values of existing product models) across items_en.tsv.
  Brand list collected on the go during the group reviews: output/brands.tsv (brand, where seen, example item).
  Count 2026-11-06 (all brands): manufacturers = items with >= 15 P176 uses (QLever, output/manufacturers_p176.tsv,
  2,089); open to-do items (not done, in no draft) whose label starts with one: 146 brands / 1,542 items
  (output/brand_open_items.tsv, incl. homonyms: Naval, North American, Lincoln, Pioneer, Sigma, Palm, Canon of …);
  with the brand + a product word in the opening: 906 items / 140 brands (output/brand_products.tsv, with sector):
  vehicles/engines 368 (Honda 25, Ford 17, Toyota 15, Ducati 14, Mercedes-Benz 11, Suzuki 11, Sunbeam 11), computers/
  chips 166 (IBM 47, Sony 20, Intel 15), other 131, phones/tablets 85 (Samsung 16, Oppo 13), cameras/AV 57, aircraft
  52, music instruments 47 (Roland 15, Yamaha 9, Korg 6). Plan: one sector at a time, as a picks review.
  DONE 2026-11-06: rounds 1-4 + series run and verified live (vehicles 255, computers 95, devices 196, other 66,
  series 11 = 623 items). Left: the skipped lists (output/qs_en_brands_*_skipped.tsv, non-products), a consistency
  pass moving the laptop / phone lines to model series, and brands below the 15-P176 threshold or not as label prefix.
- **'is a village/town in …'** openings (~1,600 items): the class has to be country-specific (village in India, …).
- **LLM check of the stub output** (output/qs_en, ~6,300 statements) on the first sentences in opening_en.tsv.
- **sitelinks_review.tsv** (577 items with mixed sitelinks): the user moves sitelinks by hand.
- **Product models: P31 '<x> model' or P279 '<x>'?** Compare Honda CL100 (Q5892302: P31 motorcycle model
  Q23866334) with Honda CL500 (Q128304327: P279 motorcycle Q34493) (user 2026-10-30). Our stub batches give product
  models P279 (rifles, phones, cameras, motorcycles). Count which way is the majority per kind (motorcycle, firearm,
  phone, camera models) before more model rows go out; if P31 '... model' wins, map those stub classes to it.
- **Family rounds found 2026-11-06**: 'Structure of the …' (43 to-do, mostly military; siblings P31 military
  organization / Wikimedia list article / order of battle / command hierarchy) and 'Ethnic groups in …' (26 to-do; model
  Ethnic groups in Indonesia: P31 group of people in a location Q130479961 + P279 ethnic group Q41710).
- **Minorities model** (user 2026-11-02): Minorities in Ukraine (Q12132975) = P31 group of people in a location
  Q130479961 + P279 minority group Q30103 + P276 + P17. 'Ethnic groups in X' (about 30 to-do items) may follow it.
- **Issues model** (user 2026-11-02): Issues in higher education in the United States (Q65045175) = P31 aspect in a
  geographic region Q74817647 + P276 + P17. Environmental issues in Japan (Q5381294) adds P279 environmental issue Q2144359
  (9 of 11 siblings have it).
- **Which aspect class** (checked 2026-11-02, P31 uses): aspect in a geographic region Q74817647 (16,276) only with a place;
  aspect of history Q17524420 (14,075); aspect in a historical period in a geographic region Q120609028 (179); bare aspect
  Q21040055 (84) + P1269 when there is no place (Health issues in athletics). 3,153 Q74817647 items have no place statement,
  829 of them no 'in/of <Name>' in the label; some are plainly wrong (Felony murder rule, continent, Ekman transport).
- **A golden example per title family** (user 2026-10-30). For every family in families.py ('Outline of',
  'Foreign relations of', 'Murder of', ...) find one well-modelled item, the way history and culture of
  breastfeeding (Q5774799) is the model for 'History of'. Note its P31 and the other statements it carries (e.g.
  P1269 facet of / P921 main subject → the X in the title, P17 country). Then follow it: add the class from the
  example and, where the example has them, the same link statements. Write the examples in families.py's FAMILY
  table, next to the class.

- **Sexagenary cycle combinations** (~30 open: Fire Rooster, Water Ox, Wood Snake, …): no class exists; Fire Horse has P31 calendar year + calendar month. Needs a new item like "sexagenary cycle combination" (user approval) before a batch.
- **Names: sitelink model for combination pages** (user, 2026-11-07). Names round option B: the enwiki article goes on the
  given name item and the family name item gets an intentional sitelink to a redirect (badge Q70894304), so interwikis reach the
  specific items that P735/P734 use. Needs enwiki redirects (user's edit), new name items and sitelink moves; it is not a P31 batch.
- **Names: link the name item to its parts (P527 / P361)** (user, 2026-11-07; golden standard Sylvain, read 2026-11-07):
  name Q18086660 (P31 name Q82799, P1705 Sylvain) has P527 male given name Q16281827 {P3831 object has role = given name Q202444}
  and P527 family name Q18001608 {P3831 = family name Q101352}; each part has P361 part of = Q18086660 {P3831 = name Q82799}.
  All carry P1705 with the same string. Round: the ~500 combination items of the names batch (P31 name Q82799) -> find the given
  name item(s) (Q202444 / Q12308941 / Q11879590 / Q3409032) and the family name item with the same P1705 (or same label when the
  part has no P1705; never another script); write P527 {P3831} on the name item and P361 {P3831 Q82799} on each part. Skip parts
  with 2+ candidates (review list), missing parts (no item created by the bot), and existing P527/P361. Also the reverse: name items
  already on Wikidata (P31 Q82799 + P1705) without P527. QS batch, user checks and runs it, as the P31 rounds.

## Names merge list — sitelink check (done 2026-11-08)
- names_merge_list.html now shows real sitelinks per item and red warning rows (46): disambiguation sitelinks on either item (27 pages, replica_disambig.py: __DISAMBIG__ prop is the reliable signal; wiki-specific surname-disambig templates don't wrap the generic one), disambiguation P31 added by others (25 of our items), Xavi azbwiki = footballer. Rebuild marks with merge_list_warn.py.
- Groups A-C DONE 2026-11-08 (fix_red_rows.py, DifoolBot single edits): 9 pages to existing disambiguation items, 11 new ones,
  splits Dossevi / Lubis / Stankūnas / Ocleppo. 30 rows stay red. Open, user's call: group D (25 items, disambiguation P31 added
  by others), holds Kasputis Q16455537 + Šír Q10510164 (referenced family-name P31), Xavi azbwiki (footballer Q17500 has one).
  Later: note to Pi bot's operator (it doesn't match name pages to existing name items; user: 'Not now').

- [x] kind-of round 2 DONE 2026-11-16 (860 items via lead wikilinks, verified live). Was: resolve the 'type of Y' phrase through the WIKILINK in the lead sentence (the
  article's own link target, redirects followed), e.g. Mao tofu 'a form of [[fermented tofu]]' -> Fermented bean curd
  Q2901605, which the head-word check now refuses. Needs the lead wikitext (links), not the plain opening.

- [ ] aspect items: complete the model of Help:Modelling/Wikipedia_and_Wikimedia_concepts (user 2026-11-14) on the items
  our aspect batches classified (P31 Q74817647 or its topic subclass): add P17 (or P30 / P131 / P276 when there is no
  country) for the place Y, and P1269 facet of = the topic (somevalue allowed). aspect_pass.py already finds Y's item.
- [ ] 'X and Y' articles about two opposite properties / topics (introversion and extraversion) -> P31 Q134972145
  (Wikimedia article covering two opposite properties or topics). Candidates: kind-of rows held as "two things ('X and Y')"
  (92) and the 'and' titles of the other passes (and_topics.py); only true opposites, other pairs = Q21484471 + P921.

- [x] kind-of pass round 1 (2026-11-14): 2,036 items classified (kind-of 2,033 + multi-topic 2 + manual 1), verified live.
  Open from it: camera lucida Q13635459 and Agency shop Q2911320 (drafted class is an instance, pick by hand); ~2,560
  'left: unresolved' and ~700 held rows in output/kindof_review.tsv for round 2 (wikilink resolution).
- [ ] aspect refine live: 60 of 120 left (output/qs_en_aspect_refine_live_rest_all.txt), stopped 2026-11-13; resume with
  aspect_refine_live.py --save when no other DifoolBot run is active, then verify all 120.

- [ ] split lists (Help:Modelling/Wikipedia_and_Wikimedia_concepts, 'complex list'; user 2026-11-14): a list split over
  several articles ('List of minerals A', '... (A-F)', '... (part 2)', '... 1900-1949') gets P361 part of = the whole list
  (P31 list + P360 as usual). Only 3 P361 lines in the P360 back-fill so far (t1); find the split lists among our list items
  (title suffix letter / range / part / period) and their parent list item.
- [ ] 'X is a category / part / component of [[Y]]' rows (e.g. Diversified financial: 'a category of the Global Industry
  Classification Standard'): P361 part of Y, not P279 (Help:Basic membership properties: part-of for components).

- [ ] P31 = P361 = parent '<sport> at the <Games>' event (user 2026-11-16, e.g. judo at the 2022 Asian Games – women's 57 kg
  Q122910175): 25 items (15 x 2022 Asian Games, 7 x 2018 Mediterranean Games, 3 other) have P31 <the parent event> next to
  the correct P361 <parent>. Fix: replace that P31 by P31 sporting event Q16510064 (as our multi-sport batch). NOTE: the
  P31 carries a QUALIFIER (Q122910175: P155 follows = the previous weight class) -> move that P155 to the P361 statement
  (the series / sequence model: P361 {P155, P156}) before removing the P31; only unreferenced P31s
  (other users' statements). Query: ?x wdt:P31 ?p ; wdt:P361 ?p . ?p wdt:P31 wd:Q51031626 .

- [ ] P2094 competition class on multi-sport weight-class events (user 2026-11-16): our multi-sport batch only added P31 +
  P361; events like 'Judo at the 2019 European Games – Women's 48 kg' (Q74113511) need P2094 competition class = the
  sport's class item (judo: women's extra lightweight Q77218624 = women's -48 kg; extra lightweight Q77217208, half
  lightweight Q77217209, heavyweight Q77217228 ...). Derive from the title's '<Men's|Women's> <n> kg' per sport (judo,
  weightlifting, wrestling, boxing, taekwondo ...); map kg -> class item per sport and era (weight limits changed); hold
  when no class item exists. Check existing P2094 use first (judo P2094 values: extra lightweight 14, half lightweight 14 ...).
- [ ] P155 / P156 (follows / followed by) for edition / event sequences (user 2026-11-16): model = qualifiers on the
  P361 / P179 statement (series model, cf. Q74113511 P179 {P155, P156}; book series rule), not as standalone statements and
  not on P31 (Q122910175 had P155 on its P31). Candidates: the year editions (yearly predecessor / successor in the same
  series), weight-class events (previous / next class within the Games event), rounds / stages (previous / next stage).
  Decide per group: which sequence (by year or by weight), and novalue at the ends?

## Drafts 2026-11-16 evening — all RUN and verified 2026-11-17 (series, tennis, namespace, lead kinds)
- output/qs_en_series_all_torun.txt (564 lines / 282 items; series_editions.py; held series classes in series_classes.tsv)
- output/qs_en_tennis_all_torun.txt (30 lines / 10 items; tennis_events.py; 226 of 236 classified by others meanwhile)
- output/qs_en_namespace_all_torun.txt (324 lines; namespace_pages.py)
- output/qs_en_leadkinds_all_torun.txt (201 lines; lead_kinds.py: wrestling shows, finals, state amendments)
Next pattern candidates (remaining open year items, 2026-11-16): '<year> in <region> men's football' categories
(done via namespace), '... squads' (101; list + P360, rule in DECISIONS 2159), '... election' variants (~300),
'<club> in international football' (no year, 161), 'Party lists for / Results of / Parties in the ...' (~60, lists),
'Boxing / Athletics at the <Games>' (sport-at-Games pass), '... qualification' (58), '... draft' (74).

## Film-genre P31 cleanup (not our items) — added 2026-11-18
WikiProject Movies/Properties: P31 = film / short film / television film, the genre in P136 (model The White Sheik
Q18397: P31 film, P136 drama film + comedy film). Items on Wikidata with a film genre as P31 (QLever 2026-11-18):
drama film Q130232 (92), documentary film Q93204 (135), comedy film Q157443 (4), thriller film Q2484376 (2), plus
other genres (romantic comedy film Q118612349, war drama Q116456802, crime comedy film Q1788980, romantic drama film
Q117536422, concert film Q430525, travel documentary Q2670855, stop-motion animated film Q18089587 ...).
Plan: list every item with P31 = a P279* film class that is a genre (not film / short film / television film /
television special / TV commercial / music video / jukebox musical / silent film, see FILM_KEEP in lead_class.py);
per item: -P31 genre, +P31 film (short / TV film where the item says so), +P136 genre (skip if already there);
mind referenced P31 statements (never change a referenced statement: remove only if the refs are Wikipedia imports).
Our own 3 items are in output/qs_en_fix_classes_all.txt.

- Before running the lead-class QS: re-run `python projects/add_class/prerun_replica.py output/qs_en_leadclass_slice_all.txt` (rows drafted from held during the 2026-11-19 review were never freshness-checked).

- Later round (extras, user 2026-11-26): end dates / states on former things that the lead states: P576 dissolved/demolished date, P3999 closure date, P5817 state of use, P5816 state of conservation (see FORMER_MODEL.md). Not in the P31/P279 rounds.
- Later round (user 2026-11-26): proposed / planned / cancelled structures that add_class gave the plain kind (railway station, tunnel ...) -> P31 a project descendant (proposed railway station Q28109487, proposed tunnel Q27464969, proposed building or structure Q811683 ...). Find them by lead words (proposed / planned / cancelled / never built) on done_en items.
