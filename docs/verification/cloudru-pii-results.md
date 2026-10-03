# Russian PII and secret pilot: measured results

Measured 2026-10-04. Local pinned Cloud.ru scanner, configured EN/RU Presidio adapter,
and native gateway callbacks. No hosted model inference. Mode remains **shadow**.

- Cloud.ru: **35/50** annotated values fully masked.
- Benign text: **14/14** unchanged.
- Residual scan: **15/64** cases after Presidio.
- Live callback and fault checks: **7/7** passed.

| Group | Cloud.ru | Configured Presidio |
|---|---|---|
| Names | 8/12 | 8/12 |
| Addresses | 3/6 | 0/6 |
| Contacts | 5/10 | 7/10 |
| Russian identifiers & cards | 10/12 | 9/12 |
| Secrets | 9/10 | 0/10 |
| Benign text | 14/14 | 12/14 |

Counts mean complete annotated-value masking; the benign row means unchanged text.
Partial masking is a miss. Span annotations include formatting characters. Every
miss and benign false positive is retained in [the complete JSON](cloudru-pii-results.json).
Cloud.ru misses: name_lowercase, name_transliterated, name_foreign, name_zero_width, address_lowercase, address_ocr, address_zero_width, email_cyrillic, email_spoken, phone_compact, phone_spoken, phone_ocr, snils_bad_checksum, passport_ocr, secret_password_ru.

The 64-case set has 50 sensitive values and 14 benign probes. It includes deliberate
OCR, lowercase, spoken and Unicode stress cases. This is an authored synthetic
probe suite, not independent production recall or F1. Secrets and addresses are
outside the configured Presidio policy, so aggregate totals do not rank the tools
in general. Presidio covers 7/10 contact probes versus Cloud.ru's 5/10.

Warm sequential local HTTP measurements (64 samples/backend): Cloud.ru p50
2.36 ms / p95 6.14 ms; Presidio p50
10.11 ms / p95 16.46 ms; residual scan
p95 6.92 ms. These include local transport and adapters,
not hosted generation or a production latency SLA.

Residual findings are observations, not extra redaction or validated leak rates.
Callback checks use synthetic signed identities and call hooks directly; they
do not exercise browser SSO or paid inference. Checks cover input/output and audit,
embedding/rerank, scanner outage with mandatory Presidio preserved, capacity,
input count limits and denial before scan for unsigned identity.

Suite SHA-256: `2c9f8e6428f44f0c479aa518e409117b09798435b1bb6d39289437119af2a7b8`. The JSON records runtime image IDs,
source fingerprints and callback scope. [Reproduce the pilot](../cloudru-pii-pilot.md).
