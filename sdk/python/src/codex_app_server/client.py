from __future__ import annotations

import json
import os
import subprocess
import threading
import uuid
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Iterator

from .conversation import ThreadSession
from .errors import AppServerError, TransportClosedError, map_jsonrpc_error
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
from .generated.schema_types import TurnStartResponse as SchemaTurnStartResponse
from .generated.schema_types import TurnSteerResponse as SchemaTurnSteerResponse
from .generated.schema_types import (
    TurnStartedNotificationPayload as SchemaTurnStartedNotificationPayload,
)
from .generated.v2_all.AgentMessageDeltaNotification import AgentMessageDeltaNotification
from .generated.v2_all.ErrorNotification import ErrorNotification
from .generated.v2_all.ItemCompletedNotification import ItemCompletedNotification
from .generated.v2_all.ItemStartedNotification import ItemStartedNotification
from .generated.v2_all.ThreadForkParams import ThreadForkParams as V2ThreadForkParams
from .generated.v2_all.ThreadListParams import ThreadListParams as V2ThreadListParams
from .generated.v2_all.ThreadNameUpdatedNotification import ThreadNameUpdatedNotification
from .generated.v2_all.ThreadResumeParams import ThreadResumeParams as V2ThreadResumeParams
from .generated.v2_all.ThreadStartParams import ThreadStartParams as V2ThreadStartParams
from .generated.v2_all.ThreadStartedNotification import ThreadStartedNotification
from .generated.v2_all.ThreadTokenUsageUpdatedNotification import (
    ThreadTokenUsageUpdatedNotification,
)
from .generated.v2_all.TurnCompletedNotification import TurnCompletedNotification
from .generated.v2_all.TurnStartParams import TurnStartParams as V2TurnStartParams
from .generated.v2_all.TurnStartedNotification import TurnStartedNotification
from .models import AskResult, JsonObject, Notification
from .retry import retry_on_overload
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

ApprovalHandler = Callable[[str, JsonObject | None], JsonObject]


def _params_dict(params: object | None) -> JsonObject:
    if params is None:
        return {}
    if hasattr(params, "model_dump"):
        return params.model_dump(exclude_none=True, mode="json")
    if isinstance(params, dict):
        return params
    raise TypeError(f"Expected generated params model or dict, got {type(params).__name__}")


_TYPED_NOTIFICATION_PARSERS = {
    "turn/completed": TurnCompletedEvent,
    "turn/started": TurnStartedEvent,
    "thread/started": ThreadStartedEvent,
    "item/agentMessage/delta": AgentMessageDeltaEvent,
    "item/started": ItemLifecycleEvent,
    "item/completed": ItemLifecycleEvent,
    "thread/nameUpdated": ThreadNameUpdatedEvent,
    "thread/tokenUsageUpdated": ThreadTokenUsageUpdatedEvent,
    "error": ErrorEvent,
}

_SCHEMA_NOTIFICATION_PARSERS = {
    "turn/completed": SchemaTurnCompletedNotificationPayload,
    "turn/started": SchemaTurnStartedNotificationPayload,
    "thread/started": SchemaThreadStartedNotificationPayload,
    "item/agentMessage/delta": SchemaAgentMessageDeltaNotificationPayload,
    "item/started": SchemaItemStartedNotificationPayload,
    "item/completed": SchemaItemCompletedNotificationPayload,
    "thread/nameUpdated": SchemaThreadNameUpdatedNotificationPayload,
    "thread/tokenUsageUpdated": SchemaThreadTokenUsageUpdatedNotificationPayload,
    "error": SchemaErrorNotificationPayload,
}

_NOTIFICATION_MODELS = {
    "turn/completed": TurnCompletedNotification,
    "turn/started": TurnStartedNotification,
    "thread/started": ThreadStartedNotification,
    "item/agentMessage/delta": AgentMessageDeltaNotification,
    "item/started": ItemStartedNotification,
    "item/completed": ItemCompletedNotification,
    "thread/nameUpdated": ThreadNameUpdatedNotification,
    "thread/tokenUsageUpdated": ThreadTokenUsageUpdatedNotification,
    "error": ErrorNotification,
}


