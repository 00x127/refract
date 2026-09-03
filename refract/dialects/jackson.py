from __future__ import annotations

import re

import httpx

from ..model import Finding
from .base import Dialect, json_body as _json

_DESERIALIZE = re.compile(r"Cannot deserialize value of type [`']([^`']+)[`']")
_CHAIN = re.compile(r'\["([^"]+)"\]')
_MISSING = re.compile(r"missing (?:property|field) [`'\"]([^`'\"]+)")

_JAVA_MAP = {
    "String": "string",
    "int": "int",
    "long": "int",
    "short": "int",
    "Integer": "int",
    "Long": "int",
    "BigInteger": "int",
    "double": "float",
    "float": "float",
    "Double": "float",
    "Float": "float",
    "BigDecimal": "float",
    "boolean": "bool",
    "Boolean": "bool",
    "UUID": "uuid",
    "LocalDate": "date",
    "LocalDateTime": "datetime",
    "Instant": "datetime",
    "Date": "datetime",
    "OffsetDateTime": "datetime",
}


class Jackson(Dialect):
    name = "jackson"
    confidence = 80

    def matches(self, resp: httpx.Response) -> bool:
        body = resp.text
        if "Cannot deserialize" in body or "JSON parse error" in body:
            return True
        data = _json(resp)
        if isinstance(data, dict) and {"timestamp", "status"} <= set(data):
            return True
        return False

    def parse(self, resp: httpx.Response) -> list[Finding]:
        out: list[Finding] = []
        body = _decoded_text(resp)

        chain = _CHAIN.findall(body)
        target = _DESERIALIZE.search(body)
        if target and chain:
            java = target.group(1).rsplit(".", 1)[-1].split("<", 1)[0]
            mapped = self._map_java(java)
            out.append(Finding(path=chain, type=mapped, confidence=self.confidence, message=target.group(0)))

        for name in _MISSING.findall(body):
            out.append(Finding(path=[name], required=True, confidence=self.confidence))

        data = _json(resp)
        for err in _spring_errors(data):
            field = err.get("field")
            if not field:
                continue
            msg = err.get("defaultMessage", "")
            required = any(w in msg.lower() for w in ("null", "empty", "blank", "required", "mandatory"))
            out.append(Finding(path=field.split("."), required=required, exists=True,
                               confidence=self.confidence, message=msg))
        return out

    def _map_java(self, java: str) -> str:
        if java in _JAVA_MAP:
            return _JAVA_MAP[java]
        if java in ("List", "ArrayList", "Collection", "Set"):
            return "array"
        if java in ("Map", "HashMap"):
            return "object"
        return "object"


def _decoded_text(resp: httpx.Response) -> str:
    data = _json(resp)
    if isinstance(data, dict):
        parts = [v for v in _strings(data)]
        if parts:
            return " ".join(parts)
    return resp.text


def _strings(node):
    if isinstance(node, dict):
        for value in node.values():
            yield from _strings(value)
    elif isinstance(node, list):
        for value in node:
            yield from _strings(value)
    elif isinstance(node, str):
        yield node


def _spring_errors(data: dict) -> list[dict]:
    if not isinstance(data, dict):
        return []
    errors = data.get("errors")
    if isinstance(errors, list):
        return [e for e in errors if isinstance(e, dict)]
    return []
