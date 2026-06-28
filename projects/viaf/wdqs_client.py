import pywikibot as pwb
from pywikibot.data import sparql


def query_wdqs(query: str, retry_counter: int = 3):
    query_object = sparql.SparqlQuery(max_retries=retry_counter)
    try:
        payload = query_object.query(query=query)
        if not payload:
            return None
        return payload["results"]["bindings"]
    except pwb.exceptions.TimeoutError:
        return None
    except Exception as ex:
        template = "An exception of type {0} occurred. Arguments:\n{1!r}"
        message = template.format(type(ex).__name__, ex.args)
        print("*** Uncaught Error ***")
        print(message)
