import pywikibot as pwb
from pathlib import Path
import json

JSON_DIR = Path("projects\\genealogics\\")


def contains_prefix(prefix: str) -> bool:
    json_path = JSON_DIR / "prefix_suffix.json"
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)  # renamed from prefix_data
    for entry in data.values():
        if entry.get("prefix_full") == prefix or prefix in entry.get(
            "prefix_variants", []
        ):
            return True
    return False


def contains_suffix(prefix: str) -> bool:
    json_path = JSON_DIR / "prefix_suffix.json"
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)  # renamed from prefix_data
    for entry in data.values():
        if entry.get("suffix_full") == prefix or prefix in entry.get(
            "suffix_variants", []
        ):
            return True
    return False


def add_affix(
    key: str, affix: str, is_prefix: bool, is_full: bool, sequence: list[str]
):
    if not affix:
        raise ValueError("No affix provided")
    if not key:
        raise ValueError("No key provided")

    json_path = JSON_DIR / "prefix_suffix.json"
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)  # renamed from prefix_data

    if key in data:
        entry = data[key]
    else:
        entry = {}

    if sequence:
        if "sequence" in entry:
            raise ValueError(f"Key {key} already has a sequence")
        entry["sequence"] = sequence
    if is_prefix:
        if is_full:
            if "prefix_full" in entry and entry["prefix_full"]:
                raise ValueError(f"Key {key} already has a full prefix")
            entry["prefix_full"] = affix
        else:
            entry["prefix_variants"] = entry.get("prefix_variants", []) + [affix]
    else:
        if is_full:
            if "suffix_full" in entry and entry["suffix_full"]:
                raise ValueError(f"Key {key} already has a full suffix")
            entry["suffix_full"] = affix
        else:
            entry["suffix_variants"] = entry.get("suffix_variants", []) + [affix]

    data[key] = entry

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

    affix_type = "prefix" if is_prefix else "suffix"
    print(f"Added {affix_type} '{affix}' with key '{key}'.")


def ask():
    affix = input("Enter a prefix/suffix: ")
    is_prefix = (
        pwb.input_choice("Prefix/suffix", [("Prefix", "p"), ("Suffix", "s")]) == "p"
    )
    if is_prefix:
        if contains_prefix(affix):
            print(f"{affix} is already a known prefix")
            return
    else:
        if contains_suffix(affix):
            print(f"{affix} is already a known suffix")
            return
    type = pwb.input_choice(
        "Full, affix or sequence", [("Full", "f"), ("Affix", "a"), ("Sequence", "s")]
    )
    sequence = []
    if type == "f" or type == "s":
        key = affix
        if type == "s":
            while True:
                sub = input("Enter a sub-affix (or empty to end): ")
                if not sub:
                    break
                sequence.append(sub)
    else:
        key = input("Enter a key: ")
    add_affix(key, affix, is_prefix, type == "f", sequence)


if __name__ == "__main__":
    ask()
