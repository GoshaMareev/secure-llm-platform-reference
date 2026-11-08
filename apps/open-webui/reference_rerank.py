"""Compatibility boundary for native Open WebUI v0.11.4 reranking.

Its query_collection recreates a rerank closure without passing the user and
accepts unscored documents on remote failure. Keep the native retriever; bind
the verified request user and require a successful external ranking instead.
"""

import math
from contextvars import ContextVar

from open_webui.models.users import UserModel

_current = ContextVar("reference_rerank_request", default=None)


def bind(request, user):
    state = {"user": UserModel.model_validate(user), "completed": 0, "failed": False}
    _current.set(state)
    request.state.reference_rerank = state
    original = request.app.state.RERANKING_FUNCTION
    if original is None or getattr(original, "reference_bound", False):
        return

    def ranked(query, documents, user=None):
        context = _current.get()
        if context is None:
            # Non-chat internal operations must supply their own verified user.
            return original(query, documents, user=user) if user is not None else None
        if context["failed"]:
            return None  # Native fallback must not repeat a failed provider call.
        try:
            scores = original(query, documents, user=context["user"])
            if (
                scores is None
                or len(scores) != len(documents)
                or not all(isinstance(s, (int, float)) and math.isfinite(s) for s in scores)
            ):
                context["failed"] = True
                return None
            context["completed"] += 1
            return scores
        except Exception:
            context["failed"] = True
            raise

    ranked.reference_bound = True
    request.app.state.RERANKING_FUNCTION = ranked
