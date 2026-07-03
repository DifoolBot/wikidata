from collections import OrderedDict
from datetime import datetime, timezone

import pywikibot as pwb

import shared_lib.change_wikidata as cwd
import shared_lib.constants as wd
from shared_lib.wikidata_site import REPO

QID_INFERRED_FROM_VIAF_ID_CONTAINING_AN_ID_ALREADY_PRESENT_IN_THE_ITEM = "Q115111315"


class ViafInferredFromReference(cwd.Reference):
    def __init__(self, pid: str, external_id: str):
        self.pid = pid
        self.external_id = external_id
        self.heuristic_qid = (
            QID_INFERRED_FROM_VIAF_ID_CONTAINING_AN_ID_ALREADY_PRESENT_IN_THE_ITEM
        )

    def is_equal_reference(self, src: dict) -> bool:
        return False

    def create_source(self):
        source = OrderedDict()

        stated_in_claim = pwb.Claim(REPO, wd.PID_STATED_IN, is_reference=True)
        stated_in_claim.setTarget(
            pwb.ItemPage(REPO, wd.QID_VIRTUAL_INTERNATIONAL_AUTHORITY_FILE)
        )
        source[wd.PID_STATED_IN] = [stated_in_claim]

        pid_claim = pwb.Claim(REPO, self.pid, is_reference=True)
        pid_claim.setTarget(self.external_id)
        source[self.pid] = [pid_claim]

        today = datetime.now(timezone.utc)
        retrieved_date = pwb.WbTime(
            year=int(today.strftime("%Y")),
            month=int(today.strftime("%m")),
            day=int(today.strftime("%d")),
        )

        retr_claim = pwb.Claim(REPO, wd.PID_RETRIEVED, is_reference=True)
        retr_claim.setTarget(retrieved_date)
        source[wd.PID_RETRIEVED] = [retr_claim]

        heur_claim = pwb.Claim(REPO, wd.PID_BASED_ON_HEURISTIC, is_reference=True)
        heur_claim.setTarget(pwb.ItemPage(REPO, self.heuristic_qid))
        #        QID_INFERRED_FROM_VIAF_ID_CONTAINING_AN_ID_ALREADY_PRESENT_IN_THE_ITEM,
        source[wd.PID_BASED_ON_HEURISTIC] = [heur_claim]

        return source

    def is_strong_reference(self) -> bool:
        return True
