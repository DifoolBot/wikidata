import re
from typing import Optional

import pywikibot as pwb

import shared_lib.constants as wd
from shared_lib.lookups.interfaces.ecartico_lookup_interface import (
    EcarticoLookupAddInterface,
    EcarticoLookupInterface,
)
import shared_lib.change_wikidata as cwd

SKIP = "SKIP"
LEEG = "LEEG"
MULTIPLE = "MULTIPLE"


class Patronym:
    """
    Normalize and represent Dutch patronyms in a consistent way.

    Behaviour:
    - Accept variations like "Pieterszoon", "Pietersz.", "Pietersz", "Pietersdochter", "Pietersdr.", "Pietersdr".
    - Normalize self.patronym to the full form ("...zoon" or "...dochter").
    - Provide a consistent short form in self.short_patronym ("...z" or "...dr").
    - Set self.gender to "male" or "female".
    """

    def __init__(
        self, patronym: str, name: str, name_qid: str, qid: Optional[str] = None
    ) -> None:
        self.qid = qid
        p = (patronym or "").strip()
        if not p:
            raise RuntimeError("Empty patronym")

        # work with a copy for case-insensitive checks
        lower = p.lower()

        # Determine suffix and base by checking longer suffixes first
        if lower.endswith("zoon"):
            base = p[: -len("zoon")]
            self.gender = "male"
            full_suffix = "zoon"
            short_suffix = "z"
        elif lower.endswith("dochter"):
            base = p[: -len("dochter")]
            self.gender = "female"
            full_suffix = "dochter"
            short_suffix = "dr"
        elif lower.endswith("z."):
            base = p[: -len("z.")]
            self.gender = "male"
            full_suffix = "zoon"
            short_suffix = "z"
        elif lower.endswith("z"):
            # avoid misclassifying a name that legitimately ends with 'z' but is intended
            # as a patronym short form we assume it's a short patronym
            base = p[: -len("z")]
            self.gender = "male"
            full_suffix = "zoon"
            short_suffix = "z"
        elif lower.endswith("dr."):
            base = p[: -len("dr.")]
            self.gender = "female"
            full_suffix = "dochter"
            short_suffix = "dr"
        elif lower.endswith("dr"):
            base = p[: -len("dr")]
            self.gender = "female"
            full_suffix = "dochter"
            short_suffix = "dr"
        else:
            # If nothing matches, raise to avoid unpredictable behavior
            raise RuntimeError(f"Unexpected patronym format: {patronym}")

        base = base.strip()
        if not base:
            raise RuntimeError(f"Unexpected patronym format (empty base): {patronym}")

        # Normalized forms
        self.patronym = base + full_suffix
        self.short_patronym = base + short_suffix
        self.name = name.strip()
        self.name_qid = name_qid

    def nl_description(self) -> str:
        return f"patroniem van {self.name}"

    def en_description(self) -> str:
        kind = "son" if self.gender == "male" else "daughter"
        return f"Dutch patronym, meaning {kind} of {self.name}"

    def get_short_dot_patronym(self) -> str:
        return self.short_patronym + "."

    def create_item(self, site, label_dict):
        new_item = pwb.ItemPage(site)
        new_item.editLabels(labels=label_dict, summary="Setting labels")
        # Add description here or in another function
        return new_item.getID()

    def get_or_create(self):
        site = pwb.Site("wikidata", "wikidata")
        repo = site.data_repository()

        if not self.qid:
            id = self.create_item(
                site,
                label_dict={
                    "nl": self.patronym,
                    "en": self.patronym,
                    "mul": self.patronym,
                },
            )
            if not id:
                raise RuntimeError("Failed to create patronym item")
            self.qid = str(id)

        item = pwb.ItemPage(repo, self.qid)
        page = cwd.WikiDataPage(item, test=False)
        page.add_statement(cwd.Description(self.en_description(), "en"))
        page.add_statement(cwd.Description(self.nl_description(), "nl"))
        page.add_statement(cwd.Label(self.get_short_dot_patronym(), "mul"))
        page.add_statement(cwd.Label(self.short_patronym, "mul"))
        page.add_statement(cwd.InstanceOf(wd.QID_PATRONYMIC, based_on=self.name_qid))
        page.add_statement(cwd.ShortName(self.get_short_dot_patronym(), "nl"))
        page.add_statement(cwd.WritingSystem(wd.QID_LATIN_SCRIPT))
        if self.gender == "male":
            page.add_statement(cwd.HasCharacteristic(wd.QID_MASCULINE))
        if self.gender == "female":
            page.add_statement(cwd.HasCharacteristic(wd.QID_FEMININE))
        page.apply()

        return self.qid


