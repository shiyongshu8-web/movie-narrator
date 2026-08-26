# Cinematic V2 upgrade impact analysis

## Decision

Add a parallel `cinematic` orchestration path and keep the existing pipeline as
`classic`. Do not reorder or replace the classic `runner.py` steps.

```text
classic (default)
script -> TTS -> align -> scenes -> match -> render

cinematic
movie -> analyzer -> scene database -> narration segments -> retrieval
      -> audio director -> master timeline -> validator -> renderer
```

The cinematic master timeline, not `narration.mp3`, is the editing authority.
Narration is one timed track placed on that timeline.

## Existing components and impact

| Existing area | Current behavior | V2 decision |
|---|---|---|
| `pipeline/runner.py` | Flat classic step order | Keep unchanged |
| `models.ScriptSegment` | Narration text only | Keep for classic; add V2 `NarrationSegment` |
| `models.Scene` | Cut index and timestamps | Keep for classic; add rich `SceneRecord` |
| `pipeline/scenes.py` | PySceneDetect timestamps | Reuse the technique in Movie Analyzer |
| `pipeline/match.py` | Narration-to-scene top-1 matching | Keep; add persistent top-K Scene Memory |
| `pipeline/tts.py` | Builds one narration master and timings | Reuse provider layer after scene binding; narration no longer controls the movie timeline |
| `pipeline/render.py` | MoviePy video + final narration mix | Keep for classic; add cinematic FFmpeg renderer |
| `pipeline/qa_gate.py` | Soft intermediate QA | Keep; cinematic timeline validator is a separate hard pre-render check |
| CLI / Web | Builds `Context`, runs classic runner | Add opt-in mode; classic remains default |
| Providers | Existing LLM/TTS factories | Reuse; no provider replacement |

## New packages

```text
src/movie_narrator/
├── cinematic/          # shared contracts, script generator, orchestrator
├── movie_analyzer/     # scene cuts, ASR, visual-analysis interface, database
├── scene_memory/       # text/visual embeddings and top-K retrieval
├── audio_director/     # narration/dialogue/BGM priority decisions
└── timeline/           # builder, validator, FFmpeg renderer
```

## Compatibility boundary

- `mn create` remains `classic` by default.
- `mn create --mode cinematic` requires a real source video.
- Classic output names and data models remain unchanged.
- Cinematic artifacts are versioned JSON and are written beside
  `preview_unverified.mp4`; `final.mp4` is reserved for approved promotion.
- Provider credentials and calls remain behind the current provider factories.
- The initial V2 implementation is additive; Web UI can opt into the same
  orchestration API later without a breaking REST/schema change.

## Existing dirty-worktree boundary

The repository had modified provider, config, CLI, export, and tests before
this upgrade. V2 commits must stage only their own paths/hunks. New code must
not depend on an uncommitted provider feature in order to import or run unit
tests.

## Main risks

1. **False dialogue verification** — ASR is a candidate transcript. Store ASR
   provenance and `UNVERIFIED` until aligned and listened to.
2. **Visual model unavailable** — retain `UNKNOWN` fields and a provider
   interface; never invent character/action/emotion metadata.
3. **Model download/network cost** — embedding and vision backends are
   optional adapters. Deterministic local fallback supports tests and degraded
   retrieval without network.
4. **Audio language collision** — validator blocks narration over a protected
   dialogue interval above configured thresholds.
5. **Timeline drift** — all output times are derived from selected source shot
   durations. Narration duration is validated against, not used to create, the
   master timeline.
6. **Renderer portability** — generate an inspectable FFmpeg command and test
   the filter graph independently before media integration tests.

## Delivery stages

1. Contracts and architecture.
2. Movie Analyzer and Scene Memory.
3. Narration Segment generator and Audio Director.
4. Timeline Builder and Timeline Validator.
5. Cinematic FFmpeg Renderer and `--mode cinematic` integration.
6. Full regression, smoke fixture, and final commit audit.
