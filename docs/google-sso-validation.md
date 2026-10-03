# Google SSO local validation

Validated on 2026-10-03 with two real Google accounts in separate Chrome
profiles, OAuth2 Proxy v7.15.2 (digest pinned in Compose), the containerized API,
live Presidio and the deterministic demo gateway. Only fictional corpus content
was queried. Account identifiers, credentials, cookies and provider screenshots
are excluded from this public report.

| Check | Observed result |
| --- | --- |
| Real login and localhost callback | Both accounts completed Google login; `/oauth2/userinfo` returned distinct stable numeric subjects |
| Identity authenticated without document grant | API returned HTTP 403 before the operator assigned a role |
| Engineer asks about emergency production access | Cited answer: incident commander and platform owner approval |
| Reader asks the same question | Grounded refusal with no restricted citations |
| Reader sends `audience: engineers` and `actor_id: engineer-demo` | Blocked with `scope_access_denied`; no citations |
| Reader queries general model policy | Answer cites only the public `model-usage` document |
| Direct prompt injection | Blocked with `input_injection_blocked`; no citations |
| Unsupported cafeteria question | Grounded refusal; no citations |
| Spoofed proxy identity headers without a session | `/docs` redirected to Google; `/oauth2/userinfo` returned HTTP 401 |
| Remove reader from proxy allowlist, restart proxy | Existing reader session received the proxy's HTTP 403; access restored only after reinstatement |
| Operational/audit correlation | All six successful HTTP exchanges had matching `request_id` events in both volumes, including refusals and blocks |
| Content separation | Operational events had no prompt/answer; default audit events had no raw prompt |

The reader's implicit-denial and public-policy requests also quarantined an
injected fictional context document (`context_injection_quarantined`). They
returned no restricted source and did not follow its instruction.

## Browser workspace validation

The workspace at `/` was checked through real Google sessions on 2026-10-03:
engineer answer, unsupported-question refusal, direct-injection block, reader
implicit refusal, reader filter/body escalation denial, and reader public-policy
answer. All six browser requests had correlated operational/audit events with no
raw prompt or answer in either stream. Both roles were read from `/v1/session`;
no browser role selector or privileged log endpoint was introduced.

The OAuth client credential was rotated locally. Fresh callbacks succeeded with
the replacement secret; the old credential was disabled by the operator. Secrets
and account policy remain outside Git and this report contains no credential values.

Unauthenticated `/` navigation redirects to Google. `/v1/session` and `/v1/ask`
return 401, including requests containing a spoofed forwarded identity header.
The UI's 401 state was separately checked with a protected local fixture: asking
was disabled and a sign-in action appeared. Browser checks of the local reader
fixture verified result clearing on question changes, request-ID copying and
responsive layout at 390 px and 1440 px without horizontal overflow. These local
fixture checks do not substitute for Google callback verification.

Automated checks: 67 Python tests (two live Presidio tests skipped in the offline
run, then passed in the 21-test Presidio suite), Ruff, five offline HTTP
walkthrough scenarios, publication scan including Git history, merged Compose
validation and the pinned proxy's `--config-test` all passed. CI now repeats the
Google configuration checks using synthetic credentials.

Reproduce the real login and request checks with [the setup walkthrough](google-sso.md).
`make verify-google-sso` tests configuration only; it does not log in to Google.
The real account-to-subject policy is operator-owned and remains in the ignored
private local directory. Changing caller filters never changes that policy.

This validates a local identity and authorization flow. HTTPS deployment, real
Entra login, Google Workspace group synchronization and external model inference
remain separate work. It does not demonstrate production deployment or model
jailbreak resistance.
