# AST PCM round-trip and loop metadata
Status: active
Last verified: 2026-11-24
Related: [#20](https://github.com/heaje/muteinous/issues/20), D05–D08
Retire/promote when: final native-format experiment documents or supersedes this evidence.

The [synthetic AST probe](../../experiments/native_ast/README.md) demonstrated byte-exact identity reconstruction using FFmpeg 7.1.5 for a narrow PCM16 stereo profile. FFmpeg's AST loop options operate in integer milliseconds, while the native fields store frame indices; exact preservation of arbitrary loop points cannot be assumed from a successful remux. Verify the native metadata separately or refuse. The result is not evidence for actual shared editing, loader acceptance, Windows support or production readiness. See the linked experiment for reproduction and remaining checks.
