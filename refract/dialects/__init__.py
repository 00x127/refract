from __future__ import annotations

import httpx

from .aspnet import AspNet
from .base import Dialect
from .drf import DRF
from .generic import Generic
from .golang import Golang
from .jackson import Jackson
from .laravel import Laravel
from .node import Node
from .pydantic import Pydantic
from .rails import Rails

# order matters so a specific dialect gets first pick and generic stays the fallback
REGISTRY: list[Dialect] = [
    Pydantic(),
    Jackson(),
    AspNet(),
    Laravel(),
    Node(),
    Golang(),
    DRF(),
    Rails(),
    Generic(),
]


def detect(resp: httpx.Response) -> Dialect:
    for dialect in REGISTRY:
        if dialect.matches(resp):
            return dialect
    return REGISTRY[-1]
