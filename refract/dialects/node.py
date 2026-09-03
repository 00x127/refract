from __future__ import annotations

import re

import httpx

from ..model import Finding
from .base import Dialect, json_body

_JOI_QUOTED = re.compile(r'"([^"]+)"\s+must be')
_AJV_TYPES = {
    "integer": "int", "number": "float", "string": "string",
    "boolean": "bool", "array": "array", "object": "object", "null": "unknown",
}
_JOI_TYPES = {
    "number": "float", "string": "string", "boolean": "bool",
    "array": "array", "object": "object", "date": "datetime",
}


class Node(Dialect):
    name = "node"
    confidence = 80

    def matches(self, resp: httpx.Response) -> bool:
        data = json_body(resp)
        for item in _ajv_items(data):
            if isinstance(item, dict) and ("instancePath" in item or "schemaPath" in item):
                return True
        if isinstance(data, dict):
            details = data.get("details")
            if isinstance(details, list) and details and isinstance(details[0], dict) and "path" in details[0]:
                return True
            if isinstance(data.get("message"), str) and _JOI_QUOTED.search(data["message"]):
                return True
        return False

    def parse(self, resp: httpx.Response) -> list[Finding]:
        data = json_body(resp)
        out: list[Finding] = []

        for item in _ajv_items(data):
            if isinstance(item, dict) and ("instancePath" in item or "keyword" in item):
                out.append(self._ajv(item))

        if isinstance(data, dict):
            for item in data.get("details", []) or []:
                if isinstance(item, dict) and "path" in item:
                    out.append(self._joi(item))
            msg = data.get("message")
            if isinstance(msg, str):
                hit = _JOI_QUOTED.search(msg)
                if hit:
                    out.append(_from_joi_message(hit.group(1), msg, self.confidence))

        return [f for f in out if f]

    def _ajv(self, item: dict) -> Finding:
        path = [p for p in item.get("instancePath", "").split("/") if p]
        keyword = item.get("keyword")
        params = item.get("params", {}) or {}
        if keyword == "required":
            name = params.get("missingProperty", "")
            return Finding(path=path + [name] if name else path, required=True,
                           exists=True, confidence=self.confidence)
        finding = Finding(path=path, exists=True, confidence=self.confidence,
                          message=item.get("message", ""))
        if keyword == "type":
            finding.type = _AJV_TYPES.get(params.get("type"))
        elif keyword == "enum":
            finding.type = "enum"
            allowed = params.get("allowedValues")
            if isinstance(allowed, list):
                finding.enum = [str(v) for v in allowed]
        return finding

    def _joi(self, item: dict) -> Finding:
        path = [str(p) for p in item.get("path", [])]
        finding = Finding(path=path, exists=True, confidence=self.confidence,
                          message=item.get("message", ""))
        kind = str(item.get("type", ""))
        base = kind.split(".")[0]
        if kind.endswith(".required"):
            finding.required = True
        elif kind.endswith(".only"):
            finding.type = "enum"
            valids = (item.get("context") or {}).get("valids")
            if isinstance(valids, list):
                finding.enum = [str(v) for v in valids]
        elif kind.endswith(".email"):
            finding.type = "email"
        elif kind.endswith(".uri"):
            finding.type = "url"
        elif kind.endswith(".guid"):
            finding.type = "uuid"
        else:
            finding.type = _JOI_TYPES.get(base)
        return finding


def _from_joi_message(field: str, msg: str, conf: int) -> Finding:
    finding = Finding(path=field.split("."), exists=True, confidence=conf, message=msg)
    low = msg.lower()
    if "required" in low:
        finding.required = True
    elif "must be a number" in low:
        finding.type = "float"
    elif "must be a string" in low:
        finding.type = "string"
    elif "must be a boolean" in low:
        finding.type = "bool"
    elif "must be an array" in low:
        finding.type = "array"
    return finding


def _ajv_items(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("errors"), list):
        return data["errors"]
    return []
