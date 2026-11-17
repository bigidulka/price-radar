from __future__ import annotations

from typing import Protocol

from ..models import Offer


class ProviderError(Exception):
    """A source could not return a price (blocked, removed, changed markup)."""


class Provider(Protocol):
    name: str

    async def fetch(self, url: str) -> Offer:  # pragma: no cover - protocol
        ...
