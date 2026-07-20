# LiveAvatarDirector — Master Plan

## 1. Purpose

LiveAvatarDirector is an open-source, production-grade AI digital-human studio built initially around the Alibaba-Quark LiveAvatar renderer.

It is not intended to remain a thin wrapper around a single model. It should become a durable application platform for:

- singing avatars,
- talking portraits,
- virtual performers,
- digital actors,
- VTubers,
- podcast presenters,
- virtual idols,
- AI news anchors,
- AI tutors,
- music videos,
- speech-driven performances,
- future multi-renderer digital-human workflows.

The initial renderer is LiveAvatar. The application architecture must remain renderer-agnostic so future engines can be added without redesigning projects, jobs, storage, the database, or the user interface.

## 2. Product Definition

LiveAvatarDirector should feel like a production application, not a research demo.

The user should be able to:

1. Create a project.
2. Upload a portrait in any common aspect ratio.
3. Upload audio.
4. Preview the normalized portrait.
5. See detected audio duration and calculated clip count.
6. Select a renderer and performance preset.
7. Start a background render.
8. Close the browser.
9. Stop or restart the container or host.
10. Return later.
11. Resume from the last safe checkpoint.
12. Review logs, status, partial outputs, and final renders.
13. Manage all files, caches, models, and configuration through the UI.
14. Export or archive the complete project.
15. Reproduce a render from its stored metadata.

## 3. Core Laws

### 3.1 Idempotent

Every operation must be safe to retry.

Repeated execution of the same step with the same inputs must either:

- return the existing valid result, or
- replace an incomplete or invalid result atomically.

A retry must never create uncontrolled duplicates, corrupt project state, or silently overwrite a known-good result.

### 3.2 Persistent

Nothing important may exist only inside the container.

All of the following must persist on host-mounted storage:

- projects,
- original assets,
- normalized assets,
- analysis output,
- generated clips,
- decoded clips,
- checkpoints,
- final renders,
- previews,
- logs,
- application database,
- configuration,
- model cache,
- Hugging Face cache,
- Torch cache,
- CUDA compile cache where practical,
- thumbnails,
- metadata,
- backups,
- queue state.

The container must be disposable.

Deleting and recreating the container must not lose project state.

### 3.3 Resumable

After a crash, reboot, container stop, host restart, GPU reset, or application upgrade, the next startup must inspect persisted state and determine what can be resumed.

The application must not rely on a browser session for execution state.

Where true model-state resume is unavailable, the application must still preserve:

- completed preprocessing,
- completed analysis,
- completed clips,
- completed decode windows,
- completed encodes,
- metadata,
- logs,
- job state,
- exact failure point.

The application must report the real recovery level:

- Level 0: retry from the start of generation,
- Level 1: reuse completed decoded clips,
- Level 2: resume generation from persisted renderer state.

Never claim resume support beyond what is actually implemented.

### 3.4 Observable

Every long-running operation must expose:

- status,
- phase,
- progress,
- current clip,
- total clips,
- elapsed time,
- estimated remaining time where available,
- worker identity,
- logs,
- errors,
- output paths,
- recovery state.

No important operation should be a black box.

### 3.4.1 Known LiveAvatar Progress Gap

The current upstream LiveAvatar generation call is monolithic and does not expose a per-clip callback to the Studio worker. During a real render, GPU computation may be healthy while the persisted UI remains at `Clip 0 / N` and the job heartbeat appears stale until the renderer call returns.

This must be treated as an observability limitation, not as evidence that the render has stopped. A follow-up integration must capture upstream clip/block progress and periodically persist:

- heartbeat timestamp,
- completed clip or block count,
- current generation stage,
- measured throughput,
- estimated remaining time.

Until that integration exists, the UI must label clip progress as unavailable during monolithic generation rather than displaying a misleading zero count. Worker liveness and GPU-process diagnostics should be shown separately from renderer progress.

### 3.5 Deterministic

Every render must record enough information to reproduce it as closely as the renderer permits:

