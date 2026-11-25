# Coding-agent entry point

This is a navigation checklist, not a second architecture or workflow specification. Version-controlled project documentation and current repository evidence govern.

## Engineering principles

Muteinous is an application, not a framework. Implement supported behavior; trust documented controlled internal contracts. Validate external inputs at appropriate boundaries, handle reachable failures, and preserve security, integrity, concurrency and other agreed guarantees. Avoid speculative hardening, incidental test assertions and exhaustive mutation resistance. Follow the [testing policy](docs/testing.md#contract-based-testing) and [review policy](docs/development.md#actionable-review-findings).

## Task routing and discovery

- Select the matching [workflow](.agents/workflows/README.md) automatically, or use the explicitly requested workflow. Clarify material ambiguity about scope, authorization or deliverables.
- Verify the assigned Issue/PR, exact ref, relevant code and tests; complete [agent-note discovery](.agents/README.md#task-start-discovery).
- Read applicable original D-number [decisions](docs/architecture/decisions.md), [release scope](docs/release-scope.md), [code organization](docs/architecture/code-organization.md) and detailed policies as relevant. Follow [architecture governance](docs/development.md#architecture-documentation-governance); do not guess at missing requirements.
- Apply [role-based delegation and independent review](docs/development.md#delegation-and-independent-review). Focused delegates use the scoped discovery procedure; do not assume inherited context.

## Before pausing or completing

- Follow applicable [validation and review](docs/development.md#work-unit-and-review-policy), [decision-coverage evidence rules](docs/architecture/decision-coverage.md#updating-this-tracker), and [knowledge-sharing/handoff procedures](.agents/README.md).
- Link existing repository files with relative Markdown links; use code for hypothetical paths.
