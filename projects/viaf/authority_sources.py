import requests

import shared_lib.constants as wd

READ_TIMEOUT = 20  # sec


class AuthorityRecord:
    def __init__(self, qid: str, wikidata_external_id: str):
        self.qid = qid
        # identifier for the Virtual International Authority File database
        self.viaf_cluster_id: str | None = None
        # the external id in Wikidata; for example Vincent van Gogh, BNF: 11927591g (BNF codes in Wikidata include the check digit)
        self.wikidata_external_id = wikidata_external_id
        # the external id in VIAF; for example Vincent van Gogh, BNF: FRBNF119275919 (BNF codes in VIAF exclude the check digit, and sometimes contain the FRBNF prefix)
        # self.xxx_viaf_external_id = None
        # the code to use to search the VIAF API; for example Vincent van Gogh, BNF: 11927591
        # VIAF calls this the localAuthorityId
        self.viaf_search_key: str | None = None
        # another code; only used by NukatAuthoritySource
        self.nukat_specific_code: str | None = None

    def matches_viaf_search_key(self, viaf_external_id: str) -> bool:
        """Checks if the given VIAF ID matches the stored VIAF search key."""
        return viaf_external_id == self.viaf_search_key

    def normalized_match(self, viaf_external_id: str) -> bool:
        """Performs a basic normalized match by removing spaces and dots."""
        return viaf_external_id.replace(" ", "").replace(
            ".", ""
        ) == self.wikidata_external_id.replace(" ", "").replace(".", "")

    def compute_viaf_search_key(self):
        """Computes the VIAF search key by normalizing the Wikidata ID (removes spaces, dots, and replaces '/' with '_')."""
        self.viaf_search_key = (
            self.wikidata_external_id.replace(" ", "")
            .replace(".", "")
            .replace("/", "_")
        )


def compute_bnf_ark_from_8digits(orig_id: str) -> str:
    bnf_xdigits = "0123456789bcdfghjkmnpqrstvwxz"
    bnf_check_digit = 0

    id = "cb" + orig_id
    for i in range(len(id)):
        bnf_check_digit += bnf_xdigits.index(id[i]) * (i + 1)
    # 29 is the radix
    return id + bnf_xdigits[bnf_check_digit % len(bnf_xdigits)]


class AuthoritySource:
    def __init__(self, pid: str, viaf_code: str, description: str):
        self.pid = pid  # Wikidata Property ID for the authority source
        # VIAF calls this the authoritySourceCode:
        self.viaf_code = viaf_code  # VIAF-assigned code for this authority source
        self.description = description  # Brief description of the authority source

    def matches_viaf_external_id(
        self, nsid: str, content_id: str, record: AuthorityRecord
    ) -> bool:
        """Checks if the given VIAF ID matches the normalized form of the authority ID."""
        return record.normalized_match(nsid)

    def compute_viaf_search_key(self, record: AuthorityRecord) -> None:
        """computes a VIAF search key using the authority-specific method."""
        record.compute_viaf_search_key()


class BnchlAuthoritySource(AuthoritySource):
    def matches_viaf_external_id(
        self, nsid: str, content_id: str, record: AuthorityRecord
    ) -> bool:
        """BNCHL-specific matching by prefixing 'BNC' to the VIAF search key."""
        if not record.viaf_search_key:
            raise RuntimeError("viaf_search_key is empty")
        return nsid == "BNC" + record.viaf_search_key

    def compute_viaf_search_key(self, record: AuthorityRecord) -> None:
        """computes a BNCHL-specific VIAF search key using a padded numeric format."""
        # The VIAF search key is a 22-digit padded number prefixed with '1'
        padded_number = ("0" * 22) + record.wikidata_external_id
        record.viaf_search_key = "1" + padded_number[-22:]


