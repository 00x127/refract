from __future__ import annotations

from .model import Field

_RULES = [
    (("email", "e_mail"), "email"),
    (("url", "uri", "link", "website", "webhook", "callback"), "url"),
    (("uuid", "guid"), "uuid"),
    (("password", "passwd", "secret", "token", "name", "title", "description", "bio", "slug"), "string"),
    (("is_", "has_", "can_", "enabled", "verified", "active", "admin"), "bool"),
    (("_id", "count", "qty", "quantity", "age", "number", "amount", "price", "total"), "int"),
    (("date", "time", "_at"), "datetime"),
]


def enrich(root: Field) -> None:
    _visit(root)


def _visit(node: Field) -> None:
    for child in node.children.values():
        if child.type in (None, "unknown"):
            guess = _from_name(child.name)
            if guess:
                child.type = guess
                child.type_guessed = True
        _visit(child)


def _from_name(name: str) -> str | None:
    low = name.lower()
    for hints, mapped in _RULES:
        for hint in hints:
            if hint.endswith("_") and low.startswith(hint):
                return mapped
            if hint.startswith("_") and low.endswith(hint):
                return mapped
            if hint in low:
                return mapped
    return None
