"""Preserve the official WebUI app while bounding its complete RAG lifecycle."""

from open_webui.main import app as native_app
from reference_capacity import CapacityMiddleware

app = CapacityMiddleware(native_app, capacity=8, chat_paths={"/api/chat/completions"})
