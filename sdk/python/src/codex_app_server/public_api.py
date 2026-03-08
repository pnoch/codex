from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator

from .client import AppServerClient, AppServerConfig
from .generated.v2_all.AgentMessageDeltaNotification import AgentMessageDeltaNotification
from .generated.v2_all.ThreadArchiveResponse import ThreadArchiveResponse
from .generated.v2_all.ThreadSetNameResponse import ThreadSetNameResponse
from .generated.v2_all.TurnCompletedNotification import TurnError
from .generated.v2_all.TurnInterruptResponse import TurnInterruptResponse
from .generated.v2_types import (
    ModelListResponse,
    ThreadCompactStartResponse,
    ThreadItem,
    ThreadListResponse,
    ThreadReadResponse,
    ThreadTokenUsageUpdatedNotification,
    TurnCompletedNotificationPayload,
    TurnSteerResponse,
)
from .models import InitializeResponse, JsonObject, Notification
from .public_types import (
    ThreadForkParams,
    ThreadListParams,
    ThreadResumeParams,
    ThreadStartParams,
    TurnStartParams,
    TurnStatus,
)


@dataclass(slots=True)
class TurnResult:
    thread_id: str
    turn_id: str
    status: TurnStatus
    error: TurnError | None
    text: str
    items: list[ThreadItem]
    usage: ThreadTokenUsageUpdatedNotification | None = None


@dataclass(slots=True)
class TextInput:
    text: str


@dataclass(slots=True)
class ImageInput:
    url: str


@dataclass(slots=True)
class LocalImageInput:
    path: str


@dataclass(slots=True)
class SkillInput:
    name: str
    path: str


@dataclass(slots=True)
class MentionInput:
    name: str
    path: str


InputItem = TextInput | ImageInput | LocalImageInput | SkillInput | MentionInput
Input = list[InputItem] | InputItem


@dataclass(slots=True)
class InitializeResult:
    server_name: str | None = None
    server_version: str | None = None


def _to_wire_item(item: InputItem) -> JsonObject:
    if isinstance(item, TextInput):
        return {"type": "text", "text": item.text}
    if isinstance(item, ImageInput):
        return {"type": "image", "url": item.url}
    if isinstance(item, LocalImageInput):
        return {"type": "localImage", "path": item.path}
    if isinstance(item, SkillInput):
        return {"type": "skill", "name": item.name, "path": item.path}
    if isinstance(item, MentionInput):
        return {"type": "mention", "name": item.name, "path": item.path}
    raise TypeError(f"unsupported input item: {type(item)!r}")


def _to_wire_input(input: Input) -> list[JsonObject]:
    if isinstance(input, list):
        return [_to_wire_item(i) for i in input]
    return [_to_wire_item(input)]


class Codex:
    """Minimal typed SDK surface for app-server v2."""

    def __init__(self, config: AppServerConfig | None = None) -> None:
        self._client = AppServerClient(config=config)
        self._client.start()
        self._init = self._parse_initialize(self._client.initialize())

    def __enter__(self) -> "Codex":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    @staticmethod
    def _parse_initialize(payload: InitializeResponse) -> InitializeResult:
        server = payload.serverInfo
        if server is None:
            return InitializeResult()
        return InitializeResult(
            server_name=server.name,
            server_version=server.version,
        )

    @property
    def metadata(self) -> InitializeResult:
        return self._init

    def close(self) -> None:
        self._client.close()

    def thread_start(self, params: ThreadStartParams) -> Thread:
        started = self._client.thread_start(params)
        return Thread(self._client, started.thread.id)

    def thread(self, thread_id: str) -> Thread:
        return Thread(self._client, thread_id)

    def thread_list(self, params: ThreadListParams | None = None) -> ThreadListResponse:
        return self._client.thread_list(params)

    def models(self, *, include_hidden: bool = False) -> ModelListResponse:
        return self._client.model_list(include_hidden=include_hidden)


@dataclass(slots=True)
class Thread:
    _client: AppServerClient
    id: str

    def turn(
        self,
        input: Input,
        *,
        params: TurnStartParams | JsonObject | None = None,
    ) -> Turn:
        turn = self._client.turn_start(self.id, _to_wire_input(input), params=params)
        return Turn(self._client, self.id, turn.turn.id)

    def resume(self, params: ThreadResumeParams) -> Thread:
        resumed = self._client.thread_resume(self.id, params)
        return Thread(self._client, resumed.thread.id)

    def read(self, *, include_turns: bool = False) -> ThreadReadResponse:
        return self._client.thread_read(self.id, include_turns=include_turns)

    def fork(self, params: ThreadForkParams) -> Thread:
        forked = self._client.thread_fork(self.id, params)
        return Thread(self._client, forked.thread.id)

    def archive(self) -> ThreadArchiveResponse:
        return self._client.thread_archive(self.id)

    def unarchive(self) -> Thread:
        unarchived = self._client.thread_unarchive(self.id)
        return Thread(self._client, unarchived.thread.id)

    def set_name(self, name: str) -> ThreadSetNameResponse:
        return self._client.thread_set_name(self.id, name)

    def compact(self) -> ThreadCompactStartResponse:
        return self._client.thread_compact(self.id)


@dataclass(slots=True)
class Turn:
    _client: AppServerClient
    thread_id: str
    id: str

    def steer(self, input: Input) -> TurnSteerResponse:
        return self._client.turn_steer(self.thread_id, self.id, _to_wire_input(input))

    def interrupt(self) -> TurnInterruptResponse:
        return self._client.turn_interrupt(self.thread_id, self.id)

    def stream(self) -> Iterator[Notification]:
        while True:
            event = self._client.next_notification()
            yield event
            if (
                event.method == "turn/completed"
                and isinstance(event.payload, TurnCompletedNotificationPayload)
                and event.payload.turn.id == self.id
            ):
                break

    def run(self) -> TurnResult:
        completed: TurnCompletedNotificationPayload | None = None
        usage: ThreadTokenUsageUpdatedNotification | None = None
        chunks: list[str] = []

        for event in self.stream():
            payload = event.payload
            if (
                isinstance(payload, AgentMessageDeltaNotification)
                and payload.turnId == self.id
            ):
                chunks.append(payload.delta)
                continue
            if (
                isinstance(payload, ThreadTokenUsageUpdatedNotification)
                and payload.turnId == self.id
            ):
                usage = payload
                continue
            if (
                isinstance(payload, TurnCompletedNotificationPayload)
                and payload.turn.id == self.id
            ):
                completed = payload

        if completed is None:
            raise RuntimeError("turn completed event not received")

        return TurnResult(
            thread_id=completed.threadId,
            turn_id=completed.turn.id,
            status=completed.turn.status,
            error=completed.turn.error,
            text="".join(chunks),
            items=list(completed.turn.items or []),
            usage=usage,
        )
