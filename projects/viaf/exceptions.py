class QleverQueryError(Exception):
    """A qlever fetch did not complete: a server error (e.g. 502 Bad Gateway), a
    rejected query, or an unparsable reply.

    Raised rather than returning an empty list, because a caller cannot
    otherwise tell a fetch that *failed* from a source that legitimately has no
    rows left. Treating the former as the latter is not a harmless miss: it
    marks the source done, advances to the next one, and -- once every source
    has been "finished" this way during a qlever outage -- drops the bot into
    its post-pass cooldown, all without doing any work. See
    ViafBot.iterate_qlever / _execute_qlever_query.
    """


class SkipRecord(Exception):
    """Skip the current authority record, with a reason recorded in the report.

    Raised for the expected, handled outcomes of processing one record: VIAF
    says not_found, the item already has a VIAF id or is a redirect, the cluster
    maps to duplicates or to several local authority ids, the search key cannot
    be built, and so on. ``process_record`` catches it, stores the reason via
    ``add_error``, logs it at info level and moves on.

    This is deliberately distinct from a bare ``RuntimeError`` (or any other
    unexpected exception): those signal a real problem and must surface on
    stderr, not be quietly filed as an ordinary skip.
    """
