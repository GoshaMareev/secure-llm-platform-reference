# Media privacy and language evidence

The frozen suite contains 64 cases: 32 images and 32 audio recordings, equally EN/RU.
Each language/kind has six benign controls, four PII, three credential and three instruction
cases. Questions/labels and the 90% benign threshold were fixed before measurements.
Physical fixture hashes and generation platform are recorded before recognition.

The accepted [natural-voice candidate](media-natural-final.json), policy `local-media-4`,
passes classification 64/64, benign controls 24/24, and reports zero **potential sensitive
escapes**. Mean normalized recognition similarity is 0.93794; this is a SequenceMatcher
proxy, not word-error rate. It uses eSpeak EN and installed macOS Milena RU. Milena artifacts
stay private because redistribution rights are unconfirmed. The portable eSpeak RU stress
set has poorer recognition and is reported separately; it is not silently substituted.

Local candidate evaluation uses actual CPU Tesseract eng/rus, pinned Whisper-small and
mandatory EN/RU Presidio, but does **not** call a model provider. Potential-escape checks,
recognition and classification are separate measurements. The [final native API smoke](native-media-final.json)
uses a regular user and eight EN/RU fixtures through actual gateway/provider routing. Sensitive
image/instruction cases block; safe speech becomes checked text; original audio is discarded.
Gateway boundary tests establish replacement of media before upstream calls. No blanket
claim of sensitive-value recall or universal media privacy follows from these finite tests.

Jev observes cleaned OCR/STT as untrusted input; it never grants document access or makes
media an authorized RAG source. It remains shadow. RU media is disabled by default and
requires an explicit operator flag after accepted verification; callers cannot choose a
language to bypass PII. Cyrillic text additionally requires the pinned RU analyzer; spans
are merged before masking. The RU wheel has SHA-256
`69978d47b43e2c4f329bebdb155e8e9d3861bba1a58ba25551419dae7d7e07fc` and MIT metadata.

Earlier [eSpeak trial](trials/media-espeak-trial1.json) found two potential credential
escapes and false blocks; later [natural trial 2](trials/media-natural-trial2.json) and
[trial 3](trials/media-natural-trial3.json) retained instruction misses despite zero
potential PII escapes. They remain rejected evidence. Fixes require a separate mask for
each sensitive cue, neutralize caller-provided mask literals, and reject commands to send
material externally even if ASR misrecognizes the word for a credential.

The final `local-media-4` hardening also rejects colon/equal-labelled credentials with an
unchecked trailing fragment, including multiword and literal-mask variants. Such strict
rules can reject benign trailing commentary. OCR omissions, unlabelled/unsupported secret
forms, faces, biometrics, hidden visual text and arbitrary recordings remain outside the
guarantee. One accepted RU email sample masks a misrecognized fragment as PERSON rather
than reconstructing the full address: its finite privacy check passes, but entity typing
and recognition are imperfect. The media fixed set was used for safety debugging and is
not independent generalization evidence.

The [final portable eSpeak stress run](trials/media-espeak-final.json), under the same policy4,
reports zero potential sensitive escapes but benign18/24 (75%), classification57/64 and mean
recognition similarity0.76180. It fails the unchanged90% benign gate. Russian speech is therefore
operator-gated with this portability limit explicit. [Bilingual text checks](bilingual-final.json)
pass11/11 on actual EN/RU Presidio and input/output rules; they do not establish general recall.
[Model/OCR artifact hashes](model-artifacts-4aa3909.json) and [notices](third-party-notices.md)
identify the measured build. The original18 local boundary checks also pass on final code.
