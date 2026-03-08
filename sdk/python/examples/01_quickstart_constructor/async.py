import asyncio

from codex_app_server.async_client import AsyncAppServerClient
from codex_app_server.generated.v2_all.AgentMessageDeltaNotification import AgentMessageDeltaNotification
from codex_app_server.generated.v2_all.TurnCompletedNotification import TurnCompletedNotification
from codex_app_server.public_types import ThreadStartParams


async def main() -> None:
    async with AsyncAppServerClient() as client:
        metadata = await client.initialize()
        server = metadata.serverInfo
        print("Server:", server.name if server else None, server.version if server else None)

        started = await client.thread_start(ThreadStartParams(model="gpt-5"))
        thread_id = started.thread.id
        turn = await client.turn_text(thread_id, "Say hello in one sentence.")
        turn_id = turn.turn.id

        text = await _collect_text_until_completed(client, turn_id)
        print("Status: completed")
        print("Text:", text)


async def _collect_text_until_completed(
    client: AsyncAppServerClient, turn_id: str
) -> str:
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
            return "".join(chunks).strip()


if __name__ == "__main__":
    asyncio.run(main())
