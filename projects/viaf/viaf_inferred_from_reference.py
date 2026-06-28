import shared_lib.change_wikidata as cwd

QID_INFERRED_FROM_VIAF_ID_CONTAINING_AN_ID_ALREADY_PRESENT_IN_THE_ITEM = "Q115111315"


class ViafInferredFromReference(cwd.Reference):
    def __init__(self, pid: str, id: str):
        self.pid = pid
        self.external_id = id
        self.heuristic_qid = (
            QID_INFERRED_FROM_VIAF_ID_CONTAINING_AN_ID_ALREADY_PRESENT_IN_THE_ITEM
        )

    def is_equal_reference(self, src: dict) -> bool:
        if self.pid not in src:
            return False
        if len(src[self.pid]) != 1:
            raise RuntimeError("Multiple external ids")
        actual = src[self.pid][0].getTarget()
        return actual == self.external_id

    def create_source(self):
        # TODO
        pass

    def is_strong_reference(self) -> bool:
        return True
