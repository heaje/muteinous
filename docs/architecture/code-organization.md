# Python and test organization — D160

**Normative decision:** [D160](decisions.md) (with D159 release phasing). One installable Python distribution under `src/muteinous/`, not multiple applications or a speculative plugin framework. Names below indicate **responsibility**, not frozen APIs or instructions to add empty directories.

```text
pyproject.toml
src/muteinous/
  models/                    # small, content-neutral shared values/invariants
  core/
    filtering/               # policy, matching, language, concrete edit planning
    speech/                  # ASR/alignment coordination and result validation
    audio/                   # time interval/PCM editing, fades, lossless scratch audio
    ...                      # scan/results/preview/apply/settings coordination
  plugins/
    contracts.py             # smallest justified content-plugin contract
    video_games/             # ONE video-game content plugin
      ...                    # discovery, probing, scanning, reconstruction
      native/                # reusable native-format/engine adapters if needed
  infrastructure/
    sources/                 # verified-original source access
    jobs/                    # bounded in-process work, progress/resources
    storage/                 # result bundles, staging, integrity, optional cache
    installation/            # SHARED game-facing writes, ownership, recovery
    inference/               # real model/backends/devices
    persistence/             # user settings and result persistence
    platform/                # platform-specific implementations only as needed
  ui/desktop/                # initial desktop presentation
  cli/                       # OPTIONAL minimal developer/diagnostic interface

tests/
  unit/                      # models/core/plugins/infrastructure/ui as useful
  contracts/                 # real public plugin contract obligations
  integration/               # safety-critical component boundaries
  e2e/                       # Scan -> Review -> Preview -> Apply -> Restore
  fixtures/                  # tiny generic synthetic data, NOT real games
  support/                   # reusable fakes/factories
```

Create directories and modules only as functionality arrives; this tree is illustrative.

## Dependency direction and ownership

- **`models/`** owns simple shared representations (`Segment` is identity-only; `SpeechAnalysisResult` and recognized-word sequence are immutable). No OS, game, plugin or UI code.
- **`core/`** owns reusable policy and user-workflow coordination: scan/results, filtering, language, speech alignment, safe PCM editing, preview, effective settings and Apply orchestration. Do not move generic censorship algorithms into native adapters. Keep scan validity and immutable speech-result validation aligned with the [source validity](decisions.md#amendment-2026-11-25-source-validity) and [speech results](decisions.md#amendment-2026-11-25-speech-analysis-results) amendments. Keep PCM editing independent of temporary storage encoding through the narrow internal boundary in [D06](decisions.md#d06--bounded-temporary-wav-workflow); select the initial lossless backend from benchmark evidence, not a speculative codec framework.
- **`plugins/video_games/`** discovers actual installations and source capabilities, identifies assets/occurrences/dependencies, extracts/decodes/reconstructs/validates native formats and **proposes staged declarative installation changes**. Its adapter knowledge is format/engine-capability based, not game-title based. Select reconstruction techniques according to the [native reconstruction fidelity amendment](decisions.md#amendment-2026-11-25-native-reconstruction-fidelity), not the convenience of a particular experimental codec. Plugin-native code never claims installation authorization.
- **`infrastructure/`** implements verified originals, job scheduling, immutable results/caches, local inference, persistence and the **only shared installer authorized to write/replace/remove game-facing files**. Not all infrastructure is OS-specific: isolate Windows/Linux/macOS divergences under `platform/` only when necessary (D02, D17–D19).
- **`ui/desktop/`** provides presentation. A fully user-facing `cli/` is **not** in initial-release scope. A small composition entry point wires real components when needed.

In general, models must not import infrastructure, UI or game adapters; core must not depend on concrete game formats or OS internals; plugins use only necessary shared models/contracts/core functions; the installer validates independently rather than trusting plugin paths or plans. See D160 for finer responsibility and exception details.

## Video-game plugin growth

Start flat. Split into `discovery/` (launcher candidates), `scanning/` (source evidence, identities and links), `native/` (reusable format detection/extraction/rebuilding/validation), and `reconstruction/` (group required native edits, stage/validate, propose plan) only when real complexity justifies it. Native adapters are internal implementation pieces, **not** independent content plugins or second SDKs.

No curated game list, per-title exception, hardcoded mod path, real-game fixture or game adapter copied from the earlier [Hushpatch implementation](https://github.com/heaje/hushpatch) (D132–D133). A real-world validation target may inform generic support but must not become a runtime dependency.

## Testing boundaries

Unit tests can mirror component responsibilities; contract tests validate actual public contracts; deterministic integration tests protect source validity, edit completeness, PCM fidelity, storage, jobs and installation; e2e tests cover the initial-release user flow. Tests need not duplicate the exact code folder hierarchy. See [testing policy](../testing.md). Do not scaffold [deferred capabilities](../release-scope.md) in the initial release.