class BnfAuthoritySource(AuthoritySource):
    def matches_viaf_external_id(
        self, nsid: str, content_id: str, record: AuthorityRecord
    ) -> bool:
        """BNF-specific matching by handling FRBNF prefixes and checksums."""
        if nsid.startswith("FRBNF"):
            nsid = nsid[5:]  # Remove "FRBNF" prefix
            if len(nsid) == 9:  # Remove possible incorrect checksum
                nsid = nsid[:-1]
            return record.matches_viaf_search_key(nsid)
        else:
            if not record.viaf_search_key:
                raise RuntimeError("No record.viaf_search_key")
            # Convert a BNF catalog URL to an authority code
            nsid = nsid.replace("http://catalogue.bnf.fr/ark:/12148/", "")
            bnf_ark = compute_bnf_ark_from_8digits(record.viaf_search_key)
            return nsid == bnf_ark

    def compute_viaf_search_key(self, record: AuthorityRecord) -> None:
        """BNF-specific VIAF search key computation by adjusting checksums."""
        search_key = record.wikidata_external_id[
            :-1
        ]  # Remove checksum from Wikidata ID
        bnf_ark = compute_bnf_ark_from_8digits(search_key)

        # Verify if BNF Ark matches expected format before assigning search key
        if bnf_ark == "cb" + record.wikidata_external_id:
            record.viaf_search_key = search_key
        else:
            record.viaf_search_key = record.wikidata_external_id


class RismAuthoritySource(AuthoritySource):
    def matches_viaf_external_id(
        self, nsid: str, content_id: str, record: AuthorityRecord
    ):
        """Standard matching using the computed VIAF search key."""
        return record.matches_viaf_search_key(nsid)

    def compute_viaf_search_key(self, record: AuthorityRecord) -> None:
        record.viaf_search_key = (
            record.wikidata_external_id.replace("people", "pe")
            .replace("_", "")
            .replace("/", "")
        )


class GndAuthoritySource(AuthoritySource):
    def matches_viaf_external_id(
        self, nsid: str, content_id: str, record: AuthorityRecord
    ):
        # http://d-nb.info/gnd/171910605 vs 171910605
        nsid = nsid.replace("http://d-nb.info/gnd/", "")
        return (nsid == record.wikidata_external_id) or (
            content_id == record.wikidata_external_id
        )


class SbnAuthoritySource(AuthoritySource):
    def matches_viaf_external_id(
        self, nsid: str, content_id: str, record: AuthorityRecord
    ):
        # IT\\ICCU\\SBLV\\015759 vs SBLV015759
        nsid = nsid.replace("IT\\ICCU", "").replace("\\", "")
        return nsid == record.wikidata_external_id


class LnbAuthoritySource(AuthoritySource):
    def matches_viaf_external_id(
        self, nsid: str, content_id: str, record: AuthorityRecord
    ):
        """Standard matching using the computed VIAF search key."""
        return record.matches_viaf_search_key(nsid)

    def compute_viaf_search_key(self, record: AuthorityRecord) -> None:
        # 000011784 -> LNC10-000011784
        #
        record.viaf_search_key = "LNC10-" + record.wikidata_external_id
        # todo; nakijken ; deze kan ook een LNB: link hebben


class NlaAuthoritySource(AuthoritySource):
    def matches_viaf_external_id(
        self, nsid: str, content_id: str, record: AuthorityRecord
    ) -> bool:
        """Standard matching using the computed VIAF search key."""
        return record.matches_viaf_search_key(nsid)

    def compute_viaf_search_key(self, record: AuthorityRecord) -> None:
        """Formats ID as a 12-digit zero-padded number for NLA."""
        res = "000000000000" + record.wikidata_external_id
        record.viaf_search_key = res[-12:]  # Extract last 12 digits


class NlrAuthoritySource(AuthoritySource):
    def matches_viaf_external_id(
        self, nsid: str, content_id: str, record: AuthorityRecord
    ):
        nsid = nsid.replace("RU\\NLR\\AUTH\\", "")
        return nsid == record.wikidata_external_id

    def compute_viaf_search_key(self, record: AuthorityRecord) -> None:
        record.viaf_search_key = "RU NLR AUTH " + record.wikidata_external_id


