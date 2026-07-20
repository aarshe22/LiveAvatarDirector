# Implementation Status

## Implemented foundation

- Host-mounted data, models, and cache roots.
- SQLite schema v1 with in-place idempotent migration and WAL durability.
- Portable project folders and atomic JSON sidecars.
- Project CRUD, hashed original asset uploads, and sanitized filenames.
- Smart-blur, padding, and centered-crop portrait normalization without stretching.
- FFmpeg audio normalization/probing and automatic round-up clip planning.
- Renderer registry with LiveAvatar and CI mock backends.
- Persistent single-worker job queue, events, checkpoints, startup reconciliation, retry, and cancellation request state.
- Validated MP4 output with audio/video stream checks and deterministic metadata.
- REST API, reconnecting web UI, file inventory/download, cache inventory, settings, diagnostics, and legacy Gradio link.
- Docker Compose API/worker separation with persistent mounts and GPU assignment.
- GPU worker layers the Studio onto the existing `liveavatar:local` inference runtime; override `LIVEAVATAR_RUNTIME_IMAGE` when using another validated upstream image.

## Honest recovery level

LiveAvatar generation currently reports recovery level 0. Completed preprocessing and analysis artifacts are reused by content-derived paths, but upstream generation is one monolithic call and resumes generation from its start. The mock renderer advertises level 1 for integration testing only.

## Remaining roadmap

Advanced face detection/manual crop UI, waveform/vocal segmentation, protected delete/trash/archive/import/backup workflows, configurable cache cleanup policies, SSE push events, incremental decode, model download management, and director/timeline features remain future phases. The API deliberately does not present these as completed controls.
