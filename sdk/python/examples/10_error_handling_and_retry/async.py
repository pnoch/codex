import asyncio
import random
from collections.abc import Awaitable, Callable
from typing import TypeVar

from codex_app_server.async_client import AsyncAppServerClient
from codex_app_server.errors import (
    InvalidParamsError,
    JsonRpcError,
    MethodNotFoundError,
    ServerBusyError,
    is_retryable_error,
)
from codex_app_server.generated.v2_all.AgentMessageDeltaNotification import AgentMessageDeltaNotification
from codex_app_server.generated.v2_all.ModelListResponse import ModelListResponse
from codex_app_server.generated.v2_all.TurnCompletedNotification import TurnCompletedNotification
from codex_app_server.public_types import ThreadStartParams

ResultT = TypeVar("ResultT")


async def retry_on_overload_async(
    op: Callable[[], Awaitable[ResultT]],
    *,
    max_attempts: int = 3,
    initial_delay_s: float = 0.25,
    max_delay_s: float = 2.0,
    jitter_ratio: float = 0.2,
) -> ResultT:
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")

    delay = initial_delay_s
    attempt = 0
    while True:
        attempt += 1
        try:
            return await op()
        except Exception as exc:  # noqa: BLE001
            if attempt >= max_attempts or not is_retryable_error(exc):
                raise
            jitter = delay * jitter_ratio
            sleep_for = min(max_delay_s, delay) + random.uniform(-jitter, jitter)
            if sleep_for > 0:
                await asyncio.sleep(sleep_for)
            delay = min(max_delay_s, delay * 2)


async def main() -> None:
    async with AsyncAppServerClient() as client:
        await client.initialize()

        started = await client.thread_start(ThreadStartParams(model="gpt-5"))
        thread_id = started.thread.id

        turn = await retry_on_overload_async(
            lambda: client.turn_text(
                thread_id, "Summarize retry best practices in 3 bullets."
            ),
            max_attempts=3,
            initial_delay_s=0.25,
            max_delay_s=2.0,
        )
        turn_id = turn.turn.id
        text = await _collect_text_until_completed(client, turn_id)
        print("Text:", text)

        try:
            await client.request(
                "demo/missingMethod",
                {},
                response_model=ModelListResponse,
            )
        except MethodNotFoundError as exc:
            print("Method not found:", exc.message)
        except InvalidParamsError as exc:
            print("Invalid params:", exc.message)
        except ServerBusyError as exc:
            print("Server overloaded after retries:", exc.message)
        except JsonRpcError as exc:
            print(f"JSON-RPC error {exc.code}: {exc.message}")


async def _collect_text_until_completed(
    client: AsyncAppServerClient, turn_id: str
) -> str:
    chunks: list[str] = []
    while True:
        event = await client.next_notification()
        if (
            isinstance(event.payload, AgentMessageDeltaNotification)
            and event.payload.turnId == turn_id
        ):
            chunks.append(event.payload.delta)
        if (
            event.method == "turn/completed"
            and isinstance(event.payload, TurnCompletedNotification)
            and event.payload.turn.id == turn_id
        ):
            return "".join(chunks).strip()


if __name__ == "__main__":
    asyncio.run(main())
