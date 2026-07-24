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
