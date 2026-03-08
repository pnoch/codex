import asyncio

from codex_app_server.async_client import AsyncAppServerClient
from codex_app_server.generated.v2_all.AgentMessageDeltaNotification import AgentMessageDeltaNotification
from codex_app_server.generated.v2_all.TurnCompletedNotification import TurnCompletedNotification
from codex_app_server.public_types import ThreadStartParams


async def main() -> None:
    print("Codex async mini CLI. Type /exit to quit.")

    async with AsyncAppServerClient() as client:
        await client.initialize()
        started = await client.thread_start(ThreadStartParams(model="gpt-5"))
        thread_id = started.thread.id
        print("Thread:", thread_id)

        while True:
            try:
                user_input = (await asyncio.to_thread(input, "you> ")).strip()
            except EOFError:
                break

            if not user_input:
                continue
            if user_input in {"/exit", "/quit"}:
                break

            turn = await client.turn_text(thread_id, user_input)
            turn_id = turn.turn.id
            text = await _collect_text_until_completed(client, turn_id)
            print("assistant>", text)


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
