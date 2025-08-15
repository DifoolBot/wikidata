import re
from calendar import monthrange
from datetime import datetime
from typing import Optional

import pywikibot as pwb
from dateutil.parser import parse as date_parse

URL_PROLEPTIC_JULIAN_CALENDAR = "http://www.wikidata.org/entity/Q1985786"
URL_PROLEPTIC_GREGORIAN_CALENDAR = "http://www.wikidata.org/entity/Q1985727"
URL_UNSPECIFIED_CALENDAR = "http://www.wikidata.org/wiki/Q18195782"


def normalize_wikicode_name(name: str) -> str:
    """
    Normalizes a template or param name by replacing underscores with spaces,
    and converting to lowercase.
    """
    return name.strip().lower().replace("_", " ")


def get_param_name_map(template):
    param_map = {}
    for param in template.params:
        original = str(param.name).strip()
        normalized = normalize_wikicode_name(original)
        param_map[normalized] = original
    return param_map


def build_wbtime(
    y,
    m,
    d,
    calendarmodel=URL_UNSPECIFIED_CALENDAR,
):
    try:
        y, m, d = int(y), int(m) if m else None, int(d) if d else None
        if d:
            return pwb.WbTime(
                year=y, month=m, day=d, precision=11, calendarmodel=calendarmodel
            )
        elif m:
            return pwb.WbTime(
                year=y, month=m, precision=10, calendarmodel=calendarmodel
            )
        else:
            return pwb.WbTime(year=y, precision=9, calendarmodel=calendarmodel)
    except Exception:
        return None


class CountryConfig:
    def __init__(self, key: Optional[str], config: dict):
        country_config = config.get(key, {})
        self.country_config = country_config or {}
        self.last_julian_date = self.country_config.get("last_julian_date")
        self.first_gregorian_date = self.country_config.get("first_gregorian_date")
        self.no_julian_calendar = self.country_config.get("no_julian_calendar")
        use = self.country_config.get("use")
        if use:
            for key, value in config.items():
                if value.get("code") == use:
                    self.last_julian_date = value.get("last_julian_date")
                    self.first_gregorian_date = value.get("first_gregorian_date")
                    self.no_julian_calendar = value.get("no_julian_calendar")
                    break
        if self.no_julian_calendar:
            # last_julian_date:
            #     year: 1582
            #     month: 10
            #     day: 4
            # first_gregorian_date:
            #     year: 1582
            #     month: 10
            #     day: 15
            self.last_julian_date = {"year": 1582, "month": 10, "day": 4}
            self.first_gregorian_date = {"year": 1582, "month": 10, "day": 15}

    def get_calendar_model(self, year, month, day) -> str:
        """
        Given a year, month, day, returns the calendar model URL.
        - If the date can be both Julian and Gregorian, returns URL_UNSPECIFIED_CALENDAR.
        - If only Julian, returns URL_PROLEPTIC_JULIAN_CALENDAR.
        - If only Gregorian, returns URL_PROLEPTIC_GREGORIAN_CALENDAR.
        - If neither, raises ValueError.
        Handles cases where only year or year+month are provided by checking both ends of the range.
        """

        def date_tuple(d):
            return (int(d.get("year", 0)), int(d.get("month", 0)), int(d.get("day", 0)))

        # If no transition info, cannot determine
        if not self.last_julian_date or not self.first_gregorian_date:
            return URL_UNSPECIFIED_CALENDAR

        last_julian = date_tuple(self.last_julian_date)
        first_gregorian = date_tuple(self.first_gregorian_date)

        # If only year is provided
        if year and not month and not day:
            # Check 1 Jan and 31 Dec of that year
            y = int(year)
            # 1 Jan
            ymd1 = (y, 1, 1)
            # 31 Dec
            ymd2 = (y, 12, 31)
            cal1 = self._calendar_for_ymd(ymd1, last_julian, first_gregorian)
            cal2 = self._calendar_for_ymd(ymd2, last_julian, first_gregorian)
            if cal1 == cal2:
                return cal1
            else:
                return URL_UNSPECIFIED_CALENDAR
        # If year and month are provided
        if year and month and not day:
            y = int(year)
            m = int(month)
            # 1st of month
            ymd1 = (y, m, 1)
            # last day of month
            last_day = monthrange(y, m)[1]
            ymd2 = (y, m, last_day)
            cal1 = self._calendar_for_ymd(ymd1, last_julian, first_gregorian)
            cal2 = self._calendar_for_ymd(ymd2, last_julian, first_gregorian)
            if cal1 == cal2:
                return cal1
            else:
                return URL_UNSPECIFIED_CALENDAR
        # If year, month, and day are provided
        if year and month and day:
            ymd = (int(year), int(month), int(day))
            return self._calendar_for_ymd(ymd, last_julian, first_gregorian)
        raise ValueError("Insufficient date information for calendar determination.")

    def _calendar_for_ymd(self, ymd, last_julian, first_gregorian):
        """
        Helper to determine calendar for a given (year, month, day) tuple.
        """
        # Julian: date <= last_julian
        is_julian = ymd <= last_julian
        # Gregorian: date >= first_gregorian
        is_gregorian = ymd >= first_gregorian
        if is_julian and is_gregorian:
            return URL_UNSPECIFIED_CALENDAR
        elif is_julian:
            return URL_PROLEPTIC_JULIAN_CALENDAR
        elif is_gregorian:
            return URL_PROLEPTIC_GREGORIAN_CALENDAR
        else:
            raise ValueError(
                f"Date {ymd} is not valid for either Julian or Gregorian calendar in this context."
            )


