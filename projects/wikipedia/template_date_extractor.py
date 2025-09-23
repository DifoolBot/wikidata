import re
from datetime import datetime
from typing import Optional

import constants as wd
import pywikibot as pwb
from calendar_system_resolver import DateCalendarService
from dateutil.parser import parse as date_parse


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
    calendarmodel=wd.URL_UNSPECIFIED_CALENDAR,
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
        date_service: DateCalendarService,
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
        self.date_service = date_service
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
                            tpl_cfg, inner_tpl, self.lang_config, self.date_service
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

        self.default_calendar_url = wd.URL_UNSPECIFIED_CALENDAR
        if "calendar" in self.values:
            raise NotImplementedError(
                "The 'calendar' parameter is not supported in this version."
            )
            calendar_key = self.values["calendar"]
            for key, meaning in calendar_key:
                normalized_key = normalize_wikicode_name(key)
                normalized_meaning = normalize_wikicode_name(meaning)
                if normalized_key == calendar_key:
                    if normalized_meaning == "julian":
                        self.default_calendar_url = URL_PROLEPTIC_JULIAN_CALENDAR
                    elif normalized_meaning == "solar_hijri":
                        raise NotImplementedError(
                            "Solar Hijri calendar is not implemented yet."
                        )
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
        calendar_url: str = wd.URL_UNSPECIFIED_CALENDAR,
        typ: Optional[str] = None,
    ):
        """
        Helper to parse date string and return a tuple (year, month, day, calendar_url), or None on failure.
        Uses two different defaults to detect which components are present.
        """
        date_str = self.lang_config.normalize_date_str(date_str)
        if not dayfirst:
            dayfirst = self.default_dayfirst
        today = datetime.today()
        default1 = datetime(today.year + 1, 2, 2)  # 2 Feb next year
        default2 = datetime(today.year + 2, 3, 3)  # 3 Mar year after next
        try:
            dt1 = date_parse(date_str, dayfirst=dayfirst, fuzzy=True, default=default1)
            dt2 = date_parse(date_str, dayfirst=dayfirst, fuzzy=True, default=default2)
        except Exception as e:
            print(f"Date parse error for '{date_str}': {e}")
            return None
        # Compare components: if they differ, that component was not present in the string
        y = dt1.year if dt1.year == dt2.year else 0
        m = dt1.month if dt1.month == dt2.month else 0
        d = dt1.day if dt1.day == dt2.day else 0
        if y == 0:
            return None
        if calendar_url == wd.URL_UNSPECIFIED_CALENDAR:
            calendar_url = self.date_service.get_calendar_url(y, m, d)
        if not typ:
            typ = self.typ if self.typ else None
        # if not typ:
        #     raise ValueError("Type (typ) must be specified for date tuple.")
        wbt = build_wbtime(y, m, d, calendarmodel=calendar_url)
        tup = (typ, wbt)
        self.results.append(tup)
        return tup

    def _parse_date_string(
        self,
        date_str: str,
        dayfirst: Optional[bool] = None,
        calendar_url: str = wd.URL_UNSPECIFIED_CALENDAR,
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
                    cal_model = wd.URL_PROLEPTIC_GREGORIAN_CALENDAR
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
                    wd.URL_PROLEPTIC_JULIAN_CALENDAR,
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
