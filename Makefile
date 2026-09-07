.PHONY: index test eval publication-check verify

index:
	python -m ingestion.build_index --source sample-data --output .local/index.json

test:
	python -m unittest discover -s tests -v

eval: index
	PYTHONPATH=".:apps/rag-assistant" python evals/run.py --index .local/index.json --cases evals/cases.jsonl

publication-check:
	python scripts/pre_publication_check.py

verify: test eval publication-check

