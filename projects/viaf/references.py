from collections import OrderedDict
import constants as wd
from datetime import datetime


def check_retrieved_year(src):
    if wd.PID_RETRIEVED in src:
        for claim in src[wd.PID_PID_RETRIEVED]:
            dt = claim.getTarget()
            current_year = datetime.now().year
            if dt and (dt.year < 2000 or dt.year > current_year):
                raise RuntimeError(f"Invalid retrieved value {dt}")


def src_has_only(src, pid):
    if pid not in src:
        return False
    for prop in src:
        if prop != pid:
            return False

    return True


def is_single_claim(src, pid: str) -> bool:
    return src_has_only(src, pid) and (len(src[pid]) == 1)


def is_single_retrieved(src):
    return is_single_claim(src, wd.PID_RETRIEVED)


def is_single_stated_in(src):
    return is_single_claim(src, wd.PID_STATED_IN)


def has_retrieved(src):
    return wd.PID_RETRIEVED in src


def has_retrieved_and_stated_in(src):
    return (wd.PID_RETRIEVED in src) and (wd.PID_STATED_IN in src)


def get_claim_count(src):
    return str(len(src))


def is_id(src):
    for prop in src:
        for claim in src[prop]:
            if claim.type in ["external-id", "url"]:
                return True
    return False


def is_id_without_retrieved(src):
    return (wd.PID_RETRIEVED not in src) and is_id(src)


def is_id_with_retrieved(src):
    return (wd.PID_RETRIEVED in src) and is_id(src)


def get_source_token(src):
    if src is None:
        return ""
    elif is_single_claim(src, wd.PID_RETRIEVED):
        return "R"
    elif is_single_claim(src, wd.PID_STATED_IN):
        return "S"
    elif (
        is_single_claim(src, wd.PID_PUBLISHER)
        or is_single_claim(src, wd.PID_SUBJECT_NAMED_AS)
        or is_single_claim(src, wd.PID_QUOTATION)
        or is_single_claim(src, wd.PID_TITLE)
        or is_single_claim(src, wd.PID_PAGES)
        or is_single_claim(src, wd.PID_PUBLICATION_DATE)
        or is_single_claim(src, wd.PID_LANGUAGE_OF_WORK_OR_NAME)
        or is_single_claim(src, wd.PID_AWARD_RATIONALE)
    ):
        # should not be singular refs
        return "Y"
    elif is_single_claim(src, wd.PID_REFERENCE_URL):
        # should not be singular refs
        return "U"
    elif is_single_claim(src, wd.PID_IMPORTED_FROM_WIKIMEDIA_PROJECT):
        return "I"
    elif is_single_claim(src, wd.PID_INFERRED_FROM):
        return "F"
    elif is_id_without_retrieved(src):
        return "W"
    elif is_id_with_retrieved(src):
        return "A"
    elif has_retrieved_and_stated_in(src):
        return "B"
    elif has_retrieved(src):
        return "C"
    else:
        # unknown, 1 should be change to Y etc.
        return get_claim_count(src)


def get_sources_tokens(sources):
    res = ""
    for src in sources:
        res = res + get_source_token(src)
    return res


def get_newest_date(pid: str, src):
    newest_date = None
    if pid in src:
        for value in src[pid]:
            date = value.getTarget()
            if not date:
                continue
            if not newest_date or (newest_date.normalize() < date.normalize()):
                newest_date = date
    return newest_date


def get_old_new_src(src1, src2):
    d1 = get_newest_date(wd.PID_RETRIEVED, src1)
    d2 = get_newest_date(wd.PID_RETRIEVED, src2)
    if d1 and d2:
        is_src1_oldest = d1.normalize() <= d2.normalize()
    else:
        is_src1_oldest = not d1
    if is_src1_oldest:
        return src1, src2
    else:
        return src2, src1


def set_pid(pid: str, t, new_source, use_only_newest_list):
    oldest_src, newest_src = t
    if pid in newest_src:
        new_source[pid] = newest_src[pid]
    elif pid not in use_only_newest_list and pid in oldest_src:
        new_source[pid] = oldest_src[pid]


