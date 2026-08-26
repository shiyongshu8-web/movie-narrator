from __future__ import annotations

import pytest

from movie_narrator.alignment.qc import evaluate_alignment
from movie_narrator.alignment.repair import plan_repairs
from movie_narrator.alignment.sync_map import build_sync_map
from movie_narrator.cinematic.models import (
    AnalysisStatus,
    SceneDatabase,
    SceneRecord,
    VerificationStatus,
)
from movie_narrator.integrations.chatcut.client import probe_chatcut_connection
from movie_narrator.integrations.chatcut.client import ChatCutClient
from movie_narrator.integrations.editing_backend import ChatCutEditingBackend
from movie_narrator.integrations.chatcut.timeline import build_timeline_plan
from movie_narrator.narration.segments import (
    BoundNarrationSegment,
    NarrationSegmentsDocument,
)
from movie_narrator.visual_events import build_visual_event_index


def _database() -> SceneDatabase:
    return SceneDatabase(
        source_video="movie.mkv",
        source_sha256="abc",
        scene_detector="test",
        asr_backend="test",
        asr_status=VerificationStatus.UNVERIFIED,
        visual_backend="test",
        visual_status=AnalysisStatus.COMPLETE,
        scenes=[
            SceneRecord(
                scene_id="SCN-0001",
                start_time=10,
                end_time=20,
                action="人物走上舞台",
                visual_description="舞台灯光亮起",
                importance_score=0.95,
                analysis_status=AnalysisStatus.COMPLETE,
            )
        ],
    )


def _narration(event_id: str, *, spoken_anchor: float | None = None) -> NarrationSegmentsDocument:
    return NarrationSegmentsDocument(
        status="TTS_READY",
        segments=[
            BoundNarrationSegment(
                narration_id="NAR-0001",
                event_ids=[event_id],
                text="人物终于走上舞台",
                target_visual_start=10,
                target_visual_end=20,
                target_duration=10,
                actual_tts_duration=4,
                visual_anchor="走上舞台",
                spoken_anchor_time=spoken_anchor,
                critical_event=True,
                sync_confidence=0.8,
            )
        ],
    )


def test_visual_event_index_is_source_first_and_candidate():
    index = build_visual_event_index(_database())
    assert index.index_status == "EVENT_INDEXED"
    assert index.events[0].shot_ids == ["SCN-0001"]
    assert index.events[0].story_event == "UNKNOWN"
    assert index.events[0].review_status == "CANDIDATE"


def test_sync_map_uses_real_tts_duration_and_detects_narration_lead():
    index = build_visual_event_index(_database())
    narration = _narration(index.events[0].event_id, spoken_anchor=0)
    timeline = {
        "items": [
            {
                "timeline_id": "TL-1",
                "narration_segment_id": "NAR-0001",
                "start": 0,
                "end": 10,
                "video": {"source_start": 10, "source_end": 20},
                "caption_aligned": True,
            }
        ]
    }
    sync_map = build_sync_map(narration, index, timeline=timeline)
    report = evaluate_alignment(sync_map)
    assert sync_map.rows[0].tts_duration == 4
    assert sync_map.rows[0].semantic_offset == 5
    assert report.status == "FAIL"
    assert any(issue.check_id == "narration_lead" for issue in report.issues)
    assert plan_repairs(report, sync_map)[0].action == "TRIM_TARGET_VIDEO"


def test_missing_readback_is_unknown_not_final_ready():
    index = build_visual_event_index(_database())
    sync_map = build_sync_map(_narration(index.events[0].event_id), index)
    report = evaluate_alignment(sync_map)
    assert report.status == "PASS_WITH_UNKNOWN"
    assert report.final_ready is False
    assert any("CHATCUT_TIMELINE_READBACK" in item for item in report.unknowns)


def test_chatcut_connection_probe_does_not_claim_success_without_evidence():
    def runner(*args, **kwargs):
        class Result:
            returncode = 0
            stdout = "Server chatcut: Needs authentication"
            stderr = ""

        return Result()

    report = probe_chatcut_connection(command_runner=runner)
    assert report.mcp_configured is True
    assert report.authenticated is False
    assert report.ready_for_edit is False


def test_chatcut_timeline_plan_has_fixed_logical_lanes():
    index = build_visual_event_index(_database())
    sync_map = build_sync_map(_narration(index.events[0].event_id), index)
    plan = build_timeline_plan(sync_map)
    assert plan.tracks["V1"] == "original_picture"
    assert {item.track for item in plan.items} == {"V1", "A2", "C1"}


def test_chatcut_client_matches_current_mcp_preview_and_edit_shapes():
    calls = []

    def gateway(tool_name, arguments):
        calls.append((tool_name, arguments))
        return {"ok": True}

    client = ChatCutClient(gateway)
    client.render_preview(project_id="P-1", timeline_id="T-1")
    client.apply_edit(
        {"updates": [{"id": "I-1", "fromFrame": 12, "durationInFrames": 30}]},
        project_id="P-1",
    )

    assert calls == [
        (
            "preview_timeline",
            {"views": ["viewer"], "projectId": "P-1", "timelineId": "T-1"},
        ),
        (
            "edit_item",
            {
                "updates": [{"id": "I-1", "fromFrame": 12, "durationInFrames": 30}],
                "projectId": "P-1",
            },
        ),
    ]


def test_chatcut_backend_reads_timeline_with_current_view_name():
    calls = []

    def gateway(tool_name, arguments):
        calls.append((tool_name, arguments))
        return {"items": []}

    backend = ChatCutEditingBackend(
        client=ChatCutClient(gateway), project_id="P-1", timeline_id="T-1"
    )
    backend.read_timeline()

    assert calls == [
        (
            "preview_timeline",
            {"views": ["timeline"], "projectId": "P-1", "timelineId": "T-1"},
        )
    ]


def test_chatcut_client_rejects_unmapped_semantic_repair():
    calls = []

    def gateway(tool_name, arguments):
        calls.append((tool_name, arguments))
        return {"ok": True}

    client = ChatCutClient(gateway)
    with pytest.raises(ValueError, match="host-side item/frame mapping"):
        client.apply_edit({"action": "TRIM_TARGET_VIDEO", "sync_id": "SYNC-0001"})
    assert calls == []
