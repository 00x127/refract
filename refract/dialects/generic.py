from __future__ import annotations

import re

import httpx

from ..model import Finding
from .base import Dialect

_TYPED = re.compile(
    r"['\"`]?([A-Za-z_][A-Za-z0-9_.]*)['\"`]?\s+"
    r"(?:must be|should be|is not a valid|expected|has to be)\s+"
    r"(?:an?\s+|a valid\s+)?"
    r"(string|integer|int|number|float|boolean|bool|array|list|object|uuid|guid|date|datetime|email|url)",
    re.IGNORECASE,
)
_REQUIRED = re.compile(
    r"['\"`]?([A-Za-z_][A-Za-z0-9_.]*)['\"`]?\s+is\s+(?:required|missing)"
    r"|(?:required|missing)(?:\s+field)?[:\s]+['\"`]?([A-Za-z_][A-Za-z0-9_.]*)",
    re.IGNORECASE,
)

_TYPE_ALIAS = {
    "integer": "int",
    "int": "int",
    "number": "float",
    "float": "float",
    "string": "string",
    "boolean": "bool",
    "bool": "bool",
    "array": "array",
    "list": "array",
    "object": "object",
    "uuid": "uuid",
    "guid": "uuid",
    "date": "date",
    "datetime": "datetime",
    "email": "email",
    "url": "url",
}


class Generic(Dialect):
    name = "generic"
    confidence = 45

    def matches(self, resp: httpx.Response) -> bool:
        return True

    def parse(self, resp: httpx.Response) -> list[Finding]:
        text = _flatten(resp)
        out: list[Finding] = []
        seen: set[tuple[str, str]] = set()

        for name, kind in _TYPED.findall(text):
            mapped = _TYPE_ALIAS.get(kind.lower())
            key = (name, "type")
            if mapped and key not in seen:
                seen.add(key)
                out.append(Finding(path=name.split("."), type=mapped, confidence=self.confidence, message=kind))

        for a, b in _REQUIRED.findall(text):
            name = a or b
            key = (name, "req")
            if name and key not in seen:
                seen.add(key)
                out.append(Finding(path=name.split("."), required=True, confidence=self.confidence))

        return out


def _flatten(resp: httpx.Response) -> str:
    try:
        data = resp.json()
    except Exception:
        return resp.text
    parts: list[str] = []

    def walk(node):
        if isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
        elif isinstance(node, str):
            parts.append(node)

    walk(data)
    return " ".join(parts) if parts else resp.text
