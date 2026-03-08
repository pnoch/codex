import asyncio

from codex_app_server import AsyncCodex, TextInput, ThreadStartParams


async def main() -> None:
    async with AsyncCodex() as codex:
        original = await codex.thread_start(ThreadStartParams(model="gpt-5"))

        first_turn = await original.turn(TextInput("Tell me one fact about Saturn."))
        first = await first_turn.run()
        print("Created thread:", first.thread_id)

        resumed = codex.thread(first.thread_id)
        second_turn = await resumed.turn(TextInput("Continue with one more fact."))
        second = await second_turn.run()
        print(second.text)


if __name__ == "__main__":
    asyncio.run(main())
