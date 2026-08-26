# SPDX-License-Identifier: AGPL-3.0-or-later

"""Semantic alignment gate and report generation."""

from __future__ import annotations

from dataclasses import dataclass

from .models import AlignmentIssue, AlignmentReport, SyncMapDocument


NARRATION_VISUAL_LEAD_GATE = "NARRATION_VISUAL_LEAD_GATE"
FINAL_SYNC_QC = "FINAL_SYNC_QC"


@dataclass(frozen=True)
class AlignmentConfig:
    preferred_visual_lead_min: float = 0.0
    preferred_visual_lead_max: float = 1.5
    narration_lead_soft_limit: float = 0.5
    narration_lead_hard_limit: float = 1.0
    normal_event_tolerance: float = 1.5
    critical_event_tolerance: float = 0.8


def _issue(sync_id: str, check_id: str, severity: str, message: str, **evidence) -> AlignmentIssue:
    return AlignmentIssue(
        check_id=check_id,
        severity=severity,
        sync_id=sync_id,
        message=message,
        evidence=evidence,
    )


def evaluate_alignment(
    sync_map: SyncMapDocument,
    *,
    config: AlignmentConfig | None = None,
) -> AlignmentReport:
    """Evaluate every row; unknown evidence never upgrades to final-ready."""

    policy = config or AlignmentConfig()
    issues: list[AlignmentIssue] = []
    unknowns: set[str] = set()
    for row in sync_map.rows:
        sid = row.sync_id
        if not row.visual_event_ids:
            issues.append(_issue(sid, "visual_anchor_exists", "ERROR", "No visual event is bound."))
        if row.event_match_status == "FAIL":
            issues.append(_issue(sid, "event_match", "ERROR", "Bound visual event cannot be resolved."))
        elif row.event_match_status != "PASS":
            unknowns.add(f"{sid}:EVENT_BINDING_REQUIRES_LOCK")
        if row.fit_status == "SYNC_FIT_FAIL":
            issues.append(
                _issue(
                    sid,
                    "tts_duration_fit",
                    "ERROR",
                    "Actual TTS duration exceeds the visual window.",
                    tts_duration=row.tts_duration,
                    source_window=[row.source_start, row.source_end],
                )
            )
        elif row.fit_status == "UNKNOWN":
            unknowns.add(f"{sid}:ACTUAL_TTS_DURATION_PENDING")
        if row.timeline_start is None or row.timeline_end is None:
            unknowns.add(f"{sid}:CHATCUT_TIMELINE_READBACK_PENDING")
        if row.anchor_timeline_time is None or row.spoken_anchor_time is None:
            unknowns.add(f"{sid}:WORD_LEVEL_ANCHOR_PENDING")
        else:
            if row.narration_lead is not None:
                tolerance = (
                    policy.critical_event_tolerance
                    if row.critical_event
                    else policy.normal_event_tolerance
                )
                hard_limit = min(tolerance, policy.narration_lead_hard_limit)
                if row.narration_lead > hard_limit:
                    issues.append(
                        _issue(
                            sid,
                            "narration_lead",
                            "ERROR",
                            "Narration leads the critical visual anchor.",
                            narration_lead=row.narration_lead,
                            allowed=hard_limit,
                        )
                    )
                elif row.narration_lead > policy.narration_lead_soft_limit:
                    issues.append(
                        _issue(
                            sid,
                            "narration_lead_soft_limit",
                            "WARNING",
                            "Narration is ahead of the visual anchor beyond the soft limit.",
                            narration_lead=row.narration_lead,
                            soft_limit=policy.narration_lead_soft_limit,
                        )
                    )
            if row.visual_lead is not None and row.visual_lead > policy.preferred_visual_lead_max:
                issues.append(
                    _issue(
                        sid,
                        "visual_lead",
                        "WARNING",
                        "Visual lead is longer than the preferred breathing window.",
                        visual_lead=row.visual_lead,
                        preferred_max=policy.preferred_visual_lead_max,
                    )
                )
        if row.original_audio_conflict:
            issues.append(
                _issue(
                    sid,
                    "original_audio_conflict",
                    "ERROR",
                    "Narration overlaps an explicitly protected original-audio interval.",
                )
            )
        if row.caption_aligned is False:
            issues.append(_issue(sid, "caption_alignment", "ERROR", "Caption timing is out of alignment."))
        elif row.caption_aligned is None:
            unknowns.add(f"{sid}:CAPTION_ALIGNMENT_PENDING")
        if row.stale_sync_map:
            issues.append(
                _issue(
                    sid,
                    "stale_sync_map",
                    "ERROR",
                    "Timeline changed after this row was mapped; read it back before QC.",
                )
            )

    has_error = any(issue.severity == "ERROR" for issue in issues)
    status = "FAIL" if has_error else "PASS_WITH_UNKNOWN" if unknowns else "PASS"
    return AlignmentReport(
        status=status,
        final_ready=status == "PASS",
        issues=issues,
        unknowns=sorted(unknowns),
        rows_checked=len(sync_map.rows),
    )
