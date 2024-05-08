import re


NAME_ORDER_WESTERN = "family name last"
NAME_ORDER_EASTERN = "family name first"
NAME_ORDER_HUNGARIAN = "family name first, Hungarian"
NAME_ORDER_UNDETERMINED = ""


def has_numbers(input_string):
    return any(char.isdigit() for char in input_string)


ignore_parentheses_text_list = [
    "enseignant",  # IdRef 128470119
    "sinologue",  # IdRef Q10800351
    RuntimeError("Invalid parentheses text in name: médecin"),  # Q1564099
]


class Name:
    def __init__(
        self,
        name: str = "",
        given_name: str = "",
        family_name: str = "",
    ):

        if family_name or given_name:
            self.short_given_name = ""
            self.family_name = family_name or ""
            self.given_name = given_name or ""
        elif name:
            self.short_given_name, self.given_name, self.family_name = (
                self.extract_names(name)
            )
        else:
            self.short_given_name = ""
            self.given_name = ""
            self.family_name = ""

        self.name_order = NAME_ORDER_UNDETERMINED

        self.check_invalid_chars(self.family_name)
        self.check_invalid_chars(self.given_name)

    def check_invalid_chars(self, name: str):
        invalid_chars = set("[]<>&$#~=$!?%^*_\+}{|/@,()0123456789")
        if any(char in invalid_chars for char in name):
            raise RuntimeError(f"Invalid chars in name: {name}")
        # Q18646095
        if "  " in name:
            raise RuntimeError(f"Double space in name: {name}")
        if "--" in name:
            raise RuntimeError(f"Double - in name: {name}")
        if name.startswith(" "):
            raise RuntimeError(f"Invalid start char: {name}")
        if name.endswith(" "):
            raise RuntimeError(f"Invalid end char: {name}")

    def extract_names(self, name: str):
        short_given_name = ""

        # , ? and () are allowed
        # example: Wedgwood, John Taylor (1783?-1856)
        invalid_chars = set("[]<>&$#~=$!%^*_\+}{|@")
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
            elif parentheses_text in ignore_parentheses_text_list:
                parentheses_text = ""
            elif parentheses_text.islower():
                raise RuntimeError(
                    f"Invalid parentheses text in name: {parentheses_text}"
                )
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
            if "@" in name:
                name = name.strip(" @")
            given_name = name
        return (short_given_name, given_name, family_name)

    def names(self):
        if self.family_name and self.given_name:
            if self.name_order == NAME_ORDER_EASTERN:
                return self.family_name_first()
            else:
                return self.family_name_last()
        elif self.family_name:
            return [self.family_name]
        elif self.given_name:
            return [self.given_name]
        else:
            return []

    def family_name_last(self):
        res = [self.full_name(self.given_name, self.family_name)]
        if self.short_given_name:
            res.append(self.full_name(self.short_given_name, self.family_name))
        return res

    def family_name_first(self):
        res = [self.full_name(self.family_name, self.given_name)]
        if self.short_given_name:
            res.append(self.full_name(self.family_name, self.short_given_name))
        return res

    def full_name(self, name1: str, name2: str) -> str:
        if not name1:
            return name2
        elif not name2:
            return name1
        elif name1.endswith("'"):
            if name1.endswith(" d'"):
                return f"{name1}{name2}"
            else:
                raise RuntimeError(f"name1 ends with quote: {name1} {name2}")
        elif name1.endswith("-"):
            return f"{name1}{name2}"
        else:
            return f"{name1} {name2}"
