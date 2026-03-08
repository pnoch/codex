from codex_app_server import Codex, ThreadListParams, ThreadStartParams


with Codex() as codex:
    thread = codex.thread_start(ThreadStartParams(model="gpt-5"))
    _ = codex.thread_list(ThreadListParams(limit=20))
    _ = thread.read(include_turns=False)
    print("Lifecycle OK:", thread.id)
