import name as nm
import pywikibot as pwb
from GlotScript import sp

QID_MALE = "Q6581097"
QID_FEMALE = "Q6581072"


def is_latin(str: str) -> bool:
    allowed = ["Latn", "Zinh", "Zyyy", "Zzzz"]

    res = sp(str)[2]
    if "details" in res:
        for script in res["details"]:
            if script != "Latn":
                print(f"{str} contains {script} characters")
            if script not in allowed:
                return False

    return True


class AuthPage:
    def __init__(self, pid, stated_in, id: str, page_language: str):
        self.pid = pid
        self.stated_in = stated_in
        self.init_id = id
        self.id = id
        self.not_found = False
        self.is_redirect = False
        self.name = None
        self.page_language = page_language
        self.birth_date = ""
        self.death_date = ""
        self.sex = ""
        self.name_order = nm.NAME_ORDER_UNDETERMINED

    def set_name_order(self, value: str):
        self.name_order = value
        if self.name:
            self.name.name_order = value

    def get_ref(self):
        res = {
            "id_pid": self.pid,
            "stated in": self.stated_in,
            "id": self.id,
        }
        return res


class Collector:
    def __init__(self):
        self.pages = []
        self.name_order = nm.NAME_ORDER_UNDETERMINED

    def retrieve(self) -> None:
        for page in self.pages:
            page.run()

        eastern_count = 0
        western_count = 0
        for page in self.pages:
            name_order = page.name_order
            if name_order == nm.NAME_ORDER_WESTERN:
                western_count += 1
            elif name_order == nm.NAME_ORDER_EASTERN:
                eastern_count += 1

        if eastern_count > 0 and western_count > 0:
            raise RuntimeError("conflicting name order")

        if eastern_count > 0:
            self.name_order = nm.NAME_ORDER_EASTERN
        else:
            # default to western order
            self.name_order = nm.NAME_ORDER_WESTERN

        for page in self.pages:
            page.set_name_order(self.name_order)

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

    def get_names(self, page_language: str):
        name_dict = {}
        index = 0
        for page in self.pages:
            if page.page_language == page_language:
                if page.name:
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
        # use a dictionary to determine if there is only one distinct sex string
        sex_dict = {}
        for page in self.pages:
            if page.sex:
                sex_dict.setdefault(page.sex, []).append(page)
        if len(sex_dict) != 1:
            if len(sex_dict) > 1:
                raise RuntimeError(f"Multiple sex strings: {sex_dict}")
            return None
        sex = next(iter(sex_dict))
        if sex == "male":
            res = sex_dict[sex][0].get_ref()
            res["qid"] = QID_MALE
            return res
        elif sex == "female":
            res = sex_dict[sex][0].get_ref()
            res["qid"] = QID_FEMALE
            return res
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

    def get_most_prec_date(self, date_dict):
        best = (0, 0, 0)
        for date in date_dict:
            comparison_result = self.compare_dates(best, date)
            if comparison_result == "different":
                return None
            if comparison_result == "use_second":
                best = date

        if best == (0, 0, 0):
            return None
        else:
            return best

    def get_date_info(self, date_type: str):
        date_dict = {}
        date_attr = "birth_date" if date_type == "birth" else "death_date"

        for page in self.pages:
            date_str = getattr(page, date_attr)
            if not date_str:
                continue

            if "," in date_str:
                # 1801, 1802
                print(f"Skipped date {date_str}")
                return None
            if "X" in date_str:
                # IdRef: 19XX
                print(f"Skipped date {date_str}")
                continue
            if "." in date_str:
                # 19..
                print(f"Skipped date {date_str}")
                continue

            date = self.split_date(date_str)
            date_dict.setdefault(date, []).append(page)

        most_prec_date = self.get_most_prec_date(date_dict)
        if not most_prec_date:
            return None

        res = date_dict[most_prec_date][0].get_ref()
        res.update({"date": self.get_WbTime(most_prec_date)})
        return res

    def get_WbTime(self, date):
        y, m, d = date
        if m == 0:
            precision = "year"
        elif d == 0:
            precision = "month"
        else:
            precision = "day"
        if y < 1582:
            # Julian
            calendarmodel = "http://www.wikidata.org/entity/Q1985786"
        else:
            # Gregorian
            calendarmodel = "http://www.wikidata.org/entity/Q1985727"

        obj = pwb.WbTime(
            year=y, month=m, day=d, precision=precision, calendarmodel=calendarmodel
        )

        return obj
