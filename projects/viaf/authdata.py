import name as nm
import pywikibot as pwb
import scriptutils
import languagecodes as lc


QID_MALE = "Q6581097"
QID_FEMALE = "Q6581072"


class AuthPage:
    def __init__(self, id: str, pid:str = '', stated_in:str = '', page_language: str = ''):
        self.pid = pid
        self.stated_in = stated_in
        self.init_id = id
        self.id = id
        self.not_found = False
        self.is_redirect = False
        self.latin_name = None
        self.page_language = page_language
        self.birth_date = ""
        self.death_date = ""
        self.sex = ""
        self.name_orders = []
        self.name_order = nm.NAME_ORDER_UNDETERMINED
        self.countries = []
        self.languages = []
        self.sources = []
        self.variants = []
        self.has_prefix = False
        self.did_run = False

    def run_once(self):
        if self.did_run: 
            return
        
        self.did_run = True
        self.run()
                
    def get_name_order(self):
        short = self.get_short_desc()
        for country in self.countries:
            if lc.is_hungarian_name_order_country(country):
                print(f"{short}: family name FIRST (hungarian) based on country")
                return nm.NAME_ORDER_HUNGARIAN
        for language in self.languages:
            if lc.is_hungarian_name_order_language(language):
                print(f"{short}: family name FIRST (hungarian) based on language")
                return nm.NAME_ORDER_HUNGARIAN

        if self.has_prefix:
            print(f"{short}: family name LAST based on existing prefix")
            return nm.NAME_ORDER_WESTERN

        if self.latin_name:
            # same if given_name or family_name is empty; for example Q3160707 (Jala; pseudonym)
            if self.latin_name.family_name_first() == self.latin_name.family_name_last():
                return nm.NAME_ORDER_UNDETERMINED

            family_name_first = 0
            family_name_last = 0
            for src in self.sources:
                for name in self.latin_name.family_name_first():
                    if name in src:
                        family_name_first += 1
                for name in self.latin_name.family_name_last():
                    if name in src:
                        family_name_last += 1
            if family_name_first > family_name_last:
                print(f"{short}:  family name FIRST based on sources")
                return nm.NAME_ORDER_EASTERN
            elif family_name_first < family_name_last:
                print(f"{short}:  family name LAST based on sources")
                return nm.NAME_ORDER_WESTERN

        for country in self.countries:
            if lc.is_eastern_name_order_country(country):
                print(f"{short}:  family name FIRST based on country")
                return nm.NAME_ORDER_EASTERN
        for language in self.languages:
            if lc.is_eastern_name_order_language(language):
                print(f"{short}:  family name FIRST based on language")
                return nm.NAME_ORDER_EASTERN

        return nm.NAME_ORDER_UNDETERMINED

    def add_country(self, country: str):
        if country and country not in self.countries:
            self.countries.append(country)

    def add_language(self, language: str):
        if language and language not in self.languages:
            self.languages.append(language)

    def set_name_order(self, value: str):
        self.name_order = value
        if self.latin_name:
            self.latin_name.name_order = value

    def get_ref(self):
        res = {
            "id_pid": self.pid,
            "stated in": self.stated_in,
            "id": self.id,
        }
        return res

    def has_hebrew_script(self):
        for name in self.variants:
            if scriptutils.is_hebrew_text(name):
                return True

        if self.has_script(lc.is_hebrew_script):
            return True

        return False

    def has_cyrillic_script(self):
        for name in self.variants:
            if scriptutils.is_cyrillic_text(name):
                return True

        if self.has_script(lc.is_cyrillic_script):
            return True

        return False

    def has_non_latin_script(self):
        for name in self.variants:
            if not scriptutils.is_latin_text(name):
                return True

        if self.has_script(lc.is_not_latin_script):
            return True

        return False

    def has_script(self, f) -> bool:
        return self.has_script_language(f) or self.has_script_country(f)

    def has_script_language(self, f) -> bool:
        for language in self.languages:
            if language not in lc.iso639_3_dict:
                raise RuntimeError(f"unknown iso language {language}")
            for script in lc.iso639_3_dict[language]:
                if f(script):
                    return True
        return False

    def has_script_country(self, f) -> bool:
        for country in self.countries:
            for language in lc.official_languages_dict[country]:
                if language not in lc.iso639_3_dict:
                    raise RuntimeError(f"unknown iso language {language}")
                for script in lc.iso639_3_dict[language]:
                    if f(script):
                        return True

        return False
    
    def has_language_info(self):
        if self.countries:
            return True
        if self.languages:
            return True
        for name in self.variants:
            if not scriptutils.is_latin_text(name):
                return True
        return False


