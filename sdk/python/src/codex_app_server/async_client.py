from __future__ import annotations

import asyncio
from typing import Iterable

from .client import AppServerClient, AppServerConfig
from .conversation import AsyncThreadSession
from .generated.protocol_types import (
    ThreadListResponse,
    ThreadReadResponse,
    ThreadResumeResponse,
    ThreadStartResponse,
    TurnStartResponse,
)
from .generated.schema_types import (
    AgentMessageDeltaNotificationPayload as SchemaAgentMessageDeltaNotificationPayload,
)
from .generated.schema_types import (
    ErrorNotificationPayload as SchemaErrorNotificationPayload,
)
from .generated.schema_types import (
    ItemCompletedNotificationPayload as SchemaItemCompletedNotificationPayload,
)
from .generated.schema_types import (
    ItemStartedNotificationPayload as SchemaItemStartedNotificationPayload,
)
from .generated.schema_types import ModelListResponse as SchemaModelListResponse
from .generated.schema_types import ThreadArchiveResponse as SchemaThreadArchiveResponse
from .generated.schema_types import ThreadForkResponse as SchemaThreadForkResponse
from .generated.schema_types import ThreadListResponse as SchemaThreadListResponse
from .generated.schema_types import (
    ThreadNameUpdatedNotificationPayload as SchemaThreadNameUpdatedNotificationPayload,
)
from .generated.schema_types import ThreadReadResponse as SchemaThreadReadResponse
from .generated.schema_types import ThreadResumeResponse as SchemaThreadResumeResponse
from .generated.schema_types import ThreadSetNameResponse as SchemaThreadSetNameResponse
from .generated.schema_types import (
    ThreadStartedNotificationPayload as SchemaThreadStartedNotificationPayload,
)
from .generated.schema_types import ThreadStartResponse as SchemaThreadStartResponse
from .generated.schema_types import (
    ThreadTokenUsageUpdatedNotificationPayload as SchemaThreadTokenUsageUpdatedNotificationPayload,
)
from .generated.schema_types import (
    ThreadUnarchiveResponse as SchemaThreadUnarchiveResponse,
)
from .generated.schema_types import (
    TurnCompletedNotificationPayload as SchemaTurnCompletedNotificationPayload,
)
from .generated.schema_types import (
    TurnStartedNotificationPayload as SchemaTurnStartedNotificationPayload,
)
from .generated.schema_types import TurnStartResponse as SchemaTurnStartResponse
from .generated.schema_types import TurnSteerResponse as SchemaTurnSteerResponse
from .generated.v2_all.ThreadForkParams import ThreadForkParams as V2ThreadForkParams
from .generated.v2_all.ThreadListParams import ThreadListParams as V2ThreadListParams
from .generated.v2_all.ThreadResumeParams import ThreadResumeParams as V2ThreadResumeParams
from .generated.v2_all.ThreadStartParams import ThreadStartParams as V2ThreadStartParams
from .generated.v2_all.TurnStartParams import TurnStartParams as V2TurnStartParams
from .models import AskResult, JsonObject, Notification
from .typed import (
    AgentMessageDeltaEvent,
    EmptyResult,
    ErrorEvent,
    ItemLifecycleEvent,
    ModelListResult,
    ThreadForkResult,
    ThreadListResult,
    ThreadNameUpdatedEvent,
    ThreadReadResult,
    ThreadResumeResult,
    ThreadStartedEvent,
    ThreadStartResult,
    ThreadTokenUsageUpdatedEvent,
    TurnCompletedEvent,
    TurnStartedEvent,
    TurnStartResult,
    TurnSteerResult,
)


