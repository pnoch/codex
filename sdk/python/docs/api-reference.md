# Codex App Server SDK — API Reference

Public surface of `codex_app_server` for app-server v2.

## Package Entry

```python
from codex_app_server import (
    Codex,
    AsyncCodex,
    Thread,
    AsyncThread,
    Turn,
    AsyncTurn,
    TurnResult,
    InitializeResult,
    Input,
    InputItem,
    TextInput,
    ImageInput,
    LocalImageInput,
    SkillInput,
    MentionInput,
    ThreadItem,
    ThreadStartParams,
    ThreadResumeParams,
    ThreadListParams,
    ThreadForkParams,
    TurnStartParams,
)
```

- Version: `codex_app_server.__version__`
- Requires Python >= 3.10

## Codex (sync)

```python
Codex(config: AppServerConfig | None = None)
```

Properties/methods:

- `metadata -> InitializeResult`
- `close() -> None`
- `thread_start(params: ThreadStartParams) -> Thread`
- `thread(thread_id: str) -> Thread`
- `thread_list(params: ThreadListParams | None = None) -> ThreadListResponse`
- `models(*, include_hidden: bool = False) -> ModelListResponse`

Context manager:

```python
with Codex() as codex:
    ...
```

## AsyncCodex (async parity)

```python
AsyncCodex(config: AppServerConfig | None = None)
```

Properties/methods:

- `metadata -> InitializeResult`
- `close() -> Awaitable[None]`
- `thread_start(params: ThreadStartParams) -> Awaitable[AsyncThread]`
- `thread(thread_id: str) -> AsyncThread`
- `thread_list(params: ThreadListParams | None = None) -> Awaitable[ThreadListResponse]`
- `models(*, include_hidden: bool = False) -> Awaitable[ModelListResponse]`

Async context manager:

```python
async with AsyncCodex() as codex:
    ...
```

## Thread / AsyncThread

`Thread` and `AsyncThread` share the same shape and intent.

### Thread

- `turn(input: Input, *, params: TurnStartParams | dict[str, object] | None = None) -> Turn`
- `resume(params: ThreadResumeParams) -> Thread`
- `read(*, include_turns: bool = False) -> ThreadReadResponse`
- `fork(params: ThreadForkParams) -> Thread`
- `archive() -> ThreadArchiveResponse`
- `unarchive() -> Thread`
- `set_name(name: str) -> ThreadSetNameResponse`
- `compact() -> ThreadCompactStartResponse`

### AsyncThread

- `turn(input: Input, *, params: TurnStartParams | dict[str, object] | None = None) -> Awaitable[AsyncTurn]`
- `resume(params: ThreadResumeParams) -> Awaitable[AsyncThread]`
- `read(*, include_turns: bool = False) -> Awaitable[ThreadReadResponse]`
- `fork(params: ThreadForkParams) -> Awaitable[AsyncThread]`
- `archive() -> Awaitable[ThreadArchiveResponse]`
- `unarchive() -> Awaitable[AsyncThread]`
- `set_name(name: str) -> Awaitable[ThreadSetNameResponse]`
- `compact() -> Awaitable[ThreadCompactStartResponse]`

## Turn / AsyncTurn

### Turn

- `steer(input: Input) -> TurnSteerResponse`
- `interrupt() -> TurnInterruptResponse`
- `stream() -> Iterator[Notification]`
- `run() -> TurnResult`

### AsyncTurn

- `steer(input: Input) -> Awaitable[TurnSteerResponse]`
- `interrupt() -> Awaitable[TurnInterruptResponse]`
- `stream() -> AsyncIterator[Notification]`
- `run() -> Awaitable[TurnResult]`

## TurnResult

```python
@dataclass
class TurnResult:
    thread_id: str
    turn_id: str
    status: TurnStatus
    error: TurnError | None
    text: str
    items: list[ThreadItem]
    usage: ThreadTokenUsageUpdatedNotification | None
```

## Inputs

```python
@dataclass class TextInput: text: str
@dataclass class ImageInput: url: str
@dataclass class LocalImageInput: path: str
@dataclass class SkillInput: name: str; path: str
@dataclass class MentionInput: name: str; path: str

InputItem = TextInput | ImageInput | LocalImageInput | SkillInput | MentionInput
Input = list[InputItem] | InputItem
```

## Retry + errors

```python
from codex_app_server import (
    retry_on_overload,
    JsonRpcError,
    MethodNotFoundError,
    InvalidParamsError,
    ServerBusyError,
    is_retryable_error,
)
```

- `retry_on_overload(...)` retries transient overload errors with exponential backoff + jitter.
- `is_retryable_error(exc)` checks if an exception is transient/overload-like.

## Example

```python
from codex_app_server import Codex, TextInput, ThreadStartParams

with Codex() as codex:
    thread = codex.thread_start(ThreadStartParams(model="gpt-5"))
    result = thread.turn(TextInput("Say hello in one sentence.")).run()
    print(result.text)
```
