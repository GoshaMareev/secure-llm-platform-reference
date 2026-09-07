# Model gateway boundary

The RAG service talks to a `ModelGateway` interface instead of importing a provider SDK into retrieval logic.

The default `demo` implementation is deterministic and offline. Set `RAG_GATEWAY_MODE=openai-compatible` only when an operator has intentionally configured a local or approved OpenAI-compatible endpoint.

`litellm-config.yaml` is an optional example for a self-hosted LiteLLM gateway. It contains environment references only—never credentials or production endpoints.

Security properties:

- provider selection is operator-controlled, not request-controlled;
- base URLs cannot contain embedded credentials;
- retrieval filters and source selection remain inside the RAG service;
- the operational log path never receives prompts, answers, or authorization headers.

