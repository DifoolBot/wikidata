from __future__ import annotations

from typing import cast

import pywikibot as pwb
from pywikibot.site import APISite, DataSite


def get_site() -> APISite:
    """Return the Wikidata Site, building it on the first call.

    ``pywikibot.Site()`` is a cache-backed factory: the first call constructs
    the site -- which performs network I/O, a cookie login whose ``userinfo``
    request reaches the Wikidata API -- and every later call returns that same
    cached instance cheaply. Fetching the site through this function instead of
    a module-level global means that merely importing this module (and, via
    ``shared_lib.change_wikidata``, almost every project) does no network I/O.

    That matters because a transient server-side ``maxlag`` spike used to raise
    ``MaxlagTimeoutError`` during import and kill an unattended job before
    ``main()`` ran; offline tooling and tests also needed live credentials just
    to import a module.
    """
    # pywikibot's Site() factory is typed to return the base ``BaseSite``, but
    # for ('wikidata', 'wikidata') it is concretely an APISite (a DataSite,
    # in fact); assert that so callers get precise typing.
    return cast(APISite, pwb.Site("wikidata", "wikidata"))


def get_repo() -> DataSite:
    """Return the Wikidata data repository. For Wikidata this is the Site
    itself; kept as its own accessor so callers read as intent (a repo for
    building Claims/ItemPages) rather than relying on that identity."""
    # data_repository() is typed ``... | None``; for Wikidata it is always the
    # DataSite, so narrow it for callers.
    return cast(DataSite, get_site().data_repository())


def ensure_login() -> None:
    """Log in and pre-fetch the CSRF token.

    pywikibot logs in lazily on the first edit (and fetches the CSRF token
    itself), so this is optional; call it from an entry point to fail fast on
    missing or invalid credentials instead of partway through a run.

    This is also the first thing that materialises the Site, so the network I/O
    that used to happen at import now happens here, inside the run -- where a
    maxlag/login failure is caught and handled rather than crashing the import.

    Deliberately NOT done at import time: this module is pulled in (via
    shared_lib.change_wikidata) by almost every project, so logging in on
    import would make merely importing any of them perform network I/O and
    require credentials -- breaking offline use, tests and tooling.
    """
    site = get_site()
    site.login()
    site.get_tokens(["csrf"])