- application version,
- Git commit,
- upstream renderer commit,
- model identifier,
- checkpoint hashes,
- LoRA hash,
- input hashes,
- normalized input metadata,
- seed,
- prompt,
- negative prompt,
- sampler,
- steps,
- guidance,
- frames per clip,
- FPS,
- resolution,
- clip count,
- audio duration,
- performance preset,
- renderer settings,
- environment details.

### 3.6 Extensible

Only renderer plugins should know renderer-specific details.

Projects, jobs, files, caches, configuration, APIs, and the UI must use generic concepts:

- Project,
- Asset,
- Analysis,
- Timeline,
- RenderJob,
- Renderer,
- Output,
- Checkpoint,
- Event.

## 4. Initial Scope

The first production milestone should focus on making the existing LiveAvatar capability reliable and usable.

Included:

- persistent projects,
- persistent database,
- persistent queue,
- background worker,
- browser reconnect,
- durable progress,
- output history,
- automatic clip calculation,
- universal image normalization,
- audio normalization,
- file manager,
- cache manager,
- configuration UI,
- deterministic metadata,
- startup reconciliation,
- crash recovery,
- legacy Gradio access,
- Docker deployment,
- tests.

Deferred until the foundation is stable:

- multi-avatar scenes,
- timeline editor,
- advanced AI director,
- morph mode,
- additional renderers,
- distributed multi-node workers,
- collaborative multi-user editing.

## 5. Repository Strategy

Keep upstream model code as intact as practical.

Recommended structure:

```text
LiveAvatarDirector/
├── liveavatar/                  # Upstream engine code
├── minimal_inference/           # Upstream and legacy entry points
├── studio/
│   ├── api/
│   ├── analysis/
│   ├── core/
│   ├── db/
│   ├── diagnostics/
│   ├── jobs/
│   ├── media/
│   ├── projects/
│   ├── renderers/
│   ├── storage/
│   ├── workers/
│   └── main.py
├── frontend/
├── migrations/
├── scripts/
├── tests/
├── docker/
├── docs/
├── PLAN.md
├── ARCHITECTURE.md
├── ROADMAP.md
├── CONTRIBUTING.md
├── CODING_STANDARDS.md
├── docker-compose.yaml
└── README.md
```

Most new application code should live outside upstream model directories.

## 6. Persistent Storage Layout

Use one configurable persistent root:

```text
/data
```

Recommended layout:

```text
/data/
├── database/
│   └── liveavatardirector.db
├── config/
│   ├── application.json
│   ├── renderers.json
│   ├── presets.json
│   └── storage.json
├── projects/
│   └── <project-id>/
│       ├── project.json
│       ├── assets/
│       │   ├── original/
│       │   ├── normalized/
│       │   └── thumbnails/
│       ├── analysis/
│       ├── jobs/
│       ├── work/
│       │   ├── clips/
│       │   ├── decoded/
│       │   ├── checkpoints/
│       │   ├── temp/
│       │   └── cache/
│       ├── renders/
│       ├── metadata/
│       └── logs/
├── models/
├── cache/
│   ├── huggingface/
│   ├── torch/
│   ├── cuda/
│   ├── thumbnails/
│   └── previews/
├── logs/
├── backups/
└── imports/
```

No final content may depend on `/tmp` or an unmounted container path.

## 7. Project Model

Each project must be independently portable and intelligible.

Minimum project metadata:

```json
{
  "schema_version": 1,
  "id": "uuid",
  "name": "Untitled Project",
  "mode": "singing_avatar",
  "status": "draft",
  "renderer": "liveavatar",
  "created_at": "ISO-8601",
  "updated_at": "ISO-8601",
  "portrait_asset_id": null,
  "audio_asset_id": null,
  "prompt": "",
  "negative_prompt": "",
  "performance_preset": "studio_vocal",
  "renderer_settings": {},
  "active_job_id": null,
  "latest_render_id": null
}
```

Project files must use atomic write and rename.

The database is the searchable index. Project folders remain the durable record.

## 8. Database

Use SQLite for the initial release, stored at:

```text
/data/database/liveavatardirector.db
```

Use Alembic migrations.

Minimum entities:

