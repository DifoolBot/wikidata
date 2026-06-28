import pywikibot as pwb
import requests
from pywikibot.data import sparql

from shared_lib.rate_limiter import rate_limit

WDQS_ENDPOINT = "https://query.wikidata.org/sparql"
WDQS_SLEEP_AFTER_TIMEOUT = 30  # sec
WDQS_SLEEP_AFTER_ERROR = 2 * 60  # sec

WD = "http://www.wikidata.org/entity/"

READ_TIMEOUT = 60  # sec


def is_slice_finished(response) -> bool:
    return (
        response.elapsed.total_seconds() < 3
        and "RuntimeException: offset is out of range" in response.text
    )


def can_retry(response) -> bool:
    return (
        response.elapsed.total_seconds() > 55
        and "java.util.concurrent.TimeoutException" in response.text
    )


# @rate_limit(15)
# def query_wdqs(query: str, retry_counter: int = 3):
#     try:
#         response = requests.get(
#             WDQS_ENDPOINT,
#             params={"query": query, "format": "json"},
#             timeout=READ_TIMEOUT,
#         )
#     except Exception as ex:
#         template = "An exception of type {0} occurred. Arguments:\n{1!r}"
#         message = template.format(type(ex).__name__, ex.args)
#         print("*** Uncaught Error ***")
#         print(message)

#         raise RuntimeError(
#             f"Request GET error; http status {response.status_code}; query time {response.elapsed.total_seconds():.2f} sec"
#         ) from ex

#     if response.status_code != 200:
#         raise RuntimeError(
#             f"http status {response.status_code}; {response.text} query time {response.elapsed.total_seconds():.2f} sec"
#         )

#     try:
#         payload = response.json()
#     except json.JSONDecodeError as e:
#         # nothing more left to slice on WDQS
#         if is_slice_finished(response):
#             return None

#         # likely timed out, try again up to three times
#         retry_counter -= 1
#         if retry_counter > 0 and can_retry(response):
#             time.sleep(WDQS_SLEEP_AFTER_TIMEOUT)
#             return query_wdqs(query, retry_counter)

#         raise RuntimeError(
#             f"Cannot parse WDQS response as JSON; http status {response.status_code}; query time {response.elapsed.total_seconds():.2f} sec"
#         ) from e


#     return payload["results"]["bindings"]
def query_wdqs(query: str, retry_counter: int = 3):
    query_object = sparql.SparqlQuery(max_retries=retry_counter)
    try:
        payload = query_object.query(query=query)
        if not payload:
            return None
        return payload["results"]["bindings"]
    except pwb.exceptions.TimeoutError:
        # if query_object.last_response and query_object.last_response.status_code == 500 and is_slice_finished(query_object.last_response):
        return None
        # else:
        #     raise
    except Exception as ex:
        template = "An exception of type {0} occurred. Arguments:\n{1!r}"
        message = template.format(type(ex).__name__, ex.args)
        print("*** Uncaught Error ***")
        print(message)


def query_wdqs_simple(query: str):
    response = requests.get(
        WDQS_ENDPOINT, params={"query": query, "format": "json"}, timeout=READ_TIMEOUT
    )
    payload = response.json()
    return payload["results"]["bindings"]


def query_wdqs_report(query):
    try:
        return query_wdqs_simple(query)
    except Exception as ex:
        return None
