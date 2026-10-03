.PHONY: index test eval eval-presidio presidio-up gateway-up smoke-presidio test-presidio publication-check verify walkthrough verify-gateway report verify-telemetry verify-google-sso

PYTHON ?= python3
COMPOSE = docker compose -f infra/docker-compose.yml

index:
	$(PYTHON) -m ingestion.build_index --source sample-data --output .local/index.json

test:
	$(PYTHON) -m unittest discover -s tests -v

eval: index
	PYTHONPATH=".:apps/rag-assistant" $(PYTHON) evals/run.py --index .local/index.json --cases evals/cases.jsonl \
		--compare --report evals/report.md

eval-presidio: index
	PYTHONPATH=".:apps/rag-assistant" $(PYTHON) evals/run.py --index .local/index.json --cases evals/cases.jsonl \
		--pii-backend presidio --compare --report evals/report-presidio.md

# Presidio analyzer (127.0.0.1:5002) and anonymizer (127.0.0.1:5001).
presidio-up:
	$(COMPOSE) up -d --wait presidio-analyzer presidio-anonymizer

# Presidio plus the LiteLLM gateway (127.0.0.1:4000) with Presidio guardrails.
gateway-up:
	$(COMPOSE) --profile gateway up -d --wait presidio-analyzer presidio-anonymizer litellm

smoke-presidio:
	$(PYTHON) scripts/smoke_presidio.py

test-presidio:
	PRESIDIO_INTEGRATION=1 $(PYTHON) -m unittest tests.test_guardrails -v

publication-check:
	$(PYTHON) scripts/pre_publication_check.py

walkthrough:
	$(PYTHON) scripts/walkthrough.py --report .local/walkthrough.md

verify-gateway:
	$(PYTHON) scripts/verify_gateway.py

verify-telemetry:
	$(PYTHON) scripts/verify_telemetry.py

verify-google-sso:
	$(PYTHON) scripts/verify_google_sso_config.py

report: index
	PYTHONPATH=".:apps/rag-assistant" $(PYTHON) evals/run.py --index .local/index.json --cases evals/cases.jsonl --compare --report docs/evaluation-report.md
	$(PYTHON) scripts/walkthrough.py --report docs/walkthrough-report.md

verify: test eval walkthrough publication-check
