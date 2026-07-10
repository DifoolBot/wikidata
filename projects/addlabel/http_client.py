"""Shared HTTP fetch helper for the authority-source pages.

Every source (LoC, BnF, IdRef, GND) used to repeat the same
ConnectionError/uncaught-exception boilerplate; this factors it into one
function. On connection trouble it sleeps (the sources tend to be rate-limited
or briefly down) and raises RuntimeError so the bot records the item as an
error and moves on.
"""

import time

import requests

READ_TIMEOUT = 60  # sec


def http_get(
    source_name: str,
    url: str,
    params: dict | None = None,
    sleep_after_error: int = 120,
    timeout: int = READ_TIMEOUT,
) -> requests.Response:
    try:
        return requests.get(url, params=params, timeout=timeout)
    except requests.exceptions.ConnectionError as e:
        print("*** ConnectionError ***")
        print(f"Error: {e}")
        time.sleep(sleep_after_error)
        raise RuntimeError(f"{source_name} Connection error")
    except Exception as ex:
        message = f"An exception of type {type(ex).__name__} occurred. Arguments:\n{ex.args!r}"
        print("*** Uncaught Error ***")
        print(message)
        time.sleep(sleep_after_error)
        raise RuntimeError(f"{source_name} Connection error: {message}")
