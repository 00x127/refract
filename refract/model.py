from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Finding:
    path: list[str]
    type: str | None = None
    required: bool = False
    enum: list[str] | None = None
    constraints: dict[str, Any] = field(default_factory=dict)
    confidence: int = 0
    exists: bool = False
    message: str = ""


@dataclass
class Field:
    name: str
    type: str | None = None
    required: bool = False
    enum: list[str] | None = None
    constraints: dict[str, Any] = field(default_factory=dict)
    confidence: int = 0
    seen_in_client: bool = False
    type_guessed: bool = False
    children: dict[str, "Field"] = field(default_factory=dict)

    @property
    def hidden(self) -> bool:
        return not self.seen_in_client

    def child(self, name: str) -> "Field":
        if name not in self.children:
            self.children[name] = Field(name=name)
        return self.children[name]


class Schema:
    def __init__(self) -> None:
        self.root = Field(name="")

    def node_at(self, path: list[str]) -> Field:
        node = self.root
        for part in path:
            node = node.child(part)
        return node

    def apply(self, finding: Finding) -> bool:
        if not finding.path:
            return False
        if not (finding.type or finding.required or finding.enum
                or finding.constraints or finding.exists):
            return False
        node = self.node_at(finding.path)
        changed = node.confidence == 0 and finding.exists

        if finding.required and not node.required:
            node.required = True
            changed = True

        if finding.type and finding.type != node.type:
            # keep the more specific answer and never drop a known type back to unknown
            if node.type in (None, "unknown") or finding.confidence >= node.confidence:
                node.type = finding.type
                changed = True

        if finding.enum and node.enum != finding.enum:
            node.enum = finding.enum
            changed = True

        for key, value in finding.constraints.items():
            if node.constraints.get(key) != value:
                node.constraints[key] = value
                changed = True

        node.confidence = max(node.confidence, finding.confidence)
        return changed

    def seed_client_field(self, path: list[str], type_hint: str | None) -> None:
        node = self.node_at(path)
        node.seen_in_client = True
        if type_hint and not node.type:
            node.type = type_hint