class NukatAuthoritySource(AuthoritySource):
    def matches_viaf_external_id(
        self, nsid: str, content_id: str, record: AuthorityRecord
    ):
        return (
            nsid.replace(" ", "") == record.wikidata_external_id.replace(" ", "")
        ) or (
            content_id.replace(" ", "") == record.wikidata_external_id.replace(" ", "")
        )

    def compute_viaf_search_key(self, record: AuthorityRecord) -> None:
        record.nukat_specific_code = record.wikidata_external_id
        if record.nukat_specific_code is None:
            record.viaf_search_key = None
        elif record.wikidata_external_id.startswith("n"):
            record.viaf_search_key = "n " + record.wikidata_external_id[1:]


class PerseusAuthoritySource(AuthoritySource):
    def matches_viaf_external_id(
        self, nsid: str, content_id: str, record: AuthorityRecord
    ):
        """Standard matching using the computed VIAF search key."""
        return record.matches_viaf_search_key(nsid)

    def compute_viaf_search_key(self, record: AuthorityRecord) -> None:
        # urn:cite:perseus:author.384.1
        record.viaf_search_key = (
            "urn:cite:perseus:author." + record.wikidata_external_id
        )


class ReroAuthoritySource(AuthoritySource):
    def matches_viaf_external_id(
        self, nsid: str, content_id: str, record: AuthorityRecord
    ):
        """Standard matching using the computed VIAF search key."""
        return record.matches_viaf_search_key(nsid)

    def compute_viaf_search_key(self, record: AuthorityRecord) -> None:
        record.viaf_search_key = record.wikidata_external_id.replace("02-", "").replace(
            "02_", ""
        )


class SelibrAuthoritySource(AuthoritySource):
    def fetch_controlnumber(self, record: AuthorityRecord):
        url = f"https://libris.kb.se/{record.wikidata_external_id}/data.json"
        response = requests.get(url, timeout=READ_TIMEOUT)
        if response.status_code != 200:
            # typical 404 NOT FOUND or 410 GONE
            raise RuntimeError(f"Status code: {response.status_code}")
        payload = response.json()
        return payload["controlNumber"]

    # def matches_viaf_external_id(self, nsid: str, content_id: str, record: AuthorityRecord):
    #     # None, selibr_determine_search_code
    #     return record.matches_viaf_search_key(viaf_external_id)

    def compute_viaf_search_key(self, record: AuthorityRecord) -> None:
        record.viaf_search_key = self.fetch_controlnumber(record)


class SrpAuthoritySource(AuthoritySource):
    def matches_viaf_external_id(
        self, nsid: str, content_id: str, record: AuthorityRecord
    ):
        """Standard matching using the computed VIAF search key."""
        return record.matches_viaf_search_key(nsid)

    def compute_viaf_search_key(self, record: AuthorityRecord) -> None:
        record.viaf_search_key = "person_" + record.wikidata_external_id


