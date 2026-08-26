# Cinematic V2 architecture

## Data flow

```text
movie.mp4
  |
  v
MovieAnalyzer --------------------> scene_database.json
  |  PySceneDetect + ASR + three-frame visual metadata + thumbnails
  v
CinematicScriptGenerator ---------> narration_segments.json
  |  each segment has target_scene and audio_priority
  v
SceneMemory.retrieve(top_k) ------> matches.json
  |  text embedding + optional cross-modal text/image embedding
  v
Preliminary AudioDirector --------> narration/original intent
  |
  v
Selective TTS Provider -----------> narration assets + durations
  |
  v
Duration fit + AudioDirector -----> audio_mix.json
  |
  v
TimelineBuilder ------------------> timeline.json
  |  source shot durations define the master timeline
  v
TimelineValidator ----------------> quality_report.json
  |
  v
CinematicRenderer (FFmpeg) -------> preview_unverified.mp4
```

## Ownership

### Movie Analyzer

- Detect shot boundaries with PySceneDetect.
- Extract dialogue candidates with `WhisperX`, `faster-whisper`, or `FunASR`.
- Accept a pluggable visual analyzer for characters, location, action,
  emotion, and visual description.
- Analyze early/middle/late samples and persist a midpoint thumbnail per shot.
- Join time-based ASR results to scenes without claiming listening
  verification.
- Persist a searchable scene database and provenance.

### Scene Memory

- Build a stable searchable representation for every scene.
- Support text and cross-modal text/image embedding adapters.
- Return top-K candidates with independent text/visual/combined scores.
- Keep `candidate_scene_ids` separate from `selected_scene_id`.

### Cinematic Script Generator

- Generate structured `NarrationSegment` objects, not a free narration blob.
- Require `target_scene`, `emotion`, and `audio_priority` per segment.
- Validate IDs and structured JSON before TTS.

### Audio Director

- Classify each matched interval as `NARRATION`, `DIALOGUE`, `CLIMAX`, or
  `TRANSITION`.
- Produce explicit narration/original/BGM enable and volume values.
- Protect verified dialogue and high-importance scenes.
- Record the rule and evidence behind each decision.
- Treat ASR-only dialogue as `UNVERIFIED`; it cannot silence narration by itself.

### Timeline Builder

- Create the output master timeline from selected source intervals.
- Place video, original audio, narration, BGM, and subtitle tracks on every
  item.
- Maintain output time, source time, track provenance, and narration timing.
- Write one canonical `timeline.json` for rendering.

### Timeline Validator

- Check continuity, source bounds, narration coverage, subtitle timing,
  dialogue protection, audio conflict, and scene-match confidence.
- Report semantic A/B mismatch as `PASS`, `FAIL`, or `UNKNOWN`; do not pretend
  similarity alone proves semantic correctness.
- Block rendering on structural or protected-dialogue failures.

### Cinematic Renderer

- Build one FFmpeg `filter_complex` graph.
- Trim/concatenate source video and original audio from timeline items.
- Overlay narration, BGM, and subtitles on output time.
- Apply timeline volumes and sidechain ducking.
- Keep BGM phase continuous across cuts and duck narration only inside verified
  dialogue windows.
- Map the graph outputs to `preview_unverified.mp4`, preserve the command
  manifest, and persist full-decode/hash QA.

### Review and recovery

- `mn cinematic-lock` validates human selections and writes a separate locked
  match document plus a hash manifest.
- `cinematic_run_state.json` records source/options/artifact hashes and supports
  guarded `--cinematic-resume` recovery.
- `final.mp4` remains reserved for an independently approved MASTER promotion.

## Failure policy

- Missing required source video, empty scene database, invalid timeline, or
  protected dialogue collision: hard fail.
- Missing visual model or optional visual embeddings: explicit degraded state,
  not fabricated metadata.
- Missing ASR backend: scenes remain valid, dialogue fields become
  `UNKNOWN/UNVERIFIED`, and dialogue-aware production cannot claim completion.
- Provider or renderer failures retain intermediate JSON and raw responses for
  resume/debugging.

## Test layers

1. Contract validation and JSON round trips.
2. Analyzer scene/ASR association with mocked backends.
3. Embedding/retrieval determinism and top-K ordering.
4. Audio-rule decisions.
5. Timeline construction and validator hard failures.
6. FFmpeg filter graph/command generation.
7. CLI mode routing and classic-default regression.
8. Optional local media integration fixture.
