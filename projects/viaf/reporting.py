class Reporting:
    def has_done(self, qid: str) -> bool:
        pass

    def has_error(self, qid: str) -> bool:
        pass

    def add_done(self, qid: str) -> None:
        pass

    def add_error(self, qid: str, msg: str) -> None:
        pass

    def clear_unknown_urls(self, qid: str) -> None:
        pass

    def add_unknown_url(self, qid: str, url: str) -> None:
        pass

    def add_query_pid(self, pid: str) -> None:
        pass