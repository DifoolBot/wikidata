import pywikibot as pwb

SITE = pwb.Site("wikidata", "wikidata")
REPO = SITE.data_repository()


def ensure_login() -> None:
    """Log in and pre-fetch the CSRF token.

    pywikibot logs in lazily on the first edit (and fetches the CSRF token
    itself), so this is optional; call it from an entry point to fail fast on
    missing or invalid credentials instead of partway through a run.

    Deliberately NOT done at import time: this module is pulled in (via
    shared_lib.change_wikidata) by almost every project, so logging in on
    import would make merely importing any of them perform network I/O and
    require credentials -- breaking offline use, tests and tooling.
    """
    SITE.login()
    SITE.get_tokens("csrf")
