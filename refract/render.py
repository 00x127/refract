from __future__ import annotations

import json
from typing import Any

from . import mutate
from .engine import Result
from .model import Field
from .triage import Lead

_C = {
    "dim": "\033[2m",
    "bold": "\033[1m",
    "red": "\033[31m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "blue": "\033[34m",
    "cyan": "\033[36m",
    "reset": "\033[0m",
}


def _paint(text: str, colour: str, use_colour: bool) -> str:
    if not use_colour:
        return text
    return f"{_C[colour]}{text}{_C['reset']}"


def tree(result: Result, colour: bool = True) -> str:
    lines: list[str] = []
    header = f"schema  (dialect: {result.dialect}, {result.requests_sent} requests)"
    lines.append(_paint(header, "bold", colour))
    if result.static:
        lines.append(_paint(
            "  no validation oracle: the response did not change with input, nothing to recover.",
            "dim", colour))
        return "\n".join(lines)
    _render_node(result.schema.root, "", lines, colour)
    return "\n".join(lines)


def _render_node(node: Field, prefix: str, lines: list[str], colour: bool) -> None:
    items = list(node.children.items())
    for index, (name, child) in enumerate(items):
        last = index == len(items) - 1
        branch = "`-- " if last else "|-- "
        lines.append(prefix + branch + _describe(child, colour))
        if child.children:
            extend = "    " if last else "|   "
            _render_node(child, prefix + extend, lines, colour)


def _describe(node: Field, colour: bool) -> str:
    type_name = (node.type or "unknown") + ("?" if node.type_guessed else "")
    parts = [_paint(node.name, "cyan", colour), _paint(type_name, "yellow", colour)]

    tags = []
    if node.required:
        tags.append(_paint("required", "red", colour))
    if node.hidden:
        tags.append(_paint("hidden", "green", colour))
    if node.enum:
        tags.append("enum{" + ",".join(node.enum) + "}")
    for key, value in node.constraints.items():
        tags.append(f"{key}={value}")
    if node.confidence:
        tags.append(_paint(f"{node.confidence}%", "dim", colour))

    line = f"{parts[0]}: {parts[1]}"
    if tags:
        line += "  " + " ".join(tags)
    return line


def _count_fields(node: Field) -> int:
    total = 0
    for child in node.children.values():
        total += 1 + _count_fields(child)
    return total


def crawl_report(base: str, endpoints, findings, colour: bool = True) -> str:
    head = f"crawl {base}  (found {len(endpoints)} endpoints, {len(findings)} with an oracle)"
    lines = [_paint(head, "bold", colour)]
    if not findings:
        lines.append(_paint("  no endpoint returned readable validation errors.", "dim", colour))
    for finding in findings:
        url = finding.endpoint.url
        if finding.kind == "graphql":
            gql = finding.result
            lines.append(_paint(f"[graphql] {url}", "green", colour)
                         + f"  ({len(gql.query_fields)} query, {len(gql.mutation_fields)} mutation, via {gql.source})")
        else:
            result = finding.result
            lines.append(_paint(f"[oracle]  {url}", "green", colour)
                         + f"  (dialect {result.dialect}, {_count_fields(result.schema.root)} fields)")
            for lead in finding.leads[:5]:
                tag = _paint(f"{lead.category}", "red", colour)
                lines.append(f"    - {tag}: {lead.path}")
    return "\n".join(lines)


def graphql_report(res, colour: bool = True) -> str:
    if not res.is_graphql:
        return _paint("not a graphql endpoint.", "dim", colour)
    head = f"graphql schema  (source: {res.source}, {res.requests_sent} requests)"
    lines = [_paint(head, "bold", colour)]
    if res.introspection_open:
        lines.append(_paint("  introspection is ENABLED (schema fully readable)", "red", colour))
    if res.root_query:
        lines.append(f"  query root: {res.root_query}")
    if res.root_mutation:
        lines.append(f"  mutation root: {res.root_mutation}")

    notable = []
    for label, fields in (("query", res.query_fields), ("mutation", res.mutation_fields)):
        if not fields:
            continue
        lines.append(_paint(f"{label} fields  ({len(fields)})", "bold", colour))
        for gf in sorted(fields, key=lambda f: f.name):
            args = ", ".join(f"{a}: {t}" for a, t in gf.args)
            sig = _paint(gf.name, "cyan", colour)
            if args:
                sig += "(" + args + ")"
            if gf.type:
                sig += ": " + _paint(gf.type, "yellow", colour)
            if _notable(gf.name):
                sig += _paint("  <-- worth a look", "green", colour)
                notable.append(f"{label} {gf.name}")
            lines.append("  " + sig)

    if notable:
        lines.append(_paint(f"notable  ({len(notable)})", "bold", colour))
        lines.append("  " + ", ".join(notable))
    return "\n".join(lines)


_NOTABLE = ("user", "admin", "account", "order", "payment", "invoice", "billing", "card",
            "token", "secret", "apikey", "api_key", "password", "email", "ssn", "role",
            "permission", "internal", "current", "me", "all", "delete", "update", "create",
            "impersonate", "reset", "grant", "revoke")


def _notable(name: str) -> bool:
    low = name.lower()
    return any(h in low for h in _NOTABLE)


def graphql_json(res) -> str:
    def fields(items):
        return [{"name": f.name, "type": f.type,
                 "args": [{"name": a, "type": t} for a, t in f.args]} for f in items]
    return json.dumps({
        "endpoint": res.endpoint,
        "is_graphql": res.is_graphql,
        "source": res.source,
        "introspection_open": res.introspection_open,
        "root_query": res.root_query,
        "root_mutation": res.root_mutation,
        "query_fields": fields(res.query_fields),
        "mutation_fields": fields(res.mutation_fields),
    }, indent=2)


def leads_block(leads: list[Lead], colour: bool = True) -> str:
    if not leads:
        return _paint("no attack-surface leads matched.", "dim", colour)
    lines = [_paint(f"leads  ({len(leads)})", "bold", colour)]
    for lead in leads:
        mark = _paint("[hidden]", "green", colour) if lead.hidden else "        "
        cat = _paint(f"{lead.category:<11}", "red", colour)
        lines.append(f"  {mark} {cat} {lead.path}")
        lines.append(f"           {_paint(lead.reason, 'dim', colour)}")
    return "\n".join(lines)


def confirmations_block(confirmations, read_endpoint, colour: bool = True) -> str:
    if not confirmations:
        note = "no mass-assignment confirmed"
        if read_endpoint:
            note += f" (read-back via {read_endpoint})"
        else:
            note += " (no read-back endpoint found; pass --read URL)"
        return _paint(note + ".", "dim", colour)

    lines = [_paint(f"CONFIRMED mass-assignment  ({len(confirmations)})", "bold", colour)]
    for c in confirmations:
        lines.append("  " + _paint(f"{c.path} = {c.value!r}", "red", colour)
                     + f"  set via the request and it persisted in {c.read_url}")
    return "\n".join(lines)


def skeleton(result: Result) -> dict[str, Any]:
    return mutate.build_object(result.schema.root, sentinel=None, valid=True)


def leaks_block(result: Result, colour: bool = True) -> str:
    if not result.leaks:
        return ""
    lines = [_paint(f"leaked internals  ({len(result.leaks)})", "bold", colour)]
    for item in result.leaks:
        lines.append("  " + item[:200])
    return "\n".join(lines)


_POC_VALUES = {
    "idor": "REPLACE_WITH_VICTIM_ID",
    "mass-assign": True,
    "money": -1,
    "ssrf": "http://169.254.169.254/latest/meta-data/",
    "traversal": "../../../../etc/passwd",
}


def _poc_value(lead: Lead, result: Result):
    if lead.category == "privesc":
        node = result.schema.node_at(lead.path.split("."))
        if node.enum:
            for pick in ("admin", "superuser", "root", "staff"):
                if pick in node.enum:
                    return pick
            return node.enum[-1]
        return True
    return _POC_VALUES.get(lead.category, True)


def poc_block(req, result: Result, leads: list[Lead], colour: bool = True) -> str:
    if not leads:
        return ""
    lines = [_paint("poc requests", "bold", colour)]
    for lead in leads:
        body = skeleton(result)
        cursor = body
        parts = lead.path.split(".")
        for part in parts[:-1]:
            cursor = cursor.setdefault(part, {})
        cursor[parts[-1]] = _poc_value(lead, result)
        lines.append(_paint(f"# {lead.category}: {lead.path}", "dim", colour))
        lines.append(_curl(req, body))
    return "\n".join(lines)


def _curl(req, body: dict) -> str:
    skip = {"content-length", "host", "content-type"}
    parts = [f"curl -X {req.method} '{req.url}'", "-H 'content-type: application/json'"]
    for key, value in req.headers.items():
        if key.lower() not in skip:
            parts.append(f"-H '{key}: {value}'")
    parts.append("-d '" + json.dumps(body) + "'")
    return " \\\n  ".join(parts)


def signals_block(signals, colour: bool = True) -> str:
    if not signals:
        return _paint("no active signals (nothing accepted an injected value).", "dim", colour)
    lines = [_paint(f"active signals  ({len(signals)})", "bold", colour)]
    colours = {"injection": "red", "reflection": "red", "mass-assign": "yellow"}
    for sig in signals:
        tag = _paint(f"[{sig.kind}]", colours.get(sig.kind, "yellow"), colour)
        lines.append(f"  {tag} {sig.path}  (HTTP {sig.status})")
        lines.append(f"           {_paint(sig.detail, 'dim', colour)}")
    return "\n".join(lines)


def as_json(result: Result, leads: list[Lead], signals=None, confirmations=None) -> str:
    def node_dict(node: Field) -> dict:
        entry: dict[str, Any] = {"type": node.type or "unknown"}
        if node.required:
            entry["required"] = True
        if node.hidden:
            entry["hidden"] = True
        if node.enum:
            entry["enum"] = node.enum
        if node.constraints:
            entry["constraints"] = node.constraints
        if node.confidence:
            entry["confidence"] = node.confidence
        if node.children:
            entry["fields"] = {n: node_dict(c) for n, c in node.children.items()}
        return entry

    payload = {
        "dialect": result.dialect,
        "requests_sent": result.requests_sent,
        "static": result.static,
        "schema": {n: node_dict(c) for n, c in result.schema.root.children.items()},
        "valid_request": skeleton(result),
        "leads": [
            {"path": l.path, "category": l.category, "hidden": l.hidden,
             "type": l.field_type, "reason": l.reason}
            for l in leads
        ],
        "leaked_internals": result.leaks,
    }
    if signals is not None:
        payload["signals"] = [
            {"kind": s.kind, "path": s.path, "detail": s.detail, "status": s.status}
            for s in signals
        ]
    if confirmations is not None:
        payload["confirmed_mass_assignment"] = [
            {"path": c.path, "value": c.value, "read_url": c.read_url}
            for c in confirmations
        ]
    return json.dumps(payload, indent=2)


def as_proto(result: Result, message: str = "Recovered") -> str:
    proto = {
        "string": "string", "int": "int64", "float": "double", "bool": "bool",
        "uuid": "string", "datetime": "string", "date": "string",
        "email": "string", "url": "string", "array": "repeated string",
        "enum": "string", None: "string", "unknown": "string",
    }
    lines: list[str] = ['syntax = "proto3";', ""]

    def emit(node: Field, name: str, indent: str) -> None:
        lines.append(f"{indent}message {name} {{")
        inner = indent + "  "
        for child in node.children.values():
            if child.type == "object" and child.children:
                emit(child, child.name.capitalize(), inner)
        for index, child in enumerate(node.children.values(), start=1):
            if child.type == "object" and child.children:
                line = f"{inner}{child.name.capitalize()} {child.name} = {index};"
            else:
                line = f"{inner}{proto.get(child.type, 'string')} {child.name} = {index};"
            if child.enum:
                line += "  // enum: " + ", ".join(child.enum)
            lines.append(line)
        lines.append(f"{indent}}}")

    emit(result.schema.root, message, "")
    return "\n".join(lines)
