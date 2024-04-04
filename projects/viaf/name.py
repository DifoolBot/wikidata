import re


def has_numbers(input_string):
    return any(char.isdigit() for char in input_string)


NAME_ORDER_WESTERN = "family name last"
NAME_ORDER_EASTERN = "family name first"
NAME_ORDER_UNDETERMINED = ""


class Name:
    def __init__(
        self,
        name_en: str = "",
        given_name_en: str = "",
        family_name_en: str = "",
        given_name: str = "",
        family_name: str = "",
    ):

        if family_name_en or given_name_en:
            self.short_given_name_en = ""
            self.given_name_en = given_name_en
            self.family_name_en = family_name_en
        # idref 073863823 returns no name_en
        elif not name_en:
            self.short_given_name_en = ""
            self.given_name_en = ""
            self.family_name_en = ""
        else:
            self.short_given_name_en, self.given_name_en, self.family_name_en = (
                self.extract_names(name_en)
            )

        self.given_name = given_name
        self.family_name = family_name
        self.name_order = NAME_ORDER_UNDETERMINED

        # self.check_invalid_chars(self.given_name)
        # self.check_invalid_chars(self.family_name)
        self.check_invalid_chars(self.family_name_en)
        self.check_invalid_chars(self.given_name_en)
        self.check_invalid_chars(self.family_name_en)

    def check_invalid_chars(self, name):
        invalid_chars = set("[]$!?%^*_\+}{|/@,()0123456789")
        if any(char in invalid_chars for char in name):
            raise RuntimeError(f"Invalid chars in name: {name}")

    def extract_names(self, name):
        short_given_name = ""

        # , and () are allowed
        invalid_chars = set("[]$!?%^*_\+}{|/@")
        if any(char in invalid_chars for char in name):
            raise RuntimeError(f"Invalid chars in name: {name}")
        # extract the part between parentheses
        match = re.search(r"\(([^)]+)\)", name)
        if match:
            # parentheses text can be birth/death year, alternative family name, long given name
            parentheses_text = match.group(1)
            name = name.replace("(" + parentheses_text + ")", "@")
            if has_numbers(parentheses_text):
                # ignore (year-year)
                parentheses_text = ""
        else:
            parentheses_text = ""

        # format = family name, given name
        if "," in name:
            # 'Ōishi, Yutaka, 1956-'
            arr = name.split(",", 3)
            if len(arr) == 3:
                # idref: Kadžaâ, Valerij Georgievič, (1942-....)
                print(f"Name with 2 or more comma's: {name} - removed: {arr[2]}")
            family_name = arr[0].strip()
            given_name = arr[1].strip()

            if "@" in family_name:
                family_name = family_name.strip(" @")

            if "@" in given_name:
                given_name = given_name.strip(" @")
                if parentheses_text:
                    short_given_name = given_name
                    given_name = parentheses_text
        else:
            family_name = ""
            given_name = name
        return (short_given_name, given_name, family_name)

    def names_en(self):
        if self.family_name_en == "":
            if self.given_name_en == "":
                return []
            else:
                return [self.given_name_en]
        elif self.name_order == NAME_ORDER_EASTERN:
            return self.family_name_first_en()
        else:
            return self.family_name_last_en()

    def family_name_last_en(self):
        res = [self.full_name(self.given_name_en, self.family_name_en)]
        if self.short_given_name_en:
            res.append(self.full_name(self.short_given_name_en, self.family_name_en))
        return res

    def family_name_first_en(self):
        res = [self.full_name(self.family_name_en, self.given_name_en)]
        if self.short_given_name_en:
            res.append(self.full_name(self.family_name_en, self.short_given_name_en))
        return res

    def full_name(self, name1, name2):
        return f"{name1}{' ' if not name1.endswith('-') else ''}{name2}".strip()
