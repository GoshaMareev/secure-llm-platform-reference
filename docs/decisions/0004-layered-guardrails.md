# ADR 0004: Layered guardrails with Presidio PII redaction and an adversarial evaluation gate

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

Personal-data redaction sits behind a `PiiRedactor` interface with two backends:

- **Presidio** (`PII_BACKEND=presidio`, the container default): Microsoft Presidio Analyzer with the spaCy `en_core_web_sm` model and Presidio Anonymizer. It detects names through NER and validates cards (Luhn), IBANs (checksum), phone numbers, US SSNs and IP addresses. DATE_TIME, LOCATION and NRP are excluded on purpose, because policy text is full of dates and place-like nouns.
- **Regex** (`PII_BACKEND=regex`): e-mail, Luhn-valid card and phone patterns with no dependencies. It keeps the hash-locked core install and the offline unit tests self-contained.

Evaluation cases that only Presidio can satisfy (a name in a question, a named person in a retrieved document, an IBAN) carry `requires: presidio`. They are skipped in regex mode and run in a separate CI job with Presidio installed. On the regex backend those cases fail as expected: the name in the roster reaches the answer.

Injection rules run on normalized text (NFKC, invisible characters removed, case-folded, whitespace collapsed), so zero-width and full-width obfuscation do not bypass them. Each rule pairs an action verb with an instruction-like target to keep ordinary policy questions answerable. Credential-exfiltration wording is checked on documents and answers but not on questions, because a user asking "should I send my token to X?" is legitimate.

A blocked request returns a policy refusal without retrieving anything, so it cannot reveal document titles or identifiers. Confidence and citations are computed only from context that survived quarantine. Redaction placeholders are removed from the retrieval query.

Verdict codes, not matched text, are recorded in the audit event, the operational event, the API response, and the `rag_policy_verdicts_total` metric. They tell an operator which control fired without moving prompt content into general telemetry.

The evaluation suite holds adversarial and benign-probe cases next to grounded ones. CI fails if any non-waived case fails. `--compare` runs the same cases without guardrails, so the effect of the layer is measured rather than asserted.

## Consequences

- direct and indirect injection, PII in both directions, and prompt echo are covered by tests and by the evaluation gate;
- the benign-probe category makes false positives visible; a rule change that blocks a legitimate question fails CI;
- injection rules are English-only pattern rules and are bypassable by paraphrase, other languages, encodings, and multi-turn setups; they demonstrate where policy runs, not state-of-the-art injection detection;
- Presidio's NER recall depends on the spaCy model; `en_core_web_sm` trades accuracy for image size, and `PRESIDIO_SPACY_MODEL` can select a larger model;
- `requirements-presidio.txt` is version-bounded but not yet hash-locked like the core dependencies;
- chunk-level quarantine drops a whole chunk, including any useful text around the injected instruction;
- the `Guardrails` methods are the substitution point for a trained prompt-injection classifier, as `PiiRedactor` already is for personal data; the verdict codes and evaluation cases stay the same.
