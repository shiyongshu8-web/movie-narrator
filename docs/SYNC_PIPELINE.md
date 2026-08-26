# Source-first visual synchronization

The formal order is:

```text
source media -> shot detection -> VISUAL_EVENT_INDEX
             -> event-bound NARRATION_SEGMENTS -> real TTS duration
             -> ChatCut timeline readback -> SYNC_MAP -> semantic QC
             -> repair -> readback -> QC again
```

## Artifacts

`movie-narrator sync build` writes:

- `VISUAL_EVENT_INDEX.json`: scene-derived visual candidates with source
  ranges, shot IDs, characters, location, action, evidence, and confidence;
- `NARRATION_SEGMENTS.json` (or `NARRATION_SEGMENTS.v3.json` when the input is
  the legacy, case-insensitive-colliding `narration_segments.json`): narration
  text bound to one or more event IDs;
- `SYNC_MAP.json`: source/timeline ranges, real TTS duration, visual and
  spoken anchors, offsets, fit state, and stale-map state;
- `ALIGNMENT_REPORT.json`: per-row gate result.

The event index is intentionally conservative. A scene midpoint is a locator
candidate, not proof that the key action happened at that exact frame. ASR and
subtitles remain locating evidence until source listening or visual review
verifies them.

## Hard rules

- Every narration segment has at least one `event_id`.
- `actual_tts_duration` is read from the generated audio; estimates do not
  pass `tts_duration_fit`.
- A critical event fails when narration leads its visual anchor by more than
  `0.8s`, and the absolute hard lead limit is `1.0s`.
- A visual lead of `0–1.5s` is the preferred range; it lets the audience see
  an event before hearing its explanation.
- Missing ChatCut readback, word-level spoken anchors, caption verification,
  or event locks remain `PASS_WITH_UNKNOWN`, never `FINAL_READY`.
- A failing row produces a repair plan. The plan may trim/extend picture,
  delay a target, shorten/split narration, or rematch an event; it is not a
  universal `move narration` shortcut.

## Example

```powershell
movie-narrator sync build `
  --scene-database .\scene_database.json `
  --narration .\narration_segments.json `
  --output-dir .\sync

movie-narrator edit --backend chatcut --sync-map .\sync\SYNC_MAP.json `
  --project-id <id> --timeline-id <id>
```

Without a real ChatCut timeline readback the artifacts are useful planning
evidence, but they are not a final editable project and cannot be declared
`MASTER`.