class LanguageConfig:
    def __init__(self, key: Optional[str], config: dict):
        lang_config = config.get(key, {})
        self.lang_config = lang_config or {}
        self.month_map = self.lang_config.get("month_map", {})
        self.date_templates = self.get_templates("date_templates")
        self.template_map = self.get_template_map("templates")
        self.date_template_map = self.get_template_map("date_templates")
        self.ignore_templates = self.get_templates("ignore_templates")
        self.year_postfix = self.lang_config.get("year_postfix")
        self.month_postfix = self.lang_config.get("month_postfix")
        self.day_postfix = self.lang_config.get("day_postfix")
        self.fallback_countrycode = self.lang_config.get("fallback_countrycode")

    def is_known_template(self, name: str) -> bool:
        """
        Checks if a template name is known in the language configuration.
        Uses case-insensitive matching.
        """
        name = normalize_wikicode_name(name)
        return (
            name in self.template_map
            or name in self.date_template_map
            or name in self.ignore_templates
        )

    def get_tpl_cfg(self, name: str):
        """
        Returns the template configuration for a given template name.
        Uses case-insensitive matching.
        """
        name = name.lower()
        if name in self.template_map:
            return self.template_map[name]
        elif name in self.date_template_map:
            return self.date_template_map[name]
        else:
            return []

    def normalize_date_str(self, date_str: str) -> str:
        cleaned = date_str
        if self.month_map:
            # longest names first, for Korea/Japan, that uses numbers
            for local_name, eng_name in sorted(
                self.month_map.items(), key=lambda x: -len(x[0])
            ):
                cleaned = cleaned.replace(local_name, " " + eng_name + " ")
        if self.year_postfix:
            cleaned = re.sub(rf"(?<=\d){self.year_postfix}", " ", cleaned)
        if self.month_postfix:
            cleaned = re.sub(rf"(?<=\d){self.month_postfix}", " ", cleaned)
        if self.day_postfix:
            cleaned = re.sub(rf"(?<=\d){self.day_postfix}", " ", cleaned)
        return cleaned

    def get_templates(self, key: str):
        date_templates = set()
        for t in self.lang_config.get(key, []):
            names = [t["name"]]
            if "name_variants" in t:
                names.extend(t["name_variants"])
            for n in names:
                normalized = normalize_wikicode_name(n)
                date_templates.add(normalized)
        return date_templates

    def get_template_map(self, key: str):
        template_map = {}

        def add_template_with_variants(tpl):
            names = [tpl["name"]]
            if "name_variants" in tpl:
                names.extend(tpl["name_variants"])
            for n in names:
                normalized = normalize_wikicode_name(n)
                template_map.setdefault(normalized, []).append(tpl)

        for tpl in self.lang_config.get(key, []):
            add_template_with_variants(tpl)
        return template_map


