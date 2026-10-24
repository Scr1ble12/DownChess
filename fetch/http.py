# fetch/http.py
"""One polite HTTP session for both sites.

Etiquette both sites ask for: a descriptive User-Agent with contact info,
one request at a time, and backing off on HTTP 429. Lichess asks you to wait a
full minute after a 429, so that is the default wait.
"""

from __future__ import annotations

import os
import time

import requests

DEFAULT_CONTACT = "https://github.com/Scr1ble12/DownChess"
RETRY_WAIT_S = 60
MAX_RETRIES = 5


def user_agent() -> str:
    # Set DOWNCHESS_CONTACT to an email if you want the sites to be able to reach you.
    contact = os.environ.get("DOWNCHESS_CONTACT", DEFAULT_CONTACT)
    return f"DownChess/0.1 (personal game analysis tool; {contact})"


def make_session() -> requests.Session:
    session = requests.Session()
    session.headers["User-Agent"] = user_agent()
    return session


class NotFound(Exception):
    pass


def get(session, url: str, *, sleep=time.sleep, **kwargs):
    """GET with retry on 429 and 5xx. Raises NotFound on 404."""
    for attempt in range(MAX_RETRIES):
        resp = session.get(url, timeout=60, **kwargs)
        if resp.status_code == 404:
            raise NotFound(url)
        if resp.status_code == 429 or resp.status_code >= 500:
            wait = int(resp.headers.get("Retry-After", RETRY_WAIT_S))
            print(f"  {resp.status_code} from server, waiting {wait}s (attempt {attempt + 1})")
            sleep(wait)
            continue
        resp.raise_for_status()
        return resp
    raise RuntimeError(f"gave up on {url} after {MAX_RETRIES} attempts")