- Project,
- Asset,
- AnalysisRecord,
- RenderJob,
- RenderEvent,
- RenderOutput,
- RendererBackend,
- ApplicationSetting,
- CacheEntry,
- FileRecord,
- BackupRecord.

The application must seed a new database only when none exists.

After initial creation, the database file must remain external to the container and be migrated in place.

Never silently recreate an existing database.

## 9. Job Queue and State Machine

Use a persistent state machine.

Recommended states:

```text
queued
validating
preprocessing
analyzing
planning
loading_renderer
generating
decoding
encoding
finalizing
validating_output
completed
failed
cancel_requested
cancelled
paused
recovering
```

Each transition must be persisted.

Every phase must be idempotent.

Example:

```text
normalize portrait
├── valid output exists with matching input hash -> reuse
├── incomplete .part exists -> delete and rerun
└── no output -> run, validate, atomic rename
```

The first implementation may run one active GPU render at a time.

Queued jobs must survive restart.

## 10. Startup Reconciliation

Startup must run a reconciliation process before accepting new work.

Sequence:

1. Open database.
2. Apply migrations.
3. Validate persistent directories.
4. Load configuration.
5. Discover renderers.
6. Validate model paths.
7. Reconcile projects with database.
8. Reconcile jobs with filesystem.
9. Mark stale running jobs as `recovering`.
10. Validate checkpoints and partial outputs.
11. Determine each job's safe resume point.
12. Return recoverable jobs to queue.
13. Preserve unrecoverable jobs as failed with diagnostics.
14. Rebuild missing thumbnails where safe.
15. Start worker.
16. Start API and UI.

A stale `running` job must never remain permanently stuck after restart.

## 11. Checkpointing

Persist checkpoints at every meaningful boundary:

- portrait accepted,
- portrait normalized,
- audio accepted,
- audio normalized,
- audio analysis complete,
- render plan complete,
- renderer prepared,
- each clip generated,
- each decode window completed,
- intermediate video written,
- final encode completed,
- final mux completed,
- output validated.

Checkpoint metadata should include:

```json
{
  "phase": "clip_generated",
  "project_id": "uuid",
  "job_id": "uuid",
  "clip_index": 12,
  "completed_at": "ISO-8601",
  "input_hashes": {},
  "output_files": [],
  "output_hashes": {},
  "valid": true
}
```

Use `.part` files and atomic rename.

## 12. Universal Image Input

The UI must accept images of any common aspect ratio without distortion.

Supported examples:

- portrait,
- landscape,
- square,
- ultra-wide,
- phone photographs,
- DSLR photographs,
- webcam captures,
- scanned images,
- PNG transparency.

Never stretch or squash the image.

Always preserve the original upload.

Create a normalized renderer input using one of these modes:

### 12.1 Smart Blur Background

Default mode.

- preserve the source aspect ratio,
- scale the original to fit,
- generate a blurred cover image for the target canvas,
- centre the original over the blurred background,
- preserve the complete face and hair where possible.

### 12.2 Smart Padding

- preserve aspect ratio,
- pad with user-selected colour, gradient, transparency, or neutral fill.

### 12.3 Face-Centred Crop

- detect primary face,
- calculate a safe crop,
- preserve hair, chin, and shoulders where possible,
- refuse destructive crops when margins are insufficient.

### 12.4 Manual Crop

- interactive crop preview,
- locked aspect ratio,
- safe-area overlays,
- reset option.

### 12.5 Outpainting

Future optional mode.

The selected renderer must expose supported input dimensions and aspect-ratio constraints.

The normalization pipeline must query renderer capabilities rather than hard-code `704x384`.

Persist:

- original dimensions,
- target dimensions,
- selected mode,
- crop box,
- padding,
- face box,
- background strategy,
- output hash.

## 13. Audio Processing

Preserve the original upload.

Create a normalized working file.

Persist:

- duration,
- codec,
- sample rate,
- channels,
- bitrate,
- source hash,
- normalized hash.

The original audio is authoritative for final muxing.

Do not concatenate generated audio chunks in a way that causes drift.

## 14. Automatic Clip Calculation

The UI must calculate clips automatically.

