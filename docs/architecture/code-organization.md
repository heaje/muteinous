# Python code and test organization (D160)

One installable Python distribution rooted at `src/muteinous/`. The layout below is a **directional map**, not an instruction to create empty directories or freeze APIs prematurely.

```text
src/muteinous/
  __init__.py
  models/                  # immutable/domain data and shared representations
  core/
    filtering/             # word matching, language and censorship rules
    speech/                # speech analysis and timings
    audio/                 # safe audio processing and previews
  plugins/
    contracts.py           # only contracts justified by actual use
    video_games/           # one content plugin; generic engine/native adapters
  infrastructure/
    ...                    # originals, jobs, storage/cache, install, inference,
                           # persistence and platform integrations as needed
  ui/
    desktop/               # desktop presentation and user interaction
  cli/                     # optional minimal developer commands; not full CLI

tests/
  unit/
  contracts/
  integration/
  e2e/
  fixtures/                # synthetic, not game-title-specific
  support/
```

`models/` replaces earlier `domain/`; `core/` contains what earlier discussion called `application/`. Infrastructure is **not** synonymous with OS-specific code. Tests approximately mirror production responsibilities where helpful, but are primarily grouped by test boundary and risk.

Create modules and directories when actual behavior demands them. Avoid speculative adapters, interface hierarchies, empty placeholder packages, format schemas, UI toolkit commitments, and future-release editing scaffolding. D132–D133 prohibit maintained game-specific logic, title lists, configuration and fixtures.
