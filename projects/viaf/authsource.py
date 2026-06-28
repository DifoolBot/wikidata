import re

import requests

PID_BANQ_AUTHORITY_ID = "P3280"
PID_BIBLIOTECA_NACIONAL_DE_ESPANA_ID = "P950"
PID_BIBLIOTHEQUE_NATIONALE_DE_FRANCE_ID = "P268"
PID_BNMM_AUTHORITY_ID = "P3788"
PID_BNRM_ID = "P7058"
PID_CANADIANA_NAME_AUTHORITY_ID = "P8179"
PID_CANTIC_ID = "P9984"
PID_CINII_BOOKS_AUTHOR_ID = "P271"
PID_CONOR_SI_ID = "P1280"
PID_CYT_CCS = "P10307"
PID_DBC_AUTHOR_ID = "P3846"
PID_EGAXA_ID = "P1309"
PID_ELNET_ID = "P6394"
PID_FAST_ID = "P2163"
PID_FLEMISH_PUBLIC_LIBRARIES_ID = "P7024"
PID_GND_ID = "P227"
PID_IDREF_ID = "P269"
PID_ISNI = "P213"
PID_LEBANESE_NATIONAL_LIBRARY_ID = "P7026"
PID_LIBRARIES_AUSTRALIA_ID = "P409"
PID_LIBRARY_OF_CONGRESS_AUTHORITY_ID = "P244"
PID_LIBRIS_URI = "P5587"
PID_NATIONALE_THESAURUS_VOOR_AUTEURSNAMEN_ID = "P1006"
PID_NATIONAL_LIBRARY_BOARD_SINGAPORE_ID = "P3988"
PID_NATIONAL_LIBRARY_OF_BRAZIL_ID = "P4619"
PID_NATIONAL_LIBRARY_OF_CHILE_ID = "P7369"
PID_NATIONAL_LIBRARY_OF_GREECE_ID = "P3348"
PID_NATIONAL_LIBRARY_OF_ICELAND_ID = "P7039"
PID_NATIONAL_LIBRARY_OF_IRELAND_ID = "P10227"
PID_NATIONAL_LIBRARY_OF_ISRAEL_J9U_ID = "P8189"
PID_NATIONAL_LIBRARY_OF_KOREA_ID = "P5034"
PID_NATIONAL_LIBRARY_OF_LATVIA_ID = "P1368"
PID_NATIONAL_LIBRARY_OF_LITHUANIA_ID = "P7699"
PID_NATIONAL_LIBRARY_OF_LUXEMBOURG_ID = "P7028"
PID_NATIONAL_LIBRARY_OF_RUSSIA_ID = "P7029"
PID_NDL_AUTHORITY_ID = "P349"
PID_NL_CR_AUT_ID = "P691"
PID_NORAF_ID = "P1015"
PID_NSK_ID = "P1375"
PID_NSZL_NAME_AUTHORITY_ID = "P3133"
PID_NSZL_VIAF_ID = "P951"
PID_NUKAT_ID = "P1207"
PID_PERSEUS_AUTHOR_ID = "P7041"
PID_PLWABN_ID = "P7293"
PID_PORTUGUESE_NATIONAL_LIBRARY_AUTHOR_ID = "P1005"
PID_RERO_ID_OBSOLETE = "P3065"
PID_RILM_ID = "P9171"
PID_RISM_ID = "P5504"
PID_SBN_AUTHOR_ID = "P396"
PID_SLOVAK_NATIONAL_LIBRARY_VIAF_ID = "P7700"
PID_SYRIAC_BIOGRAPHICAL_DICTIONARY_ID = "P6934"
PID_UAE_UNIVERSITY_LIBRARIES_ID = "P10021"
PID_UNION_LIST_OF_ARTIST_NAMES_ID = "P245"
PID_VATICAN_LIBRARY_VCBA_ID = "P8034"

READ_TIMEOUT = 20  # sec


