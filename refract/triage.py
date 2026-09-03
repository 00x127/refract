from __future__ import annotations

from dataclasses import dataclass

from .model import Field

_RULES = [
    ("idor", ("id", "uuid", "guid", "ref", "key", "token", "slug"),
     ("uuid", "int", "string"), "identifier field, swap it for another user's value"),
    ("privesc", ("role", "admin", "staff", "superuser", "permission", "scope",
                 "priv", "access", "level", "group", "tier", "plan"),
     (), "privilege field, try setting a higher value"),
    ("mass-assign", ("is_", "has_", "can_", "enabled", "verified", "active",
                     "approved", "confirmed", "internal", "debug", "owner"),
     ("bool",), "state flag the client never sends, try forcing it true"),
    ("ssrf", ("url", "uri", "callback", "webhook", "endpoint", "host",
              "link", "redirect", "fetch", "image", "avatar", "src", "target"),
     ("string", "url"), "server-side fetchable value, point it inward"),
    ("traversal", ("path", "file", "filename", "dir", "folder",
                   "template", "include", "document", "attachment"),
     ("string",), "filesystem-flavoured value, try ../ and absolute paths"),
    ("money", ("price", "amount", "cost", "balance", "credit", "discount",
               "total", "fee", "quantity", "qty", "currency"),
     ("int", "float"), "value field, try negatives and tampered totals"),
]


@dataclass
class Lead:
    path: str
    category: str
    reason: str
    hidden: bool
    field_type: str | None
    enum: list[str] | None


def analyse(root: Field) -> list[Lead]:
    leads: list[Lead] = []
    _visit(root, [], leads)
    leads.sort(key=lambda l: (not l.hidden, l.category))
    return leads


def _visit(node: Field, path: list[str], out: list[Lead]) -> None:
    for name, child in node.children.items():
        here = path + [name]
        lead = _classify(child, here)
        if lead:
            out.append(lead)
        if child.children:
            _visit(child, here, out)


def _classify(node: Field, path: list[str]) -> Lead | None:
    low = node.name.lower()
    dotted = ".".join(path)

    if node.type == "enum" and node.enum:
        if any(v.lower() in ("admin", "staff", "root", "superuser") for v in node.enum):
            return Lead(dotted, "privesc", "enum exposes a privileged value",
                        node.hidden, node.type, node.enum)

    for category, hints, types, reason in _RULES:
        if _matches(low, hints) and (not types or node.type in types or node.type in (None, "unknown")):
            return Lead(dotted, category, reason, node.hidden, node.type, node.enum)
    return None


def _matches(name: str, hints: tuple[str, ...]) -> bool:
    for hint in hints:
        if hint.endswith("_"):
            if name.startswith(hint):
                return True
        elif hint in name:
            return True
    return False
