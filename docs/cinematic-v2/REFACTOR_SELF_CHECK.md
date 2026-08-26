# Cinematic V2 refactor self-check

Date: 2026-08-20

## Result

The V2 refactor is accepted for the cinematic scope. The classic engine remains
the default, automatic renders are labeled `preview_unverified.mp4`, and no
automatic ASR/visual/retrieval result is promoted to verified editorial truth.

## Fixed conflicts

- One active `movie-narrator` Skill remains in the discovery root. The old
  same-name pre-migration copy was preserved in a private local archive outside
  this repository.
- `workflow_mode` and execution `engine` are separate fields; `cinematic_v2`
  is not a workflow/gate state.
- Historical V1 controller documents are explicitly non-authoritative.
- `quality_report.json` is the only canonical pre-render timeline QA report.
- `final.mp4` is reserved for approved MASTER promotion; automatic output is
  `preview_unverified.mp4`.

## Implemented checks and controls

- Preliminary Audio Director runs before TTS; only narration-enabled segments
  are synthesized.
- ASR-only dialogue stays `UNVERIFIED` and cannot silence narration by itself.
- Verified dialogue audibility, narration/picture coverage, subtitle duration,
  foreground collisions, and locked semantic mismatch are hard-checked.
- BGM uses continuous master-timeline offsets; narration ducking keys only from
  verified dialogue windows.
- Source-audio stream presence is checked before a render that requests it.
- Empty subtitle timelines bypass the FFmpeg subtitles filter.
- Render success persists full-decode status, output size, and SHA-256.
- Human scene selection uses `mn cinematic-lock` and a separate review hash
  manifest; locked scenes are never silently replaced.
- `cinematic_run_state.json` hashes the source, options, and artifacts; resume
  rejects changed source bytes, options, or corrupted reusable artifacts.
- Visual analysis uses early/middle/late samples and writes scene thumbnails.
  Optional CLIP-compatible text-to-image retrieval is wired end to end.
- Cinematic-specific CLI options are explicit. Classic-only options fail with
  a precise error instead of being silently ignored.

## Verification evidence

- Cinematic V2 test suite: **40 passed**. This includes the synthetic-media
  FFmpeg render and post-render full decode.
- Skill state tests: **6 passed**.
- Skill package structural validation: **passed**.
- Python compilation of the modified cinematic packages: **passed**.
- `git diff --check`: **passed** (line-ending conversion notices only).
- Exact installed launcher help: `mn` exposes `cinematic-lock`; `mn create`
  exposes ASR, visual, Top-K, lock, and resume options.
- Skill discovery scan: exactly one active directory named `movie-narrator`.

## Full-repository boundary

The complete repository run finished with **2487 passed, 33 skipped, 13
failed**. The failures are outside the cinematic V2 paths and are retained as
known worktree/environment issues:

- uncommitted MiniMax/Zhipu/default-provider and voice-map changes, including
  pydub looking for a system `ffmpeg` executable;
- classic-runner tests reaching the configured LLM preflight/circuit breaker;
- one classic script retry expectation;
- task-queue dead-letter storage denied under the user profile.

These failures mean the entire dirty repository is not claimed green. They do
not invalidate the isolated 40/40 cinematic result.

## Tooling limitation

The project virtual environment does not contain Ruff or Black. No lint/format
pass is claimed. Syntax compilation, focused tests, real FFmpeg execution, and
`git diff --check` were used instead.
