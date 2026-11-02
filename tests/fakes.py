# tests/fakes.py
"""A stand-in for requests.Session that serves fixture files, so tests never hit the network."""

from __future__ import annotations

import json
from pathlib import Path

FIXTURES = Path(__file__).with_name("fixtures")


class FakeResponse:
    def __init__(self, status_code=200, body=b"", headers=None):
        self.status_code = status_code
        self._body = body if isinstance(body, bytes) else body.encode()
        self.headers = headers or {}

    @property
    def text(self):
        return self._body.decode()

    def json(self):
        return json.loads(self._body)

    def iter_lines(self):
        return iter(self._body.splitlines())

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeSession:
    """Maps URL prefixes to responses and records every request."""

    def __init__(self, routes: dict[str, list[FakeResponse] | FakeResponse]):
        self.routes = routes
        self.calls: list[tuple[str, dict]] = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        for prefix, resp in self.routes.items():
            if url.startswith(prefix):
                if isinstance(resp, list):  # queue of responses, e.g. a 429 then a 200
                    return resp.pop(0) if len(resp) > 1 else resp[0]
                return resp
        return FakeResponse(404)


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text()
