from __future__ import annotations

import re

import httpx

from ..model import Finding
from .base import Dialect, json_body as _json

_ENUM = re.compile(r"'([^']*)'")

_TYPE_MAP = {
    "string_type": "string",
    "string_pattern_mismatch": "string",
    "string_too_short": "string",
    "string_too_long": "string",
    "int_type": "int",
    "int_parsing": "int",
    "float_type": "float",
    "float_parsing": "float",
    "decimal_type": "float",
    "decimal_parsing": "float",
    "bool_type": "bool",
    "bool_parsing": "bool",
    "list_type": "array",
    "tuple_type": "array",
    "set_type": "array",
    "dict_type": "object",
    "model_type": "object",
    "model_attributes_type": "object",
    "uuid_type": "uuid",
    "uuid_parsing": "uuid",
    "datetime_type": "datetime",
    "datetime_parsing": "datetime",
    "datetime_from_date_parsing": "datetime",
    "date_type": "date",
    "date_parsing": "date",
    "json_type": "object",
    "url_type": "url",
    "url_parsing": "url",
}

_CONSTRAINT_KEYS = (
    "gt", "ge", "lt", "le",
    "min_length", "max_length",
    "multiple_of", "pattern",
)


class Pydantic(Dialect):
    name = "pydantic"
    confidence = 95

    def matches(self, resp: httpx.Response) -> bool:
        data = _json(resp)
        detail = data.get("detail") if isinstance(data, dict) else None
        return (
            isinstance(detail, list)
            and bool(detail)
            and isinstance(detail[0], dict)
            and "loc" in detail[0]
            and "type" in detail[0]
        )

    def parse(self, resp: httpx.Response) -> list[Finding]:
        data = _json(resp) or {}
        out: list[Finding] = []
        for err in data.get("detail", []):
            loc = [str(p) for p in err.get("loc", [])]
            if loc and loc[0] in ("body", "query", "path", "header", "cookie"):
                loc = loc[1:]
            if not loc:
                continue

            kind = err.get("type", "")
            ctx = err.get("ctx") or {}
            finding = Finding(path=loc, confidence=self.confidence, message=err.get("msg", ""))

            if kind == "missing":
                finding.required = True
            elif kind == "enum":
                finding.type = "enum"
                finding.enum = _ENUM.findall(str(ctx.get("expected", "")))
            else:
                finding.type = _TYPE_MAP.get(kind)

            for key in _CONSTRAINT_KEYS:
                if key in ctx:
                    finding.constraints[key] = ctx[key]

            out.append(finding)
        return out
