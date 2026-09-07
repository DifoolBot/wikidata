"""Offline tests for gen_book_txt.py's NDL-reading helpers: the katakana -> revised-Hepburn
converter (kana_to_hepburn) and the CiNii NCID extractor (_ndl_ncid).

Run with:
    python -m pytest projects/isbn_cleanup/test_gen_book_txt.py -v
"""

import xml.etree.ElementTree as ET

from isbn_cleanup.gen_book_txt import _ndl_ncid, kana_to_hepburn


def test_hepburn_long_vowels_and_yoon():
    # long vowels from the kango ou/uu sequences, yōon (ショ/チュ/シュ/ジュ)
    assert kana_to_hepburn("キショウトウ ヒワ") == "Kishōtō hiwa"
    assert kana_to_hepburn(
        "チュウセイ ゼンシュウ ノ ジュガク ガクシュウ ト カガク チシキ"
    ) == "Chūsei zenshū no jugaku gakushū to kagaku chishiki"
    assert kana_to_hepburn("チョウ カクチュウ ノ ニホンゴ ブンガク") == \
        "Chō kakuchū no nihongo bungaku"


def test_hepburn_choonpu_macron():
    # the ー long-vowel mark -> macron on the preceding vowel
    assert kana_to_hepburn("ウィーン ノ トシ ト ケンチク") == "Wīn no toshi to kenchiku"


def test_hepburn_sokuon():
    # ッ doubles the next consonant (kk); おう -> ō
    assert kana_to_hepburn("ガッコウ") == "Gakkō"


def test_hepburn_syllabic_n_apostrophe():
    # ン before a vowel -> n'
    assert kana_to_hepburn("シンイチ") == "Shin'ichi"
    # ン before a consonant stays n
    assert kana_to_hepburn("ケンチク") == "Kenchiku"


def _item_with_seealso(url: str):
    item = ET.Element("item")
    se = ET.SubElement(item, "{http://www.w3.org/2000/01/rdf-schema#}seeAlso")
    se.set("{http://www.w3.org/1999/02/22-rdf-syntax-ns#}resource", url)
    return item


def test_ndl_ncid_extracted_from_seealso():
    assert _ndl_ncid(_item_with_seealso("https://ci.nii.ac.jp/ncid/BB14197516")) == \
        "BB14197516"


def test_ndl_ncid_ignores_other_links():
    assert _ndl_ncid(_item_with_seealso("https://opac.example.jp/detail/123")) == ""
    assert _ndl_ncid(ET.Element("item")) == ""
