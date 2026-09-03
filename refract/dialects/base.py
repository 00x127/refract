from __future__ import annotations

import re

import httpx

from ..model import Finding


class Dialect:
    name = "base"
    confidence = 50

    def matches(self, resp: httpx.Response) -> bool:
        raise NotImplementedError

    def parse(self, resp: httpx.Response) -> list[Finding]:
        raise NotImplementedError


_WORDS = [
    ("datetime", "datetime"),
    ("date", "date"),
    ("integer", "int"),
    ("number", "float"),
    ("numeric", "float"),
    ("decimal", "float"),
    ("boolean", "bool"),
    ("string", "string"),
    ("array", "array"),
    ("list", "array"),
    ("dictionary", "object"),
    ("object", "object"),
    ("uuid", "uuid"),
    ("guid", "uuid"),
    ("url", "url"),
    ("email", "email"),
]
_WORD_RE = {word: re.compile(rf"\b{word}\b", re.IGNORECASE) for word, _ in _WORDS}


def type_from_message(msg: str) -> str | None:
    for word, mapped in _WORDS:
        if _WORD_RE[word].search(msg):
            return mapped
    return None


def json_body(resp: httpx.Response):
    try:
        return resp.json()
    except Exception:
        return None