class AuthorityID:
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
        # another code; only used by NUKAT_AuthoritySource
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
        self, nsid: str, content_id: str, aid: AuthorityID
    ) -> bool:
        """Checks if the given VIAF ID matches the normalized form of the authority ID."""
        return aid.normalized_match(nsid)

    def compute_viaf_search_key(self, aid: AuthorityID) -> None:
        """computes a VIAF search key using the authority-specific method."""
        aid.compute_viaf_search_key()


class BNCHL_AuthoritySource(AuthoritySource):
    def matches_viaf_external_id(
        self, nsid: str, content_id: str, aid: AuthorityID
    ) -> bool:
        """BNCHL-specific matching by prefixing 'BNC' to the VIAF search key."""
        if not aid.viaf_search_key:
            raise RuntimeError("viaf_search_key is empty")
        return nsid == "BNC" + aid.viaf_search_key

    def compute_viaf_search_key(self, aid: AuthorityID) -> None:
        """computes a BNCHL-specific VIAF search key using a padded numeric format."""
        # The VIAF search key is a 22-digit padded number prefixed with '1'
        padded_number = ("0" * 22) + aid.wikidata_external_id
        aid.viaf_search_key = "1" + padded_number[-22:]


class BNF_AuthoritySource(AuthoritySource):
    def matches_viaf_external_id(
        self, nsid: str, content_id: str, aid: AuthorityID
    ) -> bool:
        """BNF-specific matching by handling FRBNF prefixes and checksums."""
        if nsid.startswith("FRBNF"):
            nsid = nsid[5:]  # Remove "FRBNF" prefix
            if len(nsid) == 9:  # Remove possible incorrect checksum
                nsid = nsid[:-1]
            return aid.matches_viaf_search_key(nsid)
        else:
            if not aid.viaf_search_key:
                raise RuntimeError("No aid.viaf_search_key")
            # Convert a BNF catalog URL to an authority code
            nsid = nsid.replace("http://catalogue.bnf.fr/ark:/12148/", "")
            bnf_ark = compute_bnf_ark_from_8digits(aid.viaf_search_key)
            return nsid == bnf_ark

    def compute_viaf_search_key(self, aid: AuthorityID) -> None:
        """BNF-specific VIAF search key computation by adjusting checksums."""
        search_key = aid.wikidata_external_id[:-1]  # Remove checksum from Wikidata ID
        bnf_ark = compute_bnf_ark_from_8digits(search_key)

        # Verify if BNF Ark matches expected format before assigning search key
        if bnf_ark == "cb" + aid.wikidata_external_id:
            aid.viaf_search_key = search_key
        else:
            aid.viaf_search_key = aid.wikidata_external_id


class RISM_AuthoritySource(AuthoritySource):
    def matches_viaf_external_id(self, nsid: str, content_id: str, aid: AuthorityID):
        """Standard matching using the computed VIAF search key."""
        return aid.matches_viaf_search_key(nsid)

    def compute_viaf_search_key(self, aid: AuthorityID) -> None:
        aid.viaf_search_key = (
            aid.wikidata_external_id.replace("people", "pe")
            .replace("_", "")
            .replace("/", "")
        )


class GND_AuthoritySource(AuthoritySource):
    def matches_viaf_external_id(self, nsid: str, content_id: str, aid: AuthorityID):
        # http://d-nb.info/gnd/171910605 vs 171910605
        nsid = nsid.replace("http://d-nb.info/gnd/", "")
        return (nsid == aid.wikidata_external_id) or (
            content_id == aid.wikidata_external_id
        )


class SBN_AuthoritySource(AuthoritySource):
    def matches_viaf_external_id(self, nsid: str, content_id: str, aid: AuthorityID):
        # IT\\ICCU\\SBLV\\015759 vs SBLV015759
        nsid = nsid.replace("IT\\ICCU", "").replace("\\", "")
        return nsid == aid.wikidata_external_id


