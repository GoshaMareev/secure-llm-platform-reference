# Baseline failure analysis

Historical reports remain unchanged. Synthetic raw offline diagnostics are private under `.local/implementation/baseline-0f47fa2`; no historical native raw trace was recorded. All 13 failures have an explicit observable explanation. Infrastructure errors are never treated as abstention.

| Backend | Case | Cause | Explanation |
|---|---|---|---|
| offline | access-approval-2 | evidence sufficiency | Paraphrased authorization/activation terms dilute lexical confidence; screened evidence contains both approvers. |
| offline | access-expiry-1 | extraction | Approval sentence wins shared access vocabulary; adjacent expiry sentence is not extracted. |
| offline | access-expiry-2 | extraction | Question about expiry retrieves the correct document but selects the approval sentence. |
| offline | access-expiry-3 | extraction | Indefinite-access premise is not corrected using the adjacent sixty-minute sentence. |
| offline | model-routing-3 | generation completeness | Classification is included, but the adjacent mandatory local inference route is omitted. |
| offline | incident-2 | evidence sufficiency | Preserve/responders paraphrases lower confidence despite the evidence sentence being present. |
| offline | multi-access | evidence sufficiency and extraction | Compound question dilutes lexical confidence; one-sentence extraction cannot cover approval and expiry. |
| offline | multi-recovery | evidence sufficiency and extraction | Compound question is refused despite preservation and recovery evidence in the allowed document. |
| offline | ru-access | tokenization | ASCII tokenization ignores Cyrillic question terms; production alone selects an unrelated routine sentence. |
| offline | ru-expiry | tokenization | Cyrillic expiry question reduces to break-glass; approval sentence wins. |
| offline | access-distractor | evidence sufficiency | Generic production/access overlap is accepted without evidence for the requested password. |
| offline | incident-distractor | evidence sufficiency | Generic incident/commander overlap is accepted without salary evidence. |
| native-openwebui | model-routing-3 | generation completeness | Classification is included, but the adjacent mandatory local inference route is omitted. |