Formula:

```text
clip_duration_seconds = frames_per_clip / effective_fps
number_of_clips = ceil(audio_duration_seconds / clip_duration_seconds)
```

The renderer plugin must report effective FPS.

Always round up.

Trim final video to exact source-audio duration.

Show the calculation in the UI.

Manual override belongs under Advanced Settings only.

## 15. Audio Analysis

Initial analysis:

- duration,
- waveform,
- silence,
- vocal activity,
- instrumental regions.

Optional later analysis:

- Whisper transcript,
- word timestamps,
- tempo,
- beat grid,
- energy,
- sections,
- emotion.

Persist all analysis so rerenders do not repeat unchanged work.

## 16. Performance Control

Add high-level presets:

- Studio Vocal,
- Acoustic Session,
- Ballad,
- Rock Singer,
- Metal Singer,
- Pop Performer,
- Choir,
- Rap,
- Podcast,
- News Presenter,
- Calm Speech,
- Animated VTuber,
- Custom.

Each setting must be classified as:

- native renderer parameter,
- prompt guidance,
- post-processing setting,
- unsupported.

Do not show controls that have no effect.

Instrumental sections should guide toward:

- closed or relaxed mouth,
- minimal head movement,
- steady gaze,
- natural breathing,
- occasional blinking,
- no random nodding,
- no exaggerated swaying.

## 17. Renderer Plugin Interface

Define a stable renderer interface.

Minimum methods:

```python
class RendererBackend:
    def is_available(self) -> bool: ...
    def capabilities(self) -> RendererCapabilities: ...
    def validate(self, project, settings) -> list: ...
    def estimate(self, project, settings): ...
    def prepare(self, context): ...
    def render(self, context, progress_callback): ...
    def cancel(self, context): ...
    def diagnostics(self) -> dict: ...
```

Capabilities include:

- audio-driven,
- singing,
- speech,
- long-form,
- native lip sync,
- identity conditioning,
- supported resolutions,
- supported frame counts,
- FP8,
- compilation,
- incremental decode,
- generation resume,
- effective FPS.

Implement `LiveAvatarRenderer` first.

## 18. Output Management

All production outputs must be under the project directory.

Example:

```text
/data/projects/<project-id>/renders/
```

A render is complete only after:

- file exists,
- size is non-zero,
- video stream exists,
- audio stream exists,
- duration is within tolerance,
- resolution is valid,
- frame rate is valid,
- metadata sidecar exists,
- hashes are recorded.

Use atomic finalization.

## 19. File Manager

The UI must provide full file management.

Browse:

- projects,
- original assets,
- normalized assets,
- audio,
- videos,
- checkpoints,
- logs,
- models,
- caches,
- backups.

Actions:

- preview,
- rename,
- move,
- duplicate,
- delete,
- restore from trash,
- download,
- export,
- import,
- archive,
- verify checksum,
- show references,
- show size,
- show last used.

Destructive actions must require confirmation.

Files referenced by active jobs must not be deleted.

## 20. Cache Manager

The UI must expose:

- Hugging Face cache,
- Torch cache,
- CUDA compile cache,
- renderer cache,
- project work cache,
- decoded clips,
- temporary files,
- thumbnails,
- previews.

Display:

- path,
- size,
- file count,
- last access,
- owning renderer,
- referenced or unreferenced status.

Actions:

- verify,
- clean unused,
- clean selected,
- clean all safe entries,
- rebuild,
- move cache location,
- set size limit.

Never delete active or referenced cache entries.

## 21. Configuration Manager

Manage configuration through the UI.

Configuration must live under:

```text
/data/config
```

Manage:

- storage paths,
- model paths,
- renderer settings,
- performance presets,
- queue policy,
- cleanup policy,
- backup policy,
- logging level,
- ports,
- feature flags.

Secrets must not be shown after saving.

## 22. Backup and Restore

Support backup of:

- database,
- configuration,
- project metadata,
- project assets,
- render metadata.

Allow optional exclusion of large caches and model files.

Provide restore validation before applying a backup.

## 23. API

Minimum API:

