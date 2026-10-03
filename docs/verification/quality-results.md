# RAG quality — versioned synthetic evidence

Text runtime: `4aa3909b5d34941353f13bdfea5e9fd2e8d4ad1e`. Corpus:
`northstar-reference@1.1.0`, manifest
`3db86a97a0d539ac8d71457debe5ab0d463d29fcf36ee1e9261f53acd41a1873`.
Individual reports record suite/evaluator/policy/configuration hashes, pinned images,
model parameters and per-case outcomes. Synthetic raw queries, responses and retrieved
fragments remain in `.local`; these public reports contain measurements and causes.

| Measurement | Result | Evidence |
|---|---|---|
| Native original core, repetition 1 | 32/32 | [report](native-core-r1-4aa3909.json) |
| Native original core, repetition 2 | 32/32 | [report](native-core-r2-4aa3909.json) |
| Native original core, repetition 3 | 32/32 | [report](native-core-r3-4aa3909.json) |
| Offline original core | 32/32, no prior-success regressions | [final report](offline-core-2421193.json) |
| Native expanded | 125/128 = 97.66% | [report](native-expanded-4aa3909.json) |
| Development / holdout | 63/64 / 30/32 = 93.75% holdout | [report](native-expanded-4aa3909.json) |
| Native access/policy/media boundaries | 28/28 access/policy; 6/6 original media API | [ACL](native-acl-63f1b26.json), [media](native-media-4aa3909.json) |

The original 32 are unchanged. The additional 96 contain 48 English and 48 Russian
cases, split before inference into 64 development and 32 holdout (16 of each language).
Fixed thresholds remain: three strict core runs; offline at least 28/32; native expanded
at least 95%; holdout at least 90%; all access/privacy/critical refusal checks strict.
Infrastructure, capacity and policy-service failures never count as grounded abstentions.

The evaluator tests partial facts, negation in both directions, contradiction,
keyword-only answers, invented numeric citations and service failures. It is an observable
phrase/fact checker, not a universal semantic judge. Three automatic failures remain:
`expanded-07-en` (development) and `expanded-09-ru`, `expanded-18-ru` (holdout).
Source inspection found faithful paraphrases that the frozen alternatives did not match;
the failures have not been waived and no holdout-derived tuning was applied.

All 32 holdout responses were inspected against authorized documents by Codex. This is
source-based manual inspection, **not independent human review**. One answer has an
unsupported placeholder-specific preface despite correct required policy facts; seven
of sixteen Russian holdout responses are English. A refusal uses composite citation syntax
not parsed by the numeric mapper. See [per-case review](holdout-review-4aa3909.md).
These issues are outside the frozen numeric gate and remain visible limitations.

Native models, pgvector, embedding and reranker are unchanged. The prompt now requires
all requested conditions/exceptions and source-backed routing facts, including the local
route for restricted content. Offline reference extracts complementary sentences from
permitted documents with Unicode tokenization and a bilingual glossary. It stays
deterministic and extractive; the core score does not imply fluent bilingual generation.

[Historical failure analysis](baseline-causes.md) explains all 12 offline and one native
baseline failure. The baseline was 20/32 offline and 31/32 native. The first expanded
native trial was [119/128](native-expanded-1b03896.json); it failed the unchanged 95% gate.
Historical reports and baseline files have not been overwritten. An early offline smoke
ran the full suite before a group filter existed; no holdout case outcomes were used for
tuning. Subsequent changes used core/development errors. This protocol deviation is
recorded rather than describing holdout as wholly untouched by execution.

Corpus 1.1.0 changes glossary only, with document facts unchanged and a complete 1.0.0
snapshot retained. [Lifecycle evidence](corpus-lifecycle-1b03896.json) covers interrupted
upload, retry, idempotent bootstrap, byte-hash rejection, stale model denial and rollback.
Activation consists of several upstream API calls and fails closed on inconsistent state;
it is not a transactional multi-model database operation.

Final independent API extractor revision is `24211939c4b3bf56275629c5d7f5ba51845e66c7`.
CI at375c2a7 exposed eight regex/nine Presidio legacy-suite regressions from counting
grammatical action words and masked contact noise as unsupported facts. Exact grammar words
and already-masked declarative/recipient normalization restore the original gates; factual
question clauses and unknown specific nouns remain checked. [API regression evidence](api-regression-final.json)
is42/43 with actual Presidio,39/40 with regex, retaining the sole previously documented
`benign-system-word` limitation. Original quality core remains32/32 with no regressions.
The native prompt/retrieval/gateway/media/audit runtime and frozen suites are unchanged by this fix;
prior native observations retain their actual4aa3909 source. No holdout-based change was made.

Supplemental review rejected the first masked-prefix normalizer because it could discard
a factual imperative beside a mask. Revision2421193 limits removal to complete recognized
contact/card introduction grammar; EN/RU budget imperatives remain refusal regressions.
The [rejected candidate observation](trials/api-regression-07754aa.json) is retained.
