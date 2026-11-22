# Muteinous v2

Muteinous v2 is a Windows-first desktop application for reviewing and safely applying profanity censorship to supported video-game content. This repository is the new implementation, not a port of the legacy game-specific implementation.

**Status:** architecture reviewed through D161; implementation readiness: **ready with nonblocking open items**. Initial release scope is reduced by D159. There is not yet an application implementation.

## Start here

- [Initial-release scope](docs/release-scope.md)
- [Architecture decisions D01–D161](docs/architecture/decisions.md)
- [Code organization](docs/architecture/code-organization.md)
- [Testing requirements](docs/testing.md)
- [Development and PR workflow](docs/development.md)
- [Decision coverage tracker](docs/architecture/decision-coverage.md)
- [Agent instructions](AGENTS.md) and [temporary handoffs](.agent/README.md)

The original architecture decision log is at https://chatgpt.com/space/page_35393eb6e1848191ae3624e3148e3dbd. The committed decision log is a complete snapshot at documentation handoff. **Until an explicit source-of-truth transition is agreed, the Space page remains canonical.** Do not silently change or reinterpret decisions in either location.

No game-specific maintained adapters, title lists, or fixtures should be introduced; discover capabilities from actual content evidence (D132–D133).
