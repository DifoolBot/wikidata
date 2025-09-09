import re


class NameParser:
    def __init__(self, raw_name, prefixes=None, suffixes=None):
        self.raw_name = self._normalize_unicode(raw_name)
        self.cleaned_name = None
        self.location = None
        self.variants = []
        self.uncertain_given_name = False
        self.placeholders = []
        self.prefixes = prefixes or []
        self.suffixes = suffixes or []
        self.extracted_prefixes = []
        self.extracted_suffixes = []

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

        # Step 2: Extract suffixes (postfixes) after last comma
        name_core, extracted_suffixes = self._extract_suffixes(name_core)
        self.extracted_suffixes = extracted_suffixes

        # Step 3: Extract prefixes at the start
        name_core, extracted_prefixes = self._extract_prefixes(name_core)
        self.extracted_prefixes = extracted_prefixes

        # Step 4: Handle bracketed placeholders
        bracket_matches = re.findall(r"\[([^\]]+)\]", name_core)
        if bracket_matches:
            self.placeholders.extend(bracket_matches)
            name_core = re.sub(r"\[[^\]]+\]", "", name_core)

        # Step 5: Handle parenthetical variants
        paren_match = re.search(r"\(([^)]+)\)", name_core)
        if paren_match:
            variant = paren_match.group(1).strip()
            base_name = re.sub(r"\s*\([^)]*\)", "", name_core).strip()
            self.cleaned_name = base_name
            self.variants.append(f"{base_name.split()[0]} {variant}")
        else:
            self.cleaned_name = name_core.strip()

        # Step 6: Handle pipe-separated variants
        pipe_match = re.search(r"(\w+)\|(\w+)", self.cleaned_name)
        if pipe_match:
            first, second = pipe_match.groups()
            surname = self.cleaned_name.split()[-1]
            self.cleaned_name = f"{first} {surname}"
            self.variants.append(f"{second} {surname}")

        # Step 7: Handle uncertain given name
        uncertain_match = re.match(r"(\w+)\?", self.cleaned_name)
        if uncertain_match:
            given_name = uncertain_match.group(1)
            surname = self.cleaned_name.split()[-1]
            self.cleaned_name = f"{given_name} {surname}"
            self.uncertain_given_name = True

        # Final cleanup
        self.cleaned_name = re.sub(r"\s+", " ", self.cleaned_name).strip()

    def _extract_prefixes(self, name):
        """
        Extracts all prefixes from the start of the name, returns (name_without_prefixes, [prefixes])
        """
        prefixes_found = []
        name_parts = name.strip().split()
        while name_parts:
            part = name_parts[0].rstrip(",")
            # Check for multi-word prefixes (e.g., "Prof. Dr.")
            matched = False
            for prefix in sorted(self.prefixes, key=lambda x: -len(x.split())):
                prefix_parts = prefix.split()
                if name_parts[: len(prefix_parts)] == prefix_parts:
                    prefixes_found.append(prefix)
                    name_parts = name_parts[len(prefix_parts) :]
                    matched = True
                    break
            if not matched:
                # Check for single-word prefix
                if part in self.prefixes:
                    prefixes_found.append(part)
                    name_parts = name_parts[1:]
                else:
                    break
        return " ".join(name_parts), prefixes_found

    def _extract_suffixes(self, name):
        """
        Extracts all suffixes from the end of the name (after comma or at the end), returns (name_without_suffixes, [suffixes])
        """
        suffixes_found = []
        # First, check for comma-separated suffixes
        parts = [p.strip() for p in name.split(",")]
        name_main = parts[0]
        for suffix in parts[1:]:
            for s in [s.strip() for s in suffix.split()]:
                if s in self.suffixes:
                    suffixes_found.append(s)
        # Now, check for suffixes at the end of the name (not comma-separated)
        name_words = name_main.split()
        while name_words:
            candidate = name_words[-1]
            if candidate in self.suffixes:
                suffixes_found.insert(0, candidate)
                name_words = name_words[:-1]
            else:
                break
        name_main = " ".join(name_words)
        return name_main, suffixes_found

    def __repr__(self):
        return (
            f"NameParser(cleaned_name='{self.cleaned_name}', "
            f"location='{self.location}', "
            f"variants={self.variants}, "
            f"uncertain_given_name={self.uncertain_given_name}, "
            f"placeholders={self.placeholders}, "
            f"prefixes={self.extracted_prefixes}, "
            f"suffixes={self.extracted_suffixes}, "
        )


def _test_nameparser():
    prefixes = ["Prof.", "Dr.", "Sir", "prof", "Dr."]
    suffixes = ["Jr.", "Sr.", "III", "PhD", "Jr"]
    examples = [
        # (input, expected_prefix, expected_cleaned, expected_suffix)
        ("Prof. Dr. John Smith, Jr.", "Prof. Dr.", "John Smith", "Jr."),
        ("Sir Isaac Newton", "Sir", "Isaac Newton", None),
        ("Martin Luther King Jr.", None, "Martin Luther King", "Jr."),
        ("prof Dr. Alice Johnson, PhD", "prof Dr.", "Alice Johnson", "PhD"),
        ("Dr. Jane Doe", "Dr.", "Jane Doe", None),
        ("John Smith, III", None, "John Smith", "III"),
        ("John Smith", None, "John Smith", None),
    ]
    for raw, exp_prefix, exp_cleaned, exp_suffix in examples:
        np = NameParser(raw, prefixes=prefixes, suffixes=suffixes)
        prefix = " ".join(np.extracted_prefixes) if np.extracted_prefixes else None
        suffix = " ".join(np.extracted_suffixes) if np.extracted_suffixes else None
        assert (
            prefix == exp_prefix
        ), f"Prefix failed: {raw} got '{prefix}' expected '{exp_prefix}'"
        assert (
            np.cleaned_name == exp_cleaned
        ), f"Cleaned name failed: {raw} got '{np.cleaned_name}' expected '{exp_cleaned}'"
        assert (
            suffix == exp_suffix
        ), f"Suffix failed: {raw} got '{suffix}' expected '{exp_suffix}'"
    print("All NameParser tests passed.")


if __name__ == "__main__":
    _test_nameparser()
