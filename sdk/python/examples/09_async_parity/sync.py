from codex_app_server.client import AppServerClient
from codex_app_server.generated.v2_all.AgentMessageDeltaNotification import AgentMessageDeltaNotification
from codex_app_server.generated.v2_all.TurnCompletedNotification import TurnCompletedNotification
from codex_app_server.public_types import ThreadStartParams

with AppServerClient() as client:
    metadata = client.initialize()
    server = metadata.serverInfo
    print("Server:", server.name if server else None, server.version if server else None)

    started = client.thread_start(ThreadStartParams(model="gpt-5"))
    thread_id = started.thread.id

    turn = client.turn_text(thread_id, "Say hello in one sentence.")
    turn_id = turn.turn.id

    chunks: list[str] = []
    while True:
        event = client.next_notification()
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
            break

    print("Thread:", thread_id)
    print("Turn:", turn_id)
    print("Text:", "".join(chunks).strip())