class TemplateDateExtractor:
    """
    Extracts and normalizes date values from Wikipedia templates using flexible parameter mapping and language-specific configuration.
    Handles Julian/Gregorian calendar assignment, month normalization, and special template logic.
    """

    def __init__(
        self,
        tpl_cfg: dict,
        tpl,
        lang_config: LanguageConfig,
        country_config: CountryConfig,
    ):
        self.tpl_cfg = tpl_cfg
        self.param_names = tpl_cfg.get("param_names", {})
        self.booleans = tpl_cfg.get("booleans", {})
        self.default_dayfirst = tpl_cfg.get("dayfirst", True)
        self.tpl = tpl
        self.values = {}
        self.birth_values = {}
        self.death_values = {}
        self.results = []
        self.lang_config = lang_config
        self.country_config = country_config
        # Handle param_names (dictionary mapping)
        if self.param_names:
            param_map = get_param_name_map(tpl)
            for key, meaning in self.param_names.items():
                normalized_key = normalize_wikicode_name(key)
                normalized_meaning = normalize_wikicode_name(meaning)
                if normalized_key not in param_map:
                    continue

                val = tpl.get(param_map[normalized_key]).value
                dates = []
                names = []
                for inner_tpl in val.filter_templates():
                    name = normalize_wikicode_name(inner_tpl.name.strip_code())
                    if name in self.lang_config.ignore_templates:
                        continue
                    names.append(name)
                    for tpl_cfg in self.lang_config.get_tpl_cfg(name):
                        extractor = TemplateDateExtractor(
                            tpl_cfg, inner_tpl, self.lang_config, self.country_config
                        )
                        for res in extractor.get_all_dates():
                            dates.append(res)
                if dates:
                    self.values[normalized_meaning] = dates
                else:
                    if names:
                        raise RuntimeError(
                            f"Templates '{names}' in '{tpl.name}' did not yield any dates."
                        )
                    self.values[normalized_meaning] = val.strip_code().strip()

        # TODO: rewrite
        # Determine if julian flag is set using booleans from tpl_cfg if available
        julian_val = (
            self.values.get("julian", "").strip().lower()
            if "julian" in self.values
            else ""
        )
        true_values = ["1", "true", "yes"]
        if "yes" in self.booleans:
            true_values.append(self.booleans["yes"].strip().lower())
        self.julian_flag = julian_val in true_values
        # Set default calendar URL based on julian_flag
        if self.julian_flag:
            self.default_calendar_url = URL_PROLEPTIC_JULIAN_CALENDAR
        else:
            self.default_calendar_url = URL_UNSPECIFIED_CALENDAR
        # birth/death/None; None is for infobox templates
        # that combine both birth and death fields
        self.typ = tpl_cfg.get("typ")

    def get_value(self, typ: str, field: str):
        """
        Helper to get a value from self.values using normalized keys.
        typ: 'birth', 'death', or ''
        field: 'date', 'day and month', 'year', etc.
        """
        if typ:
            key = f"{typ} {field}"
        else:
            key = field
        return self.values.get(key)

    def __parse_date_string(
        self,
        date_str: str,
        dayfirst: Optional[bool],
        calendar_url: str = URL_UNSPECIFIED_CALENDAR,
        typ: Optional[str] = None,
    ):
        """
        Helper to parse date string and return a tuple (year, month, day, calendar_url), or None on failure.
        Uses two different defaults to detect which components are present.
        """
        try:
            date_str = self.lang_config.normalize_date_str(date_str)
            if not dayfirst:
                dayfirst = self.default_dayfirst
            today = datetime.today()
            default1 = datetime(today.year + 1, 2, 2)  # 2 Feb next year
            default2 = datetime(today.year + 2, 3, 3)  # 3 Mar year after next
            dt1 = date_parse(date_str, dayfirst=dayfirst, fuzzy=True, default=default1)
            dt2 = date_parse(date_str, dayfirst=dayfirst, fuzzy=True, default=default2)
            # Compare components: if they differ, that component was not present in the string
            y = dt1.year if dt1.year == dt2.year else 0
            m = dt1.month if dt1.month == dt2.month else 0
            d = dt1.day if dt1.day == dt2.day else 0
            if y == 0:
                return None
            if calendar_url == URL_UNSPECIFIED_CALENDAR:
                calendar_url = self.country_config.get_calendar_model(y, m, d)
            if not typ:
                typ = self.typ if self.typ else None
            # if not typ:
            #     raise ValueError("Type (typ) must be specified for date tuple.")
            wbt = build_wbtime(y, m, d, calendarmodel=calendar_url)
            tup = (typ, wbt)
            self.results.append(tup)
            return tup
        except Exception as e:
            print(f"Date parse error for '{date_str}': {e}")
            return None

    def _parse_date_string(
        self,
        date_str: str,
        dayfirst: Optional[bool] = None,
        calendar_url: str = URL_UNSPECIFIED_CALENDAR,
        typ: Optional[str] = None,
    ):
        result = self.__parse_date_string(date_str, dayfirst, calendar_url, typ)
        if not result:
            # remove (Aged: 87)
            cleaned_date_str = re.sub(r"\s*\(.*?\)", "", date_str)
            result = self.__parse_date_string(
                cleaned_date_str, dayfirst, calendar_url, typ
            )
        if result:
            print(f"{date_str} -> {result}")
        else:
            print(f"{date_str} -> ???")

    def _parse_components(
        self, day, month, year, calendar_url: str, typ: Optional[str] = None
    ):
        """
        Helper to parse date string and return a tuple (year, month, day, calendar_url), or None on failure.
        """
        if year:
            date_str = f"{day or ''} {month or ''} {year}".strip()
            self._parse_date_string(
                date_str, dayfirst=True, calendar_url=calendar_url, typ=typ
            )

    def get_all_dates(self) -> list:
        """
        Returns a list of tuples: (type, year, month, day, calendar_type)
        Handles param_names, param, params, and infobox_templates (combined birth/death fields).
        Uses self.dayfirst for date parsing.
        """
        self.results = []

        for typ in ["birth", "death", ""]:
            has_julian = any(
                self.get_value(typ, k)
                for k in ["year julian", "month julian", "day julian"]
            )
            g_year = self.get_value(typ, "year gregorian")
            g_month = self.get_value(typ, "month gregorian")
            g_day = self.get_value(typ, "day gregorian")
            if g_year:
                if has_julian:
                    cal_model = URL_PROLEPTIC_GREGORIAN_CALENDAR
                else:
                    # without julian, it can be julian or gregorian
                    # so we use the default calendar URL
                    cal_model = self.default_calendar_url
                self._parse_components(
                    g_day, g_month, g_year, cal_model, typ=typ if typ else None
                )
            if has_julian:
                j_year = self.get_value(typ, "year julian") or g_year
                j_month = self.get_value(typ, "month julian") or g_month
                j_day = self.get_value(typ, "day julian") or g_day
                self._parse_components(
                    j_day,
                    j_month,
                    j_year,
                    URL_PROLEPTIC_JULIAN_CALENDAR,
                    typ=typ if typ else None,
                )

            date = self.get_value(typ, "date")
            day_or_fulldate = self.get_value(typ, "day or full date")
            day_month = self.get_value(typ, "day and month")
            day = self.get_value(typ, "day")
            month = self.get_value(typ, "month")
            year = self.get_value(typ, "year")

            dayfirst = None
            if day_or_fulldate:
                if day_or_fulldate.isdigit():
                    day = day_or_fulldate
                else:
                    date = day_or_fulldate
            elif day_month and year:
                dayfirst = True
                date = f"{day_month} {year}"

            if date:
                if isinstance(date, str):
                    self._parse_date_string(
                        date,
                        dayfirst=dayfirst,
                        calendar_url=self.default_calendar_url,
                        typ=typ if typ else None,
                    )
                elif isinstance(date, list):
                    self.results.extend(
                        [(d_typ or typ, d_wbt) for d_typ, d_wbt in date]
                    )
            elif year:
                self._parse_components(
                    day,
                    month,
                    year,
                    self.default_calendar_url,
                    typ=typ if typ else None,
                )

        return self.results
