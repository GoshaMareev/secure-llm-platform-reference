# Versioned synthetic text corpus

The active corpus is `northstar-reference@1.1.0`. Its release manifest is
[`sample-data/releases/1.1.0.json`](../sample-data/releases/1.1.0.json).

A release records document IDs, titles, paths, metadata (including audience), raw-byte SHA-256 values,
and hashes of the catalog, glossary and identity policy. A canonical manifest digest identifies the complete
release. Document order does not affect the sorted manifest inventory, but catalog changes still change its
canonical hash. These hashes detect drift; they are not signatures or a tamper-evident storage system.

```bash
python -m ingestion.corpus --source sample-data
python -m ingestion.build_index --source sample-data --output .local/index.json
make quality
```

The builder verifies the frozen release before and after ingestion. Index schema 2 embeds that manifest,
a digest of indexed chunks and a fingerprint of the ingestion code. Schema 1 indexes must be rebuilt.
The evaluation runners reject a stale index or a suite targeting another corpus version. API readiness,
answers and audit records identify the release that supplied their evidence.

## Publishing a new version

1. Change synthetic source documents or retrieval/access metadata.
2. Increment `corpus_version` in `sample-data/catalog.json` (numeric `major.minor.patch`).
3. Run `python -m ingestion.corpus --source sample-data --publish`.
4. Update the quality suite's target version and reference facts; rebuild the index and measure the new release.
5. Review its complete case outcomes, then create a new baseline with `--record-baseline NEW_PATH`.
6. Commit source files, manifest, suite and reports together so Git preserves the exact input bytes.

Publishing uses exclusive file creation and cannot overwrite an existing version. Immutable source snapshots live in `sample-data/snapshots/1.0.0`; 1.1.0 changes only the bilingual glossary, not document facts. A manifest alone cannot reconstruct bytes. Bootstrap supports `--release 1.0.0` for the retained snapshot and `--release 1.1.0` for the current source. The installed manifest selects the verified active release; models must match it. Do not edit an old manifest to
make drift checks pass.

## Native Knowledge activation

Bootstrap uses release-specific collection names (`General` / `Engineering`, version and manifest digest).
It verifies the exact document inventory and downloads stored file bytes to check each SHA-256. A filename
match alone no longer skips validation. Partial uploads can be retried: the next run reconciles the same
release collection and rechecks its content.

Only after both collections pass validation does bootstrap point the two RAG models to the release and
write the operator manifest with native file/collection IDs. It clears read grants on the previously managed
collections and preserves their contents for rollback. Activation uses several upstream API calls and is
not transactional: a failed activation requires a bootstrap retry. The global filter blocks a model whose
version/digest disagrees with the verified installed release. Live evaluation checks native inventory and
stored bytes before and after running, as well as the models' assigned collection scopes.

The release contains synthetic **text**. Media has a separate fixed-suite verification path and does not become an authorized corpus source. See [lifecycle evidence](verification/corpus-lifecycle-1b03896.json) and [media results](verification/media-results.md).
