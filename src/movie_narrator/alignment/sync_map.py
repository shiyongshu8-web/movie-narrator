# SPDX-License-Identifier: AGPL-3.0-or-later

"""Build a synchronization map from narration, visual events, and readback."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .models import SyncMapDocument, SyncMapRow, TimelineItemSnapshot
from ..narration.segments import NarrationSegmentsDocument
from ..visual_events.models import VisualEventIndex


def _timeline_items(payload: Any) -> list[TimelineItemSnapshot]:
    """Normalize local v2 timelines and connector readback projections.

    The ChatCut adapter is responsible for converting its live tool result to
    this projection.  This function only accepts explicit item arrays and
    never invents project, timeline, track, or asset IDs.
    """

    if payload is None:
        return []
    if isinstance(payload, list):
        raw_items = payload
    elif isinstance(payload, dict):
        raw_items = payload.get("items")
        if raw_items is None and isinstance(payload.get("timeline"), dict):
            raw_items = payload["timeline"].get("items")
        if raw_items is None:
            raw_items = []
    else:
        raise TypeError("timeline payload must be a dict, list, or None")
    result: list[TimelineItemSnapshot] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        video = raw.get("video") or {}
        result.append(
            TimelineItemSnapshot(
                item_id=str(raw.get("item_id") or raw.get("timeline_id") or raw.get("id")),
                track_id=str(raw.get("track_id") or raw.get("track") or "UNKNOWN"),
                track_type=str(raw.get("track_type") or raw.get("type") or "VIDEO"),
                timeline_start=float(raw.get("timeline_start", raw.get("start", 0.0))),
                timeline_end=float(raw.get("timeline_end", raw.get("end", 0.0))),
                source_start=(
                    float(raw["source_start"])
                    if raw.get("source_start") is not None
                    else float(video["source_start"])
                    if video.get("source_start") is not None
                    else None
                ),
                source_end=(
                    float(raw["source_end"])
                    if raw.get("source_end") is not None
                    else float(video["source_end"])
                    if video.get("source_end") is not None
                    else None
                ),
                narration_id=(
                    raw.get("narration_id")
                    or raw.get("narration_segment_id")
                    or raw.get("metadata", {}).get("narration_id")
                ),
                event_ids=list(raw.get("event_ids") or raw.get("metadata", {}).get("event_ids", [])),
                original_audio_conflict=bool(raw.get("original_audio_conflict", False)),
                caption_aligned=raw.get("caption_aligned"),
            )
        )
    return result


def _map_source_to_timeline(source_time: float, item: TimelineItemSnapshot) -> float | None:
    if item.source_start is None or item.source_end is None:
        return None
    source_duration = item.source_end - item.source_start
    if source_duration <= 0:
        return None
    ratio = max(0.0, min(1.0, (source_time - item.source_start) / source_duration))
    return item.timeline_start + ratio * (item.timeline_end - item.timeline_start)


def _hash_payload(payload: Any) -> str | None:
    if payload is None:
        return None
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_sync_map(
    narration: NarrationSegmentsDocument,
    visual_events: VisualEventIndex,
    *,
    timeline: Any = None,
    timeline_readback_hash: str | None = None,
    previous_timeline_hash: str | None = None,
) -> SyncMapDocument:
    """Create rows without treating estimated TTS or stale coordinates as facts."""

    items = _timeline_items(timeline)
    if timeline_readback_hash is None:
        timeline_readback_hash = _hash_payload(timeline)
    event_by_id = {event.event_id: event for event in visual_events.events}
    rows: list[SyncMapRow] = []
    for index, segment in enumerate(narration.segments, 1):
        events = [event_by_id[event_id] for event_id in segment.event_ids if event_id in event_by_id]
        if not events:
            raise ValueError(f"{segment.narration_id} has no resolvable visual events")
        source_start = min(event.source_start for event in events)
        source_end = max(event.source_end for event in events)
        anchor_source = segment.anchor_source_time or events[0].anchor_source_time
        if anchor_source is None:
            anchor_source = (source_start + source_end) / 2.0
        matched = [item for item in items if item.narration_id == segment.narration_id]
        if not matched:
            matched = [
                item
                for item in items
                if set(item.event_ids).intersection(segment.event_ids)
            ]
        timeline_start = min((item.timeline_start for item in matched), default=None)
        timeline_end = max((item.timeline_end for item in matched), default=None)
        anchor_timeline = None
        if matched:
            anchor_timeline = _map_source_to_timeline(anchor_source, matched[0])

        spoken_anchor = segment.spoken_anchor_time
        if spoken_anchor is None and segment.spoken_anchor_offset is not None and timeline_start is not None:
            spoken_anchor = timeline_start + segment.spoken_anchor_offset
        semantic_offset = None
        narration_lead = None
        visual_lead = None
        if anchor_timeline is not None and spoken_anchor is not None:
            semantic_offset = anchor_timeline - spoken_anchor
            narration_lead = max(0.0, semantic_offset)
            visual_lead = max(0.0, -semantic_offset)

        picture_window = segment.target_duration
        if timeline_start is not None and timeline_end is not None:
            picture_window = min(picture_window, timeline_end - timeline_start)
        fit_status = "UNKNOWN"
        if segment.actual_tts_duration is not None:
            fit_status = (
                "PASS"
                if segment.actual_tts_duration <= picture_window + 1e-6
                else "SYNC_FIT_FAIL"
            )
        event_match_status = (
            "PASS"
            if segment.binding_status == "LOCKED" and len(events) == len(segment.event_ids)
            else "CANDIDATE"
            if len(events) == len(segment.event_ids)
            else "FAIL"
        )
        rows.append(
            SyncMapRow(
                sync_id=f"SYNC-{index:04d}",
                narration_id=segment.narration_id,
                visual_event_ids=list(segment.event_ids),
                source_start=source_start,
                source_end=source_end,
                timeline_start=timeline_start,
                timeline_end=timeline_end,
                narration_text=segment.text,
                tts_duration=segment.actual_tts_duration,
                visual_anchor=segment.visual_anchor,
                anchor_source_time=anchor_source,
                anchor_timeline_time=anchor_timeline,
                spoken_anchor_time=spoken_anchor,
                semantic_offset=semantic_offset,
                narration_lead=narration_lead,
                visual_lead=visual_lead,
                fit_status=fit_status,
                event_match_status=event_match_status,
                stale_sync_map=(
                    previous_timeline_hash is not None
                    and timeline_readback_hash != previous_timeline_hash
                ),
                original_audio_conflict=any(item.original_audio_conflict for item in matched),
                caption_aligned=(
                    all(item.caption_aligned is True for item in matched)
                    if matched and all(item.caption_aligned is not None for item in matched)
                    else None
                ),
                critical_event=segment.critical_event or any(event.critical for event in events),
                confidence=min(
                    segment.sync_confidence,
                    *(event.confidence for event in events),
                ),
                evidence={
                    "timeline_items": [item.item_id for item in matched],
                    "timeline_readback": bool(matched),
                },
            )
        )
    stale = any(row.stale_sync_map for row in rows)
    status = "STALE" if stale else "SYNC_MAPPED"
    return SyncMapDocument(
        status=status,
        timeline_readback_hash=timeline_readback_hash,
        rows=rows,
    )


def load_sync_map(path: str | Path) -> SyncMapDocument:
    return SyncMapDocument.model_validate_json(Path(path).read_text(encoding="utf-8"))


def write_sync_map(document: SyncMapDocument, output_path: str | Path) -> Path:
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(document.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target
