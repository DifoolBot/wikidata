"""Offline unit tests for the sectioned book.txt parsing added for the one-file
WORK + N-editions format (split_sections / inherit_work_fields). The interactive
confirm/create path is exercised by make_book's dry run.

Run with:
    python -m pytest projects/shared_lib/test_book_paste.py -v
"""

from shared_lib.book_paste import (
    _split_names,
    inherit_work_fields,
    parse_metadata,
    split_sections,
    work_edition_labels,
)


def test_split_names_keeps_cjk_only_name():
    # A pure-CJK contributor (no ASCII letters) must survive the "(s)" residue filter.
    assert _split_names(["中本浩"]) == ["中本浩"]
    assert _split_names(["何森健"]) == ["何森健"]


def test_split_names_drops_label_residue_and_splits():
    assert _split_names(["(s)"]) == []
    assert _split_names(["-"]) == []
    assert _split_names(["Smith, Jones and 中本浩"]) == ["Smith", "Jones", "中本浩"]


def test_parse_metadata_ignores_leading_comments():
    # leading '#' comments (even with a colon) must not pollute the title block / fields
    p = parse_metadata("# NO ISBN: it's a price\n# note 2\nTitle: Turbo Prolog\nSubtitle: x\n")
    assert p["_titleblock"] == []
    assert p["title"] == ["Turbo Prolog"] and p["subtitle"] == ["x"]

RARE_SUGARS = """# one work, two editions
[work]
Title: 希少糖秘話
Title kana: キショウトウヒワ
Title romaji: Kishōtō hiwa
Title translation: The secret story of rare sugars
Author: 何森健 [Q17193319]
Subjects: 希少糖 [Q11480900]
Language: ja

[edition ja]
Title: 希少糖秘話
Publisher: 希少糖生産技術研究所
Published: 2013-01
ISBN: 978-4-9906839-0-0

[edition en]
Title: The secret story of rare sugars
Translator: Shigeyuki Tajima [Q135811713]
Publisher: Izumoring
Published: 2016-09
"""


def test_split_sections_none_is_legacy():
    # A file with no headers is the legacy single block: whole text back, no editions.
    text = "Title: Foo\nAuthor: Bar\n"
    assert split_sections(text) == (text, [])


def test_split_sections_work_and_editions():
    work_text, editions = split_sections(RARE_SUGARS)
    wp = parse_metadata(work_text)
    assert wp["title"] == ["希少糖秘話"]
    assert wp["title_romaji"] == ["Kishōtō hiwa"]
    assert wp["subjects"] == ["希少糖 [Q11480900]"]
    assert [lang for lang, _ in editions] == ["ja", "en"]
    ja = parse_metadata(editions[0][1])
    en = parse_metadata(editions[1][1])
    assert ja["title"] == ["希少糖秘話"] and ja.get("title_romaji") is None
    assert en["translators"] == ["Shigeyuki Tajima [Q135811713]"]
    assert en["publisher"] == ["Izumoring"]


def test_split_sections_bare_edition_has_empty_lang():
    _work, editions = split_sections("[work]\nTitle: X\n[edition]\nISBN: 1\n")
    assert editions[0][0] == ""


def test_split_sections_no_work_header_uses_preamble():
    # No [work] header -> the preamble before the first [edition] is the work block.
    work_text, editions = split_sections("Title: Solo\nAuthor: A\n[edition en]\nISBN: 1\n")
    assert parse_metadata(work_text)["title"] == ["Solo"]
    assert [lang for lang, _ in editions] == ["en"]


def test_inherit_always_contributors():
    work = parse_metadata(RARE_SUGARS.split("[edition")[0].split("[work]")[1])
    ed = {"title": ["The secret story of rare sugars"]}
    inherit_work_fields(work, ed, same_lang=False)
    assert ed["authors"] == ["何森健 [Q17193319]"]       # inherited
    assert "title_romaji" not in ed                       # NOT inherited (different language)


def test_inherit_same_lang_title_readings_but_not_translation():
    work = parse_metadata(RARE_SUGARS.split("[edition")[0].split("[work]")[1])
    ed = {}                                               # ja edition states nothing of its own
    inherit_work_fields(work, ed, same_lang=True)
    assert ed["title"] == ["希少糖秘話"]
    assert ed["title_kana"] == ["キショウトウヒワ"]
    assert ed["title_romaji"] == ["Kishōtō hiwa"]
    assert "title_translation" not in ed                  # P2441 stays on the work only


def test_inherit_does_not_override_stated_fields():
    work = parse_metadata(RARE_SUGARS.split("[edition")[0].split("[work]")[1])
    ed = {"title": ["Own title"], "authors": ["Someone [Q1]"]}
    inherit_work_fields(work, ed, same_lang=True)
    assert ed["title"] == ["Own title"]                   # kept
    assert ed["authors"] == ["Someone [Q1]"]              # kept


def test_work_edition_labels_uses_translation_titles():
    # Korean work, no romaji -> base labels are just {mul: original}. Each translation
    # edition supplies label/<lang>; original label added; mul untouched.
    base = {"mul": "브로콜리 펀치"}
    edition_titles = {"ko": "브로콜리 펀치", "en": "Broccoli Punch", "pl": "Brokułowy cios"}
    labels = work_edition_labels(base, "ko", "브로콜리 펀치", edition_titles)
    assert labels == {
        "mul": "브로콜리 펀치",
        "ko": "브로콜리 펀치",
        "en": "Broccoli Punch",
        "pl": "Brokułowy cios",
    }


def test_work_edition_labels_translation_wins_over_fallback_but_not_mul_or_orig():
    # A romaji/gloss fallback put en=romanization; a real en edition title overrides it,
    # while mul and the original-language label are left as-is.
    base = {"ja": "希少糖秘話", "mul": "Kishōtō hiwa", "en": "Kishōtō hiwa"}
    labels = work_edition_labels(base, "ja", "希少糖秘話",
                                 {"ja": "希少糖秘話", "en": "The Secret Story of Rare Sugars"})
    assert labels["mul"] == "Kishōtō hiwa"                 # fallback kept for mul
    assert labels["ja"] == "希少糖秘話"                     # original untouched
    assert labels["en"] == "The Secret Story of Rare Sugars"  # real edition title wins


def test_work_edition_labels_no_editions_is_identity_plus_orig():
    base = {"mul": "브로콜리 펀치"}
    assert work_edition_labels(base, "ko", "브로콜리 펀치", None) == {
        "mul": "브로콜리 펀치", "ko": "브로콜리 펀치",
    }
