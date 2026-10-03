# AI service incident response

An incident is declared when the assistant returns unsupported answers, exposes content outside the requested metadata scope, or suffers sustained availability degradation.

The responder first disables external answer generation while keeping health and audit endpoints available. The retrieval index version, gateway route, request identifiers, and policy verdicts are preserved. Raw prompts are read only through the restricted audit process.

Recovery requires a synthetic regression evaluation, an index integrity check, and approval from the incident commander. Operational logs alone must not be used to reconstruct prompt content.

