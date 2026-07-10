"""Writing-script detection (Latin / Hebrew / Cyrillic) based on GlotScript.

Zinh (inherited), Zyyy (common) and Zzzz (unknown) are always allowed because
they cover punctuation, digits and combining marks shared by all scripts.
"""

from GlotScript import sp

ALLOWED_LATIN_SCRIPTS = ["Latn", "Zinh", "Zyyy", "Zzzz"]
ALLOWED_HEBREW_SCRIPTS = ["Hebr", "Zinh", "Zyyy", "Zzzz"]
ALLOWED_CYRILLIC_SCRIPTS = ["Cyrl", "Zinh", "Zyyy", "Zzzz"]


def is_script(text: str, allowed_scripts: list) -> bool:
    """Return True if the text contains only the allowed scripts."""
    if not text:
        return False
    res = sp(text)[2]
    if "details" in res and res["details"]:
        for script in res["details"]:
            if script not in allowed_scripts:
                return False
    return True


def is_hebrew_text(text: str) -> bool:
    return is_script(text, ALLOWED_HEBREW_SCRIPTS)


def is_latin_text(text: str) -> bool:
    return is_script(text, ALLOWED_LATIN_SCRIPTS)


def is_cyrillic_text(text: str) -> bool:
    return is_script(text, ALLOWED_CYRILLIC_SCRIPTS)
