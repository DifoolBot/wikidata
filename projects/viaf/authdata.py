import name
import pywikibot as pwb
from GlotScript import sp

QID_MALE = "Q6581097"
QID_FEMALE = "Q6581072"


def remove_duplicates_ordered(arr):
    seen = set()
    result = []
    for item in arr:
        if item not in seen:
            result.append(item)
            seen.add(item)
    return result


def is_latin(str: str) -> bool:
    allowed = ["Latn", "Zinh", "Zyyy", "Zzzz"]

    res = sp(str)[2]
    if "details" in res:
        for script in res["details"]:
            if not (script in allowed):
                print(f"Skipped: {str} contains {script} characters")
                return False
            if script != "Latn":
                print(f"{str} contains {script} characters")

    return True


class AuthPage:
    def __init__(self, id: str, page_language: str):
        self.init_id = id
        self.id = id
        self.not_found = False
        self.is_redirect = False
        self.name = None
        self.page_language = page_language
        self.birth_date = ""
        self.death_date = ""
        self.sex = ""


class Collector:
    def __init__(self):
        self.pages = []
        self.name_order = ""

    def retrieve(self) -> None:
        for page in self.pages:
            page.run()

        eastern_count = 0
        western_count = 0
        for page in self.pages:
            name_order = page.name_order()
            if name_order == name.NAME_ORDER_WESTERN:
                western_count += 1
            elif name_order == name.NAME_ORDER_EASTERN:
                eastern_count += 1

        if eastern_count > 0 and western_count > 0:
            raise ValueError("conflicting name order")

        if eastern_count > 0:
            self.name_order = name.NAME_ORDER_EASTERN
        else:
            # default to western order
            self.name_order = name.NAME_ORDER_WESTERN

        for page in self.pages:
            if page.name is not None:
                page.name.name_order = self.name_order

    def add(self, page: AuthPage):
        self.pages.append(page)

    def has_duplicates(self) -> bool:
        seen = set()
        for page in self.pages:
            short_desc = page.get_short_desc()
            if short_desc in seen:
                return True
            seen.add(short_desc)

        return False

    def has_redirect(self) -> bool:
        for page in self.pages:
            if page.is_redirect or page.not_found:
                return True

        return False

    def resolve_redirect(self):
        pass

    def get_names(self, page_language: str):
        name_dict = {}
        index = 0
        for page in self.pages:
            if page.page_language == page_language:
                if page.name is not None:
                    for name in page.name.names_en():
                        if not is_latin(name):
                            continue
                        if not name in name_dict:
                            name_dict[name] = {"index": index, "pages": []}
                            index += 1
                        name_dict[name]["pages"].append(page)

        result_list = [
            {"name": name, "index": data["index"], "pages": data["pages"]}
            for name, data in name_dict.items()
        ]

        result_list.sort(key=lambda x: x["index"])

        return result_list

    def get_sex_info(self):
        # create a dictionary with all sex strings listed by the pages
        sex_dict = {}
        for page in self.pages:
            sex = page.sex
            if len(sex) > 0:
                if sex not in sex_dict:
                    sex_dict[sex] = []
                sex_dict[sex].append(page)
        # only return a result if there is only one distinct sex string
        if len(sex_dict) != 1:
            return None
        sex = next(iter(sex_dict))
        if sex == "male":
            res = sex_dict[sex][0].get_ref()
            res["qid"] = QID_MALE
            return res
        elif sex == "female":
            res = sex_dict[sex][0].get_ref()
            res["qid"] = QID_FEMALE
        else:
            raise ValueError(f"Unexpected sex: {sex}")

    def split_date(self, date_str: str):
        parts = date_str.split("-")
        if len(parts) == 1:
            return (int(parts[0]), 0, 0)
        elif len(parts) == 2:
            return (int(parts[0]), int(parts[1]), 0)
        elif len(parts) == 3:
            return (int(parts[0]), int(parts[1]), int(parts[2]))
        else:
            raise ValueError(f"Invalid date string: {date_str}")

    def compare_dates(self, date1, date2) -> str:
        # return which date has the most precision; date1 (first) or date2 (second)
        # if the dates are different, then return 'different'

        y1, m1, d1 = date1
        y2, m2, d2 = date2

        if y2 == 0:
            return "use_first"
        if y1 == 0:
            return "use_second"
        if y1 != y2:
            return "different"
        if m2 == 0:
            return "use_first"
        if m1 == 0:
            return "use_second"
        if m1 != m2:
            return "different"
        if d2 == 0:
            return "use_first"
        if d1 == 0:
            return "use_second"
        if d1 != d2:
            return "different"
        else:
            return "use_first"

    def get_most_prec_date(self, date_dict) -> str:
        best = (0, 0, 0)
        for date_str in date_dict:
            if "," in date_str:
                print(f"Skipped date {date_str}")
                return None
            this = self.split_date(date_str)
            comparison_result = self.compare_dates(best, this)
            if comparison_result == "different":
                return None
            if comparison_result == "use_second":
                best = this

        y, m, d = best
        if y == 0:
            return None
        elif m == 0:
            return str(y)
        elif d == 0:
            return f"{y}-{m:02d}"
        else:
            return f"{y}-{m:02d}-{d:02d}"

    def get_date_info(self, date_type):
        date_dict = {}
        date_attr = "birth_date" if date_type == "birth" else "death_date"

        for page in self.pages:
            date_str = getattr(page, date_attr)
            if len(date_str) > 0:
                date_dict.setdefault(date_str, []).append(page)

        date_str = self.get_most_prec_date(date_dict)
        if date_str is not None:
            res = date_dict[date_str][0].get_ref()
            y, m, d = self.split_date(date_str)
            if m == 0:
                precision = "year"
            elif d == 0:
                precision = "month"
            else:
                precision = "day"
            if y < 1582:
                # julian
                calendarmodel = "http://www.wikidata.org/entity/Q1985786"
            else:
                # Gregorian
                calendarmodel = "http://www.wikidata.org/entity/Q1985727"

            date = pwb.WbTime(
                year=y, month=m, day=d, precision=precision, calendarmodel=calendarmodel
            )
            res.update({"date": date})
            return res
        else:
            return None
