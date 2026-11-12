"""Thin wrapper around toon-format for artifact serialisation."""

from __future__ import annotations

from typing import Any

from toons import dumps as _dumps
from toons import loads as _loads


def dumps(obj: Any) -> str:
    return _dumps(obj)


def loads(s: str) -> Any:
    return _loads(s)
