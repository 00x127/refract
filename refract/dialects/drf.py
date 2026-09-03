from __future__ import annotations

import httpx

from ..model import Finding
from .base import Dialect, json_body, type_from_message

_REQUIRED = ("this field is required", "may not be null", "may not be blank", "no data provided",
             "required")
_ENVELOPE = ("jsonrpc", "error", "exception", "traceback", "stacktrace", "code", "status_code")
_WRAPPERS = ("labels", "fields", "validation", "validationerrors", "messages", "field_errors")
_MESSAGE = ("valid", "required", "must", "invalid", "may not", "blank", "null",
            "expected", "not a", "no data", "already", "too ", "at least", "at most",
            "type", "default", "unique", "taken", "exists", "format", "numeric",
            "integer", "string", "boolean", "email", "min", "max")


class DRF(Dialect):
    name = "drf"
    confidence = 85

    def matches(self, resp: httpx.Response) -> bool:
        data = json_body(resp)
        if not isinstance(data, dict) or not data:
            return False
        if isinstance(data.get("detail"), list):
            return False
        if isinstance(data.get("errors"), (dict, list)):
            return False
        if any(key in data for key in _ENVELOPE):
            return False
        return any(_looks_like_field(v) and _is_validation(v) for v in data.values())

    def parse(self, resp: httpx.Response) -> list[Finding]:
        data = json_body(resp)
        out: list[Finding] = []
        if isinstance(data, dict):
            _walk(_unwrap(data), [], out, self.confidence)
        return out


def _looks_like_field(value) -> bool:
    if isinstance(value, list):
        return any(isinstance(x, str) for x in value)
    return isinstance(value, dict)


def _is_validation(value) -> bool:
    if isinstance(value, dict):
        return any(_looks_like_field(v) and _is_validation(v) for v in value.values())
    text = " ".join(str(x) for x in value).lower()
    return any(word in text for word in _MESSAGE)


def _walk(node: dict, path: list[str], out: list[Finding], conf: int) -> None:
    for key, value in node.items():
        if key in ("non_field_errors", "detail"):
            continue
        here = path + [key]
        if isinstance(value, dict):
            _walk(value, here, out, conf)
        elif isinstance(value, list):
            out.append(_message_finding(here, " ".join(str(x) for x in value), conf))


def _unwrap(data: dict) -> dict:
    # some apis bury all the field errors under one wrapper key so peel it off first
    if len(data) == 1:
        (key, value), = data.items()
        if key.lower() in _WRAPPERS and isinstance(value, dict):
            return value
    return data


def _message_finding(path: list[str], msg: str, conf: int) -> Finding:
    finding = Finding(path=path, exists=True, confidence=conf, message=msg)
    low = msg.lower()
    if "not a valid choice" in low:
        finding.type = "enum"
    else:
        finding.type = type_from_message(msg)
    if finding.type is None and any(word in low for word in _REQUIRED):
        finding.required = True
    return finding
