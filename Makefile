.PHONY: index test eval eval-presidio publication-check verify

index:
	python -m ingestion.build_index --source sample-data --output .local/index.json

test:
	python -m unittest discover -s tests -v

eval: index
	PYTHONPATH=".:apps/rag-assistant" python evals/run.py --index .local/index.json --cases evals/cases.jsonl \
		--compare --report evals/report.md

eval-presidio: index
	PYTHONPATH=".:apps/rag-assistant" python evals/run.py --index .local/index.json --cases evals/cases.jsonl \
		--pii-backend presidio --compare --report evals/report-presidio.md

publication-check:
	python scripts/pre_publication_check.py

verify: test eval publication-check

