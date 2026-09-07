"""Offline unit tests for book_paste.py's new fields: native non-Latin title readings
(P1814/P2125/P2441 qualifiers on P1476/P1680), translator (P655) and CiNii NCID (P1739).

Run with:
    python -m pytest projects/shared_lib/test_book_paste.py -v
"""

import shared_lib.constants as wd
from shared_lib.book_paste import build_edition, build_work, parse_metadata


def _facts(**over):
    """A complete facts dict (as confirm_facts returns), overridable per test."""
    f = dict(
        title="", title_en=None, subtitle=None,
        title_kana=None, title_romaji=None, title_translation=None,
        subtitle_kana=None, subtitle_romaji=None, subtitle_translation=None,
        lang_code="ja", lang_qid="Q5287",
        work_type_qid="Q47461344", authors=[], editors=[], translators=[],
        publisher_qids=[], pub_name=None, place_qid=None, date=None,
        isbn10=[], isbn13=[], pages=None, edition_no=None, doi=None, lccn=None,
        is_ebook=False, subject_qids=[], series_qid=None,
        ol_work=None, ol_edition=None, ia_id=None, full_url=None, oclc=None, ncid=None,
    )
    f.update(over)
    return f


def _find(specs, pid):
    return [s for s in specs if s[0] == pid]


# --------------------------------------------------------------- parse

def test_parse_new_labels():
    blob = (
        "Title: 希少糖秘話\n"
        "Title kana: キショウトウヒワ\n"
        "Title romaji: Kishōtō hiwa\n"
        "Title translation: The secret story of rare sugars\n"
        "Translator: Shigeyuki Tajima [Q135811713]\n"
        "CiNii: BB14197516\n"
    )
    p = parse_metadata(blob)
    assert p["title"] == ["希少糖秘話"]
    assert p["title_kana"] == ["キショウトウヒワ"]
    assert p["title_romaji"] == ["Kishōtō hiwa"]
    assert p["title_translation"] == ["The secret story of rare sugars"]
    assert p["translators"] == ["Shigeyuki Tajima [Q135811713]"]
    assert p["ncid"] == ["BB14197516"]
    # "Title kana"/"Title romaji" must not be swallowed by the shorter "title" label
    assert "希少糖秘話" not in p["title_kana"]


# --------------------------------------------------------------- title readings

def test_title_readings_become_p1476_qualifiers():
    facts = _facts(title="希少糖秘話", title_kana="キショウトウヒワ",
                   title_romaji="Kishōtō hiwa",
                   title_translation="The secret story of rare sugars")
    _, _, wspecs = build_work(facts)
    title = _find(wspecs, wd.PID_TITLE)[0]
    assert title[1] == ("希少糖秘話", "ja") and title[2] == "monolingual"
    quals = dict((q[0], q[1]) for q in title[3])
    assert quals[wd.PID_NAME_IN_KANA] == "キショウトウヒワ"
    assert quals[wd.PID_REVISED_HEPBURN_ROMANIZATION] == "Kishōtō hiwa"
    assert quals[wd.PID_LITERAL_TRANSLATION] == ("The secret story of rare sugars", "en")


def test_no_readings_leaves_plain_title():
    _, _, wspecs = build_work(_facts(title="Plain Book", lang_code="en"))
    title = _find(wspecs, wd.PID_TITLE)[0]
    assert len(title) == 3  # no qualifiers tuple appended


def test_subtitle_readings_on_p1680():
    facts = _facts(title="張赫宙の日本語文学", subtitle="植民地朝鮮/帝国日本のはざまで",
                   subtitle_kana="ショクミンチチョウセンテイコクニホンノハザマデ",
                   subtitle_romaji="Shokuminchi Chōsen | teikoku Nihon no hazama de")
    _, _, wspecs = build_work(facts)
    sub = _find(wspecs, wd.PID_SUBTITLE)[0]
    quals = dict((q[0], q[1]) for q in sub[3])
    assert quals[wd.PID_NAME_IN_KANA].startswith("ショクミンチ")
    assert "|" in quals[wd.PID_REVISED_HEPBURN_ROMANIZATION]


# --------------------------------------------------------------- translator + ncid

def test_translator_item_and_ncid_on_edition():
    facts = _facts(title="The secret story of rare sugars", lang_code="en", lang_qid="Q1860",
                   translators=[("Q135811713", "Shigeyuki Tajima")], ncid="BD03659501")
    _, _, especs = build_edition(facts, "Q1")
    tr = _find(especs, wd.PID_TRANSLATOR)[0]
    assert tr[1] == "Q135811713" and tr[2] == "item"
    ncid = _find(especs, wd.PID_NACSIS_CAT_BIBLIOGRAPHY_ID)[0]
    assert ncid[1] == "BD03659501" and ncid[2] == "string"


def test_translator_name_only_is_somevalue_named_as():
    facts = _facts(title="X", translators=[(None, "Jane Roe")])
    _, _, especs = build_edition(facts, "Q1")
    tr = _find(especs, wd.PID_TRANSLATOR)[0]
    assert tr[2] == "somevalue"
    assert tr[3] == [(wd.PID_OBJECT_NAMED_AS, "Jane Roe", "string")]


def test_translator_is_edition_only_not_on_work():
    facts = _facts(title="X", translators=[("Q135811713", "Shigeyuki Tajima")])
    _, _, wspecs = build_work(facts)
    assert _find(wspecs, wd.PID_TRANSLATOR) == []


# --------------------------------------------------------------- labels (Genji model)

def test_genji_labels_from_romanization():
    labels, _, _ = build_work(_facts(
        title="希少糖秘話", title_romaji="Kishōtō hiwa",
        title_translation="The secret story of rare sugars", lang_code="ja"))
    assert labels == {"ja": "希少糖秘話", "mul": "Kishōtō hiwa",
                      "en": "The secret story of rare sugars"}


def test_romanization_label_en_falls_back_to_romaji():
    labels, _, _ = build_work(_facts(title="羅生門", title_romaji="Rashōmon", lang_code="ja"))
    assert labels == {"ja": "羅生門", "mul": "Rashōmon", "en": "Rashōmon"}


def test_english_book_labels_unchanged():
    labels, _, _ = build_work(_facts(title="Plain Book", lang_code="en"))
    assert labels == {"mul": "Plain Book"}
