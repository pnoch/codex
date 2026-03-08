import asyncio

from codex_app_server.async_client import AsyncAppServerClient
from codex_app_server.generated.v2_all.TurnCompletedNotification import TurnCompletedNotification
from codex_app_server.public_types import ThreadStartParams


async def main() -> None:
    async with AsyncAppServerClient() as client:
        await client.initialize()
        started = await client.thread_start(ThreadStartParams(model="gpt-5"))
        thread_id = started.thread.id

        turn = await client.turn_text(thread_id, "Write a short haiku about compilers.")
        turn_id = turn.turn.id

        while True:
            event = await client.next_notification()
            print(event.method, event.payload)
            if (
                event.method == "turn/completed"
                and isinstance(event.payload, TurnCompletedNotification)
                and event.payload.turn.id == turn_id
            ):
                break


if __name__ == "__main__":
    asyncio.run(main())
