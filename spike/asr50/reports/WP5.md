# WP5 — ASR model-artifact manifest research

**As of 2026-11-26.** Metadata-only research. Hugging Face public model and recursive tree APIs were queried with `Invoke-RestMethod`; no model payload/content URL was fetched. Each revision below is the observed immutable 40-character commit. Sizes are API byte counts. SHA-256 is listed only when supplied as LFS `lfs.oid`; non-LFS files expose git blob SHA-1 only and are not represented as SHA-256.

## Approval-set totals

- **Minimum proposed set:** Whisper Small.en / faster-whisper CT2 — 486,098,798 bytes (0.452 GiB). One candidate for an English-only initial runtime, not a final D47 selection.
- **Full candidate catalog:** 13,652,742,736 bytes (12.715 GiB) summed across 16 listed combo alternatives; not a deployable set because entries are alternatives and some supporting files overlap.
- Per-combo expected installed size is estimated equal to listed download bytes; runtime cache, extraction, and package overhead are excluded.

## Candidate combo manifest

Per-file exact filenames, sizes, LFS SHA-256 or explicit unverified reason, and revision are in the companion [machine-readable manifest](WP5-manifest.json).

| Model/runtime | Revision (repo) | Variant | Download / expected install bytes | License / gating |
|---|---|---|---:|---|
| Whisper Large-v3 Turbo / whisper.cpp | `5359861c739e955e79d9a303bcbc70fb988958b1` (`ggerganov/whisper.cpp`) | q5_0 `ggml-large-v3-turbo-q5_0.bin` | 574,041,195 | MIT / ungated |
| Whisper Large-v3 Turbo / whisper.cpp | same | q8_0 `ggml-large-v3-turbo-q8_0.bin` | 874,188,075 | MIT / ungated |
| Whisper Large-v3 Turbo / faster-whisper CT2 | `4df90f75321148c3a29a9e2351b7ddf8f5b115a8` (`deepdml/faster-whisper-large-v3-turbo-ct2`) | `model.bin`, config, preprocessor, tokenizer, vocabulary | 1,621,665,983 | MIT / ungated |
| Whisper Large-v3 Turbo / ONNX | `360ebcde2559d60bb474678be3c1de9ef347d01a` (`onnx-community/whisper-large-v3-turbo`) | encoder/merged decoder/past decoder q4 + tokenizer/config files | 1,089,188,291 | Unknown API license / ungated |
| Whisper Large-v3 Turbo / ONNX | same | fp16 equivalent trio + tokenizer/config files | 1,940,730,655 | Unknown API license / ungated |
| Whisper Small.en / whisper.cpp | `5359861c739e955e79d9a303bcbc70fb988958b1` (`ggerganov/whisper.cpp`) | q5_1 `ggml-small.en-q5_1.bin` | 190,098,681 | MIT / ungated |
| Whisper Small.en / whisper.cpp | same | q8_0 `ggml-small.en-q8_0.bin` | 264,477,561 | MIT / ungated |
| Whisper Small.en / faster-whisper CT2 | `d1d751a5f8271d482d14ca55d9e2deeebbae577f` (`Systran/faster-whisper-small.en`) | model + config/tokenizer/vocabulary | 486,098,798 | MIT / ungated |
| Parakeet TDT 0.6B v2 / sherpa-onnx | `84b478d541cdbf0c296a7ab5f1e20a6f8f998114` (`csukuangfj/sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8`) | encoder/decoder/joiner int8 + tokens | 661,288,526 | CC-BY-4.0 / ungated |
| Parakeet TDT 0.6B v2 / sherpa-onnx | `a6cc4e24ed264a93a17575dad416dacc4238497a` (`csukuangfj/sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-fp16`) | encoder/decoder/joiner fp16 + tokens | 1,257,157,987 | CC-BY-4.0 / ungated |
| Parakeet TDT 0.6B v2 / NeMo | `c00e38779b028d48624b08ab3d9909952db43901` (`nvidia/parakeet-tdt-0.6b-v2`) | `.nemo` | 2,472,222,720 | CC-BY-4.0 / ungated |
| Moonshine tiny / HF | `390624ed33d594443aa4aa221f5b9f283b545b5a` (`moonshine-ai/moonshine-tiny`) | safetensors + config/generation/preprocessor/tokenizer | 110,376,023 | MIT / ungated |
| Moonshine base / HF | `7a73d8d55ac0ba2ef3ae761593f6784b51f96dcf` (`moonshine-ai/moonshine-base`) | safetensors + config/generation/preprocessor/tokenizer | 248,066,838 | MIT / ungated |
| Moonshine tiny / ONNX | `a6da1241cd305dcd64eab1edbd615f2bb9aabb95` (`onnx-community/moonshine-tiny-ONNX`) | fp16 encoder/merged decoder/past decoder + config/tokenizer | 132,709,711 | MIT / ungated |
| Moonshine base / ONNX | `b1e9b6aae3c3c7298f10c3798393fdf38e8fbbad` (`onnx-community/moonshine-base-ONNX`) | int8 encoder/merged decoder/past decoder + config/tokenizer | 105,876,417 | MIT / ungated |

