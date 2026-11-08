"""Preserve the official WebUI app while bounding its complete RAG lifecycle."""

import time

import open_webui.main as native
import open_webui.utils.middleware as native_middleware
from reference_capacity import CapacityMiddleware
from secure_rag.telemetry import REQUEST_CONTEXT, STAGE_SECONDS

_create_task = native.create_task
_retrieve = native_middleware.chat_completion_files_handler


async def timed_retrieval(request, body, extra_params, user):
    start, verdict = time.monotonic(), "error"
    alias = body.get("model")
    if alias not in {"reference-general-rag", "reference-engineering-rag"}:
        alias = "reference-rag"
    try:
        result = await _retrieve(request, body, extra_params, user)
        verdict = "completed"
        return result
    finally:
        STAGE_SECONDS.labels(stage="retrieval", model_alias=alias, verdict=verdict).observe(
            time.monotonic() - start
        )


async def tracked_create_task(redis, coroutine, id=None, task_id=None):
    context = REQUEST_CONTEXT.get()
    result = await _create_task(redis, coroutine, id=id, task_id=task_id)
    if context is not None and "native_tasks" in context:
        context["native_tasks"].append(result[1])
    return result


# Pinned main.py imports this helper into its own namespace. Preserve native
# WebSocket events/storage while joining its chat task before HTTP completion.
native.create_task = tracked_create_task
native_middleware.chat_completion_files_handler = timed_retrieval
app = CapacityMiddleware(
    native.app,
    capacity=8,
    chat_paths={"/api/chat/completions", "/api/v1/chat/completions"},
    join_native_tasks=True,
)
