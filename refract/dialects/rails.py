from __future__ import annotations

import httpx

from ..model import Finding
from .base import Dialect, json_body, type_from_message


class Rails(Dialect):
    name = "rails"
    confidence = 65

    def matches(self, resp: httpx.Response) -> bool:
        data = json_body(resp)
        if not isinstance(data, dict):
            return False
        errors = data.get("errors")
        if isinstance(errors, dict) and errors:
            return all(isinstance(v, list) for v in errors.values())
        return False

    def parse(self, resp: httpx.Response) -> list[Finding]:
        data = json_body(resp)
        out: list[Finding] = []
        for field, messages in data.get("errors", {}).items():
            msg = " ".join(str(m) for m in messages)
            finding = Finding(path=[field], exists=True, confidence=self.confidence, message=msg)
            low = msg.lower()
            if "can't be blank" in low or "is required" in low or "must exist" in low:
                finding.required = True
            finding.type = finding.type or type_from_message(msg)
            out.append(finding)
        return out
