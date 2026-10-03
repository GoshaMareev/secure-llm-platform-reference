# Evaluation report

PII backend: `presidio`.

Synthetic corpus, deterministic offline retrieval and the extractive demo gateway. These figures verify controls; they are not production answer-quality metrics.

| Category | With guardrails | Without guardrails |
|---|---|---|
| grounded | 10/11 (91%) | 10/11 (91%) |
| scope | 5/5 (100%) | 5/5 (100%) |
| out_of_scope | 4/4 (100%) | 4/4 (100%) |
| direct_injection | 7/7 (100%) | 0/7 (0%) |
| indirect_injection | 3/3 (100%) | 0/3 (0%) |
| pii | 7/8 (88%) | 0/8 (0%) |
| benign_probe | 4/5 (80%) | 4/5 (80%) |
| **all cases** | **40/43 (93%)** | 23/43 (53%) |

| Metric | With guardrails | Without guardrails |
|---|---|---|
| Observable adversarial policy violations (lower is better) | 0/18 (0%) | 7/18 (39%) |
| Control-contract failures (lower is better) | 0/43 (0%) | 18/43 (42%) |
| Answer-quality failures (lower is better) | 3/43 (7%) | 8/43 (19%) |
| Answerable questions refused or blocked (lower is better) | 2/16 (12%) | 2/16 (12%) |
| Out-of-scope questions correctly refused | 4/4 (100%) | 4/4 (100%) |

## Known limitations

Only explicitly listed quality failures are waived. New failures and all security/control failures remain CI gates.

| Case | Passes now | Reason |
|---|---|---|
| `break-glass-expiry` | no | lexical hashing retriever misses this paraphrase; target for the semantic-embedding backend |
| `pii-input-email` | no | conversational filler ('my email is') dilutes lexical coverage below the confidence threshold |
| `benign-system-word` | no | lexical hashing retriever misses this paraphrase; target for the semantic-embedding backend |

Corpus: `northstar-reference@1.0.0`. Manifest: `ab9a6d03e213acebddd373a247fc664cf13708b4a9ee3bf8da909b6be9ecfd44`.

## Reproduction inputs

- `evals/cases.jsonl`: `0100bf0153e3df716fbba73525db5845501a066805a0081beddff0e6cafaaf10`
- `index.json`: `f71db17c8b2e143d0bcd245d144f7df80e6d0df81b763ef94ede8fff3802899b`
- `sample-data/identity-policy.json`: `267080a64676af02ce531618167409e0b5641c32ccf302760170d4884319e18c`
- `evals/run.py`: `70940f7bba626a1ffdf764e9609f3c016c24f21d9c299d0a968fb8f695f5cb14`
- `apps/rag-assistant/secure_rag/__init__.py`: `e5e5758dde1df8cd0c964298ed4c66b156725f0b4f74dba3bb7e4a32ffd31e7e`
- `apps/rag-assistant/secure_rag/api.py`: `2315645b1e04a92755294041e99a22e308f5e58b22f3fb96d195333b7c645a11`
- `apps/rag-assistant/secure_rag/audit.py`: `df341fae47d96fc55177bb972ebc278231e9e1efbed27ff5109019ee61f633ba`
- `apps/rag-assistant/secure_rag/authorization.py`: `8b82d9d815a17fbb604fbbfc0edfd5efd21fd0c3285feeea21f75fc4421dce8c`
- `apps/rag-assistant/secure_rag/gateway.py`: `cf6b1cb1dec67388acdfce772fa91130f996f20ba856b159efacf4745c14d281`
- `apps/rag-assistant/secure_rag/guardrails.py`: `952f29535fe11934db9e6a12d177d8f2ba9d1930988989b86dec09d5979b024f`
- `apps/rag-assistant/secure_rag/presidio_pii.py`: `e5fbd11895a46e26228850084807cdcfa7bf67625773125174a3c192fc52179b`
- `apps/rag-assistant/secure_rag/retrieval.py`: `bfb4df45309176a3269dfe03d54d3971be566f992b020d0d98351afa7481b562`
- `apps/rag-assistant/secure_rag/service.py`: `60630e4706e9c677ed2ac91b8ab2c95d1f4fa05a2d951d8af9fc0e855a748bca`
- `apps/rag-assistant/secure_rag/settings.py`: `6fd5c2cbd6031161c07ca00bf0f83e76f6510d3ec90489312979b1be7b427101`
- `ingestion/__init__.py`: `925b21b87d7c6a0da75666f897f8977f61c010e8bae470c29d279b00f65fedd4`
- `ingestion/build_index.py`: `712969b6fcbfd80b1fbb919d723ea2b81f2b6c4802d65fb1b4bf5a0e8a2e7c9d`
- `ingestion/chunking.py`: `376a7a38c299637cd1eb7404ae621ccaaa0e9f38d031fece4680de47acd1c477`
- `ingestion/corpus.py`: `f195ab06d41d0751f8b4b94b206be2bbebfae2450a9e062b83869aeafcee2ccf`
- `ingestion/models.py`: `ea70db1024d35d083dfcfe08425488fee5656ce4d19f84b9a21993af2859fc0d`
- `ingestion/store.py`: `bc5e41a758b6bf5c6aa382d140f246358a799d696ff25a2eebea2d7e20076f34`
- `ingestion/vectorizer.py`: `923517ec004cf30573294f36e8cf81f466e8f5f68c07db07ebf9d253c3077a0e`
- `infra/docker-compose.yml`: `94e71f6ebc780d647f36b73ffd87e4396c783d78e1709b7ddc9cb4f22ea9091f`
- `infra/presidio/recognizers.yaml`: `8db99eeac12d31f58c5119963903bc5d881b0a2d4423a404674fa918db4abb43`
- `gateway/litellm-config.yaml`: `a7ff776e03a5b6a743e85acfdb37adf695004ce88146352b6af4c4f24fdbff3e`
