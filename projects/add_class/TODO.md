# add_class TODO

- **Same-style descriptions for template-like list items.** Many list items have descriptions that follow a
  pattern but differ in style ('Hungarian records in track cycling', 'Papua New Guinean records in Olympic
  Weightlifting'). Sync them to one style per family (capitalisation, wording), e.g. the national-records lists
  (title 'List of <nationality> records in <sport>'). First count the families and their description variants,
  then pick the majority style. This is a description edit, so it needs a separate plan and approval.
- **'is a village/town in …'** openings (~1,600 items): the class has to be country-specific (village in India, …).
- **LLM check of the stub output** (output/qs_en, ~6,300 statements) on the first sentences in opening_en.tsv.
- **sitelinks_review.tsv** (577 items with mixed sitelinks): the user moves sitelinks by hand.
- **Product models: P31 '<x> model' or P279 '<x>'?** Compare Honda CL100 (Q5892302: P31 motorcycle model
  Q23866334) with Honda CL500 (Q128304327: P279 motorcycle Q34493) (user 2026-10-30). Our stub batches give product
  models P279 (rifles, phones, cameras, motorcycles). Count which way is the majority per kind (motorcycle, firearm,
  phone, camera models) before more model rows go out; if P31 '... model' wins, map those stub classes to it.
