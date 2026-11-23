# Initial-release scope — D159

This summary explains what to implement first. The [architecture decision log](architecture/decisions.md), especially the release-phasing decision D159, controls detailed requirements. Permission to support an optional capability is not a promise that every such path must ship in the first release.

## Initial-release user flow

1. **Discover candidates** from generic launcher/OS evidence or a user-selected folder. Automatic bounded **read-only lightweight probes** may indicate provisional capabilities; neither startup nor merely choosing a game launches a comprehensive scan (D132–D133, D137–D138).
2. **User explicitly requests a comprehensive scan.** Inspect supported assets, preserve source identities/validity, assess likely speech using proportional generic methods and analyze speech where warranted. Do **not** indiscriminately run ASR on every audio file, infer absent native subtitles or claim complete coverage from incomplete evidence (D10–D15, D21, D30–D31, D138–D140).
3. **Show read-only results.** Distinguish exact source-backed native text, inferred speech transcripts, valid timed detections, unknown/unaligned words, unsupported/uninspected content, language-coverage limitations and uncertain speech roles/links. Searching/filtering and selecting an occurrence to **preview** is not a per-occurrence censorship override.
4. **Preview verified audio safely.** Offer user-selected and a small set of suggested actual scanned dialogue examples, with original and temporarily censored versions produced using the shared core PCM path for **verified, applicable intervals**. Preview never changes the game and does not prove format rebuilding, loader acceptance or Apply safety (D146).
5. **Edit global/appropriate per-content word lists, presets and effective censorship settings.** Reevaluate relevant outcomes/invalidation as decisions require; saving settings and previewing are independent of Apply (D40–D46).
6. **Explicit Apply** to an independently supported, **user-selected scope** after validating all required edits, native reconstruction, freshness, audio/text fidelity and installation authority. Every requested required edit in that scope must succeed before the plan is accepted; no automatic post-failure scope reduction. Maintain verified originals, ownership, backup/restore, game-running and game-update protection (D01–D02, D05, D10–D19, D24, D141–D143).

## Initial language support — D51–D57

The initial release officially supports **English-language filtering only** (D51). Skip known unsupported-language occurrences and report the exclusion; for unknown-language occurrences, attempt English filtering with **unverified language coverage**, not a claim that the content is English (D52–D54). Assess independently filterable occurrences separately when an asset contains multiple languages (D53). Within a single known mixed-language occurrence, filter only reliably isolated English portions; otherwise skip it and report incomplete coverage (D55). Language-coverage limitations produce **nonblocking warnings** for an otherwise safe Apply (D56–D57), not exemptions from required edits or other safety gates.

## Refuse rather than fabricate

An unresolved required censorship edit, missing valid word timing, unsupported or ambiguous audio/text role, uncertain relationship needed for the proposed edit, stale evidence, unsupported native reconstruction or unsafe install destination **blocks the affected selected scope**. The initial release must not silently bypass these cases because advanced source-bound user approvals are deferred. A separately supported, independently safe partial scope can be **explicitly selected before preparation**, with clear non-censored/unknown coverage reporting (D72–D76, D133, D143, D159).

Nonblocking **language-coverage exclusions** remain separately governed by D51–D57; do not relabel a missing required edit as a language warning. Optional D134 key entry and D135 reversible experimental loader tests have independent safeguards **if offered** and do not waive native validation or install safety. For D136/D140, D159's refusal obligations apply now; whether the first release offers these source-bound confirmations is an **open question pending [maintainer review](development.md#architecture-documentation-governance)**. Until decided, do not build the confirmations and refuse any affected requested scope. Large model downloads and updates require the separate approvals and integrity checks of D144–D145.

## Deferred features — preserve the decisions, do not build them yet

Per-occurrence censorship overrides, manual censor ranges, import/export, transcript corrections, bulk review changes and review Undo/Redo are later-phase capabilities under D159, not rescinded requirements. Do not scaffold their UI, state stores, history mechanisms or plugin methods for the initial release. Consult the [decision log](architecture/decisions.md) for each deferred capability's precise scope and dependencies.

## Release evidence

Required representative PR safety tests and complete applicable release checks must substantiate source validity, required-edit completeness, PCM/native fidelity, cache/result integrity, native rebuilding, ownership/recovery and Apply restrictions (D160–D161). Never claim automatic game compatibility or full-game censorship from a successful scan/preview alone.
