from __future__ import annotations

import httpx

from ..model import Finding
from .base import Dialect, json_body, type_from_message


class Laravel(Dialect):
    name = "laravel"
    confidence = 85

    def matches(self, resp: httpx.Response) -> bool:
        data = json_body(resp)
        return (
            isinstance(data, dict)
            and "message" in data
            and isinstance(data.get("errors"), dict)
            and bool(data["errors"])
        )

    def parse(self, resp: httpx.Response) -> list[Finding]:
        data = json_body(resp)
        out: list[Finding] = []
        for field, messages in data.get("errors", {}).items():
            msg = " ".join(messages) if isinstance(messages, list) else str(messages)
            finding = Finding(path=field.split("."), exists=True,
                              confidence=self.confidence, message=msg)
            low = msg.lower()
            if "must be one of" in low or "invalid" in low and "selected" in low:
                finding.type = "enum"
            else:
                finding.type = type_from_message(msg)
            if "required" in low or "must be present" in low:
                finding.required = True
            out.append(finding)
        return out
