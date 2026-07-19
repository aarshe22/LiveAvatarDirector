# LiveAvatarDirector — Architecture

## 1. Architectural Goal

LiveAvatarDirector separates durable application concerns from renderer-specific inference.

```text
Frontend
   │
   ▼
API
   │
   ├── Projects
   ├── Assets
   ├── Jobs
   ├── Files
   ├── Caches
   ├── Settings
   └── Diagnostics
   │
   ▼
Persistent Database + /data
   │
   ▼
GPU Worker
   │
   ▼
Renderer Plugin
   │
   ▼
LiveAvatar Engine
```

## 2. Process Boundaries

### API Process

Responsibilities:

- CRUD,
- authentication-ready request handling,
- project state,
- job submission,
- file management,
- cache management,
- diagnostics,
- events.

Must not load the 14B model.

### Worker Process

Responsibilities:

- claim jobs,
- own GPU model lifecycle,
- run preprocessing,
- analysis,
- render,
- decode,
- encode,
- checkpoint,
- finalize.

### Frontend Process

Responsibilities:

- render API state,
- reconnect automatically,
- never own canonical job state.

### Legacy Gradio Process

Optional compatibility process.

## 3. Core Domain Objects

### Project

Container for assets, analysis, settings, jobs, and renders.

### Asset

Original or derived media with hash, MIME type, dimensions, duration, and references.

### RenderJob

Persistent state machine representing one render attempt.

### RenderOutput

Validated final or preview media.

### Checkpoint

Validated boundary that enables safe reuse or resume.

### RendererBackend

Plugin that translates generic project intent into renderer execution.

### FileRecord

Indexed persistent file with ownership and reference counts.

### CacheEntry

Managed cache object with references, size, last access, and cleanup eligibility.

## 4. Idempotency Model

Each phase computes an idempotency key from:

```text
phase name
input hashes
settings hash
renderer version
application schema version
```

If a valid output exists for the same key, reuse it.

If a partial output exists, remove or quarantine it before retry.

All final writes use:

```text
target.part
fsync
validate
atomic rename
```

## 5. Recovery Model

On startup:

```text
running -> recovering
recovering -> queued | failed | completed
```

Recovery inspects:

- phase,
- checkpoints,
- file hashes,
- output validity,
- renderer resume capability.

The database and filesystem must be reconciled in both directions.

## 6. Storage Ownership

Every file has:

- project owner,
- optional job owner,
- type,
- persistent path,
- hash,
- references,
- lifecycle state.

No UI delete operation may bypass ownership checks.

## 7. Renderer Capability Contract

The UI derives controls from renderer capabilities.

Example:

```json
{
  "name": "liveavatar",
  "native_lip_sync": true,
  "supports_long_form": true,
  "supports_incremental_decode": false,
  "resume_level": 1,
  "supported_sizes": ["704x384", "512x288"],
  "supported_frames_per_clip": [48],
  "effective_fps": 16
}
```

## 8. Data Flow

```text
Upload
  -> hash
  -> persist original
  -> create Asset
  -> normalize
  -> checkpoint
  -> analyze
  -> checkpoint
  -> plan
  -> queue
  -> render
  -> incremental persistence
  -> encode
  -> mux source audio
  -> validate
  -> metadata
  -> completed
```

## 9. Event Model

Persist events and publish them live.

Examples:

```text
project.created
asset.persisted
portrait.normalized
audio.analyzed
job.queued
job.started
job.phase_changed
job.progress
checkpoint.created
render.output_validated
job.completed
job.failed
recovery.started
recovery.completed
```

## 10. Configuration

Load configuration from `/data/config`.

Database-backed settings may override file defaults.

Configuration changes must be versioned and validated.

## 11. Deployment

Recommended mounts:

```yaml
volumes:
  - ./data:/data
  - ./models:/models
  - ./cache:/cache
```

All generated content and the seeded database remain outside the container.

## 12. Future Extensions

- multiple GPU workers,
- remote workers,
- PostgreSQL,
- object storage,
- multi-user auth,
- timeline editor,
- node pipeline,
- additional renderers.
