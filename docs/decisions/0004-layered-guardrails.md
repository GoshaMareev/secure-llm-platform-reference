# ADR 0004: Layered guardrails, shared Presidio services and an adversarial evaluation gate

- Status: accepted
- Date: 2026-10-01

## Context

A retrieval assistant has three places where untrusted text enters the model's view: the user's question, the retrieved documents, and the model's own answer. Prompt injection arrives through the first two; data leakage leaves through the third. The reference previously relied on the confidence gate alone, which stops unsupported answers but not instructions hidden in a question or in a well-matching document.

The reference targets English-language deployments. The core test suite must stay offline and reproducible, so it cannot depend on a hosted moderation API.

## Decision

Add a `Guardrails` component with one checkpoint per entry point:

| Checkpoint | Detects | Action | Verdict code |
| --- | --- | --- | --- |
| input | instruction override, system-prompt extraction, persona/mode switching | block before retrieval | `input_injection_blocked` |
| input | personal data (see below) | redact, then continue | `input_pii_redacted` |
| retrieved context | injection rules, credential-exfiltration requests, fake `system:` / `<system>` markers | quarantine the chunk | `context_injection_quarantined` |
| output | operator prompt fingerprint | block | `output_prompt_leak_blocked` |
| output | relayed injection or exfiltration instruction | block | `output_injection_echo_blocked` |
| output | personal data (see below) | redact | `output_pii_redacted` |

Personal-data redaction runs on **shared Presidio services**, not inside the application:

```text
                    ┌──────────────────── presidio-analyzer :3000 ───┐
RAG API ── HTTP ───►│  spaCy NER + validated recognizers             │◄── HTTP ── LiteLLM gateway
(input, context,    └──────────────────── presidio-anonymizer :3000 ─┘    (pre_call / post_call
 output, audit)                                                            guardrails, every app)
```

- **Gateway layer (LiteLLM).** `presidio-pii-input` (`pre_call`) masks names, contacts, cards, IBANs and IP addresses before any prompt reaches a model, and blocks requests carrying a US SSN. `presidio-pii-output` (`post_call`) masks the response. Both are `default_on`, so every application behind the gateway gets them, not only this one. `output_parse_pii` is off: retrieved documents travel inside the prompt, and restoring masked values would put personal data from the corpus back into answers.
- **Application layer (RAG API).** The gateway sees only what is sent to the model. The application also needs redaction where the gateway is not involved: the retrieval query, the offline demo gateway, and the answer it returns. It calls the same Presidio containers over HTTP (`PII_BACKEND=presidio`). The image carries no spaCy model, and recognizer changes happen in one place.
- **Fail closed.** If Presidio is unreachable or answers with an unexpected payload, the request is blocked with `pii_check_unavailable_blocked`. An unchecked prompt never reaches retrieval or the model.
- **Regex fallback** (`PII_BACKEND=regex`): e-mail, Luhn-valid card and phone patterns with no dependencies. It keeps the hash-locked install and offline unit tests self-contained. A fake HTTP server in the unit tests covers the Presidio adapter, including both fail-closed paths.

Presidio is configured for English with entity types PERSON, EMAIL_ADDRESS, PHONE_NUMBER, CREDIT_CARD, IBAN_CODE, US_SSN and IP_ADDRESS. DATE_TIME, LOCATION and NRP are excluded on purpose, because policy text is full of dates and place-like nouns.

Evaluation cases that only Presidio can satisfy (a name in a question, a named person in a retrieved document, an IBAN) carry `requires: presidio`. They are skipped in regex mode and run in a separate CI job against the Presidio containers. On the regex backend those cases fail as expected: the name in the roster reaches the answer.

Injection rules run on normalized text (NFKC, invisible characters removed, case-folded, whitespace collapsed), so zero-width and full-width obfuscation do not bypass them. Each rule pairs an action verb with an instruction-like target to keep ordinary policy questions answerable. Credential-exfiltration wording is checked on documents and answers but not on questions, because a user asking "should I send my token to X?" is legitimate.

A blocked request returns a policy refusal without retrieving anything, so it cannot reveal document titles or identifiers. Confidence and citations are computed only from context that survived quarantine. Redaction placeholders are removed from the retrieval query.

Verdict codes, not matched text, are recorded in the audit event, the operational event, the API response, and the `rag_policy_verdicts_total` metric. They tell an operator which control fired without moving prompt content into general telemetry.

The evaluation suite holds adversarial and benign-probe cases next to grounded ones. CI fails if any non-waived case fails. `--compare` runs the same cases without guardrails, so the effect of the layer is measured rather than asserted.

## Consequences

- direct and indirect injection, PII in both directions, and prompt echo are covered by tests and by the evaluation gate;
- the benign-probe category makes false positives visible; a rule change that blocks a legitimate question fails CI;
- injection rules are English-only pattern rules and are bypassable by paraphrase, other languages, encodings, and multi-turn setups; they demonstrate where policy runs, not state-of-the-art injection detection;
- Presidio's NER recall depends on the spaCy model in the analyzer image; names that the model does not tag as PERSON pass through;
- Presidio's e-mail recognizer validates the top-level domain against the public suffix list, so addresses on non-public domains (`.example`, `.local`, `.corp`, an internal mail zone) are not detected; this surfaced in the evaluation, where the regex fallback caught an address Presidio missed. Deployments with internal mail domains need a custom recognizer;
- Presidio adds a network hop and a dependency on two more services; fail-closed means a Presidio outage stops the assistant, which is the intended trade-off;
- the Presidio and LiteLLM images are referenced by tag, not yet by digest like the other images;
- chunk-level quarantine drops a whole chunk, including any useful text around the injected instruction;
- the `Guardrails` methods are the substitution point for a trained prompt-injection classifier, as `PiiRedactor` already is for personal data; LiteLLM's guardrail list is the matching place at the gateway layer.
