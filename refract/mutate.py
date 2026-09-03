from __future__ import annotations

from typing import Any

from .model import Field

# each of these is the wrong type for most fields so the server tells us what it wanted
SENTINELS: list[Any] = [[], "refract", 1, True]

_VALID = {
    "string": "refract",
    "int": 1,
    "float": 1.0,
    "bool": True,
    "array": ["refract"],
    "object": {},
    "uuid": "00000000-0000-0000-0000-000000000000",
    "datetime": "2020-01-01T00:00:00Z",
    "date": "2020-01-01",
    "email": "a@refract.test",
    "url": "https://refract.test",
    "enum": None,
}


def valid_value(node: Field) -> Any:
    if node.type == "enum" and node.enum:
        return node.enum[0]
    if node.type == "object":
        return build_object(node, sentinel=None, valid=True)
    return _VALID.get(node.type or "", "refract")


def build_object(node: Field, sentinel: Any, valid: bool = False) -> dict:
    body: dict[str, Any] = {}
    for name, child in node.children.items():
        if child.type == "object":
            body[name] = build_object(child, sentinel, valid)
        elif child.type in (None, "unknown") and not valid:
            body[name] = sentinel
        else:
            body[name] = valid_value(child)
    return body
