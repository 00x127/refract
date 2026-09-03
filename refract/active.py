from __future__ import annotations

import copy
import secrets
from dataclasses import dataclass
from typing import Any

from . import mutate
from .client import Client, Request
from .dialects import detect
from .model import Field, Schema
from .triage import Lead

MONGO = [{"$ne": None}, {"$gt": ""}, {"$regex": ".*"}]
JUGGLE = [True, 0]


@dataclass
class Signal:
    kind: str
    path: str
    detail: str
    status: int


class Active:
    def __init__(self, client: Client, req: Request, schema: Schema, encoding: str = "json"):
        self.client = client
        self.req = req
        self.schema = schema
        self.encoding = encoding
        self.base = mutate.build_object(schema.root, sentinel=None, valid=True)
        self.signals: list[Signal] = []
        self.sent = 0

    def run(self, leads: list[Lead]) -> tuple[list[Signal], int]:
        self._injection_pass()
        self._acceptance_pass(leads)
        return self.signals, self.sent

    def _injection_pass(self) -> None:
        string_like = ("string", "uuid", "email", "url", None, "unknown")
        for path, field in _leaves(self.schema.root):
            if field.type in ("object", "array"):
                continue
            payloads = list(MONGO)
            if field.type in string_like:
                payloads += JUGGLE

            # if the field takes any scalar then acceptance proves nothing
            control_accepted = self._accepted(self._send(self._with(path, _control_value(field))), path)
            if control_accepted:
                continue

            # a payload getting through where a plain wrong type was rejected is the real signal
            for payload in payloads:
                if self._accepted(self._send(self._with(path, payload)), path):
                    label = "mongo operator" if isinstance(payload, dict) else "type juggling"
                    self.signals.append(Signal(
                        "injection", ".".join(path),
                        f"{label} {payload!r} accepted where a wrong-typed scalar was rejected",
                        200))
                    break

    def _acceptance_pass(self, leads: list[Lead]) -> None:
        for lead in leads:
            if lead.category not in ("privesc", "mass-assign", "ssrf", "traversal"):
                continue
            path = lead.path.split(".")
            node = self.schema.node_at(path)
            value, marker = _attack_value(lead, node)
            resp = self._send(self._with(path, value))
            if not self._accepted(resp, path):
                continue
            if marker and marker in resp.text:
                self.signals.append(Signal("reflection", lead.path,
                                           "injected value reflected in a 2xx response", resp.status_code))
            elif lead.category in ("privesc", "mass-assign"):
                self.signals.append(Signal("mass-assign", lead.path,
                                           f"server accepted {value!r} in a 2xx response", resp.status_code))

    def _send(self, body: Any):
        resp = self.client.send(self.req, body, self.encoding)
        self.sent += 1
        return resp

    def _with(self, path: list[str], value: Any) -> dict:
        body = copy.deepcopy(self.base)
        cursor = body
        for part in path[:-1]:
            cursor = cursor.setdefault(part, {})
        cursor[path[-1]] = value
        return body

    def _rejected_at(self, resp, path: list[str]) -> bool:
        for finding in detect(resp).parse(resp):
            if finding.path == path:
                return True
        return False

    def _accepted(self, resp, path: list[str]) -> bool:
        if self._rejected_at(resp, path):
            return False
        return 200 <= resp.status_code < 300


def _leaves(node: Field, path: list[str] | None = None):
    path = path or []
    for name, child in node.children.items():
        here = path + [name]
        if child.children:
            yield from _leaves(child, here)
        else:
            yield here, child


def _control_value(field: Field) -> Any:
    if field.type == "string":
        return 999999999
    return "refract_control"


def _attack_value(lead: Lead, node: Field) -> tuple[Any, str | None]:
    marker = "refract" + secrets.token_hex(3)
    if lead.category == "privesc":
        if node.enum:
            for pick in ("admin", "superuser", "root", "staff"):
                if pick in node.enum:
                    return pick, None
            return node.enum[-1], None
        return True, None
    if lead.category == "mass-assign":
        return True, None
    if lead.category == "ssrf":
        return f"https://{marker}.example.com", marker
    if lead.category == "traversal":
        return f"{marker}/../../x", marker
    return True, None