def get_merge(
    src1,
    src2,
    use_only_newest_list=[
        wd.PID_SUBJECT_NAMED_AS,
        wd.PID_OBJECT_NAMED_AS,
        wd.PID_TITLE,
    ],
):
    check_retrieved_year(src1)
    check_retrieved_year(src2)

    new_source = OrderedDict()

    t = get_old_new_src(src1, src2)

    set_pid(wd.PID_STATED_IN, t, new_source, [])

    # remove reference urls;
    # skip stated in, retrieved and pid; these are already done above
    props = []
    for prop in src1:
        if prop not in props:
            props.append(prop)
    for prop in src2:
        if prop not in props:
            props.append(prop)
    skip = set([wd.PID_STATED_IN, wd.PID_RETRIEVED, wd.PID_PUBLICATION_DATE])

    props = [x for x in props if x not in skip]

    for prop in props:
        # use the value of the newest, or the oldest (if the newest doesn't have the prop);
        # if prop is title/subject named as, then only newest
        set_pid(
            prop,
            t,
            new_source,
            use_only_newest_list=use_only_newest_list,
        )

    set_pid(wd.PID_PUBLICATION_DATE, t, new_source, [])
    set_pid(wd.PID_RETRIEVED, t, new_source, [])

    return new_source


class References:
    def __init__(self, claim, sources):
        self.claim = claim
        self.sources = sources
        self.did_remove = False
        self.did_merge = False
        self.did_something = False

    def get_tokens(self) -> str:
        return get_sources_tokens(self.sources)

    def try_remove_all_single_retrieved(self):
        # single retrieved with others with retrieved
        t = self.get_tokens()
        if (
            "R" in t
            and "S" not in t
            and "W" not in t
            and ("A" in t or "B" in t)
            and "X" not in t
        ):
            self.did_remove = True
            self.did_something = True
            new_sources = []
            for src in self.sources:
                if is_single_retrieved(src):
                    check_retrieved_year(src)
                    # skip
                    continue
                else:
                    new_sources.append(src)
            self.sources = new_sources

    def remove_sources(self, removable_list):
        self.did_remove = True

        new_sources = []
        for index, src in enumerate(self.sources):
            if index in removable_list:
                check_retrieved_year(src)
            else:
                new_sources.append(src)
        self.sources = new_sources

    def merge(self, index1, index2, keep: bool = False) -> None:
        new_sources = []
        merge_done = False
        for index, src in enumerate(self.sources):
            if index == index1 or index == index2:
                if merge_done:
                    if keep:
                        new_sources.append(src)
                    continue

                new_sources.append(
                    get_merge(
                        self.sources[index1],
                        self.sources[index2],
                        use_only_newest_list=[],
                    )
                )
                self.did_merge = True
                merge_done = True
            else:
                new_sources.append(src)

        self.sources = new_sources

    def handle_patterns(self):

        def find(pattern: str) -> int:
            if len(self.sources) <= 1:
                return -1
            t = "A" + self.get_tokens().replace("B", "A") + "A"
            index = t.find("A" + pattern + "A")
            return index

        def find_multiple(pattern_list) -> int:
            if len(self.sources) <= 1:
                return -1
            for pattern in pattern_list:
                index = find(pattern)
                if index >= 0:
                    return index
            return -1

        def is_single_claim_list(sources, pid_list) -> bool:
            if len(sources) != len(pid_list):
                return False
            for index, src in enumerate(sources):
                if not is_single_claim(src, pid_list[index]):
                    return False

            return True

        def find_single_pids(pid_list) -> int:
            for index, src in enumerate(self.sources):
                x = slice(index, index + len(pid_list))
                if is_single_claim_list(self.sources[x], pid_list):
                    return index
            return -1

        while True:
            index = find_multiple(["RW", "WR", "RS", "SR", "RU", "FR"])
            if index >= 0:
                self.did_something = True
                self.merge(index, index + 1)
                continue

            index = find("RI")
            if index >= 0:
                if self.claim.type not in ["external-id", "url"]:
                    self.did_something = True
                    self.remove_sources([index])
                    continue

            index = find("IR")
            if index >= 0:
                if self.claim.type not in ["external-id", "url"]:
                    self.did_something = True
                    self.remove_sources([index + 1])
                    continue

            index = find("RC")
            if index >= 0:
                self.did_something = True
                self.remove_sources([index])
                continue

            index = find("R")
            if index >= 0:
                self.did_something = True
                self.remove_sources([index])
                continue

            index = find("SWR")
            if index >= 0:
                self.did_something = True
                self.merge(index + 1, index + 2)
                continue

            index = find_multiple(["SYR", "URY", "YUR", "UYR", "WRY"])  # IRW sometimes
            if index >= 0:
                # merge all three
                self.did_something = True
                self.merge(index + 1, index + 2)
                self.merge(index + 0, index + 1)
                continue

            index = find_multiple(["WRS", "URS", "SRW", "WRW"])
            if index >= 0:
                # merge the R part with the first part
                self.did_something = True
                self.merge(index, index + 1)
                continue

            index = find("IWR")
            if index >= 0:
                # merge the W and R part
                self.did_something = True
                self.merge(index + 1, index + 2)
                continue

            index = find("RR")
            if index >= 0:
                self.did_something = True
                self.merge(index, index + 1)
                continue

            index = find("UR")
            if index >= 0:
                self.did_something = True
                self.merge(index, index + 1)
                continue

            index = find_multiple(["URU", "URI"])
            if index >= 0:
                self.did_something = True
                self.merge(index, index + 1)
                continue

            index = find_multiple(["UUR", "WWR", "WUR", "UWR", "SSR"])
            if index >= 0:
                self.did_something = True
                self.merge(index + 1, index + 2, keep=True)
                self.merge(index, index + 2)
                continue

            index = find("IUUR")
            if index >= 0:
                self.did_something = True
                self.merge(index + 2, index + 3, keep=True)
                self.merge(index + 1, index + 3)
                continue

            index = find_multiple(["UUUR", "WWWR"])
            if index >= 0:
                self.did_something = True
                self.merge(index + 2, index + 3, keep=True)
                self.merge(index + 1, index + 3, keep=True)
                self.merge(index, index + 3)
                continue

            index = find("UYRY")
            if index >= 0:
                # reference url - Y - retrieved - Y; merge all together
                self.did_something = True
                self.merge(index + 2, index + 3)
                self.merge(index + 1, index + 2)
                self.merge(index + 0, index + 1)
                continue

            index = find("URUR")
            if index >= 0:
                self.did_something = True
                self.merge(index + 2, index + 3)
                self.merge(index, index + 1)
                continue

            index = find_multiple(["USR", "WSR"])
            if index >= 0:
                # ref url + stated in + retrieved; could probably be merged to 1 reference
                self.did_something = True
                self.merge(index + 1, index + 2)
                continue

            index = find("SRU")
            if index >= 0:
                # stated in + retrieved + ref url; could probably be merged to 1 reference
                self.did_something = True
                self.merge(index, index + 1)
                continue

            index = find("SUR")
            if index >= 0:
                # stated in + ref url + retrieved ; could probably be merged to 1 reference
                self.did_something = True
                self.merge(index + 1, index + 2)
                continue

            index = find_single_pids(
                [wd.PID_REFERENCE_URL, wd.PID_LANGUAGE_OF_WORK_OR_NAME]
            )
            if index >= 0:
                self.did_something = True
                self.merge(index, index + 1)
                continue

            index = find_single_pids([wd.PID_REFERENCE_URL, wd.PID_SUBJECT_NAMED_AS])
            if index >= 0:
                self.did_something = True
                self.merge(index, index + 1)
                continue

            break

    def remove_single_retrieved(self):
        while len(self.sources) > 1:

            self.did_something = False

            self.try_remove_all_single_retrieved()
            if "R" not in self.get_tokens():
                return
            # self.remove_isolated_single_retrieved()
            # if "R" not in self.get_tokens():
            #     return

            self.handle_patterns()
            if "R" not in self.get_tokens():
                return

            if not self.did_something:
                break
