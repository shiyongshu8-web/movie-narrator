# MOVIE_NARRATOR_AUDIT

```text
AUDIT_DATE = 2026-08-23
SCOPE = existing D:\\codex\\movie-narrator source repo
MODE = AUDIT_RECOVERY -> additive integration implementation
ENGINE = cinematic_v2 retained; ChatCut is an explicit editing backend
```

## Current chain

The existing cinematic path already has source probing, PySceneDetect scene
boundaries, optional ASR, per-scene VLM descriptions/thumbnails, candidate
scene retrieval, audio decisions, real post-TTS duration measurement, a
backend-neutral multi-track JSON timeline, an FFmpeg renderer, and timeline
QA. Its legacy order still generates the v2 script/TTS before the new formal
event-binding contract, so this change adds the visual-event and semantic-QC
layer around that stable path rather than deleting it.

| Area | Audit finding | Decision |
| --- | --- | --- |
| Source media | `MovieAnalyzer` hashes/probes the source and writes `scene_database.json`; raw media stays outside derived artifacts. | KEEP |
| Shot detection | PySceneDetect is the existing detector, with a duration fallback. | KEEP |
| Subtitle/ASR | ASR cues are attached to scenes but remain `UNVERIFIED`; subtitle/ASR is locator evidence, not dialogue proof. | KEEP; MODIFY status use in new QC |
| Visual analysis | Existing VLM scene analysis is per scene and can fall back to `UNKNOWN`. | KEEP; ADD `VISUAL_EVENT_INDEX` |
| Story/script | Cinematic generator returns structured `NarrationSegment` items bound to `target_scene`. | KEEP compatibility; MODIFY via event-bound adapter |
| TTS | Cinematic synthesizer writes each audio asset and reads actual duration with pydub. | KEEP; ADD `actual_tts_duration` contract |
| Timeline | Existing `TimelineBuilder` creates V1/original, narration, original audio, BGM, and captions in a JSON timeline. | KEEP; ADD ChatCut logical track plan |
| FFmpeg | `CinematicRenderer` remains the local render/debug backend. | DO_NOT_TOUCH as a fallback |
| Semantic matching | Existing text/visual retrieval produces `CANDIDATE` or `LOCKED` scene matches and timeline similarity checks. | MODIFY with event binding and semantic offset gate |
| Visual event index | No formal `VISUAL_EVENT_INDEX` existed. | ADD |
| Sync map | No formal `SYNC_MAP` existed. | ADD |
| Final QC | Existing timeline QA checks duration, audio collision, source dialogue protection, similarity, and captions. | KEEP; ADD `ALIGNMENT_REPORT` |
| ChatCut | No official ChatCut integration or live readback existed in the Python package. | ADD injected official-MCP boundary |
| Other similarly named projects | Not used. | DEPRECATE/DO_NOT_TOUCH |

## Added artifacts and entry points

```text
VISUAL_EVENT_INDEX.json
NARRATION_SEGMENTS.json / NARRATION_SEGMENTS.v3.json
SYNC_MAP.json
ALIGNMENT_REPORT.json

movie-narrator chatcut status
movie-narrator sync build
movie-narrator edit --backend chatcut
```

The `.v3.json` suffix is used when the legacy `narration_segments.json` is in
the same Windows directory because Windows treats names differing only by
case as the same file. This prevents a new contract from overwriting the
legacy resume artifact.

## ChatCut connection report

```text
mcp_configured = UNKNOWN
authenticated = UNKNOWN
project_access = UNKNOWN
timeline_access = UNKNOWN
asset_access = UNKNOWN
edit_access = UNKNOWN
preview_access = UNKNOWN
export_access = UNKNOWN
endpoint = https://api.chatcut.io/api/external-mcp/mcp
blocker = codex CLI probe returned PermissionError; no mcp__chatcut__* tools are exposed in this session
```

No ChatCut mutation, media upload, export, or paid provider call was made.
