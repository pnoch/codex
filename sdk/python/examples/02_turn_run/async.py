import asyncio

from codex_app_server.async_client import AsyncAppServerClient
from codex_app_server.generated.v2_all.AgentMessageDeltaNotification import AgentMessageDeltaNotification
from codex_app_server.generated.v2_all.TurnCompletedNotification import TurnCompletedNotification
from codex_app_server.public_types import ThreadStartParams


async def main() -> None:
    async with AsyncAppServerClient() as client:
        await client.initialize()
        started = await client.thread_start(ThreadStartParams(model="gpt-5"))
        thread_id = started.thread.id

        turn = await client.turn_text(thread_id, "Give 3 bullets about SIMD.")
        turn_id = turn.turn.id
        completed, text = await _wait_completed(client, turn_id)

        print("thread_id:", thread_id)
        print("turn_id:", turn_id)
        print("status:", completed.turn.status)
        print("error:", completed.turn.error)
        print("text:", text)
        print("items:", completed.turn.items)
        print("usage:", None)


async def _wait_completed(
    client: AsyncAppServerClient, turn_id: str
) -> tuple[TurnCompletedNotification, str]:
    chunks: list[str] = []
    while True:
        event = await client.next_notification()
        if isinstance(event.payload, AgentMessageDeltaNotification):
            chunks.append(event.payload.delta)
        if (
            event.method == "turn/completed"
            and isinstance(event.payload, TurnCompletedNotification)
            and event.payload.turn.id == turn_id
        ):
            return event.payload, "".join(chunks).strip()


if __name__ == "__main__":
    asyncio.run(main())
