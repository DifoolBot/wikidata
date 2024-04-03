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

        self.short_given_name_en = ""
        if family_name_en or given_name_en:
            self.family_name_en = family_name_en
            self.given_name_en = given_name_en
        # idref 073863823 returns no name_en
        elif (name_en is None) or (name_en == ""):
            self.family_name_en = ""
            self.given_name_en = ""
        else:
            # extract the part between parentheses
            match = re.search(r"\(([^)]+)\)", name_en)
            if match:
                parentheses_text = match.group(1)
                if has_numbers(parentheses_text):
                    # ignore (year-year)
                    parentheses_text = ""
            else:
                parentheses_text = ""

            # text before the parentheses
            name_en = name_en.split("(", 1)[0].strip()

            # format = family name, given name
            if "," in name_en:
                # 'Ōishi, Yutaka, 1956-'
                arr = name_en.split(",", 3)
                if len(arr) == 3:
                    print(f"{name_en} - {arr[2]}")
                self.family_name_en = arr[0].strip()
                if parentheses_text:
                    self.given_name_en = parentheses_text
                    self.short_given_name_en = arr[1].strip()
                else:
                    self.given_name_en = arr[1].strip()
            else:
                self.family_name_en = ""
                self.given_name_en = name_en

        self.given_name = given_name
        self.family_name = family_name
        self.name_order = NAME_ORDER_UNDETERMINED

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
