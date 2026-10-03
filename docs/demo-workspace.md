# Two-minute workspace walkthrough

The browser workspace at `/` uses the same protected API as Swagger. It has no
frontend role selector: `/v1/session` reports the current subject's server-owned
permissions, and `/v1/ask` enforces those permissions independently on every call.
No Google emails, subject IDs, tokens or client secrets are displayed.

## Start

Follow [Google SSO setup](google-sso.md) and enroll an engineer and a reader.
Open **http://localhost:4180/**. Google login leads directly into the workspace.
The access card shows the current role and document audiences. For an offline
preview, follow the Python quickstart in the README and open
**http://127.0.0.1:8000/**; that mode clearly says **Local operator configuration**.

## Present the boundary

| Step | Account / preset | Expected result |
| --- | --- | --- |
| 1 | Engineer → Production access | Answer with permitted sources and a request ID. |
| 2 | Engineer → No evidence | Insufficient evidence; no citations. |
| 3 | Engineer → Prompt injection | Request blocked; `input_injection_blocked`; no citations. |
| 4 | Switch account → Reader → Production access | Insufficient evidence; engineering sources are not disclosed. |
| 5 | Reader → Restricted scope | Access denied; `scope_access_denied`; caller filters and `actor_id` cannot expand access. |
| 6 | Reader → Public policy | Answer citing `model-usage`, available to both roles. |

**Request details** exposes the submitted synthetic payload, including the spoof
attempt in Restricted scope. **Copy ID** copies only the response's request ID.
Use it with the [event walkthrough](walkthrough.md)
to find the separate operational and audit records. The UI does not claim to
have fetched those records or to possess administrative log access.

Switch account clears the proxy cookie and starts login again. Google may still
remember its account; choose the intended account in Google's account chooser.
An expired API session returns 401 and disables asking until the user signs in.
An authenticated but unassigned subject receives 403 and no document permissions.

## Reference boundaries

The current demonstration uses fictional documents, deterministic retrieval,
an extractive demo gateway and live Presidio in Compose. It verifies the stated
identity and policy paths; it does not demonstrate production model quality.
The footer reports the actual gateway mode and whether guardrails are enabled.
Existing retrieval-quality limitations remain in the evaluation reports.

The workspace uses local static HTML/CSS/JavaScript with no CDN or new runtime
dependency. API/session responses are not cached; content is rendered as text,
with a restrictive CSP and no inline scripts. Loading and network/session errors
are explicit. Changing the question clears the previous result, and pending
requests disable the composer to avoid showing an answer to a different question.

## Verification

Run the HTTP authorization/header tests and existing regression suite:

```bash
python -m unittest discover -s tests -v
make verify-google-sso
make test-presidio
make report
```

These automated tests verify server behavior and configuration. The real browser
checks are documented in [Google SSO validation](google-sso-validation.md).