## Notes, risks, and source evidence

- Whisper.cpp GGML quantized rows are single-file artifacts. Full precision large-v3 Turbo `ggml-large-v3-turbo.bin` is 1,624,555,275 bytes. Its q5_0 is 574,041,195; q8_0 is 874,188,075.
- CT2 rows require model weights plus tokenizer/config/vocabulary assets. Whisper ONNX requires the selected encoder/decoder variant trio, tokenizer/config/generation/preprocessor files, vocabulary and merges as listed in JSON. Do not download multiple variant alternatives together. Verify runtime support and whether `decoder_with_past` is required before approval.
- `alignment_heads` was not exposed as a separate file in these trees. Repository tree metadata alone does not establish word-alignment suitability; inspect pinned config/card and validate behavior before relying on word timestamps.
- Current Parakeet sherpa repos found using HF search: `csukuangfj/sherpa-onnx-nemo-parakeet-tdt-0.6b-v2`, `...-int8`, `...-fp16`. Full inference bundle is encoder + decoder + joiner + `tokens.txt`; variants are alternatives. NVIDIA `.nemo` is a different runtime bundle.
- `UsefulSensors/moonshine-{tiny,base}` and `moonshine-ai/moonshine-{tiny,base}` currently resolve to identical HF revisions/trees. The Moonshine Voice README describes on-device use and links model docs, but this task did not inspect package source/wheel. Therefore exact `moonshine-voice` model fetch host (HF vs other CDN) and filenames remain unknown, not assumed. Sources: https://github.com/moonshine-ai/moonshine and https://moonshine-voice.readthedocs.io/en/latest/models/ (accessed 2026-11-26).
- `onnx-community` Whisper repositories returned no license field in HF API model metadata. Marked unknown; do not infer MIT based on upstream base model. HF metadata gate flags were false on successful lookups. API `Systran/faster-whisper-large-v3-turbo` lookup returned HTTP 401; used accessible `deepdml/faster-whisper-large-v3-turbo-ct2` candidate instead.
- License labels are card metadata, not legal advice. CC-BY-4.0 requires attribution/notice compliance. Check exact pinned license text and applicable model terms before redistribution. Per issue #50, do not mirror models in GitHub Releases.
- Secondary models omitted: Distil-Whisper and medium.en are not necessary to assess listed English candidates. Silero VAD is silence gating, not ASR; only justify if measured scanning cost warrants its own model/dependency.
- Model delivery/approval must follow D144–D145: explicit approval before large downloads, trusted pinned provenance, digest verification before inference, safe staging and offline reuse; model updates/reassessment require explicit user initiation. D47 leaves model/runtime selection open.

## Sources and reproducibility

Hugging Face API endpoints used: `https://huggingface.co/api/models/<repo>` and `https://huggingface.co/api/models/<repo>/tree/<revision>?recursive=true&expand=true`; also public model search for Parakeet and Moonshine. Accessed 2026-11-26. The JSON contains per-file API sizes, LFS digests and non-LFS blob SHAs. No weight payloads were downloaded.

## Summary (<400 words)

Metadata confirms Whisper.cpp GGML quantizations, CT2/ONNX alternatives, current sherpa-onnx Parakeet exports, and HF-hosted Moonshine model candidates with immutable revisions. The smallest listed Whisper Small.en choice is GGML q5_1 at 190,098,681 bytes; the proposed minimum approval set is one faster-whisper Small.en CT2 combo at 486,098,798 bytes. This is a candidate, not a D47 final decision. Parakeet sherpa int8/fp16 exports are viable metadata candidates. Moonshine Voice’s exact runtime download host remains unresolved because package source was not inspected. Non-LFS SHA-256, some license metadata, ONNX compatibility, and word-alignment suitability need follow-up; unknown values are left null/explicitly unknown rather than invented.

Commands: PowerShell `Invoke-RestMethod` against HF model/tree/search endpoints. Elapsed ~15 minutes. No hardware inference/support claim made. No model weights downloaded. Maintainer approval remains required before any payload download or implementation commitment.


## Review correction (2026-11-26)
Moonshine Voice's official docs (moonshine-voice.readthedocs.io/en/latest/using/downloading-models/) name the model host https://download.moonshine.ai/model/<model>/<dated dir> (for example medium-streaming-en/quantized_26_08_21) and .ort component files (adapter, cross_kv, decoder_kv, encoder, frontend model/weights, streaming_config.json, tokenizer.bin). Docs give no fixed commit or per-file SHA-256, so D144 pinning remains an open caveat. The earlier 'host unknown' statement above is superseded.
