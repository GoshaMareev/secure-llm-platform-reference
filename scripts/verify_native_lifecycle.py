"""Run inside isolated WebUI: native aliases, owned background completion and bounded fanout."""

import concurrent.futures
import json
import time
import uuid
from pathlib import Path

from bootstrap import BASE
from verify import signin


def run():
    identities = json.loads(Path("/run/secrets/identity-enrollment").read_text())["users"]
    identity = next(i for i in identities if i["scope"] == "engineer")
    session, _ = signin(identity["email"])
    checks = []
    for route in ["/api/chat/completions", "/api/v1/chat/completions"]:
        user_id, assistant_id = str(uuid.uuid4()), str(uuid.uuid4())
        chat = session.post(
            BASE + "/api/v1/chats/new",
            json={
                "chat": {
                    "title": "Synthetic lifecycle verification",
                    "models": ["reference-engineering-rag"],
                    "history": {"messages": {}, "currentId": None},
                    "messages": [],
                }
            },
            timeout=15,
        )
        chat.raise_for_status()
        chat_id = chat.json()["id"]
        try:
            start = time.monotonic()
            response = session.post(
                BASE + route,
                json={
                    "model": "reference-engineering-rag",
                    "stream": False,
                    "session_id": "synthetic-verification-session",
                    "chat_id": chat_id,
                    "user_message": {
                        "id": user_id,
                        "role": "user",
                        "content": "Who approves emergency production access?",
                        "timestamp": int(time.time()),
                    },
                    "messages": [{"role": "user", "content": "Who approves emergency production access?"}],
                    "message_ids": [{"model_id": "reference-engineering-rag", "message_id": assistant_id}],
                },
                timeout=60,
            )
            elapsed = (time.monotonic() - start) * 1000
            saved = session.get(BASE + "/api/v1/chats/" + chat_id, timeout=15).json()
            message = saved.get("chat", {}).get("history", {}).get("messages", {}).get(assistant_id, {})
            health = session.get(BASE + "/reference/health", timeout=5).json()
            checks.append(
                {
                    "route": route,
                    "status": response.status_code,
                    "background_task_returned": bool(response.json().get("task_ids")),
                    "stored_answer_done": bool(message.get("done") and message.get("content")),
                    "active_on_return": health.get("active"),
                    "elapsed_ms": round(elapsed, 2),
                    "passed": response.status_code == 200
                    and bool(response.json().get("task_ids"))
                    and bool(message.get("done") and message.get("content"))
                    and health.get("active") == 0,
                }
            )
        finally:
            session.delete(BASE + "/api/v1/chats/" + chat_id, timeout=15)
    response = session.post(
        BASE + "/api/v1/chat/completions",
        json={
            "model": "reference-engineering-rag",
            "messages": [{"role": "user", "content": "Who approves emergency production access?"}],
            "message_ids": [
                {"model_id": "reference-engineering-rag", "message_id": str(uuid.uuid4())} for _ in range(2)
            ],
        },
        timeout=15,
    )
    checks.append(
        {
            "check": "multi-model fanout denied",
            "status": response.status_code,
            "passed": response.status_code == 400,
        }
    )

    def call(index):
        response = session.post(
            BASE + ("/api/chat/completions" if index % 2 else "/api/v1/chat/completions"),
            json={
                "model": "reference-engineering-rag",
                "stream": False,
                "messages": [{"role": "user", "content": "Who approves emergency production access?"}],
            },
            timeout=60,
        )
        body = response.json()
        return {"status": response.status_code, "code": body.get("error", {}).get("code")}

    with concurrent.futures.ThreadPoolExecutor(max_workers=9) as pool:
        rows = list(pool.map(call, range(9)))
    checks.append(
        {
            "check": "nine native requests cannot exceed eight admissions across both aliases",
            "native_capacity_rejections": sum(
                r["code"] == "capacity_exhausted" and r["status"] == 429 for r in rows
            ),
            "statuses": [r["status"] for r in rows],
            "passed": any(r["code"] == "capacity_exhausted" and r["status"] == 429 for r in rows),
        }
    )
    result = {
        "profile": "isolated synthetic upstream; native background storage, no hosted credentials",
        "checks": checks,
        "accepted": all(c["passed"] for c in checks),
    }
    print(json.dumps(result, indent=2))
    return result["accepted"]


if __name__ == "__main__":
    raise SystemExit(0 if run() else 1)
