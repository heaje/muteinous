# Initial-release scope (D159)

This summary is subordinate to the full [Architecture Decision Log](architecture/decisions.md).

## Included

- Conservative discovery/probing of candidate game installations and actual supported content capabilities, without maintained title-specific logic.
- User-initiated, source-valid comprehensive scanning and speech analysis, with clear evidence, coverage, uncertainty, and distinction between source-backed text and inferred transcripts.
- Read-only review of detected content and safe original-versus-censored audio previews.
- Word lists/presets and effective censorship settings, including re-evaluation when settings change.
- Explicit **Apply**, with validation of the complete selected required-edit scope, safe native asset preparation, installation ownership, verified originals, backups/recovery, and fidelity safeguards.
- Honest reporting of unsupported/unresolved content; only explicitly selected, independently safe partial scope may proceed under the relevant decisions.

Scanning, review, preview, and settings changes must not write game-facing files. Never silently shrink selected scope after a preparation failure, infer missing word timings or native subtitles, or claim full-game coverage without evidence.

## Deferred beyond initial release

Per-occurrence Censor/Don't Censor editing; manual audio-range authoring; corrected transcripts; bulk review changes; import/export; review Undo/Redo. Their architecture decisions remain preserved but do not authorize implementing them in the initial release.

## Definition of safe release

The initial release must pass applicable source-validity, edit-completeness, PCM timing/fidelity, storage-integrity, installation ownership, backup/recovery, game-running/update-safety, and conservative-error requirements. See D159 and all cross-referenced decisions for the normative detail.