class CachedEcarticoLookup(EcarticoLookupAddInterface):
    def __init__(
        self,
        cache: EcarticoLookupAddInterface,
        ecartico_source: EcarticoLookupInterface,
        wikidata_source: EcarticoLookupInterface,
    ) -> None:
        self.cache = cache
        self.ecartico_source = ecartico_source
        self.wikidata_source = wikidata_source

    def get_occupation(self, occupation_id: str) -> Optional[tuple[str, str]]:
        t = self.cache.get_occupation(occupation_id)
        if not t:
            t = self.ecartico_source.get_occupation(occupation_id)
            if t:
                qid, description = t
            else:
                qid = LEEG
                description = ""
            self.cache.add_occupation(occupation_id, description, qid)
        else:
            qid, description = t

        if qid == SKIP:
            return None
        if qid and qid.startswith("Q"):
            return qid, description

        raise RuntimeError(
            f"unrecognized occupation: {occupation_id} {description} -> {qid}"
        )

    def get_patronym_qid(self, text: str) -> Optional[str]:
        qid = self.cache.get_patronym_qid(text)
        if not qid:
            qid = LEEG
            self.cache.add_patronym(text, qid)

        if qid == SKIP:
            return None
        if qid and qid.startswith("Q"):
            return qid

        choice = pwb.input_choice(
            f"Unrecognized patronym '{text}' - what to do?",
            [("Add", "a"), ("Skip/Ignore", "s"), ("Error", "e")],
            default="e",
        )
        if choice == "a":
            patronyn = input("Enter full patronym text (e.g. Pietersz.): ")
            name = input('Enter name part (e.g. "Pieter"): ')
            name_qid = input("Enter QID of the name part: ")
            p = Patronym(patronyn, name, name_qid)
            qid = p.get_or_create()
            if not qid:
                raise RuntimeError("Failed to create patronym item")
            qid = str(qid)
            self.cache.add_patronym(text, qid)
            return qid
        elif choice == "s":
            qid = SKIP
            self.cache.add_patronym(text, "SKIP")
            return None

        raise RuntimeError(f"unrecognized patronym: {text} -> {qid}")

    def get_place(self, place_id: str) -> Optional[tuple[str, str]]:
        t = self.cache.get_place(place_id)
        if t:
            qid, description = t
        else:
            t = self.ecartico_source.get_place(place_id)
            if t:
                qid, description = t
            else:
                qid = LEEG
                description = ""
            self.cache.add_place(place_id, description, qid)

        if qid == SKIP:
            return None
        if qid and qid.startswith("Q"):
            return qid, description

        raise RuntimeError(f"unrecognized place: {place_id} {description}-> {qid}")

    def get_religion_qid(self, text: str) -> Optional[str]:
        qid = self.cache.get_religion_qid(text)
        if not qid:
            qid = LEEG
            self.cache.add_religion(text, qid)

        if qid == SKIP:
            return None
        if qid and qid.startswith("Q"):
            return qid

        raise RuntimeError(f"unrecognized religion: {text} -> {qid}")

    def get_rkdimage_qid(self, rkdimage_id: str) -> Optional[str]:
        qid = self.cache.get_rkdimage_qid(rkdimage_id)
        if not qid:
            # load
            qid = self.wikidata_source.get_rkdimage_qid(rkdimage_id)
            # qid = self.get_qids_from_rkdimage_id(rkdimage_id)
            # if len(qids) > 1:
            #     qid = MULTIPLE
            # elif not qids:
            #     qid = SKIP
            # else:
            #     qid = qids[0]
            if not qid:
                qid = SKIP
            self.cache.add_rkdimage_qid(rkdimage_id, qid)

        if qid == SKIP:
            return None
        if qid and qid.startswith("Q"):
            return qid

        raise RuntimeError(f"unrecognized rkdimage: {rkdimage_id} -> {qid}")

    def get_source(self, source_id: str) -> Optional[tuple[str, str]]:
        t = self.cache.get_source(source_id)
        if t:
            qid, description = t
        else:
            # load
            t = self.ecartico_source.get_source(source_id)
            if t:
                qid, description = t
            else:
                qid = LEEG
                description = ""
            self.cache.add_source(source_id, description, qid)

        if qid == SKIP:
            return None
        if qid and qid.startswith("Q"):
            return qid, description

        # todo; tijdelijk
        return None
        raise RuntimeError(f"unrecognized source: {source_id}-{description} -> {qid}")

    def get_genre_qid(self, attribute: str, value: str) -> Optional[str]:
        qid = self.cache.get_genre_qid(attribute, value)

        if not qid:
            qid = LEEG
            self.cache.add_genre(attribute, value, qid)

        if qid == SKIP:
            return None
        if qid and qid.startswith("Q"):
            return qid

        raise RuntimeError(f"unrecognized genre: {attribute} {value} -> {qid}")

    def add_genre(self, attribute: str, value: str, qid: str) -> None:
        self.cache.add_genre(attribute, value, qid)

    def add_gutenberg_ebook_id_qid(self, ebook_id: str, qid: str) -> None:
        self.cache.add_gutenberg_ebook_id_qid(ebook_id, qid)

    def add_is_possible(self, ecartico_id: Optional[str], qid: str):
        self.cache.add_is_possible(ecartico_id, qid)

    def add_occupation(self, occupation_id, description: str, qid: str):
        self.cache.add_occupation(occupation_id, description, qid)

    def add_occupation_type(self, qid: str, description: str, text: str) -> None:
        self.cache.add_occupation_type(qid, description, text)

    def add_patronym(self, text: str, qid: str) -> None:
        self.cache.add_patronym(text, qid)

    def add_person(
        self, ecartico_id: Optional[str], description: Optional[str], qid: Optional[str]
    ):
        self.cache.add_person(ecartico_id, description, qid)

    def add_place(self, place_id: str, description: str, qid: str):
        self.cache.add_place(place_id, description, qid)

    def add_religion(self, religion: str, qid: str) -> None:
        self.cache.add_religion(religion, qid)

    def add_rijksmuseum_qid(self, inventory_number: str, qid: str) -> None:
        self.cache.add_rijksmuseum_qid(inventory_number, qid)

    def add_rkdimage_qid(self, rkdimage_id: str, qid: str) -> None:
        self.cache.add_rkdimage_qid(rkdimage_id, qid)

    def add_source(self, source_id: str, description: str, qid: str):
        self.cache.add_source(source_id, description, qid)

    def get_person(self, ecartico_id: str) -> Optional[tuple[str, str]]:
        t = self.cache.get_person(ecartico_id)
        if t:
            qid, description = t
        else:
            e_description = ""
            t = self.ecartico_source.get_person(ecartico_id)
            if t:
                e_qid, e_description = t
                if e_qid and e_qid.startswith("Q"):
                    self.cache.add_person(ecartico_id, e_description, e_qid)
                    return e_qid, e_description

            t = self.wikidata_source.get_person(ecartico_id)
            if t:
                w_qid, w_description = t
                if w_qid and w_qid.startswith("Q"):
                    if w_description == "?":
                        w_description = None
                    w_description = w_description or e_description
                    if not w_description:
                        w_description = "?"
                    self.cache.add_person(ecartico_id, w_description, w_qid)
                    return w_qid, w_description

        if qid == SKIP:
            return None
        if qid and qid.startswith("Q"):
            return qid, description

        raise RuntimeError(f"unrecognized person: {ecartico_id} {description} -> {qid}")

    # def get_person_qid(self, ecartico_id: Optional[str]) -> Optional[str]:
    #     qid = self.cache.get_person_qid(ecartico_id)
    #     if not qid:

    #         # load from ecartico
    #         complete_url = f"https://ecartico.org/persons/{ecartico_id}"
    #         qid, description = self.extract_qid_from_ecartico_page(complete_url)
    #         if qid and qid.startswith("Q"):
    #             self.cache.add_person(ecartico_id, description, qid)
    #             return qid

    #         # load from wikidata
    #         qids = self.get_qids_from_ecartico_id(ecartico_id)
    #         if len(qids) > 1:
    #             qid = MULTIPLE
    #         elif not qids:
    #             qid = SKIP
    #         else:
    #             qid = qids[0]
    #         self.cache.add_person(ecartico_id, description, qid)

    #     if qid == SKIP:
    #         return None
    #     if qid and qid.startswith("Q"):
    #         return qid

    #     raise RuntimeError(f"unrecognized person qid: {ecartico_id} -> {qid}")

    def get_gutenberg_qid(self, ebook_id: Optional[str]) -> Optional[str]:
        qid = self.cache.get_gutenberg_qid(ebook_id)
        if not qid:
            # load from wikidata
            qid = self.wikidata_source.get_gutenberg_qid(ebook_id)
            # if len(qids) > 1:
            #     qid = MULTIPLE
            if not qid:
                qid = SKIP
            # else:
            #     qid = qids[0]
            self.cache.add_gutenberg_ebook_id_qid(ebook_id, qid)

        if qid == SKIP:
            return None
        if qid and qid.startswith("Q"):
            return qid

    def get_rijksmuseum_inventory_number(self, url: str) -> str:
        match = re.search(
            r"^https?:\/\/www.rijksmuseum\.nl\/nl\/zoeken\/objecten\?q=([A-Z0-9.-]+)",
            url,
            re.IGNORECASE,
        )
        if not match:
            raise RuntimeError(f"Unexpected url {url}")
        inventory_number = match.group(1)

        return inventory_number

    def get_rijksmuseum_qid(
        self, url: str, inventory_number: Optional[str]
    ) -> Optional[str]:
        if not inventory_number:
            inventory_number = self.get_rijksmuseum_inventory_number(url)

        qid = self.cache.get_rijksmuseum_qid(url, inventory_number)
        if not qid:
            # load from wikidata
            qid = self.wikidata_source.get_rijksmuseum_qid(url, inventory_number)
            # if len(qids) > 1:
            #     qid = MULTIPLE
            if not qid:
                qid = SKIP
            # else:
            #     qid = qids[0]
            self.cache.add_rijksmuseum_qid(inventory_number, qid)

        if qid == SKIP:
            return None
        if qid and qid.startswith("Q"):
            return qid

        raise RuntimeError(
            f"unrecognized rijksmuseum_inventory_number qid: {inventory_number} -> {qid}"
        )

    def is_possible(self, ecartico_id: Optional[str], qid: str) -> bool:
        return self.cache.is_possible(ecartico_id, qid)

    def get_occupation_type(self, qid: str) -> Optional[str]:
        text = self.cache.get_occupation_type(qid)
        if text == LEEG:
            return None
        if text:
            return text

        # load
        description = self.wikidata_source.get_description(qid)
        if not description:
            raise RuntimeError(f"No description for occupation {qid}")

        types = []

        if self.wikidata_source.get_is(qid, wd.QID_POSITION):
            types.append("Position")
        if self.wikidata_source.get_is(qid, wd.QID_NOBLE_TITLE):
            types.append("NobleTitle")
        if self.wikidata_source.get_is(qid, wd.QID_OCCUPATION):
            types.append("Occupation")

        text = "+".join(types) if types else LEEG

        self.cache.add_occupation_type(qid, description, text)
        return text

    def get_description(self, qid: str) -> Optional[str]:
        return self.wikidata_source.get_description(qid)

    def get_is(self, qid: str, query: str) -> bool:
        return self.wikidata_source.get_is(qid, query)


# def main():
#     p = Patronym("Eliasz.", "Elias", "Q11878157", qid="Q136511567")
#     p.get_or_create()


# if __name__ == "__main__":
#     main()