class LNB_AuthoritySource(AuthoritySource):
    def matches_viaf_external_id(self, nsid: str, content_id: str, aid: AuthorityID):
        """Standard matching using the computed VIAF search key."""
        return aid.matches_viaf_search_key(nsid)

    def compute_viaf_search_key(self, aid: AuthorityID) -> None:
        # 000011784 -> LNC10-000011784
        #
        aid.viaf_search_key = "LNC10-" + aid.wikidata_external_id
        # todo; nakijken ; deze kan ook een LNB: link hebben


class NLA_AuthoritySource(AuthoritySource):
    def matches_viaf_external_id(
        self, nsid: str, content_id: str, aid: AuthorityID
    ) -> bool:
        """Standard matching using the computed VIAF search key."""
        return aid.matches_viaf_search_key(nsid)

    def compute_viaf_search_key(self, aid: AuthorityID) -> None:
        """Formats ID as a 12-digit zero-padded number for NLA."""
        res = "000000000000" + aid.wikidata_external_id
        aid.viaf_search_key = res[-12:]  # Extract last 12 digits


class NLR_AuthoritySource(AuthoritySource):
    def matches_viaf_external_id(self, nsid: str, content_id: str, aid: AuthorityID):
        nsid = nsid.replace("RU\\NLR\\AUTH\\", "")
        return nsid == aid.wikidata_external_id

    def compute_viaf_search_key(self, aid: AuthorityID) -> None:
        aid.viaf_search_key = "RU NLR AUTH " + aid.wikidata_external_id


class NUKAT_AuthoritySource(AuthoritySource):
    def fetch_nukat_code(self, aid: AuthorityID):
        # test: http://katalog.nukat.edu.pl/lib/authority?lccn=n%20%2001041400
        #       http://katalog.nukat.edu.pl/lib/authority?lccn=n 01041400
        if aid.wikidata_external_id.startswith("n"):
            ncode = "n " + aid.wikidata_external_id[1:]
        else:
            return None
        url = f"http://katalog.nukat.edu.pl/lib/authority?lccn={ncode}"
        response = requests.get(url, timeout=READ_TIMEOUT)
        regex = r'\<tr\>\s*<td width="10">001<\/td>.*?<td class="tagdata">(.*?)<\/td>'
        matches = re.search(regex, response.text, re.MULTILINE | re.DOTALL)
        return matches.group(1) if matches else None

    def matches_viaf_external_id(self, nsid: str, content_id: str, aid: AuthorityID):
        return (nsid.replace(" ", "") == aid.wikidata_external_id.replace(" ", "")) or (
            content_id.replace(" ", "") == aid.wikidata_external_id.replace(" ", "")
        )

    def compute_viaf_search_key(self, aid: AuthorityID) -> None:
        # aid.nukat_specific_code = self.fetch_nukat_code(aid)
        aid.nukat_specific_code = aid.wikidata_external_id
        if aid.nukat_specific_code is None:
            aid.viaf_search_key = None
        elif aid.wikidata_external_id.startswith("n"):
            aid.viaf_search_key = "n " + aid.wikidata_external_id[1:]


class PERSEUS_AuthoritySource(AuthoritySource):
    def matches_viaf_external_id(self, nsid: str, content_id: str, aid: AuthorityID):
        """Standard matching using the computed VIAF search key."""
        return aid.matches_viaf_search_key(nsid)

    def compute_viaf_search_key(self, aid: AuthorityID) -> None:
        # urn:cite:perseus:author.384.1
        aid.viaf_search_key = "urn:cite:perseus:author." + aid.wikidata_external_id


class RERO_AuthoritySource(AuthoritySource):
    def matches_viaf_external_id(self, nsid: str, content_id: str, aid: AuthorityID):
        """Standard matching using the computed VIAF search key."""
        return aid.matches_viaf_search_key(nsid)

    def compute_viaf_search_key(self, aid: AuthorityID) -> None:
        aid.viaf_search_key = aid.wikidata_external_id.replace("02-", "").replace(
            "02_", ""
        )