class Collector:
    def __init__(self, force_name_order: str = nm.NAME_ORDER_UNDETERMINED):
        self.pages = []
        self.name_order = nm.NAME_ORDER_UNDETERMINED
        self.force_name_order = force_name_order

    def retrieve(self) -> None:
        for page in self.pages:
            page.run_once()

        self.after_run()

    def after_run(self):
        if self.force_name_order == nm.NAME_ORDER_UNDETERMINED:
            self.determine_name_order()
        else:
            self.name_order = self.force_name_order

        for page in self.pages:
            page.set_name_order(self.name_order)

    def determine_name_order(self):
        # set self.name_orders and self.name_order
        self.name_orders = []
        for page in self.pages:
            name_order = page.name_order
            if name_order not in self.name_orders:
                self.name_orders.append(name_order)

        if nm.NAME_ORDER_HUNGARIAN in self.name_orders:
            self.name_order = nm.NAME_ORDER_HUNGARIAN
            return

        if nm.NAME_ORDER_UNDETERMINED in self.name_orders:
            self.name_orders.remove(nm.NAME_ORDER_UNDETERMINED)

        if len(self.name_orders) > 1:
            print("conflicting name order")
            self.name_order = nm.NAME_ORDER_UNDETERMINED
        elif len(self.name_orders) == 1:
            self.name_order = self.name_orders[0]
        else:
            # default to western order
            self.name_order = nm.NAME_ORDER_WESTERN

    def has_language_info(self):
        for page in self.pages:
            if page.has_language_info():
                return True
        return False
    def can_change_labels(self):
        # names from non Latin script? skip for now
        if self.has_hebrew_script():
            return False
        if self.has_cyrillic_script():
            return False
        if self.has_non_latin_script():
            return False

        # skip eastern order for now
        if self.name_order == nm.NAME_ORDER_HUNGARIAN:
            return True
        if nm.NAME_ORDER_EASTERN in self.name_orders:
            return False
        if len(self.name_orders) > 1:
            return False

        return True

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

    def has_hebrew_script(self):
        for page in self.pages:
            if page.has_hebrew_script():
                return True

        return False

    def has_cyrillic_script(self):
        for page in self.pages:
            if page.has_cyrillic_script():
                return True

        return False

    def has_non_latin_script(self):
        for page in self.pages:
            if page.has_non_latin_script():
                return True

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
                if page.latin_name:
                    for name in page.latin_name.names():
                        if not scriptutils.is_latin_text(name):
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
            raise RuntimeError(f"Unexpected sex: {sex}")

    def split_date(self, date_str: str):
        parts = date_str.split("-")
        if len(parts) == 1:
            if parts[0].isdigit():
                return (int(parts[0]), 0, 0)
            else:
                # typos: for example idref: 059640340 has a196
                #        1521~
                print(f"Invalid date string: {date_str}")
                return None

        elif len(parts) == 2:
            return (int(parts[0]), int(parts[1]), 0)
        elif len(parts) == 3:
            return (int(parts[0]), int(parts[1]), int(parts[2]))
        else:
            raise RuntimeError(f"Invalid date string: {date_str}")

    def compare_dates(self, date1, date2) -> str:
        """
        Return which date has the most precision; date1 (first) or date2 (second)
        if the dates are different, then return 'different'.
        """

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
            if date:
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
