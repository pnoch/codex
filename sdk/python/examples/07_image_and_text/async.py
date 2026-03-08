import asyncio

from codex_app_server import AsyncCodex, ImageInput, TextInput, ThreadStartParams


async def main() -> None:
    async with AsyncCodex() as codex:
        thread = await codex.thread_start(ThreadStartParams(model="gpt-5"))

        turn = await thread.turn(
            [
                TextInput("What is in this image? Give 3 bullets."),
                ImageInput("https://upload.wikimedia.org/wikipedia/commons/3/3a/Cat03.jpg"),
            ]
        )
        result = await turn.run()

        print("Status:", result.status)
        print(result.text)


if __name__ == "__main__":
    asyncio.run(main())
