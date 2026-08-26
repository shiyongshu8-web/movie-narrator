# Cinematic V2 data contracts

All JSON documents use `schema_version: "2.0"`. Times are seconds as numbers;
display timecodes are derived views, not authoritative values.

## `scene_database.json`

```json
{
  "schema_version": "2.0",
  "source_video": "movie.mp4",
  "source_sha256": "...",
  "asr_backend": "faster-whisper",
  "visual_backend": "openai-compatible",
  "scenes": [
    {
      "scene_id": "SCN-0001",
      "start_time": 0.0,
      "end_time": 8.4,
      "characters": [],
      "location": "UNKNOWN",
      "action": "UNKNOWN",
      "emotion": "UNKNOWN",
      "dialogue": [
        {
          "start_time": 2.1,
          "end_time": 4.0,
          "text": "ASR candidate",
          "speaker": "UNKNOWN",
          "verification_status": "UNVERIFIED"
        }
      ],
      "visual_description": "UNKNOWN",
      "importance_score": 0.5,
      "analysis_status": "PARTIAL",
      "thumbnail_path": "scene_thumbnails/SCN-0001.jpg"
    }
  ]
}
```

## `narration_segments.json`

```json
{
  "schema_version": "2.0",
  "segments": [
    {
      "id": "NAR-0001",
      "narration": "杰克曾经是万人追捧的明星。",
      "target_scene": "第一次登台",
      "emotion": "落寞",
      "audio_priority": "narration",
      "estimated_duration": null,
      "tts_asset": null,
      "tts_duration": null
    }
  ]
}
```

## `matches.json`

```json
{
  "schema_version": "2.0",
  "matches": [
    {
      "narration_segment_id": "NAR-0001",
      "candidates": [
        {
          "scene_id": "SCN-0023",
          "text_score": 0.81,
          "visual_score": null,
          "similarity_score": 0.81
        }
      ],
      "selected_scene_id": "SCN-0023",
      "selection_status": "CANDIDATE"
    }
  ]
}
```

`CANDIDATE` is not a human-reviewed lock. Production can set `LOCKED` only in
an explicit review step.

## `audio_mix.json`

```json
{
  "schema_version": "2.0",
  "decisions": [
    {
      "narration_segment_id": "NAR-0001",
      "scene_id": "SCN-0023",
      "classification": "NARRATION",
      "narration_enabled": true,
      "narration_volume": 1.0,
      "original_enabled": true,
      "original_volume": 0.2,
      "bgm_enabled": true,
      "bgm_volume": 0.3,
      "protect_dialogue": false,
      "rule": "background_or_plot_exposition"
    }
  ]
}
```

## `timeline.json`

```json
{
  "schema_version": "2.0",
  "timebase": "seconds",
  "duration": 8.4,
  "items": [
    {
      "timeline_id": "TL-0001",
      "start": 0.0,
      "end": 8.4,
      "video": {
        "scene_id": "SCN-0023",
        "source_start": 124.0,
        "source_end": 132.4
      },
      "audio": {
        "narration": {"enabled": true, "volume": 1.0, "asset": "NAR-0001.mp3", "duration": 3.2},
        "original": {"enabled": true, "volume": 0.2, "duration": 8.4},
        "bgm": {"enabled": true, "volume": 0.3, "asset": "bgm.mp3", "duration": 8.4}
      },
      "subtitle": {"text": "杰克曾经是万人追捧的明星。", "start": 0.0, "end": 3.2},
      "match": {"similarity_score": 0.81, "selection_status": "CANDIDATE"}
    }
  ]
}
```

## `quality_report.json`

```json
{
  "schema_version": "2.0",
  "status": "FAIL",
  "issues": [
    {
      "check_id": "DIALOGUE_OVERLAP",
      "severity": "ERROR",
      "timeline_id": "TL-0004",
      "message": "Protected dialogue is covered by narration.",
      "evidence": {}
    }
  ],
  "unknowns": ["SEMANTIC_AV_ALIGNMENT_REQUIRES_REVIEW"]
}
```

The only canonical timeline QA filename is `quality_report.json`. V2 no longer
emits a second compatibility copy because two independently editable reports
would create competing truth sources.
