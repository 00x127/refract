from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit

from . import graphql
from .client import Client, Request
from .dialects import detect
from .engine import Engine
from .triage import Lead, analyse

_REL = re.compile(r"""["'](/(?:api|rest|graphql|v\d|users|auth|oauth|account|session|query)"""
                  r"""[A-Za-z0-9_\-/.]{0,60})["']""")
_ABS = re.compile(r"""https?://[A-Za-z0-9._\-]+/(?:api|rest|graphql|v\d)[A-Za-z0-9_\-/.]{0,60}""")
_SCRIPT = re.compile(r'src=["\']([^"\']+\.js[^"\']*)["\']')
_SPEC_PATHS = ["/openapi.json", "/api/openapi.json", "/v1/openapi.json", "/swagger.json"]
_CURATED = [
    "/api/login", "/api/v1/login", "/api/auth/login", "/login", "/api/session",
    "/api/register", "/api/signup", "/api/auth/register", "/api/users", "/api/account",
    "/api/contact", "/api/subscribe", "/api/forgot-password", "/graphql", "/api/graphql",
]


@dataclass
class Endpoint:
    url: str
    kind: str = "json"
    method: str = "POST"


@dataclass
class Finding:
    endpoint: Endpoint
    kind: str
    result: object = None
    leads: list[Lead] = field(default_factory=list)


def spider(client: Client, base: str, headers: dict, max_endpoints: int = 40,
           max_js: int = 8, verbose: bool = False) -> tuple[list[Endpoint], list[Finding]]:
    endpoints = _discover(client, base, headers, max_js)
    findings: list[Finding] = []

    for ep in endpoints[:max_endpoints]:
        if verbose:
            print(f"[refract] probing {ep.url}")
        try:
            if ep.kind == "graphql":
                res = graphql.recover(client, Request("POST", ep.url, dict(headers)))
                if res.is_graphql and (res.query_fields or res.mutation_fields):
                    findings.append(Finding(ep, "graphql", res))
            else:
                finding = _probe_rest(client, ep, headers)
                if finding:
                    findings.append(finding)
        except Exception:
            continue
    return endpoints, findings


def _probe_rest(client: Client, ep: Endpoint, headers: dict) -> Finding | None:
    req = Request(ep.method, ep.url, dict(headers), "")
    resp = client.send(req, {"refract_probe": [1]}, "json")
    dialect = detect(resp)
    if dialect.name == "generic" or not dialect.parse(resp):
        return None
    result = Engine(client, req).run()
    if result.static or not result.schema.root.children:
        return None
    return Finding(ep, "rest", result, analyse(result.schema.root))


def _discover(client: Client, base: str, headers: dict, max_js: int) -> list[Endpoint]:
    base = base if base.startswith("http") else "https://" + base
    host = urlsplit(base).netloc
    found: dict[str, Endpoint] = {}

    def add(url: str) -> None:
        url = url.split("#")[0].split("?")[0]
        if urlsplit(url).netloc.split(":")[0].split(".")[-2:] != host.split(":")[0].split(".")[-2:]:
            return
        kind = "graphql" if "graphql" in url.lower() else "json"
        found.setdefault(url, Endpoint(url, kind))

    # always try these common paths even when the page links to none of them
    for path in _CURATED:
        add(urljoin(base, path))

    try:
        home = client.get(base, headers)
    except Exception:
        home = None

    if home is not None:
        html = home.text
        for path in _REL.findall(html):
            add(urljoin(base, path))
        for url in _ABS.findall(html):
            add(url)
        for src in _SCRIPT.findall(html)[:max_js]:
            js_url = src if src.startswith("http") else urljoin(base, src)
            try:
                body = client.get(js_url, headers).text
            except Exception:
                continue
            for path in _REL.findall(body):
                add(urljoin(base, path))
            for url in _ABS.findall(body):
                add(url)

    _from_openapi(client, base, headers, add)
    return list(found.values())


def _from_openapi(client: Client, base: str, headers: dict, add) -> None:
    for path in _SPEC_PATHS:
        try:
            resp = client.get(urljoin(base, path), headers)
        except Exception:
            continue
        if resp.status_code != 200:
            continue
        try:
            spec = resp.json()
        except Exception:
            continue
        if not (isinstance(spec, dict) and isinstance(spec.get("paths"), dict)):
            continue
        servers = spec.get("servers") or [{"url": "/"}]
        server = servers[0].get("url", "/")
        spec_base = server if server.startswith("http") else base.rstrip("/") + ("" if server == "/" else server)
        for route, ops in spec["paths"].items():
            if "{" in route or not isinstance(ops, dict):
                continue
            if "post" in ops:
                add(spec_base.rstrip("/") + route)
        return
