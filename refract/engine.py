from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from typing import Any

from . import infer, mutate
from .client import Client, Request
from .dialects import detect
from .model import Field, Schema

CANDIDATES = [
    "role", "roles", "is_admin", "admin", "is_staff", "is_superuser", "superuser",
    "user_id", "account_id", "org_id", "organization_id", "owner_id", "owner", "created_by",
    "password", "passwd", "token", "api_key", "apikey", "secret",
    "email", "verified", "is_verified", "is_active", "active", "enabled", "disabled",
    "debug", "internal", "permissions", "permission", "scope", "scopes",
    "balance", "price", "amount", "cost", "quantity", "qty", "discount", "total",
    "status", "state", "type", "kind",
    "url", "uri", "callback", "webhook", "redirect", "redirect_uri", "next", "return_url",
    "file", "filename", "path", "filepath", "avatar", "avatar_url", "bio",
    "tags", "metadata", "extra", "settings", "config",
]

_INTERNAL_MARKERS = (
    "Traceback", "java.", "org.springframework", "SQLSTATE", "SQL syntax",
    "at java.base", "System.", "Microsoft.", "psycopg2", "sqlalchemy",
    "/usr/lib", "/home/", "/var/www", "node_modules",
)


@dataclass
class Result:
    schema: Schema
    dialect: str
    requests_sent: int
    baseline_status: int | None
    static: bool = False
    leaks: list[str] = field(default_factory=list)


class Engine:
    def __init__(self, client: Client, req: Request, max_rounds: int = 24,
                 max_depth: int = 5, verbose: bool = False, encoding: str = "json"):
        self.client = client
        self.req = req
        self.max_rounds = max_rounds
        self.max_depth = max_depth
        self.verbose = verbose
        self.encoding = encoding
        self.schema = Schema()
        self.dialect = None
        self.sent = 0
        self.baseline_status: int | None = None
        self.leaks: list[str] = []
        self.prints: set[str] = set()

    def run(self) -> Result:
        self._seed_from_client()
        self._probe({})

        stale = 0
        for rnd in range(self.max_rounds):
            sentinel = mutate.SENTINELS[rnd % len(mutate.SENTINELS)]
            body = mutate.build_object(self.schema.root, sentinel)
            changed = self._probe(body)
            self._log(f"round {rnd + 1}: sentinel={sentinel!r} new={changed}")
            # if nothing we send ever changes the reply there is no oracle here to read
            if rnd >= 2 and len(self.prints) <= 1:
                break
            stale = 0 if changed else stale + 1
            if stale >= len(mutate.SENTINELS):
                break

        # optional fields with defaults never error on their own so we name likely ones and probe them
        self._candidate_scan()
        static = len(self.prints) <= 1
        if static:
            _prune_discovered(self.schema.root)
        else:
            infer.enrich(self.schema.root)

        return Result(
            schema=self.schema,
            dialect=self.dialect.name if self.dialect else "none",
            requests_sent=self.sent,
            baseline_status=self.baseline_status,
            static=static,
            leaks=self.leaks,
        )

    def _seed_from_client(self) -> None:
        body = self.req.json_body()
        if isinstance(body, dict):
            _walk_client(self.schema, [], body)

    def _candidate_scan(self) -> None:
        base = mutate.build_object(self.schema.root, sentinel=None, valid=True)
        for path in self._object_paths():
            node = self.schema.node_at(path)
            names = [c for c in CANDIDATES if c not in node.children]
            if not names:
                continue
            for sentinel in ([], "refract_probe"):
                body = copy.deepcopy(base)
                target = body
                for part in path:
                    target = target.setdefault(part, {})
                for name in names:
                    target[name] = sentinel
                self._probe(body, accept_only=set(names), at_path=path)

    def _object_paths(self) -> list[list[str]]:
        paths: list[list[str]] = [[]]
        queue: list[tuple[list[str], Field]] = [([], self.schema.root)]
        while queue:
            path, node = queue.pop(0)
            if len(path) >= self.max_depth:
                continue
            for name, child in node.children.items():
                if child.type == "object":
                    here = path + [name]
                    paths.append(here)
                    queue.append((here, child))
        return paths

    def _probe(self, body: Any, accept_only: set[str] | None = None,
               at_path: list[str] | None = None) -> int:
        resp = self.client.send(self.req, body, self.encoding)
        self.sent += 1
        if self.baseline_status is None:
            self.baseline_status = resp.status_code

        self.prints.add(_fingerprint(resp))

        found = detect(resp)
        if self.dialect is None or (found.name != "generic" and self.dialect.name == "generic"):
            self.dialect = found

        self._collect_leaks(resp)

        changed = 0
        for finding in found.parse(resp):
            if accept_only is not None and not _in_scope(finding.path, at_path or [], accept_only):
                continue
            if self.schema.apply(finding):
                changed += 1
        return changed

    def _collect_leaks(self, resp) -> None:
        text = resp.text
        joined = " ".join(self.leaks)
        for marker in _INTERNAL_MARKERS:
            if marker in text and marker not in joined:
                snippet = _around(text, marker)
                if snippet:
                    self.leaks.append(snippet)
                    joined += " " + snippet

    def _log(self, msg: str) -> None:
        if self.verbose:
            print(f"[refract] {msg}")


def _in_scope(path: list[str], at_path: list[str], names: set[str]) -> bool:
    return len(path) == len(at_path) + 1 and path[:len(at_path)] == at_path and path[-1] in names


def _walk_client(schema: Schema, path: list[str], obj: dict) -> None:
    for key, value in obj.items():
        here = path + [key]
        schema.seed_client_field(here, _infer_type(value))
        if isinstance(value, dict):
            _walk_client(schema, here, value)


def _infer_type(value: Any) -> str | None:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return None


def _around(text: str, marker: str, width: int = 160) -> str:
    idx = text.find(marker)
    start = max(0, idx - 20)
    return " ".join(text[start:idx + width].split())


_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def _fingerprint(resp) -> str:
    text = resp.text[:4000].lower()
    text = _UUID.sub("", text)
    text = re.sub(r"[0-9a-f]{16,}", "", text)
    text = re.sub(r"\b[a-z0-9]{12,}\b", "", text)
    text = re.sub(r"\d+", "", text)
    text = re.sub(r"\s+", " ", text)
    return f"{resp.status_code}|{text}"


def _prune_discovered(node: Field) -> None:
    for name in list(node.children):
        child = node.children[name]
        if not child.seen_in_client:
            del node.children[name]
        else:
            _prune_discovered(child)
