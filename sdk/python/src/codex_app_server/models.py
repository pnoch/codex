from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | dict[str, "JsonValue"] | list["JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]


@dataclass(slots=True)
class Notification:
    method: str
    params: JsonObject | object | None


@dataclass(slots=True)
class RequestMessage:
    id: str | int
    method: str
    params: JsonObject | None


@dataclass(slots=True)
class ResponseMessage:
    id: str | int
    result: object


@dataclass(slots=True)
class AskResult:
    """High-level notebook-friendly response bundle for text turns."""

    thread_id: str
    text: str
    completed: Notification