def _bundled_codex_path() -> Path:
    import platform

    sys_name = platform.system().lower()
    machine = platform.machine().lower()

    if sys_name.startswith("darwin"):
        platform_dir = "darwin-arm64" if machine in {"arm64", "aarch64"} else "darwin-x64"
        exe = "codex"
    elif sys_name.startswith("linux"):
        platform_dir = "linux-arm64" if machine in {"arm64", "aarch64"} else "linux-x64"
        exe = "codex"
    elif sys_name.startswith("windows") or os.name == "nt":
        platform_dir = "windows-arm64" if machine in {"arm64", "aarch64"} else "windows-x64"
        exe = "codex.exe"
    else:
        raise RuntimeError(f"Unsupported OS for bundled codex binary: {sys_name}/{machine}")

    return Path(__file__).resolve().parent / "bin" / platform_dir / exe


@dataclass(slots=True)
class AppServerConfig:
    codex_bin: str = str(_bundled_codex_path())
    launch_args_override: tuple[str, ...] | None = None
    config_overrides: tuple[str, ...] = ()
    cwd: str | None = None
    env: dict[str, str] | None = None
    client_name: str = "codex_python_sdk"
    client_title: str = "Codex Python SDK"
    client_version: str = "0.2.0"
    experimental_api: bool = True


