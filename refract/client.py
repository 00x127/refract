from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

DEFAULT_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def _with_ua(headers: dict) -> dict:
    if not any(k.lower() == "user-agent" for k in headers):
        headers["User-Agent"] = DEFAULT_UA
    return headers


@dataclass
class Request:
    method: str
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    body: str = ""

    def json_body(self) -> Any | None:
        if not self.body.strip():
            return None
        try:
            return json.loads(self.body)
        except json.JSONDecodeError:
            return None


class Client:
    def __init__(self, proxy: str | None = None, insecure: bool = False,
                 timeout: float = 20.0, delay: float = 0.0):
        self.delay = delay
        self._client = httpx.Client(
            proxy=proxy,
            verify=not insecure,
            timeout=timeout,
            follow_redirects=True,
        )

    def send(self, req: Request, body: Any, encoding: str = "json") -> httpx.Response:
        headers = _with_ua(dict(req.headers))
        headers.pop("content-length", None)
        method = req.method

        if encoding == "form":
            headers["content-type"] = "application/x-www-form-urlencoded"
            kwargs = {"data": _flatten_form(body)}
        elif encoding == "query":
            headers.pop("content-type", None)
            kwargs = {"params": _flatten_form(body)}
            method = "GET"
        else:
            headers["content-type"] = "application/json"
            kwargs = {"content": json.dumps(body)}

        if self.delay:
            time.sleep(self.delay)
        return self._client.request(method, req.url, headers=headers, **kwargs)

    def send_json(self, req: Request, body: Any) -> httpx.Response:
        return self.send(req, body, encoding="json")

    def raw(self, method: str, url: str, headers: dict, content: str) -> httpx.Response:
        if self.delay:
            time.sleep(self.delay)
        return self._client.request(method, url, headers=headers, content=content)

    def gql(self, req: Request, query: str, variables: dict | None = None) -> httpx.Response:
        headers = _with_ua(dict(req.headers))
        headers["content-type"] = "application/json"
        headers.pop("content-length", None)
        payload: dict[str, Any] = {"query": query}
        if variables is not None:
            payload["variables"] = variables
        if self.delay:
            time.sleep(self.delay)
        return self._client.request("POST", req.url, headers=headers, content=json.dumps(payload))

    def get(self, url: str, headers: dict | None = None) -> httpx.Response:
        if self.delay:
            time.sleep(self.delay)
        return self._client.get(url, headers=_with_ua(dict(headers or {})))

    def close(self) -> None:
        self._client.close()


def _flatten_form(body: Any) -> dict[str, str]:
    out: dict[str, str] = {}

    def walk(prefix: str, node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                walk(f"{prefix}[{key}]" if prefix else key, value)
        elif isinstance(node, list):
            out[prefix] = ",".join(str(v) for v in node)
        else:
            out[prefix] = str(node)

    walk("", body)
    return out


def from_raw(path: str, scheme: str = "https") -> Request:
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        raw = handle.read()

    head, _, body = raw.replace("\r\n", "\n").partition("\n\n")
    lines = head.split("\n")
    method, target, *_ = lines[0].split(" ")

    headers: dict[str, str] = {}
    for line in lines[1:]:
        if ":" in line:
            key, _, value = line.partition(":")
            headers[key.strip()] = value.strip()

    host = headers.get("Host") or headers.get("host", "")
    if target.startswith(("http://", "https://")):
        url = target
    else:
        url = f"{scheme}://{host}{target}"
    return Request(method=method.upper(), url=url, headers=headers, body=body)


def from_args(url: str, method: str, header: list[str], data: str | None) -> Request:
    headers: dict[str, str] = {}
    for item in header or []:
        key, _, value = item.partition(":")
        headers[key.strip()] = value.strip()
    return Request(method=method.upper(), url=url, headers=headers, body=data or "")