class AuthoritySources:
    def __init__(self):

        self._sources_by_pid = {}

        sources = [
            (AuthoritySource, wd.PID_BNMM_AUTHORITY_ID, "ARBABN", "BNMM authority ID"),
            (AuthoritySource, wd.PID_BANQ_AUTHORITY_ID, "B2Q", "BAnQ authority ID"),
            (
                AuthoritySource,
                wd.PID_VATICAN_LIBRARY_VCBA_ID,
                "BAV",
                "Vatican Library VcBA ID",
            ),
            (AuthoritySource, wd.PID_NORAF_ID, "BIBSYS", "NORAF ID"),
            (
                AuthoritySource,
                wd.PID_NATIONAL_LIBRARY_OF_BRAZIL_ID,
                "BLBNB",
                "National Library of Brazil ID",
            ),
            (AuthoritySource, wd.PID_CANTIC_ID, "BNC", "CANTIC ID"),
            (
                BnchlAuthoritySource,
                wd.PID_NATIONAL_LIBRARY_OF_CHILE_ID,
                "BNCHL",
                "National Library of Chile ID",
            ),
            (
                AuthoritySource,
                wd.PID_BIBLIOTECA_NACIONAL_DE_ESPANA_ID,
                "BNE",
                "Biblioteca Nacional de España ID",
            ),
            (
                BnfAuthoritySource,
                wd.PID_BIBLIOTHEQUE_NATIONALE_DE_FRANCE_ID,
                "BNF",
                "Bibliothèque nationale de France ID",
            ),
            (
                AuthoritySource,
                wd.PID_NATIONAL_LIBRARY_OF_LUXEMBOURG_ID,
                "BNL",
                "National Library of Luxembourg ID",
            ),
            (
                AuthoritySource,
                wd.PID_CANADIANA_NAME_AUTHORITY_ID,
                "CAOONL",
                "Canadiana Name Authority ID",
            ),
            (AuthoritySource, wd.PID_CYT_CCS, "CYT", "CYT/CCS"),  # 2 varianten
            (AuthoritySource, wd.PID_DBC_AUTHOR_ID, "DBC", "DBC author ID"),
            (RismAuthoritySource, wd.PID_RISM_ID, "DE633", "RISM ID"),
            # uitgezet
            # (AuthoritySource, wd.PID_RISM_ID, "DE663", "RISM ID"),
            (GndAuthoritySource, wd.PID_GND_ID, "DNB", "GND ID"),
            (AuthoritySource, wd.PID_EGAXA_ID, "EGAXA", "EGAXA ID"),
            (AuthoritySource, wd.PID_ELNET_ID, "ERRR", "ELNET ID"),
            (AuthoritySource, wd.PID_FAST_ID, "FAST", "FAST ID"),
            (
                AuthoritySource,
                wd.PID_NATIONAL_LIBRARY_OF_GREECE_ID,
                "GRATEVE",
                "National Library of Greece ID",
            ),
            (SbnAuthoritySource, wd.PID_SBN_AUTHOR_ID, "ICCU", "SBN author ID"),
            # werkt nu; veel fouten:
            (AuthoritySource, wd.PID_ISNI, "ISNI", "ISNI"),
            # weinig fouten:
            (
                AuthoritySource,
                wd.PID_NATIONAL_LIBRARY_OF_ISRAEL_J9U_ID,
                "J9U",
                "National Library of Israel J9U ID",
            ),
            (
                AuthoritySource,
                wd.PID_UNION_LIST_OF_ARTIST_NAMES_ID,
                "JPG",
                "Union List of Artist Names ID",
            ),
            (
                AuthoritySource,
                wd.PID_NATIONAL_LIBRARY_OF_KOREA_ID,
                "KRNLK",
                "National Library of Korea ID",
            ),
            (
                AuthoritySource,
                wd.PID_LIBRARY_OF_CONGRESS_AUTHORITY_ID,
                "LC",
                "Library of Congress authority ID",
            ),  # tested
            (
                AuthoritySource,
                wd.PID_NATIONAL_LIBRARY_OF_LITHUANIA_ID,
                "LIH",
                "National Library of Lithuania ID",
            ),
            (
                LnbAuthoritySource,
                wd.PID_NATIONAL_LIBRARY_OF_LATVIA_ID,
                "LNB",
                "National Library of Latvia ID",
            ),
            (
                AuthoritySource,
                wd.PID_LEBANESE_NATIONAL_LIBRARY_ID,
                "LNL",
                "Lebanese National Library ID",
            ),
            (AuthoritySource, wd.PID_BNRM_ID, "MRBNR", "BNRM ID"),
            (
                AuthoritySource,
                wd.PID_NATIONAL_LIBRARY_OF_IRELAND_ID,
                "N6I",
                "National Library of Ireland ID",
            ),
            (AuthoritySource, wd.PID_NDL_AUTHORITY_ID, "NDL", "NDL Authority ID"),
            (
                AuthoritySource,
                wd.PID_CINII_BOOKS_AUTHOR_ID,
                "NII",
                "CiNii Books author ID",
            ),
            (AuthoritySource, wd.PID_NL_CR_AUT_ID, "NKC", "NL CR AUT ID"),
            (
                NlaAuthoritySource,
                wd.PID_LIBRARIES_AUSTRALIA_ID,
                "NLA",
                "Libraries Australia ID",
            ),
            (
                AuthoritySource,
                wd.PID_NATIONAL_LIBRARY_BOARD_SINGAPORE_ID,
                "NLB",
                "National Library Board Singapore ID",
            ),
            (
                NlrAuthoritySource,
                wd.PID_NATIONAL_LIBRARY_OF_RUSSIA_ID,
                "NLR",
                "National Library of Russia ID",
            ),
            (AuthoritySource, wd.PID_NSK_ID, "NSK", "NSK ID"),  # tested
            (
                AuthoritySource,
                wd.PID_NSZL_NAME_AUTHORITY_ID,
                "NSZL",
                "NSZL name authority ID",
            ),
            (AuthoritySource, wd.PID_NSZL_VIAF_ID, "NSZL", "NSZL (VIAF), ID"),
            (
                AuthoritySource,
                wd.PID_NATIONALE_THESAURUS_VOOR_AUTEURSNAMEN_ID,
                "NTA",
                "Nationale Thesaurus voor Auteursnamen ID",
            ),
            (NukatAuthoritySource, wd.PID_NUKAT_ID, "NUKAT", "NUKAT ID"),
            (AuthoritySource, wd.PID_RILM_ID, "NYNYRILM", "RILM ID"),
            (
                PerseusAuthoritySource,
                wd.PID_PERSEUS_AUTHOR_ID,
                "PERSEUS",
                "Perseus author ID",
            ),
            (AuthoritySource, wd.PID_PLWABN_ID, "PLWABN", "PLWABN ID"),
            (
                AuthoritySource,
                wd.PID_PORTUGUESE_NATIONAL_LIBRARY_AUTHOR_ID,
                "PTBNP",
                "Portuguese National Library author ID",
            ),
            (
                ReroAuthoritySource,
                wd.PID_RERO_ID_OBSOLETE,
                "RERO",
                "RERO ID (obsolete),",
            ),
            (SelibrAuthoritySource, wd.PID_LIBRIS_URI, "SELIBR", "Libris-URI"),
            (AuthoritySource, wd.PID_CONOR_SI_ID, "SIMACOB", "CONOR.SI ID"),
            (
                AuthoritySource,
                wd.PID_SLOVAK_NATIONAL_LIBRARY_VIAF_ID,
                "SKMASNL",
                "Slovak National Library (VIAF), ID",
            ),
            (
                SrpAuthoritySource,
                wd.PID_SYRIAC_BIOGRAPHICAL_DICTIONARY_ID,
                "SRP",
                "Syriac Biographical Dictionary ID",
            ),
            (AuthoritySource, wd.PID_IDREF_ID, "SUDOC", "IdRef ID"),
            # uitgezet:
            # (AuthoritySource, wd.PID_GND_ID, "SZ", "GND ID"),
            (
                AuthoritySource,
                wd.PID_UAE_UNIVERSITY_LIBRARIES_ID,
                "UAE",
                "UAE University Libraries ID",
            ),
            (
                AuthoritySource,
                wd.PID_NATIONAL_LIBRARY_OF_ICELAND_ID,
                "UIY",
                "National Library of Iceland ID",
            ),
            (
                AuthoritySource,
                wd.PID_FLEMISH_PUBLIC_LIBRARIES_ID,
                "VLACC",
                "Flemish Public Libraries ID",
            ),
            # uitgezet:
            # self.add(AuthoritySource, wd.PID_NORAF_ID, "W2Z", "NORAF ID"))
        ]
        for source_class, pid, viaf_code, description in sources:
            self.add(source_class(pid, viaf_code, description))

    def add(self, item: AuthoritySource) -> None:
        if item.pid in self._sources_by_pid:
            raise RuntimeError(f"{item.pid} is already assigned")
        self._sources_by_pid[item.pid] = item

    def get(self, pid: str) -> AuthoritySource:
        return self._sources_by_pid[pid]