class AsyncAppServerClient:
    """Async wrapper around AppServerClient using thread offloading."""

    def __init__(self, config: AppServerConfig | None = None):
        self._sync = AppServerClient(config=config)

    async def __aenter__(self) -> "AsyncAppServerClient":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def _call_sync(self, fn, /, *args, **kwargs):
        return await asyncio.to_thread(fn, *args, **kwargs)

    async def start(self) -> None:
        await self._call_sync(self._sync.start)

    async def close(self) -> None:
        await self._call_sync(self._sync.close)

    async def initialize(self) -> JsonObject:
        return await self._call_sync(self._sync.initialize)

    async def thread_start(self, params: V2ThreadStartParams | JsonObject | None = None, **legacy_params: object) -> ThreadStartResponse:
        return await self._call_sync(self._sync.thread_start, params, **legacy_params)

    async def thread_resume(
        self, thread_id: str, params: V2ThreadResumeParams | JsonObject | None = None, **legacy_params: object
    ) -> ThreadResumeResponse:
        return await self._call_sync(self._sync.thread_resume, thread_id, params, **legacy_params)

    async def thread_list(self, params: V2ThreadListParams | JsonObject | None = None, **legacy_params: object) -> ThreadListResponse:
        return await self._call_sync(self._sync.thread_list, params, **legacy_params)

    async def thread_read(
        self, thread_id: str, include_turns: bool = False
    ) -> ThreadReadResponse:
        return await self._call_sync(self._sync.thread_read, thread_id, include_turns)

    async def thread_fork(self, thread_id: str, params: V2ThreadForkParams | JsonObject | None = None) -> JsonObject:
        return await self._call_sync(self._sync.thread_fork, thread_id, params)

    async def thread_archive(self, thread_id: str) -> JsonObject:
        return await self._call_sync(self._sync.thread_archive, thread_id)

    async def thread_unarchive(self, thread_id: str) -> JsonObject:
        return await self._call_sync(self._sync.thread_unarchive, thread_id)

    async def thread_set_name(self, thread_id: str, name: str) -> JsonObject:
        return await self._call_sync(self._sync.thread_set_name, thread_id, name)

    async def turn_start(
        self,
        thread_id: str,
        input_items: list[JsonObject] | JsonObject | str,
        params: V2TurnStartParams | JsonObject | None = None,
        **legacy_params: object,
    ) -> TurnStartResponse:
        return await self._call_sync(
            self._sync.turn_start, thread_id, input_items, params, **legacy_params
        )

    async def turn_text(
        self, thread_id: str, text: str, params: V2TurnStartParams | JsonObject | None = None, **legacy_params: object
    ) -> TurnStartResponse:
        return await self._call_sync(self._sync.turn_text, thread_id, text, params, **legacy_params)

    async def turn_interrupt(self, thread_id: str, turn_id: str) -> JsonObject:
        return await self._call_sync(self._sync.turn_interrupt, thread_id, turn_id)

    async def turn_steer(
        self,
        thread_id: str,
        expected_turn_id: str,
        input_items: list[JsonObject] | JsonObject | str,
    ) -> JsonObject:
        return await self._call_sync(
            self._sync.turn_steer, thread_id, expected_turn_id, input_items
        )

    async def model_list(self, include_hidden: bool = False) -> JsonObject:
        return await self._call_sync(self._sync.model_list, include_hidden)

    def thread(self, thread_id: str) -> AsyncThreadSession:
        return AsyncThreadSession(client=self, thread_id=thread_id)

    async def thread_start_session(
        self, *, model: str | None = None, params: V2ThreadStartParams | JsonObject | None = None
    ) -> AsyncThreadSession:
        started = await self.thread_start(params=params if model is None else {**(params or {}), "model": model})
        return AsyncThreadSession(client=self, thread_id=started["thread"]["id"])

    async def thread_start_typed(self, params: V2ThreadStartParams | JsonObject | None = None) -> ThreadStartResult:
        return await self._call_sync(self._sync.thread_start_typed, params)

    async def thread_resume_typed(
        self, thread_id: str, params: V2ThreadResumeParams | JsonObject | None = None
    ) -> ThreadResumeResult:
        return await self._call_sync(
            self._sync.thread_resume_typed, thread_id, params
        )

    async def thread_read_typed(
        self, thread_id: str, include_turns: bool = False
    ) -> ThreadReadResult:
        return await self._call_sync(
            self._sync.thread_read_typed, thread_id, include_turns
        )

    async def thread_fork_typed(
        self, thread_id: str, params: V2ThreadForkParams | JsonObject | None = None
    ) -> ThreadForkResult:
        return await self._call_sync(self._sync.thread_fork_typed, thread_id, params)

    async def thread_archive_typed(self, thread_id: str) -> EmptyResult:
        return await self._call_sync(self._sync.thread_archive_typed, thread_id)

    async def thread_unarchive_typed(self, thread_id: str) -> EmptyResult:
        return await self._call_sync(self._sync.thread_unarchive_typed, thread_id)

    async def thread_set_name_typed(self, thread_id: str, name: str) -> EmptyResult:
        return await self._call_sync(self._sync.thread_set_name_typed, thread_id, name)

    async def thread_list_typed(self, params: V2ThreadListParams | JsonObject | None = None) -> ThreadListResult:
        return await self._call_sync(self._sync.thread_list_typed, params)

    async def model_list_typed(self, include_hidden: bool = False) -> ModelListResult:
        return await self._call_sync(self._sync.model_list_typed, include_hidden)

    async def turn_start_typed(
        self,
        thread_id: str,
        input_items: list[JsonObject] | JsonObject | str,
        params: V2TurnStartParams | JsonObject | None = None,
    ) -> TurnStartResult:
        return await self._call_sync(
            self._sync.turn_start_typed, thread_id, input_items, params
        )

    async def turn_text_typed(
        self, thread_id: str, text: str, params: V2TurnStartParams | JsonObject | None = None
    ) -> TurnStartResult:
        return await self._call_sync(
            self._sync.turn_text_typed, thread_id, text, params
        )

    async def turn_steer_typed(
        self,
        thread_id: str,
        expected_turn_id: str,
        input_items: list[JsonObject] | JsonObject | str,
    ) -> TurnSteerResult:
        return await self._call_sync(
            self._sync.turn_steer_typed, thread_id, expected_turn_id, input_items
        )

    async def thread_start_schema(self, params: V2ThreadStartParams | JsonObject | None = None) -> SchemaThreadStartResponse:
        return await self._call_sync(self._sync.thread_start_schema, params)

    async def thread_resume_schema(
        self, thread_id: str, params: V2ThreadResumeParams | JsonObject | None = None
    ) -> SchemaThreadResumeResponse:
        return await self._call_sync(
            self._sync.thread_resume_schema, thread_id, params
        )

    async def thread_read_schema(
        self, thread_id: str, include_turns: bool = False
    ) -> SchemaThreadReadResponse:
        return await self._call_sync(
            self._sync.thread_read_schema, thread_id, include_turns
        )

    async def thread_list_schema(self, params: V2ThreadListParams | JsonObject | None = None) -> SchemaThreadListResponse:
        return await self._call_sync(self._sync.thread_list_schema, params)

    async def thread_fork_schema(
        self, thread_id: str, params: V2ThreadForkParams | JsonObject | None = None
    ) -> SchemaThreadForkResponse:
        return await self._call_sync(self._sync.thread_fork_schema, thread_id, params)

    async def thread_archive_schema(
        self, thread_id: str
    ) -> SchemaThreadArchiveResponse:
        return await self._call_sync(self._sync.thread_archive_schema, thread_id)

    async def thread_unarchive_schema(
        self, thread_id: str
    ) -> SchemaThreadUnarchiveResponse:
        return await self._call_sync(self._sync.thread_unarchive_schema, thread_id)

    async def thread_set_name_schema(
        self, thread_id: str, name: str
    ) -> SchemaThreadSetNameResponse:
        return await self._call_sync(self._sync.thread_set_name_schema, thread_id, name)

    async def model_list_schema(
        self, include_hidden: bool = False
    ) -> SchemaModelListResponse:
        return await self._call_sync(self._sync.model_list_schema, include_hidden)

    async def turn_start_schema(
        self,
        thread_id: str,
        input_items: list[JsonObject] | JsonObject | str,
        params: V2TurnStartParams | JsonObject | None = None,
    ) -> SchemaTurnStartResponse:
        return await self._call_sync(
            self._sync.turn_start_schema, thread_id, input_items, params
        )

    async def turn_text_schema(
        self, thread_id: str, text: str, params: V2TurnStartParams | JsonObject | None = None
    ) -> SchemaTurnStartResponse:
        return await self._call_sync(
            self._sync.turn_text_schema, thread_id, text, params
        )

    async def turn_steer_schema(
        self,
        thread_id: str,
        expected_turn_id: str,
        input_items: list[JsonObject] | JsonObject | str,
    ) -> SchemaTurnSteerResponse:
        return await self._call_sync(
            self._sync.turn_steer_schema, thread_id, expected_turn_id, input_items
        )

    async def parse_notification_typed(
        self, notification: Notification
    ) -> (
        TurnCompletedEvent
        | TurnStartedEvent
        | ThreadStartedEvent
        | AgentMessageDeltaEvent
        | ItemLifecycleEvent
        | ThreadNameUpdatedEvent
        | ThreadTokenUsageUpdatedEvent
        | ErrorEvent
        | None
    ):
        return await self._call_sync(self._sync.parse_notification_typed, notification)

    async def parse_notification_schema(
        self, notification: Notification
    ) -> (
        SchemaTurnCompletedNotificationPayload
        | SchemaTurnStartedNotificationPayload
        | SchemaThreadStartedNotificationPayload
        | SchemaAgentMessageDeltaNotificationPayload
        | SchemaItemStartedNotificationPayload
        | SchemaItemCompletedNotificationPayload
        | SchemaThreadNameUpdatedNotificationPayload
        | SchemaThreadTokenUsageUpdatedNotificationPayload
        | SchemaErrorNotificationPayload
        | None
    ):
        return await self._call_sync(self._sync.parse_notification_schema, notification)

    async def request_with_retry_on_overload(
        self,
        method: str,
        params: JsonObject | None = None,
        *,
        max_attempts: int = 3,
        initial_delay_s: float = 0.25,
        max_delay_s: float = 2.0,
    ) -> object:
        return await self._call_sync(
            self._sync.request_with_retry_on_overload,
            method,
            params,
            max_attempts=max_attempts,
            initial_delay_s=initial_delay_s,
            max_delay_s=max_delay_s,
        )

    async def next_notification(self) -> Notification:
        return await self._call_sync(self._sync.next_notification)

    async def wait_for_turn_completed(self, turn_id: str) -> Notification:
        return await self._call_sync(self._sync.wait_for_turn_completed, turn_id)

    async def stream_until_methods(
        self, methods: Iterable[str] | str
    ) -> list[Notification]:
        return await self._call_sync(self._sync.stream_until_methods, methods)

    async def run_text_turn(
        self, thread_id: str, text: str, params: V2TurnStartParams | JsonObject | None = None
    ) -> tuple[str, Notification]:
        return await self._call_sync(
            self._sync.run_text_turn, thread_id, text, params
        )

    async def ask_result(
        self, text: str, *, model: str | None = None, thread_id: str | None = None
    ) -> AskResult:
        return await self._call_sync(
            self._sync.ask_result, text, model=model, thread_id=thread_id
        )

    async def ask(
        self, text: str, *, model: str | None = None, thread_id: str | None = None
    ) -> tuple[str, str]:
        return await self._call_sync(
            self._sync.ask, text, model=model, thread_id=thread_id
        )

    async def stream_text(self, thread_id: str, text: str, params: V2TurnStartParams | JsonObject | None = None) -> list[str]:
        return await self._call_sync(
            lambda: list(self._sync.stream_text(thread_id, text, params))
        )
