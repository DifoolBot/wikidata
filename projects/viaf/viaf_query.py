import requests
import time


class VIAFResult:
    def __init__(self, status: str, redirect_to: str = None, data=None):
        self.status = status
        self.redirect_to = redirect_to
        self.viaf_id = None
        self.source_mapping = {}

        if data:
            self.extract_data(data)

    def __str__(self):
        return (
            f"VIAFResult(status='{self.status}', redirect_to={self.redirect_to}, "
            f"viaf_id={self.viaf_id}, source_mapping={self.source_mapping})"
        )

    def extract_data(self, data):
        """Extracts useful information from VIAF API response."""
        cluster = data.get("ns1:VIAFCluster", {})
        sources = cluster.get("ns1:sources", {})
        source_entries = sources.get("ns1:source", [])

        self.viaf_id = str(cluster.get("ns1:viafID", ""))

        if isinstance(source_entries, dict):  # Normalize to a list for consistency
            source_entries = [source_entries]

        for entry in source_entries:
            key, nsid = entry["content"].split("|")
            self.source_mapping.setdefault(key, []).append(str(entry["nsid"]))

        # print(json.dumps(self.source_mapping, indent=4))


class VIAFQuery:
    BASE_URL = "https://viaf.org/viaf/"
    HEADERS = {"Accept": "application/json", "Origin": "https://www.wikidata.org/"}

    def query_viaf(self, url) -> VIAFResult:
        response = requests.get(url, headers=self.HEADERS)

        if response.status_code == 429:
            retry_after = int(response.headers.get("Ratelimit-Reset", 60))
            print(f"Rate limit exceeded! Waiting {retry_after} seconds...")
            time.sleep(retry_after)
            return self.query_viaf(url)  # Retry after delay

        if response.status_code == 404:
            return VIAFResult("not_found")

        data = response.json()
        if not data:
            # seen with query_viaf_sourceid + LC
            return VIAFResult("empty")

        abandoned = data.get("ns0:abandoned_viaf_record", {})

        if abandoned:
            redirect = abandoned.get("ns0:redirect", {})
            return (
                VIAFResult("redirect", redirect_to=redirect.get("ns0:directto", {}))
                if redirect
                else VIAFResult("abandoned")
            )

        return VIAFResult("found", data=data)

    def query_viaf_sourceid(self, code: str, local_auth_id: str) -> VIAFResult:
        url = f"{self.BASE_URL}sourceID/{code}%7C{local_auth_id}"
        return self.query_viaf(url)

    def query_viaf_lccn(self, lccn: str) -> VIAFResult:
        url = f"{self.BASE_URL}lccn/{lccn}"
        return self.query_viaf(url)

    def query_viaf_id(self, viaf_id: str) -> VIAFResult:
        url = f"{self.BASE_URL}{viaf_id}"
        return self.query_viaf(url)



def test_gnd() -> None:
    # found
    # Q108320349 1089388047
    qry = VIAFQuery()
    res = qry.query_viaf_sourceid("GND", "103459037")
    print(res)


def test_bnf() -> None:
    # not found
    # Q104680968 103459037
    qry = VIAFQuery()
    res = qry.query_viaf_sourceid("BNF", "103459037")
    print(res)


def test_loc() -> None:
    # 	n86084265; 	nr99002962; no2024135806
    qry = VIAFQuery()
    # res = qry.query_viaf_sourceid("LC", 'no2024135806') # empty
    # res = qry.query_viaf_sourceid("LC", 'no%202024135806') # empty
    # res = qry.query_viaf_sourceid("LC", 'n86084265') # empty
    # res = qry.query_viaf_sourceid("JPG", '500334113') # found
    # res = qry.query_viaf_lccn('n79022935') # Vincent van Gogh
    # https://viaf.org/viaf/LC%257Cn%20%2079022935
    res = qry.query_viaf_sourceid("LC", "n  79022935")

    print(res)


def test_abandoned() -> None:
    qry = VIAFQuery()
    res = qry.query_viaf_id("48754610")
    print(res)


def test_redirect() -> None:
    qry = VIAFQuery()
    res = qry.query_viaf_id("9611149544633400490005")
    print(res)


def test_found() -> None:
    qry = VIAFQuery()
    res = qry.query_viaf_id("120062731")
    print(res)


def main() -> None:
    test_loc()


if __name__ == "__main__":
    main()
