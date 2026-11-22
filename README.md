# Muteinous v2

Muteinous v2 is the new Windows-first desktop application for source-aware profanity censorship of supported video-game content. Its architecture avoids maintained game-specific knowledge and prioritizes preserving original data and native asset fidelity.

**Current state:** architecture decisions D01–D161 agreed; implementation-readiness review concluded **ready with nonblocking open items**. This branch contains **documentation handoff only**; no runnable v2 application or CI has been established.

## For coding agents and contributors

1. Read [`AGENTS.md`](AGENTS.md), then the [initial-release scope](docs/release-scope.md) and the applicable **full architecture decisions**.
2. Use [code organization](docs/architecture/code-organization.md) and [test policy](docs/testing.md) when implementing.
3. Check [implementation/development workflow](docs/development.md), [decision coverage](docs/architecture/decision-coverage.md) and [temporary handoffs/findings](.agent/README.md) before repeating investigations.

## Architecture decision history

[`docs/architecture/decisions.md`](docs/architecture/decisions.md) contains the complete D01–D161 historical text, with D70 superseded by D71 and the D159 initial-release reduction preserved. The source [ChatGPT Space Architecture Decision Log](https://chatgpt.com/space/page_35393eb6e1848191ae3624e3148e3dbd) remains canonical **until an explicit repository transition is approved**. The committed snapshot is intentionally usable by coding agents who cannot read ChatGPT Space.

Do not import old game's title-specific Hushpatch adapter logic or fixtures: any supported native format/engine capability must be established through reusable evidence-driven mechanisms (D132–D133).
