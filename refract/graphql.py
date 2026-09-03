from __future__ import annotations

import re
from dataclasses import dataclass, field

from .client import Client, Request

_ON_TYPE = re.compile(r'on type ["\']([A-Za-z_][A-Za-z0-9_]*)["\']')
_SUGGEST = re.compile(r"Did you mean (.+?)\?")
_QUOTED = re.compile(r"['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]")
_ARG_REQ = re.compile(r'argument ["\']([A-Za-z0-9_]+)["\'] of type ["\']([^"\']+)["\']')
_FIELD_TYPE = re.compile(r'Field ["\'][A-Za-z0-9_]+["\'] of type ["\']([^"\']+)["\']')

_WORDLIST = [
    "user", "users", "me", "viewer", "currentUser", "account", "accounts", "node", "nodes",
    "search", "order", "orders", "product", "products", "post", "posts", "comment", "comments",
    "profile", "profiles", "organization", "organizations", "team", "teams", "project", "projects",
    "customer", "customers", "invoice", "invoices", "payment", "payments", "subscription",
    "settings", "config", "session", "token", "role", "roles", "permission", "permissions",
    "file", "files", "image", "images", "message", "messages", "notification", "notifications",
    "cart", "checkout", "address", "addresses", "company", "companies", "employee", "employees",
    "question", "questions", "answer", "answers", "tag", "tags", "category", "categories",
]

_MUTATION_WORDS = [
    "login", "logout", "signIn", "signUp", "register", "authenticate", "refreshToken",
    "createUser", "updateUser", "deleteUser", "updateProfile", "updateAccount", "changePassword",
    "resetPassword", "forgotPassword", "createProject", "updateProject", "deleteProject",
    "createOrder", "updateOrder", "cancelOrder", "createComment", "deleteComment",
    "uploadFile", "inviteUser", "removeUser", "updateSettings", "createPoint", "updatePoint",
    "createFolder", "updateFolder", "createList", "updateList", "createRoom",
]


@dataclass
class GQLField:
    name: str
    type: str | None = None
    args: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class GQLResult:
    endpoint: str
    is_graphql: bool
    source: str
    root_query: str | None = None
    root_mutation: str | None = None
    query_fields: list[GQLField] = field(default_factory=list)
    mutation_fields: list[GQLField] = field(default_factory=list)
    requests_sent: int = 0
    introspection_open: bool = False


def looks_like_graphql(req: Request) -> bool:
    url = req.url.lower()
    if "graphql" in url or url.rstrip("/").endswith("/query"):
        return True
    body = req.body.lower()
    return '"query"' in body and ("{" in body)


def recover(client: Client, req: Request, budget: int = 160) -> GQLResult:
    res = GQLResult(endpoint=req.url, is_graphql=False, source="none")

    probe = _errors(client.gql(req, "{ __typename }"))
    res.requests_sent += 1
    hello = client.gql(req, "{ zqzq_refract }")
    res.requests_sent += 1
    errs = _errors(hello)
    if probe is None and errs is None:
        return res
    res.is_graphql = True

    root = _root_type(errs) or "Query"
    res.root_query = root
    mut = _errors(client.gql(req, "mutation { zqzq_refract }"))
    res.requests_sent += 1
    res.root_mutation = _root_type(mut)

    # try introspection first and otherwise rebuild the schema from the error messages
    schema = _introspect(client, req)
    res.requests_sent += 1
    if schema:
        res.source = "introspection"
        res.introspection_open = True
        res.query_fields = _fields_of(schema, res.root_query)
        res.mutation_fields = _fields_of(schema, res.root_mutation)
        return res

    res.source = "error-mining"
    res.query_fields = _mine(client, req, root, res, budget, "query")
    if res.root_mutation:
        res.mutation_fields = _mine(client, req, res.root_mutation, res, budget, "mutation")
    return res


def _introspect(client: Client, req: Request):
    query = (
        "query{__schema{queryType{name}mutationType{name}"
        "types{name kind fields{name "
        "args{name type{kind name ofType{kind name ofType{kind name ofType{kind name}}}}} "
        "type{kind name ofType{kind name ofType{kind name ofType{kind name}}}}}}}}"
    )
    data = _data(client.gql(req, query))
    if isinstance(data, dict) and isinstance(data.get("__schema"), dict):
        return data["__schema"]
    return None


def _fields_of(schema: dict, type_name: str | None) -> list[GQLField]:
    if not type_name:
        return []
    for t in schema.get("types", []):
        if t.get("name") == type_name and t.get("fields"):
            out = []
            for f in t["fields"]:
                gf = GQLField(f["name"], _typeref(f.get("type")))
                for a in f.get("args") or []:
                    gf.args.append((a["name"], _typeref(a.get("type"))))
                out.append(gf)
            return out
    return []


def _typeref(ref) -> str | None:
    if not isinstance(ref, dict):
        return None
    kind = ref.get("kind")
    if kind == "NON_NULL":
        inner = _typeref(ref.get("ofType"))
        return f"{inner}!" if inner else None
    if kind == "LIST":
        inner = _typeref(ref.get("ofType"))
        return f"[{inner}]" if inner else None
    return ref.get("name")


def _mine(client: Client, req: Request, root: str, res: GQLResult,
          budget: int, operation: str) -> list[GQLField]:
    found: dict[str, GQLField] = {}
    tried: set[str] = set()
    queue = list(_WORDLIST) + list(_MUTATION_WORDS) if operation == "mutation" else list(_WORDLIST)

    while queue and res.requests_sent < budget:
        cand = queue.pop(0)
        if cand in tried:
            continue
        tried.add(cand)
        msg = _messages(client.gql(req, "%s { %s }" % (operation, cand)))
        res.requests_sent += 1

        for suggestion in _SUGGEST.findall(msg):
            for name in _QUOTED.findall(suggestion):
                if name not in found and name not in tried:
                    queue.append(name)
                found.setdefault(name, GQLField(name))

        if f'field "{cand}"' not in msg.lower() and f"field '{cand}'" not in msg.lower():
            found.setdefault(cand, GQLField(cand))

    for name, gf in list(found.items()):
        if res.requests_sent >= budget:
            break
        _describe_field(client, req, gf, operation)
        res.requests_sent += 1
    return list(found.values())


def _describe_field(client: Client, req: Request, gf: GQLField, operation: str) -> None:
    msg = _messages(client.gql(req, "%s { %s }" % (operation, gf.name)))
    for arg, atype in _ARG_REQ.findall(msg):
        if (arg, atype) not in gf.args:
            gf.args.append((arg, atype))
    hit = _FIELD_TYPE.search(msg)
    if hit:
        gf.type = hit.group(1)


def _root_type(errs) -> str | None:
    if not errs:
        return None
    for e in errs:
        m = _ON_TYPE.search(e.get("message", ""))
        if m:
            return m.group(1)
    return None


def _json(resp):
    try:
        return resp.json()
    except Exception:
        return None


def _data(resp):
    body = _json(resp)
    return body.get("data") if isinstance(body, dict) else None


def _errors(resp):
    body = _json(resp)
    if isinstance(body, dict) and isinstance(body.get("errors"), list):
        return body["errors"]
    return None


def _messages(resp) -> str:
    errs = _errors(resp) or []
    return " ".join(str(e.get("message", "")) for e in errs)
