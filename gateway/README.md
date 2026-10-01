# Model gateway boundary

The RAG service talks to a `ModelGateway` interface instead of importing a provider SDK into retrieval logic.

The default `demo` implementation is deterministic and offline. Set `RAG_GATEWAY_MODE=openai-compatible` only when an operator has intentionally configured a local or approved OpenAI-compatible endpoint.

`litellm-config.yaml` configures the self-hosted LiteLLM gateway started by `make gateway-up` (Compose profile `gateway`). It contains `os.environ/` references only, never credentials or production endpoints.

The gateway runs two Presidio guardrails on every call, for every application behind it:

- `presidio-pii-input` (`pre_call`) masks names, e-mail addresses, phone numbers, cards, IBANs and IP addresses, and blocks requests that contain a US SSN;
- `presidio-pii-output` (`post_call`) masks the same entities in responses.

The gateway uses Presidio's own placeholders (`<PERSON>`, `<EMAIL_ADDRESS>`); the RAG API uses `[REDACTED_PERSON]`-style placeholders. Both come from the same Presidio services.

`output_parse_pii` stays off because retrieved documents travel in the prompt; restoring masked values would leak corpus personal data into answers. Check the running guardrail without a model:

```bash
make gateway-up && make smoke-presidio
```

Security properties:

- provider selection is operator-controlled, not request-controlled;
- base URLs cannot contain embedded credentials;
- retrieval filters and source selection remain inside the RAG service;
- the operational log path never receives prompts, answers, or authorization headers.

