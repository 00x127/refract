from __future__ import annotations

import re

import httpx

from ..model import Finding
from .base import Dialect, json_body

_DOTNET = {
    "Int16": "int", "Int32": "int", "Int64": "int", "Byte": "int",
    "Single": "float", "Double": "float", "Decimal": "float",
    "Boolean": "bool", "String": "string", "DateTime": "datetime",
    "DateTimeOffset": "datetime", "Guid": "uuid",
}
_TYPE = re.compile(r"System\.(\w+)")


class AspNet(Dialect):
    name = "aspnet"
    confidence = 85

    def matches(self, resp: httpx.Response) -> bool:
        data = json_body(resp)
        if not isinstance(data, dict) or not isinstance(data.get("errors"), dict):
            return False
        title = str(data.get("title", "")).lower()
        return "valid" in title or "problem" in str(data.get("type", "")).lower()

    def parse(self, resp: httpx.Response) -> list[Finding]:
        data = json_body(resp)
        out: list[Finding] = []
        for field, messages in data.get("errors", {}).items():
            if field.startswith("$"):
                field = field[1:]
            field = field.lstrip(".")
            if not field:
                continue
            msg = " ".join(messages) if isinstance(messages, list) else str(messages)
            finding = Finding(path=field.split("."), exists=True,
                              confidence=self.confidence, message=msg)
            hit = _TYPE.search(msg)
            if hit:
                finding.type = _DOTNET.get(hit.group(1))
            if "is required" in msg.lower() or "required field" in msg.lower():
                finding.required = True
            out.append(finding)
        return out
