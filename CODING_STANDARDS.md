# LiveAvatarDirector — Coding Standards

## Python

- Python 3.10+.
- Use type hints.
- Prefer dataclasses or Pydantic models for structured data.
- Use pathlib.
- Use explicit exceptions.
- Avoid broad `except Exception` unless logging and re-raising or converting at a boundary.
- Keep functions focused.
- Use dependency injection for storage, database, and renderer services.

## Async

Use async for API and I/O orchestration.

Do not run GPU inference directly in the API event loop.

## Database

- Use migrations.
- Use transactions.
- Persist job transitions atomically.
- Keep timestamps in UTC.
- Use UUIDs for external identifiers.

## Filesystem

- Never trust filenames.
- Sanitize uploads.
- Use managed roots.
- Use `.part` files.
- Validate before atomic rename.
- Hash persistent assets.
- Do not overwrite original uploads.

## Idempotency

Every phase must define:

- inputs,
- idempotency key,
- output paths,
- validation,
- retry behavior,
- cleanup behavior.

## Logging

Use structured logs.

Include project and job IDs.

Never log secrets, embeddings, image bytes, or full private transcripts by default.

## API

- Version endpoints when public stability begins.
- Use consistent error envelopes.
- Do not leak internal paths unnecessarily.
- Validate all inputs.
- Keep destructive actions explicit.

## TypeScript

- Strict mode.
- Avoid `any`.
- Use generated API types where practical.
- Treat backend as source of truth.
- Handle reconnect and stale data.

## Frontend State

Do not store canonical job state only in memory.

Refresh state from API.

## Docker

- Pin major dependencies.
- Keep persistent data outside the image.
- Provide health checks.
- Support degraded startup when models are missing.
- Avoid crash loops for recoverable configuration issues.

## Testing

- Unit tests for pure logic.
- Integration tests for persistence and recovery.
- Mock renderer for CI.
- Optional GPU smoke tests.
- Test restart and container recreation explicitly.

## Documentation

Every user-facing setting needs:

- purpose,
- valid range,
- default,
- effect,
- performance impact,
- whether native or prompt-guided.

## Definition of Complete

A feature is complete only when:

- backend works,
- UI works if applicable,
- state persists,
- retries are safe,
- failures are visible,
- tests pass,
- documentation is updated.
