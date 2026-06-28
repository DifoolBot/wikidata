import viaf.authority_sources
import viaf.viaf_bot
from viaf.firebird_viaf_reporting import FirebirdViafReporting

import shared_lib.constants as wd


def main() -> None:

    authsrcs = viaf.authority_sources.AuthoritySources()
    # nothing found:
    #              : PID_FAST_ID
    #              : PID_CONOR_SI_ID
    #              : PID_PERSEUS_AUTHOR_ID
    # lots of not found: PID_BIBLIOTECA_NACIONAL_DE_ESPANA_ID; PID_ISNI
    # niets gevonden: PID_EGAXA_ID; PID_BNRM_ID
    # done; PID_IDREF_ID; PID_GND_ID; PID_SBN_AUTHOR_ID; PID_NL_CR_AUT_ID; PID_VATICAN_LIBRARY_VCBA_ID; PID_NATIONAL_LIBRARY_OF_KOREA_ID
    #       PID_BNMM_AUTHORITY_ID; PID_NSK_ID; PID_LIBRARIES_AUSTRALIA_ID; PID_NATIONAL_LIBRARY_OF_BRAZIL_ID
    #       PID_CANADIANA_NAME_AUTHORITY_ID; PID_RISM_ID; PID_NORAF_ID; PID_NATIONAL_LIBRARY_OF_IRELAND_ID
    #       PID_LEBANESE_NATIONAL_LIBRARY_ID; PID_NATIONAL_LIBRARY_OF_ICELAND_ID
    #       PID_NATIONALE_THESAURUS_VOOR_AUTEURSNAMEN_ID; PID_NDL_AUTHORITY_ID; PID_RERO_ID_OBSOLETE
    #       PID_PORTUGUESE_NATIONAL_LIBRARY_AUTHOR_ID; PID_PLWABN_ID; PID_CANTIC_ID; PID_BANQ_AUTHORITY_ID; PID_RILM_ID
    #       PID_ELNET_ID; PID_DBC_AUTHOR_ID; PID_CINII_BOOKS_AUTHOR_ID; PID_NATIONAL_LIBRARY_OF_RUSSIA_ID
    #       PID_CYT_CCS; PID_NATIONAL_LIBRARY_OF_LATVIA_ID; PID_LIBRIS_URI; PID_BIBLIOTHEQUE_NATIONALE_DE_FRANCE_ID
    #       PID_SYRIAC_BIOGRAPHICAL_DICTIONARY_ID; PID_NUKAT_ID; PID_NATIONAL_LIBRARY_OF_CHILE_ID

    bot = viaf.viaf_bot.ViafBot(
        authsrcs.get(wd.PID_LIBRARY_OF_CONGRESS_AUTHORITY_ID),
        report=FirebirdViafReporting(),
    )
    bot.test = False
    bot.run()


if __name__ == "__main__":
    main()
