# Contributing to LiveAvatarDirector

## Project Intent

LiveAvatarDirector aims to be a dependable open-source production tool, not only a model demonstration.

Contributions should improve reliability, persistence, usability, extensibility, observability, or output quality.

## Before Coding

1. Read `PLAN.md`.
2. Read `ARCHITECTURE.md`.
3. Check `ROADMAP.md`.
4. Search existing issues and pull requests.
5. Discuss large architectural changes before implementation.

## Contribution Rules

- Preserve upstream LiveAvatar behavior.
- Keep engine patches small.
- Add application features outside upstream engine directories where possible.
- Do not introduce important container-local state.
- Make long-running operations idempotent.
- Add tests.
- Document environment variables.
- Do not expose controls that have no effect.
- Do not claim resume behavior that has not been verified.

## Development Setup

Use Docker for reproducible deployment.

Use a mock renderer for most development and CI.

Real GPU tests should remain optional.

## Pull Requests

A pull request should include:

- problem statement,
- implementation summary,
- files changed,
- schema or migration impact,
- storage impact,
- API impact,
- tests,
- screenshots for UI changes,
- limitations,
- rollback notes.

## Commit Style

Prefer focused commits.

Examples:

```text
feat(projects): add persistent project metadata
fix(recovery): reconcile stale running jobs on startup
test(storage): verify outputs survive container recreation
docs(renderer): document LiveAvatar capability contract
```

## Tests

Required before submission:

```text
unit tests
integration tests
formatting
lint
type checks
docker build
health check
```

GPU smoke tests are required only for renderer changes when hardware is available.

## Database Changes

Use migrations.

Never replace an existing database file.

Never modify production data directly in migration code without backup-safe behavior.

## Storage Changes

All new persistent files must live under configured data roots.

Every new path must be documented.

## UI Changes

The UI must:

- derive state from API,
- survive refresh,
- handle reconnect,
- show failure states,
- avoid hidden destructive actions,
- remain usable with long-running jobs.

## Security

Never accept arbitrary filesystem paths from the client.

Never allow traversal outside managed roots.

Never log secrets or raw private media.

## Upstream Sync

Keep an `upstream` remote for Alibaba-Quark/LiveAvatar.

Prefer adapters over invasive engine changes.
