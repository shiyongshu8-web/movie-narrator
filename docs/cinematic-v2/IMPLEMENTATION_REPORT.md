# Cinematic V2 implementation report

## Result

The repository now has an additive, source-first cinematic pipeline. The
existing classic runner remains the default. The cinematic renderer consumes
`timeline.json`; it does not use a combined narration file as the edit clock.

## Implemented modules

| Area | Implementation | Test evidence |
|---|---|---|
| Contracts | Versioned Pydantic scene, narration, match, audio, timeline, and quality models | Contract and range tests |
| Movie Analyzer | PySceneDetect, ASR adapters, three-frame visual analysis, persistent scene thumbnails | Mocked shot/ASR/visual association tests |
| Scene Memory | Text and optional CLIP-compatible cross-modal retrieval, local hashing fallback, top-K candidates | Text and text-to-image retrieval tests |
| Script Generator | JSON-only `NarrationSegment` generation with target scene and audio priority | Structured response and prose rejection tests |
| Audio Director | Preliminary/final decisions; only explicit or VERIFIED dialogue can silence narration | Volume/enable/provenance tests |
| Timeline Builder | Movie-source intervals drive output time; five tracks per item | Timing, TTS-fit, and artifact tests |
| Timeline Validator | Continuity, duration, subtitle, dialogue, audio, and semantic review checks | PASS/FAIL/UNKNOWN tests |
| Renderer | FFmpeg `filter_complex`, continuous BGM, verified-dialogue-window ducking, source-audio preflight, full decode/hash report | Command tests plus real synthetic-media render/decode |
| Orchestrator | Artifact hash chain, guarded resume, preview labeling, persistent post-render QA | Injected end-to-end/resume tests |
| CLI/review | Cinematic-specific options, explicit unsupported-option errors, `mn cinematic-lock` | Typer routing/review tests |

## Artifact contract

The cinematic run writes:

- `scene_database.json`
- `narration_segments.json`
- `matches.json`
- `audio_mix.json`
- `timeline.json`
- `quality_report.json`
- `render_manifest.json`
- `post_render_quality.json`
- `cinematic_run_state.json`
- `preview_unverified.mp4`

## Verification performed

The refactor verification is refreshed in `REFACTOR_SELF_CHECK.md`. Historical
test counts from the first V2 implementation are not current acceptance evidence.

## Deliberate acceptance limits

- ASR dialogue remains `UNVERIFIED` until aligned human listening.
- Automatic top-1 remains `CANDIDATE`; use `mn cinematic-lock` for a reviewed
  lock and pass the result through `--cinematic-locked-matches`.
- Visual analysis may be `PARTIAL` or `UNVERIFIED` when the configured model
  cannot supply evidence.
- Hashing embeddings are an offline degraded fallback; semantic confidence is
  reported, not presented as proof that narration A visibly matches scene A.
- `PASS_WITH_UNKNOWN` may produce `preview_unverified.mp4` but cannot by itself
  promote a production `MASTER`.
- The Web UI is not broken or replaced. It can call the new orchestration API,
  but this upgrade does not add a new UI selector.
- No real paid LLM/TTS production run was made during implementation. Such a
  run requires explicit provider authorization and real source media.

The Git history is the canonical commit record; this document intentionally
does not duplicate a hand-maintained commit list.
