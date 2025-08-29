import re


class NameParser:
    def __init__(self, raw_name):
        self.raw_name = self._normalize_unicode(raw_name)
        self.cleaned_name = None
        self.location = None
        self.variants = []
        self.uncertain_given_name = False
        self.placeholders = []

        self._parse()

    def _normalize_unicode(self, text):
        replacements = {
            "\u2018": "'",  # left single quote
            "\u201c": '"',  # left double quote
            "\u201d": '"',  # right double quote
            "\u2010": "-",  # hyphen
            "\u00a0": " ",  # no-break space
        }
        for char, replacement in replacements.items():
            text = text.replace(char, replacement)
        return text.strip()

    def _parse(self):
        # Step 1: Extract location
        loc_match = re.search(r",\s*of\s+(.*)$", self.raw_name)
        if loc_match:
            self.location = loc_match.group(1).strip()

        name_core = re.sub(r",\s*of\s+.*$", "", self.raw_name)

        # Step 2: Handle bracketed placeholders
        bracket_matches = re.findall(r"\[([^\]]+)\]", name_core)
        if bracket_matches:
            self.placeholders.extend(bracket_matches)
            name_core = re.sub(r"\[[^\]]+\]", "", name_core)

        # Step 3: Handle parenthetical variants
        paren_match = re.search(r"\(([^)]+)\)", name_core)
        if paren_match:
            variant = paren_match.group(1).strip()
            base_name = re.sub(r"\s*\([^)]*\)", "", name_core).strip()
            self.cleaned_name = base_name
            self.variants.append(f"{base_name.split()[0]} {variant}")
        else:
            self.cleaned_name = name_core.strip()

        # Step 4: Handle pipe-separated variants
        pipe_match = re.search(r"(\w+)\|(\w+)", self.cleaned_name)
        if pipe_match:
            first, second = pipe_match.groups()
            surname = self.cleaned_name.split()[-1]
            self.cleaned_name = f"{first} {surname}"
            self.variants.append(f"{second} {surname}")

        # Step 5: Handle uncertain given name
        uncertain_match = re.match(r"(\w+)\?", self.cleaned_name)
        if uncertain_match:
            given_name = uncertain_match.group(1)
            surname = self.cleaned_name.split()[-1]
            self.cleaned_name = f"{given_name} {surname}"
            self.uncertain_given_name = True

        # Final cleanup
        self.cleaned_name = re.sub(r"\s+", " ", self.cleaned_name).strip()

    def __repr__(self):
        return (
            f"NameParser(cleaned_name='{self.cleaned_name}', "
            f"location='{self.location}', "
            f"variants={self.variants}, "
            f"uncertain_given_name={self.uncertain_given_name}, "
            f"placeholders={self.placeholders})"
        )
