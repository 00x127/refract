from __future__ import annotations

import re

import httpx

from ..model import Finding
from .base import Dialect, json_body

_UNMARSHAL = re.compile(
    r"cannot unmarshal \w+ into Go struct field [\w.]*?(\w+) of type ([\w\[\]\*.]+)"
)
_VALIDATOR = re.compile(r"Key: '([^']+)' Error:Field validation for '[^']+' failed on the '([^']+)' tag")

_GO_TYPES = {
    "int": "int", "int8": "int", "int16": "int", "int32": "int", "int64": "int",
    "uint": "int", "uint32": "int", "uint64": "int",
    "float32": "float", "float64": "float",
    "bool": "bool", "string": "string",
    "time.Time": "datetime",
}


class Golang(Dialect):
    name = "golang"
    confidence = 80

    def matches(self, resp: httpx.Response) -> bool:
        text = _error_text(resp)
        return "Go struct field" in text or "Field validation for" in text

    def parse(self, resp: httpx.Response) -> list[Finding]:
        text = _error_text(resp)
        out: list[Finding] = []

        for field, gotype in _UNMARSHAL.findall(text):
            mapped = _map_go(gotype)
            out.append(Finding(path=[field], type=mapped, exists=True, confidence=self.confidence))

        for key, tag in _VALIDATOR.findall(text):
            path = _strip_struct(key)
            finding = Finding(path=path, exists=True, confidence=self.confidence)
            self._apply_tag(finding, tag)
            out.append(finding)
        return out

    def _apply_tag(self, finding: Finding, tag: str) -> None:
        if tag == "required":
            finding.required = True
        elif tag == "email":
            finding.type = "email"
        elif tag == "url":
            finding.type = "url"
        elif tag == "uuid":
            finding.type = "uuid"
        elif tag in ("numeric", "number"):
            finding.type = "float"
        elif tag.startswith("oneof="):
            finding.type = "enum"
            finding.enum = tag.split("=", 1)[1].split()


def _map_go(gotype: str) -> str:
    gotype = gotype.lstrip("*")
    if gotype.startswith("[]"):
        return "array"
    if gotype.startswith("map["):
        return "object"
    return _GO_TYPES.get(gotype, "object")


def _strip_struct(key: str) -> list[str]:
    parts = key.split(".")
    if len(parts) > 1:
        parts = parts[1:]
    return [p[0].lower() + p[1:] if p else p for p in parts]


def _error_text(resp: httpx.Response) -> str:
    data = json_body(resp)
    if isinstance(data, dict):
        for key in ("error", "message", "msg"):
            if isinstance(data.get(key), str):
                return data[key]
    return resp.text