```text
GET    /api/health
GET    /api/system
GET    /api/renderers
GET    /api/projects
POST   /api/projects
GET    /api/projects/{id}
PATCH  /api/projects/{id}
DELETE /api/projects/{id}
POST   /api/projects/{id}/portrait
POST   /api/projects/{id}/audio
POST   /api/projects/{id}/analyze
POST   /api/projects/{id}/render
GET    /api/projects/{id}/renders
GET    /api/jobs
GET    /api/jobs/{id}
POST   /api/jobs/{id}/cancel
POST   /api/jobs/{id}/retry
POST   /api/jobs/{id}/resume
GET    /api/files
GET    /api/caches
POST   /api/caches/clean
GET    /api/settings
PATCH  /api/settings
```

Use WebSocket or Server-Sent Events for progress.

## 24. UI

Main sections:

- Projects,
- New Project,
- Project Editor,
- Assets,
- Audio Analysis,
- Render Settings,
- Queue,
- Render History,
- Files,
- Caches,
- Models,
- Settings,
- Diagnostics,
- Legacy Gradio.

The UI must restore state from the backend after reconnect.

The frontend must never be the source of truth for job state.

## 25. Docker

Recommended services:

```text
api
worker
frontend
legacy-gradio
model-downloader
```

Initial releases may combine services in one image, but processes should remain separate.

Persistent mounts:

```text
/data
/models
/cache
```

The database, configuration, generated content, and caches must all be outside the container.

The application should start in degraded mode when models are missing instead of crash-looping.

## 26. Testing

Required unit tests:

- project creation,
- database seeding,
- migrations,
- project schema migration,
- atomic writes,
- asset hashing,
- portrait normalization,
- arbitrary aspect ratios,
- no distortion,
- audio probing,
- clip calculation,
- state transitions,
- checkpoint validation,
- startup reconciliation,
- queue recovery,
- retry idempotency,
- file deletion protection,
- cache reference protection,
- metadata generation.

Required integration tests:

- browser disconnect does not stop render,
- restart recovers queued jobs,
- restart reconciles running jobs,
- completed outputs survive container recreation,
- config survives container recreation,
- database survives container recreation,
- generated files remain outside container,
- arbitrary image aspect ratio renders through mock backend,
- active-job files cannot be removed,
- completed job is visible after API restart.

Use a mock renderer for CI.

Add optional GPU smoke tests.

## 27. Security and Safety

- sanitize filenames,
- prevent path traversal,
- enforce data-root boundaries,
- validate MIME types,
- validate uploads,
- protect destructive actions,
- do not expose secrets,
- do not execute user-provided shell commands,
- avoid logging private media contents.

## 28. Implementation Principles for Codex

Codex must:

1. Audit before changing code.
2. Preserve upstream engine behavior.
3. Build vertical slices.
4. Add tests with each phase.
5. Avoid placeholders presented as complete features.
6. Avoid inactive UI controls.
7. Use atomic writes.
8. Use persisted state.
9. Keep the GPU worker responsible for model lifecycle.
10. Avoid loading the model separately in the API process.
11. Reuse valid work.
12. Validate before marking complete.
13. Report real limitations.
14. Keep container-local data disposable.
15. Document all new environment variables.

## 29. Definition of Done for the Foundation

The foundation is complete when:

- projects persist,
- database persists,
- configuration persists,
- assets persist,
- outputs persist,
- caches persist,
- queued jobs survive restart,
- interrupted jobs reconcile at startup,
- resumable work resumes at the strongest valid checkpoint,
- arbitrary image aspect ratios are normalized without distortion,
- clip count is automatic,
- browser reconnect restores status,
- file management works through UI,
- cache management works through UI,
- legacy Gradio remains available,
- tests pass,
- Docker Compose starts cleanly,
- health reports system state,
- no important content lives only inside the container.

## 30. Completion Report

After each implementation phase, report:

- files changed,
- schema changes,
- migration details,
- storage changes,
- API changes,
- UI changes,
- idempotency behavior,
- resume behavior,
- tests run,
- test results,
- container build result,
- startup result,
- health result,
- genuine remaining limitations.