class SELIBR_AuthoritySource(AuthoritySource):
    def fetch_controlnumber(self, aid: AuthorityID):
        url = f"https://libris.kb.se/{aid.wikidata_external_id}/data.json"
        response = requests.get(url, timeout=READ_TIMEOUT)
        if response.status_code != 200:
            # typical 404 NOT FOUND or 410 GONE
            raise RuntimeError(f"Status code: {response.status_code}")
        payload = response.json()
        return payload["controlNumber"]

    # def matches_viaf_external_id(self, nsid: str, content_id: str, aid: AuthorityID):
    #     # None, selibr_determine_search_code
    #     return aid.matches_viaf_search_key(viaf_external_id)

    def compute_viaf_search_key(self, aid: AuthorityID) -> None:
        aid.viaf_search_key = self.fetch_controlnumber(aid)


class SRP_AuthoritySource(AuthoritySource):
    def matches_viaf_external_id(self, nsid: str, content_id: str, aid: AuthorityID):
        """Standard matching using the computed VIAF search key."""
        return aid.matches_viaf_search_key(nsid)

    def compute_viaf_search_key(self, aid: AuthorityID) -> None:
        aid.viaf_search_key = "person_" + aid.wikidata_external_id


class AuthoritySources:
    def __init__(self):

        self.dict = {}

        sources = [
            (AuthoritySource, PID_BNMM_AUTHORITY_ID, "ARBABN", "BNMM authority ID"),
            (AuthoritySource, PID_BANQ_AUTHORITY_ID, "B2Q", "BAnQ authority ID"),
            (
                AuthoritySource,
                PID_VATICAN_LIBRARY_VCBA_ID,
                "BAV",
                "Vatican Library VcBA ID",
            ),
            (AuthoritySource, PID_NORAF_ID, "BIBSYS", "NORAF ID"),
            (
                AuthoritySource,
                PID_NATIONAL_LIBRARY_OF_BRAZIL_ID,
                "BLBNB",
                "National Library of Brazil ID",
            ),
            (AuthoritySource, PID_CANTIC_ID, "BNC", "CANTIC ID"),
            (
                BNCHL_AuthoritySource,
                PID_NATIONAL_LIBRARY_OF_CHILE_ID,
                "BNCHL",
                "National Library of Chile ID",
            ),
            (
                AuthoritySource,
                PID_BIBLIOTECA_NACIONAL_DE_ESPANA_ID,
                "BNE",
                "Biblioteca Nacional de España ID",
            ),
            (
                BNF_AuthoritySource,
                PID_BIBLIOTHEQUE_NATIONALE_DE_FRANCE_ID,
                "BNF",
                "Bibliothèque nationale de France ID",
            ),
            (
                AuthoritySource,
                PID_NATIONAL_LIBRARY_OF_LUXEMBOURG_ID,
                "BNL",
                "National Library of Luxembourg ID",
            ),
            (
                AuthoritySource,
                PID_CANADIANA_NAME_AUTHORITY_ID,
                "CAOONL",
                "Canadiana Name Authority ID",
            ),
            (AuthoritySource, PID_CYT_CCS, "CYT", "CYT/CCS"),  # 2 varianten
            (AuthoritySource, PID_DBC_AUTHOR_ID, "DBC", "DBC author ID"),
            (RISM_AuthoritySource, PID_RISM_ID, "DE633", "RISM ID"),
            # uitgezet
            # (AuthoritySource, PID_RISM_ID, "DE663", "RISM ID"),
            (GND_AuthoritySource, PID_GND_ID, "DNB", "GND ID"),
            (AuthoritySource, PID_EGAXA_ID, "EGAXA", "EGAXA ID"),
            (AuthoritySource, PID_ELNET_ID, "ERRR", "ELNET ID"),
            (AuthoritySource, PID_FAST_ID, "FAST", "FAST ID"),
            (
                AuthoritySource,
                PID_NATIONAL_LIBRARY_OF_GREECE_ID,
                "GRATEVE",
                "National Library of Greece ID",
            ),
            (SBN_AuthoritySource, PID_SBN_AUTHOR_ID, "ICCU", "SBN author ID"),
            # werkt nu; veel fouten:
            (AuthoritySource, PID_ISNI, "ISNI", "ISNI"),
            # weinig fouten:
            (
                AuthoritySource,
                PID_NATIONAL_LIBRARY_OF_ISRAEL_J9U_ID,
                "J9U",
                "National Library of Israel J9U ID",
            ),
            (
                AuthoritySource,
                PID_UNION_LIST_OF_ARTIST_NAMES_ID,
                "JPG",
                "Union List of Artist Names ID",
            ),
            (
                AuthoritySource,
                PID_NATIONAL_LIBRARY_OF_KOREA_ID,
                "KRNLK",
                "National Library of Korea ID",
            ),
            (
                AuthoritySource,
                PID_LIBRARY_OF_CONGRESS_AUTHORITY_ID,
                "LC",
                "Library of Congress authority ID",
            ),  # tested
            (
                AuthoritySource,
                PID_NATIONAL_LIBRARY_OF_LITHUANIA_ID,
                "LIH",
                "National Library of Lithuania ID",
            ),
            (
                LNB_AuthoritySource,
                PID_NATIONAL_LIBRARY_OF_LATVIA_ID,
                "LNB",
                "National Library of Latvia ID",
            ),
            (
                AuthoritySource,
                PID_LEBANESE_NATIONAL_LIBRARY_ID,
                "LNL",
                "Lebanese National Library ID",
            ),
            (AuthoritySource, PID_BNRM_ID, "MRBNR", "BNRM ID"),
            (
                AuthoritySource,
                PID_NATIONAL_LIBRARY_OF_IRELAND_ID,
                "N6I",
                "National Library of Ireland ID",
            ),
            (AuthoritySource, PID_NDL_AUTHORITY_ID, "NDL", "NDL Authority ID"),
            (
                AuthoritySource,
                PID_CINII_BOOKS_AUTHOR_ID,
                "NII",
                "CiNii Books author ID",
            ),
            (AuthoritySource, PID_NL_CR_AUT_ID, "NKC", "NL CR AUT ID"),
            (
                NLA_AuthoritySource,
                PID_LIBRARIES_AUSTRALIA_ID,
                "NLA",
                "Libraries Australia ID",
            ),
            (
                AuthoritySource,
                PID_NATIONAL_LIBRARY_BOARD_SINGAPORE_ID,
                "NLB",
                "National Library Board Singapore ID",
            ),
            (
                NLR_AuthoritySource,
                PID_NATIONAL_LIBRARY_OF_RUSSIA_ID,
                "NLR",
                "National Library of Russia ID",
            ),
            (AuthoritySource, PID_NSK_ID, "NSK", "NSK ID"),  # tested
            (
                AuthoritySource,
                PID_NSZL_NAME_AUTHORITY_ID,
                "NSZL",
                "NSZL name authority ID",
            ),
            (AuthoritySource, PID_NSZL_VIAF_ID, "NSZL", "NSZL (VIAF), ID"),
            (
                AuthoritySource,
                PID_NATIONALE_THESAURUS_VOOR_AUTEURSNAMEN_ID,
                "NTA",
                "Nationale Thesaurus voor Auteursnamen ID",
            ),
            (NUKAT_AuthoritySource, PID_NUKAT_ID, "NUKAT", "NUKAT ID"),
            (AuthoritySource, PID_RILM_ID, "NYNYRILM", "RILM ID"),
            (
                PERSEUS_AuthoritySource,
                PID_PERSEUS_AUTHOR_ID,
                "PERSEUS",
                "Perseus author ID",
            ),
            (AuthoritySource, PID_PLWABN_ID, "PLWABN", "PLWABN ID"),
            (
                AuthoritySource,
                PID_PORTUGUESE_NATIONAL_LIBRARY_AUTHOR_ID,
                "PTBNP",
                "Portuguese National Library author ID",
            ),
            (RERO_AuthoritySource, PID_RERO_ID_OBSOLETE, "RERO", "RERO ID (obsolete),"),
            (SELIBR_AuthoritySource, PID_LIBRIS_URI, "SELIBR", "Libris-URI"),
            (AuthoritySource, PID_CONOR_SI_ID, "SIMACOB", "CONOR.SI ID"),
            (
                AuthoritySource,
                PID_SLOVAK_NATIONAL_LIBRARY_VIAF_ID,
                "SKMASNL",
                "Slovak National Library (VIAF), ID",
            ),
            (
                SRP_AuthoritySource,
                PID_SYRIAC_BIOGRAPHICAL_DICTIONARY_ID,
                "SRP",
                "Syriac Biographical Dictionary ID",
            ),
            (AuthoritySource, PID_IDREF_ID, "SUDOC", "IdRef ID"),
            # uitgezet:
            # (AuthoritySource, PID_GND_ID, "SZ", "GND ID"),
            (
                AuthoritySource,
                PID_UAE_UNIVERSITY_LIBRARIES_ID,
                "UAE",
                "UAE University Libraries ID",
            ),
            (
                AuthoritySource,
                PID_NATIONAL_LIBRARY_OF_ICELAND_ID,
                "UIY",
                "National Library of Iceland ID",
            ),
            (
                AuthoritySource,
                PID_FLEMISH_PUBLIC_LIBRARIES_ID,
                "VLACC",
                "Flemish Public Libraries ID",
            ),
            # uitgezet:
            # self.add(AuthoritySource, PID_NORAF_ID, "W2Z", "NORAF ID"))
        ]
        for source_class, pid, viaf_code, description in sources:
            self.add(source_class(pid, viaf_code, description))

    def bnf_viaf_qry(self, wikidata_id):
        # Identifiant de la notice  : ark:/12148/cb11916320z
        # Notice n° : FRBNF11916320
        # https://viaf.org/viaf/sourceID/BNF|11916320/justlinks.json  -> FRBNF119163208
        #
        # Identifiant de la notice  : ark:/12148/cb120493546
        # Notice n° : FRBNF12049354
        # https://viaf.org/viaf/sourceID/BNF|12049354/justlinks.json  -> http://catalogue.bnf.fr/ark:/12148/cb12049354 ['6' weg]
        #
        # Identifiant de la notice  : ark:/12148/cb170700059
        # Notice n° : FRBNF17070005
        # https://viaf.org/viaf/sourceID/BNF|17070005/justlinks.json  -> not found
        #
        # Identifiant de la notice  : ark:/12148/cb17074051f
        # Notice n° : FRBNF17074051
        # https://viaf.org/viaf/sourceID/BNF|17074051/justlinks.json  -> not found
        #
        # Identifiant de la notice  : ark:/12148/cb16728223r
        # Notice n° : FRBNF16728223
        # https://viaf.org/viaf/sourceID/BNF|16728223/justlinks.json  -> not found
        #
        # Identifiant de la notice  : ark:/12148/cb101761115
        # Notice n° : FRBNF10176111
        # https://viaf.org/viaf/sourceID/BNF|10176111/justlinks.json  -> not found

        return wikidata_id[:-1]

    def add(self, item: AuthoritySource) -> None:
        if item.pid in self.dict:
            raise RuntimeError(f"{item.pid} is already assigned")
        self.dict[item.pid] = item

    def get(self, pid: str) -> AuthoritySource:
        return self.dict[pid]


def main() -> None:

    authsrcs = AuthoritySources()


if __name__ == "__main__":
    main()
