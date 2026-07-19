# LiveAvatarDirector — Roadmap

## Phase 0 — Audit and Baseline

Goal: understand upstream before refactoring.

Deliverables:

- current inference flow map,
- output-path map,
- model lifecycle map,
- FPS and clip-duration verification,
- supported resolution verification,
- baseline GPU smoke test,
- legacy behavior tests.

Exit criteria:

- existing Gradio path remains reproducible,
- current commit is pinned,
- known limitations are documented.

## Phase 1 — Persistent Data Foundation

Goal: ensure nothing important lives only inside the container.

Implement:

- `/data` root,
- persistent database,
- persistent config,
- persistent project folders,
- persistent models and caches,
- deterministic output paths,
- migration framework,
- storage validation.

Exit criteria:

- container recreation preserves database, config, assets, and output,
- database seeds only when absent,
- migrations run safely.

## Phase 2 — Projects and Assets

Implement:

- project CRUD,
- asset upload,
- hashing,
- metadata,
- project portability,
- render history model,
- project JSON sidecar.

Exit criteria:

- projects survive restart,
- assets are never stored only in temp paths.

## Phase 3 — Universal Image Normalization

Implement:

- any aspect ratio,
- no distortion,
- smart blur,
- padding,
- safe crop,
- manual preview,
- renderer-driven target dimensions,
- persisted normalization metadata.

Exit criteria:

- portrait, landscape, square, and ultra-wide test images normalize correctly,
- original files remain untouched.

## Phase 4 — Audio and Clip Planning

Implement:

- audio normalization,
- duration probing,
- exact clip calculation,
- source-audio preservation,
- final trim plan.

Exit criteria:

- no manual clip math is required,
- final target duration is exact.

## Phase 5 — Persistent Queue

Implement:

- job state machine,
- one GPU worker,
- queued jobs,
- cancellation,
- retry,
- event log,
- browser-independent execution.

Exit criteria:

- closing the browser does not affect rendering,
- queued jobs survive restart.

## Phase 6 — Checkpoints and Recovery

Implement:

- phase checkpoints,
- startup reconciliation,
- stale-job recovery,
- partial-output validation,
- safe resume or retry.

Exit criteria:

- stopping the container during a job leaves recoverable state,
- restart restores the job to a valid state.

## Phase 7 — Studio UI

Implement:

- projects,
- editor,
- queue,
- history,
- diagnostics,
- reconnect,
- legacy Gradio link.

Exit criteria:

- UI state is rebuilt from API after refresh.

## Phase 8 — File and Cache Management

Implement:

- file browser,
- previews,
- delete protection,
- archive/export/import,
- cache inventory,
- safe cleanup,
- size policies.

Exit criteria:

- routine maintenance requires no shell access.

## Phase 9 — Performance Presets and Vocal Gating

Implement:

- presets,
- vocal activity,
- instrumental restraint,
- clear control classifications.

Exit criteria:

- presets produce documented prompt and renderer behavior,
- no inactive controls.

## Phase 10 — Incremental Decode

Investigate and implement strongest valid recovery level.

Exit criteria:

- decoded windows persist where technically possible,
- recovery level is reported honestly.

## Phase 11 — Renderer Plugin Stabilization

Implement:

- stable interface,
- capabilities,
- diagnostics,
- backend discovery.

Exit criteria:

- a mock second renderer can be registered without changing project or queue code.

## Phase 12 — Director Features

Future:

- transcript,
- beat grid,
- sections,
- emotion,
- timeline,
- performance plans,
- prompt automation.

## Phase 13 — Multi-Renderer Production

Future:

- scene renderers,
- lip-sync refiners,
- upscalers,
- compositors,
- node graph.
