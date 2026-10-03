# Third-party inventory and license evidence

The reference application is **All Rights Reserved**, as declared in `pyproject.toml`.
This document does not grant a redistribution license for dependencies or hosted
services. CycloneDX inventories and [license metadata](sbom-4aa3909/licenses.csv) are
produced by hash-verified **Syft 1.54.0**. The [inventory index](sbom-4aa3909/index.json)
records actual Docker image IDs; platform packages and wheels come from pinned
images/locked requirements. `UNCONFIRMED` means supporting license metadata was
not available; it is not an inferred permissive license. Findings or unknown
licenses must be reviewed before redistributing a complete container supply.

| Artifact / dependency | Version or identity | License evidence / use |
|---|---|---|
| Syft | 1.54.0, official release checksum verified | Apache-2.0, operator inventory tool |
| spaCy Russian pipeline | ru_core_news_sm 3.8.0 | MIT in official model release metadata |
| Russian wheel | SHA-256 `69978d47b43e2c4f329bebdb155e8e9d3861bba1a58ba25551419dae7d7e07fc` | Verified before pip installation; CPU pipeline |
| English spaCy pipeline | en_core_web_lg in pinned Presidio image | Exact installed version and license in analyzer inventory |
| faster-whisper small | revision `536b0662742c02347bc0e980a01041f333bce120` | Systran model metadata; derivative weights separately identified |
| Tesseract language packs | eng/rus, installed Debian package versions | OS package inventory; OCR data follows its package metadata |
| Presidio | analyzer/anonymizer pinned base images | MIT project; transitive OS/Python licenses enumerated separately |
| Open WebUI | 0.11.4 slim digest pinned in Compose | Custom upstream license; review the exact image's bundled notices, not an assumed MIT license |
| LiteLLM | immutable image digest in Compose | Project and included dependencies enumerated in its inventory |
| PostgreSQL / pgvector | PostgreSQL 17, pgvector 0.8.6 image | PostgreSQL license plus OS/transitive package notices |
| eSpeak-ng | installed Debian version in fixture image | GPL-3.0-or-later tool, test generation only; absent from deployed inspector |
| macOS Milena | installed OS voice, physical fixture hashes recorded | Proprietary OS component; redistribution rights unconfirmed. Generated RU speech remains private and is excluded from the video |
| Jev / hosted chat, embedding, rerank | fixed aliases in report/configuration | Remote service terms; no model binaries redistributed |

Pymorphy, Russian dictionaries and `dawg2-python` are hash-locked in
`infra/presidio/requirements-ru.lock`; package notices are retained in the analyzer
image inventory. The SBOM application document marks lock-derived supplementary
components explicitly because Syft's directory cataloger did not recognize the
`.lock` filenames. Model revisions/checksums supplement package discovery: an
SBOM cataloger is not proof that every model/data artifact was recognized.

Official references: [Syft](https://github.com/anchore/syft),
[spaCy Russian model](https://github.com/explosion/spacy-models/releases/tag/ru_core_news_sm-3.8.0),
[faster-whisper small](https://huggingface.co/Systran/faster-whisper-small),
[Open WebUI license](https://github.com/open-webui/open-webui/blob/v0.11.4/LICENSE).

The final inventory also includes the portfolio npm lock, OAuth2 Proxy, Fluent Bit, Loki and Prometheus images. [Model and OCR artifact hashes](model-artifacts-4aa3909.json) supplement directory/package cataloging and are embedded as explicit file components in the application CycloneDX document. The historical `sbom/` inventory remains unchanged. Unknown licenses are enumerated, not declared cleared.
