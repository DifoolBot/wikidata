class Reporting:
    """
    A class to handle reporting of done items, errors, and unknown URLs.
    """

    def has_done(self, qid: str) -> bool:
        """
        Checks if the given QID has been marked as done.

        Args:
            qid (str): The QID to check.

        Returns:
            bool: True if the QID has been marked as done, False otherwise.
        """
        pass

    def has_error(self, qid: str) -> bool:
        """
        Checks if the given QID has been marked with an error.

        Args:
            qid (str): The QID to check.

        Returns:
            bool: True if the QID has been marked with an error, False otherwise.
        """
        pass

    def add_done(self, qid: str) -> None:
        """
        Marks the given QID as done.

        Args:
            qid (str): The QID to mark as done.
        """
        pass

    def add_error(self, qid: str, msg: str) -> None:
        """
        Logs an error message for the given QID.

        Args:
            qid (str): The QID to mark with an error.
            msg (str): The error message to log.
        """
        pass

    def clear_unknown_urls(self, qid: str) -> None:
        """
        Clears unknown URLs for the given QID.

        Args:
            qid (str): The QID for which to clear unknown URLs.
        """
        pass

    def add_unknown_url(self, qid: str, url: str) -> None:
        """
        Logs an unknown URL for the given QID.

        Args:
            qid (str): The QID to log the unknown URL for.
            url (str): The unknown URL to log.
        """
        pass

    def add_query_index_pid(self, pid: str, index: int) -> None:
        """
        Logs a query index for the given PID.

        Args:
            pid (str): The PID to log the query for.
            index (int): The index
        """
        pass
