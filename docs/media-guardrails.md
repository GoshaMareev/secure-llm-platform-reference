# Local media privacy checks

Inline attachments in the native Open WebUI profile now pass a mandatory gateway
check before hosted inference. `local-media-1` uses private Tesseract OCR and
faster-whisper-small speech recognition, followed by the same Presidio services
and English injection rules used for text. The caller cannot disable this layer.

| Input | Result before provider routing |
|---|---|
| Inline PNG/JPEG/WebP | Decode, single-frame/dimension checks, local OCR, injection and PII/credential checks. Detected sensitive text blocks the whole image. Allowed pixels are re-encoded as PNG without metadata. |
| Inline WAV/MP3 speech | Decode/resample locally, detect English speech, transcribe, screen instructions, normalize common spoken-email forms and redact PII/credentials. Replace the audio part with text; no raw recording reaches the provider. |
| Ambiguous sensitive speech | A sensitive label such as “email address”, “phone number” or “password” without a corresponding successful redaction blocks the request. |
| Remote URL, video, unknown part/file type | Reject before fetching or provider routing. |
| Inspector/PII unavailable, malformed result, unreviewed ASR revision, low confidence or unsupported speech language | Deny with a stable reason code; never return the raw transcript or decoder error. |

Text parts are rebuilt from their checked text, and unrecognized message fields
and provider media extras cannot carry an unchecked attachment. The check applies
to every media part in the supplied conversation, including historical messages.
The native grounded RAG filter can replace an attachment-bearing user message
with its text question; the plain vision/multimodal aliases are the validated
attachment path. Microphone, TTS and native media-upload controls are not enabled
by this change.

## Privacy and runtime limits

The inspector has no provider credentials, host port or outbound network route.
It runs as an unprivileged user on the internal platform network with a read-only
filesystem, temporary-memory OCR files, a 1.5 GiB memory limit, two CPU cores,
64-process limit and one active inspection. Capacity exhaustion denies a request.
The gateway waits at most 45 seconds per media part; there is no retry or provider
fallback. Up to four parts are allowed per completion, each at most 4 MB decoded.
Images are limited to 4 million pixels. Audio is limited to 30 seconds, one audio
stream, at most stereo and 48 kHz input; recognition uses 16 kHz mono samples.
Extracted text is capped at 12,000 characters.

Tesseract's minimum recognized-word confidence must be at least 0.65. Speech must
have English language probability at least 0.70, per-segment `exp(avg_logprob)`
at least 0.45 and no-speech probability at most 0.60. These thresholds are policy
limits, not measured privacy guarantees. Empty OCR results can permit text-free
images; empty/unreliable speech does not permit audio.

The shared Presidio NER model is English. Cyrillic OCR text and non-English
detected speech are denied. Other image languages, handwriting, tiny/faint text,
rotations, mixed speech and unlabeled spoken secrets are not reliably covered.
The sensitive-label fallback can also reject benign discussions of email or
credentials; this conservative false-positive tradeoff has not been calibrated.
Faces, biometric identity, background voices and non-text visual personal data
are outside this boundary. An OCR/STT confidence score can be high while words
are wrong or omitted; broader representative testing is required before real
sensitive-media use. Native chat/document storage can still retain originals
under its own access and retention policy; gateway redaction does not delete them.

Extracted text, original media and cleaned transcripts are transient and omitted
from both event streams. Events carry request ID, stable verdict, policy version,
media kind, redacted entity kinds and the audio model revision. Jev shadow checks
run afterward and do not receive raw media. The inspector has no access logs,
and content-bearing decoder/model exceptions become a fixed unavailable verdict.

## Model and reproducibility

The model is downloaded at image build time from
[Systran/faster-whisper-small](https://huggingface.co/Systran/faster-whisper-small)
at revision `536b0662742c02347bc0e980a01041f333bce120`. Downloaded LFS hashes are
verified, and the model-file SHA-256 manifest is checked again at service startup.
Runtime downloads are disabled. Python dependencies are pinned with hashes in
[the inspector lockfile](../apps/media-inspector/requirements.lock); the Python
base image is digest-pinned. Debian OCR/TTS packages are installed at build time,
so their package versions can change between builds. TTS exists only in the
test-fixture stage. The CPU recognition setup follows
[faster-whisper](https://github.com/SYSTRAN/faster-whisper) and
[CTranslate2 hardware support](https://opennmt.net/CTranslate2/hardware_support.html);
OCR confidence comes from [Tesseract TSV output](https://tesseract-ocr.github.io/tessdoc/Command-Line-Usage.html).

```bash
# Build public model artifacts, run isolated local OCR/STT/Presidio checks,
# then remove only the test project's containers/network.
make test-media

# Reuse an existing private stack without stopping any of its services.
python3 scripts/test_media_boundaries.py \
  --network secure-llm-platform-reference_platform
```

Fixtures are locally rendered screenshots and offline eSpeak speech containing
fictional values. No provider key is read or mounted. Only the build needs public
network access; runtime test containers cannot reach the internet. Generated
media stays under `.local/media-evaluation/fixtures`; the report contains case
IDs, verdicts, booleans, latency and source hashes. CI runs the isolated version
and publishes only that JSON report.

## Observed evaluation

On 2026-10-03, the actual OCR/STT + Presidio + gateway callback checks passed
**18/18** on synthetic fixtures. See [machine-readable evidence](media-evaluation.json).
The tests cover image email/phone/card/name/credential blocking, media injection,
metadata removal, benign inputs, corruption, dimensions, URL/video rejection,
speech and no-speech handling. They verify that accepted audio becomes text.
The spoken-email fixture was misrecognized despite passing speech confidence;
the sensitive-label fallback blocked it. This observed failure motivates the
fallback and is not evidence of perfect ASR or general PII recall.

The gateway/native policy suites passed **24/24** in pinned images without network
or provider keys. The existing live native RAG/ACL suite passed **28/28** with this
media layer enabled. Native attachments passed **6/6** checks through a regular
user's WebUI chat API, with denial verdicts correlated in the private audit
stream and hosted responses for the allowed image and speech fixtures. Results are recorded in
[the native media report](media-native-evaluation.json). These are bounded control
tests, not a production privacy, jailbreak or transcription-quality benchmark.

To repeat native media checks, first generate fixtures with the local runner
above and recreate the full stack so its verifier mount is present. Then copy
only those synthetic fixtures into the WebUI temporary filesystem:

```bash
docker exec secure-llm-platform-reference-open-webui-1 mkdir -p /tmp/media-fixtures
tar -C .local/media-evaluation/fixtures -cf - . | \
  docker exec -i secure-llm-platform-reference-open-webui-1 \
  tar -xf - -C /tmp/media-fixtures
# This command incurs hosted model charges for accepted synthetic attachments.
docker exec secure-llm-platform-reference-open-webui-1 \
  python /reference/verify-native-media.py --fixtures /tmp/media-fixtures --live
docker exec secure-llm-platform-reference-open-webui-1 rm -r /tmp/media-fixtures
```

Native WebUI deliberately presents a generic policy-denial message. The verifier
checks HTTP status and the corresponding media verdict in the private audit
stream; its public report contains only verdicts, request IDs and booleans.