class AppServerClient:
    """Synchronous JSON-RPC client for `codex app-server` over stdio."""

    def __init__(
        self,
        config: AppServerConfig | None = None,
        approval_handler: ApprovalHandler | None = None,
    ) -> None:
        self.config = config or AppServerConfig()
        self._approval_handler = approval_handler or self._default_approval_handler
        self._proc: subprocess.Popen[str] | None = None
        self._lock = threading.Lock()
        self._pending_notifications: deque[Notification] = deque()
        self._stderr_lines: deque[str] = deque(maxlen=400)
        self._stderr_thread: threading.Thread | None = None

    def __enter__(self) -> "AppServerClient":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def start(self) -> None:
        if self._proc is not None:
            return

        if self.config.launch_args_override is not None:
            args = list(self.config.launch_args_override)
        else:
            codex_bin = Path(self.config.codex_bin)
            if not codex_bin.exists():
                raise FileNotFoundError(
                    f"Pinned codex binary not found at {codex_bin}. Run `python scripts/update_sdk_artifacts.py --channel stable` from sdk/python."
                )
            args = [str(codex_bin)]
            for kv in self.config.config_overrides:
                args.extend(["--config", kv])
            args.extend(["app-server", "--listen", "stdio://"])

        env = os.environ.copy()
        if self.config.env:
            env.update(self.config.env)

        self._proc = subprocess.Popen(
            args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=self.config.cwd,
            env=env,
            bufsize=1,
        )

        self._start_stderr_drain_thread()

    def close(self) -> None:
        if self._proc is None:
            return
        proc = self._proc
        self._proc = None

        if proc.stdin:
            proc.stdin.close()
        try:
            proc.terminate()
            proc.wait(timeout=2)
        except Exception:
            proc.kill()

        if self._stderr_thread and self._stderr_thread.is_alive():
            self._stderr_thread.join(timeout=0.5)

    def initialize(self) -> JsonObject:
        result = self.request(
            "initialize",
            {
                "clientInfo": {
                    "name": self.config.client_name,
                    "title": self.config.client_title,
                    "version": self.config.client_version,
                },
                "capabilities": {
                    "experimentalApi": self.config.experimental_api,
                },
            },
        )
        self.notify("initialized", None)
        return result if isinstance(result, dict) else {}

    def request(self, method: str, params: JsonObject | None = None) -> object:
        request_id = str(uuid.uuid4())
        self._write_message({"id": request_id, "method": method, "params": params or {}})

        while True:
            msg = self._read_message()

            if "method" in msg and "id" in msg:
                response = self._handle_server_request(msg)
                self._write_message({"id": msg["id"], "result": response})
                continue

            if "method" in msg and "id" not in msg:
                self._pending_notifications.append(self._coerce_notification(msg["method"], msg.get("params")))
                continue

            if msg.get("id") != request_id:
                continue

            if "error" in msg:
                err = msg["error"]
                if isinstance(err, dict):
                    raise map_jsonrpc_error(
                        int(err.get("code", -32000)),
                        str(err.get("message", "unknown")),
                        err.get("data"),
                    )
                raise AppServerError("Malformed JSON-RPC error response")

            return msg.get("result")

    def notify(self, method: str, params: JsonObject | None = None) -> None:
        self._write_message({"method": method, "params": params or {}})

    def next_notification(self) -> Notification:
        if self._pending_notifications:
            return self._pending_notifications.popleft()

        while True:
            msg = self._read_message()
            if "method" in msg and "id" in msg:
                response = self._handle_server_request(msg)
                self._write_message({"id": msg["id"], "result": response})
                continue
            if "method" in msg and "id" not in msg:
                return self._coerce_notification(msg["method"], msg.get("params"))

    def thread_start(
        self,
        params: V2ThreadStartParams | JsonObject | None = None,
        **legacy_params: object,
    ) -> ThreadStartResponse:
        result = self.request("thread/start", {**_params_dict(params), **legacy_params})
        return result if isinstance(result, dict) else {}

    def thread_resume(
        self,
        thread_id: str,
        params: V2ThreadResumeParams | JsonObject | None = None,
        **legacy_params: object,
    ) -> ThreadResumeResponse:
        payload = {"threadId": thread_id, **_params_dict(params), **legacy_params}
        result = self.request("thread/resume", payload)
        return result if isinstance(result, dict) else {}

    def thread_list(
        self,
        params: V2ThreadListParams | JsonObject | None = None,
        **legacy_params: object,
    ) -> ThreadListResponse:
        result = self.request("thread/list", {**_params_dict(params), **legacy_params})
        return result if isinstance(result, dict) else {}

    def thread_read(self, thread_id: str, include_turns: bool = False) -> ThreadReadResponse:
        result = self.request("thread/read", {"threadId": thread_id, "includeTurns": include_turns})
        return result if isinstance(result, dict) else {}

    def thread_fork(
        self,
        thread_id: str,
        params: V2ThreadForkParams | JsonObject | None = None,
        **legacy_params: object,
    ) -> JsonObject:
        result = self.request("thread/fork", {"threadId": thread_id, **_params_dict(params), **legacy_params})
        return result if isinstance(result, dict) else {}

    def thread_archive(self, thread_id: str) -> JsonObject:
        result = self.request("thread/archive", {"threadId": thread_id})
        return result if isinstance(result, dict) else {}

    def thread_unarchive(self, thread_id: str) -> JsonObject:
        result = self.request("thread/unarchive", {"threadId": thread_id})
        return result if isinstance(result, dict) else {}

    def thread_set_name(self, thread_id: str, name: str) -> JsonObject:
        result = self.request("thread/setName", {"threadId": thread_id, "name": name})
        return result if isinstance(result, dict) else {}

    def turn_start(
        self,
        thread_id: str,
        input_items: list[JsonObject] | JsonObject | str,
        params: V2TurnStartParams | JsonObject | None = None,
        **legacy_params: object,
    ) -> TurnStartResponse:
        payload = {
            **_params_dict(params),
            **legacy_params,
            "threadId": thread_id,
            "input": self._normalize_input_items(input_items),
        }
        result = self.request("turn/start", payload)
        return result if isinstance(result, dict) else {}

    def turn_text(
        self,
        thread_id: str,
        text: str,
        params: V2TurnStartParams | JsonObject | None = None,
        **legacy_params: object,
    ) -> TurnStartResponse:
        return self.turn_start(thread_id, text, params=params, **legacy_params)

    def turn_interrupt(self, thread_id: str, turn_id: str) -> JsonObject:
        result = self.request("turn/interrupt", {"threadId": thread_id, "turnId": turn_id})
        return result if isinstance(result, dict) else {}

    def turn_steer(
        self,
        thread_id: str,
        expected_turn_id: str,
        input_items: list[JsonObject] | JsonObject | str,
    ) -> JsonObject:
        result = self.request(
            "turn/steer",
            {
                "threadId": thread_id,
                "expectedTurnId": expected_turn_id,
                "input": self._normalize_input_items(input_items),
            },
        )
        return result if isinstance(result, dict) else {}

    def model_list(self, include_hidden: bool = False) -> JsonObject:
        result = self.request("model/list", {"includeHidden": include_hidden})
        return result if isinstance(result, dict) else {}

    def thread(self, thread_id: str) -> ThreadSession:
        return ThreadSession(client=self, thread_id=thread_id)

    def thread_start_session(self, *, model: str | None = None, params: V2ThreadStartParams | JsonObject | None = None) -> ThreadSession:
        payload = _params_dict(params)
        if model is not None:
            payload["model"] = model
        started = self.thread_start(payload)
        thread = started.get("thread")
        thread_id = thread.get("id") if isinstance(thread, dict) else ""
        return ThreadSession(client=self, thread_id=str(thread_id))

    def thread_start_typed(self, params: V2ThreadStartParams | JsonObject | None = None) -> ThreadStartResult:
        return ThreadStartResult.from_dict(self.thread_start(params))

    def thread_resume_typed(self, thread_id: str, params: V2ThreadResumeParams | JsonObject | None = None) -> ThreadResumeResult:
        return ThreadResumeResult.from_dict(self.thread_resume(thread_id, params))

    def thread_read_typed(self, thread_id: str, include_turns: bool = False) -> ThreadReadResult:
        return ThreadReadResult.from_dict(self.thread_read(thread_id, include_turns=include_turns))

    def thread_fork_typed(self, thread_id: str, params: V2ThreadForkParams | JsonObject | None = None) -> ThreadForkResult:
        return ThreadForkResult.from_dict(self.thread_fork(thread_id, params))

    def thread_archive_typed(self, thread_id: str) -> EmptyResult:
        return EmptyResult.from_dict(self.thread_archive(thread_id))

    def thread_unarchive_typed(self, thread_id: str) -> EmptyResult:
        return EmptyResult.from_dict(self.thread_unarchive(thread_id))

    def thread_set_name_typed(self, thread_id: str, name: str) -> EmptyResult:
        return EmptyResult.from_dict(self.thread_set_name(thread_id, name))

    def thread_list_typed(self, params: V2ThreadListParams | JsonObject | None = None) -> ThreadListResult:
        return ThreadListResult.from_dict(self.thread_list(params))

    def model_list_typed(self, include_hidden: bool = False) -> ModelListResult:
        return ModelListResult.from_dict(self.model_list(include_hidden=include_hidden))

    def turn_start_typed(
        self,
        thread_id: str,
        input_items: list[JsonObject] | JsonObject | str,
        params: V2TurnStartParams | JsonObject | None = None,
    ) -> TurnStartResult:
        return TurnStartResult.from_dict(self.turn_start(thread_id, input_items, params=params))

    def turn_text_typed(self, thread_id: str, text: str, params: V2TurnStartParams | JsonObject | None = None) -> TurnStartResult:
        return TurnStartResult.from_dict(self.turn_text(thread_id, text, params=params))

    def turn_steer_typed(
        self,
        thread_id: str,
        expected_turn_id: str,
        input_items: list[JsonObject] | JsonObject | str,
    ) -> TurnSteerResult:
        return TurnSteerResult.from_dict(self.turn_steer(thread_id, expected_turn_id, input_items))

    def thread_start_schema(self, params: V2ThreadStartParams | JsonObject | None = None) -> SchemaThreadStartResponse:
        return SchemaThreadStartResponse.from_dict(self.thread_start(params))

    def thread_resume_schema(self, thread_id: str, params: V2ThreadResumeParams | JsonObject | None = None) -> SchemaThreadResumeResponse:
        return SchemaThreadResumeResponse.from_dict(self.thread_resume(thread_id, params))

    def thread_read_schema(self, thread_id: str, include_turns: bool = False) -> SchemaThreadReadResponse:
        return SchemaThreadReadResponse.from_dict(self.thread_read(thread_id, include_turns=include_turns))

    def thread_list_schema(self, params: V2ThreadListParams | JsonObject | None = None) -> SchemaThreadListResponse:
        return SchemaThreadListResponse.from_dict(self.thread_list(params))

    def thread_fork_schema(self, thread_id: str, params: V2ThreadForkParams | JsonObject | None = None) -> SchemaThreadForkResponse:
        return SchemaThreadForkResponse.from_dict(self.thread_fork(thread_id, params))

    def thread_archive_schema(self, thread_id: str) -> SchemaThreadArchiveResponse:
        return SchemaThreadArchiveResponse.from_dict(self.thread_archive(thread_id))

    def thread_unarchive_schema(self, thread_id: str) -> SchemaThreadUnarchiveResponse:
        return SchemaThreadUnarchiveResponse.from_dict(self.thread_unarchive(thread_id))

    def thread_set_name_schema(self, thread_id: str, name: str) -> SchemaThreadSetNameResponse:
        return SchemaThreadSetNameResponse.from_dict(self.thread_set_name(thread_id, name))

    def model_list_schema(self, include_hidden: bool = False) -> SchemaModelListResponse:
        return SchemaModelListResponse.from_dict(self.model_list(include_hidden=include_hidden))

    def turn_start_schema(
        self,
        thread_id: str,
        input_items: list[JsonObject] | JsonObject | str,
        params: V2TurnStartParams | JsonObject | None = None,
    ) -> SchemaTurnStartResponse:
        return SchemaTurnStartResponse.from_dict(self.turn_start(thread_id, input_items, params=params))

    def turn_text_schema(self, thread_id: str, text: str, params: V2TurnStartParams | JsonObject | None = None) -> SchemaTurnStartResponse:
        return self.turn_start_schema(thread_id, text, params=params)

    def turn_steer_schema(
        self,
        thread_id: str,
        expected_turn_id: str,
        input_items: list[JsonObject] | JsonObject | str,
    ) -> SchemaTurnSteerResponse:
        return SchemaTurnSteerResponse.from_dict(self.turn_steer(thread_id, expected_turn_id, input_items))

    def parse_notification_typed(
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
        return self._parse_notification_with(notification, _TYPED_NOTIFICATION_PARSERS)

    def parse_notification_schema(
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
        return self._parse_notification_with(notification, _SCHEMA_NOTIFICATION_PARSERS)

    def request_with_retry_on_overload(
        self,
        method: str,
        params: JsonObject | None = None,
        *,
        max_attempts: int = 3,
        initial_delay_s: float = 0.25,
        max_delay_s: float = 2.0,
    ) -> object:
        return retry_on_overload(
            lambda: self.request(method, params),
            max_attempts=max_attempts,
            initial_delay_s=initial_delay_s,
            max_delay_s=max_delay_s,
        )

    def wait_for_turn_completed(self, turn_id: str) -> Notification:
        while True:
            n = self.next_notification()
            event = self._notification_params_dict(n)
            if (
                n.method == "turn/completed"
                and isinstance(event.get("turn"), dict)
                and event["turn"].get("id") == turn_id
            ):
                return n

    def stream_until_methods(self, methods: Iterable[str] | str) -> list[Notification]:
        target_methods = {methods} if isinstance(methods, str) else set(methods)
        out: list[Notification] = []
        while True:
            n = self.next_notification()
            out.append(n)
            if n.method in target_methods:
                return out

    def run_text_turn(
        self,
        thread_id: str,
        text: str,
        params: V2TurnStartParams | JsonObject | None = None,
    ) -> tuple[str, Notification]:
        turn = self.turn_text(thread_id, text, params=params)
        turn_data = turn.get("turn")
        turn_id = str(turn_data.get("id")) if isinstance(turn_data, dict) else ""

        chunks: list[str] = []
        completed: Notification | None = None
        while True:
            n = self.next_notification()
            event = self._notification_params_dict(n)
            if n.method == "item/agentMessage/delta":
                chunks.append(str(event.get("delta", "")))
            if (
                n.method == "turn/completed"
                and isinstance(event.get("turn"), dict)
                and event["turn"].get("id") == turn_id
            ):
                completed = n
                break

        assert completed is not None
        return "".join(chunks), completed

    def ask_result(self, text: str, *, model: str | None = None, thread_id: str | None = None) -> AskResult:
        if thread_id is None:
            start_params = V2ThreadStartParams(model=model) if model else None
            started = self.thread_start(start_params)
            thread = started.get("thread")
            thread_id = str(thread.get("id")) if isinstance(thread, dict) else ""
        assistant_text, completed = self.run_text_turn(thread_id, text)
        return AskResult(thread_id=thread_id, text=assistant_text, completed=completed)

    def ask(self, text: str, *, model: str | None = None, thread_id: str | None = None) -> tuple[str, str]:
        result = self.ask_result(text, model=model, thread_id=thread_id)
        return result.thread_id, result.text

    def stream_text(
        self,
        thread_id: str,
        text: str,
        params: V2TurnStartParams | JsonObject | None = None,
    ) -> Iterator[str]:
        turn = self.turn_text(thread_id, text, params=params)
        turn_data = turn.get("turn")
        turn_id = str(turn_data.get("id")) if isinstance(turn_data, dict) else ""
        while True:
            event = self.next_notification()
            payload = self._notification_params_dict(event)
            if event.method == "item/agentMessage/delta":
                yield str(payload.get("delta", ""))
            if (
                event.method == "turn/completed"
                and isinstance(payload.get("turn"), dict)
                and payload["turn"].get("id") == turn_id
            ):
                break

    def _coerce_notification(self, method: str, params: object) -> Notification:
        # Keep Notification.params as JSON-like dict for broad example compatibility.
        # Typed parsing is available through parse_notification_* helpers.
        params_dict = params if isinstance(params, dict) else None
        return Notification(method=method, params=params_dict)

    def _notification_params_dict(self, notification: Notification) -> JsonObject:
        params = notification.params
        if hasattr(params, "model_dump"):
            payload = params.model_dump(mode="json")
            return payload if isinstance(payload, dict) else {}
        if isinstance(params, dict):
            return params
        return {}

    def _parse_notification_with(self, notification: Notification, parsers: dict[str, type]) -> object | None:
        parser = parsers.get(notification.method)
        if parser is None:
            return None
        return parser.from_dict(self._notification_params_dict(notification))

    def _normalize_input_items(
        self, input_items: list[JsonObject] | JsonObject | str
    ) -> list[JsonObject]:
        if isinstance(input_items, str):
            return [{"type": "text", "text": input_items}]
        if isinstance(input_items, dict):
            return [input_items]
        return input_items

    def _default_approval_handler(self, method: str, params: JsonObject | None) -> JsonObject:
        if method == "item/commandExecution/requestApproval":
            return {"decision": "accept"}
        if method == "item/fileChange/requestApproval":
            return {"decision": "accept"}
        return {}

    def _start_stderr_drain_thread(self) -> None:
        if self._proc is None or self._proc.stderr is None:
            return

        def _drain() -> None:
            stderr = self._proc.stderr
            if stderr is None:
                return
            for line in stderr:
                self._stderr_lines.append(line.rstrip("\n"))

        self._stderr_thread = threading.Thread(target=_drain, daemon=True)
        self._stderr_thread.start()

    def _stderr_tail(self, limit: int = 40) -> str:
        return "\n".join(list(self._stderr_lines)[-limit:])

    def _handle_server_request(self, msg: JsonObject) -> JsonObject:
        method = msg["method"]
        params = msg.get("params")
        request_params = params if isinstance(params, dict) else None
        return self._approval_handler(str(method), request_params)

    def _write_message(self, payload: JsonObject) -> None:
        if self._proc is None or self._proc.stdin is None:
            raise TransportClosedError("app-server is not running")
        with self._lock:
            self._proc.stdin.write(json.dumps(payload) + "\n")
            self._proc.stdin.flush()

    def _read_message(self) -> JsonObject:
        if self._proc is None or self._proc.stdout is None:
            raise TransportClosedError("app-server is not running")

        line = self._proc.stdout.readline()
        if not line:
            raise TransportClosedError(
                f"app-server closed stdout. stderr_tail={self._stderr_tail()[:2000]}"
            )

        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise AppServerError(f"Invalid JSON-RPC line: {line!r}") from exc
        if not isinstance(payload, dict):
            raise AppServerError(f"Expected JSON object message, got: {type(payload).__name__}")
        return payload


def default_codex_home() -> str:
    return str(Path.home() / ".codex")
