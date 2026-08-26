# SPDX-License-Identifier: AGPL-3.0-or-later

"""Hard validation for cinematic multi-track timelines."""

from __future__ import annotations

import json
from pathlib import Path

from ..cinematic.models import (
    QualityIssue,
    QualityReport,
    TimelineDocument,
    VerificationStatus,
)


_EPSILON = 0.001


class TimelineValidationError(RuntimeError):
    def __init__(self, report: QualityReport) -> None:
        super().__init__("cinematic timeline validation failed")
        self.report = report


class TimelineValidator:
    def __init__(
        self,
        *,
        minimum_similarity: float = 0.2,
        protected_dialogue_narration_limit: float = 0.1,
    ) -> None:
        self.minimum_similarity = minimum_similarity
        self.protected_dialogue_narration_limit = protected_dialogue_narration_limit

    def validate(self, timeline: TimelineDocument) -> QualityReport:
        issues: list[QualityIssue] = []
        unknowns: set[str] = set()
        expected_start = 0.0

        for item in timeline.items:
            if abs(item.start - expected_start) > _EPSILON:
                issues.append(
                    self._issue(
                        "TIMELINE_GAP_OR_OVERLAP",
                        "ERROR",
                        item.timeline_id,
                        "Timeline items are not contiguous.",
                        {"expected_start": expected_start, "actual_start": item.start},
                    )
                )
            output_duration = item.end - item.start
            source_duration = item.video.source_end - item.video.source_start
            if abs(output_duration - source_duration) > _EPSILON:
                issues.append(
                    self._issue(
                        "SOURCE_DURATION_MISMATCH",
                        "ERROR",
                        item.timeline_id,
                        "Output duration differs from selected source interval.",
                        {"output_duration": output_duration, "source_duration": source_duration},
                    )
                )

            narration = item.audio.narration
            if narration.enabled:
                if not narration.asset:
                    issues.append(
                        self._issue(
                            "NARRATION_ASSET_MISSING",
                            "ERROR",
                            item.timeline_id,
                            "Narration is enabled but no TTS asset is assigned.",
                        )
                    )
                if item.subtitle is None:
                    issues.append(
                        self._issue(
                            "NARRATION_TIMING_MISSING",
                            "ERROR",
                            item.timeline_id,
                            "Narration is enabled but timed subtitle coverage is missing.",
                        )
                    )
                elif not item.subtitle.text.strip():
                    issues.append(
                        self._issue(
                            "SUBTITLE_TEXT_MISSING",
                            "ERROR",
                            item.timeline_id,
                            "Narration is enabled but subtitle text is empty.",
                        )
                    )
                if narration.duration is None:
                    unknowns.add("NARRATION_ASSET_DURATION_VERIFICATION_PENDING")
                elif narration.duration > output_duration + _EPSILON:
                    issues.append(
                        self._issue(
                            "NARRATION_EXCEEDS_PICTURE",
                            "ERROR",
                            item.timeline_id,
                            "Narration duration exceeds the selected picture interval.",
                            {
                                "narration_duration": narration.duration,
                                "picture_duration": output_duration,
                            },
                        )
                    )

            if item.subtitle:
                if (
                    item.subtitle.start < item.start - _EPSILON
                    or item.subtitle.end > item.end + _EPSILON
                    or item.subtitle.end <= item.subtitle.start
                ):
                    issues.append(
                        self._issue(
                            "SUBTITLE_OUT_OF_BOUNDS",
                            "ERROR",
                            item.timeline_id,
                            "Subtitle timing falls outside its timeline item.",
                            {
                                "subtitle": [item.subtitle.start, item.subtitle.end],
                                "item": [item.start, item.end],
                            },
                        )
                    )
                if narration.enabled and narration.duration is not None:
                    subtitle_duration = item.subtitle.end - item.subtitle.start
                    if abs(subtitle_duration - narration.duration) > 0.1:
                        issues.append(
                            self._issue(
                                "SUBTITLE_NARRATION_DESYNC",
                                "ERROR",
                                item.timeline_id,
                                "Subtitle duration does not match the narration asset duration.",
                                {
                                    "subtitle_duration": subtitle_duration,
                                    "narration_duration": narration.duration,
                                },
                            )
                        )

            verified_dialogue = [
                cue
                for cue in item.protected_dialogue
                if cue.verification_status is VerificationStatus.VERIFIED
            ]
            unverified_dialogue = [
                cue
                for cue in item.protected_dialogue
                if cue.verification_status is not VerificationStatus.VERIFIED
            ]
            overlapping_verified_dialogue = [
                cue
                for cue in verified_dialogue
                if self._dialogue_overlaps_narration(item, cue)
            ]
            if (
                overlapping_verified_dialogue
                and narration.enabled
                and narration.volume > self.protected_dialogue_narration_limit
            ):
                issues.append(
                    self._issue(
                        "DIALOGUE_OVERLAP",
                        "ERROR",
                        item.timeline_id,
                        "Verified source dialogue is covered by narration.",
                        {
                            "narration_volume": narration.volume,
                            "overlap_count": len(overlapping_verified_dialogue),
                        },
                    )
                )
            if unverified_dialogue:
                unknowns.add("SOURCE_DIALOGUE_LISTENING_VERIFICATION_PENDING")

            original = item.audio.original
            if verified_dialogue and (
                not original.enabled or original.volume < 0.5
            ):
                issues.append(
                    self._issue(
                        "VERIFIED_DIALOGUE_NOT_AUDIBLE",
                        "ERROR",
                        item.timeline_id,
                        "Verified source dialogue is not preserved at an audible level.",
                        {
                            "original_enabled": original.enabled,
                            "original_volume": original.volume,
                        },
                    )
                )
            if verified_dialogue and item.audio.bgm.enabled and item.audio.bgm.volume >= 0.5:
                issues.append(
                    self._issue(
                        "BGM_DIALOGUE_COLLISION",
                        "ERROR",
                        item.timeline_id,
                        "BGM is foreground-level during verified dialogue.",
                        {"bgm_volume": item.audio.bgm.volume},
                    )
                )
            if narration.enabled and original.enabled:
                if narration.volume >= 0.8 and original.volume >= 0.7:
                    issues.append(
                        self._issue(
                            "AUDIO_LANGUAGE_COLLISION",
                            "ERROR",
                            item.timeline_id,
                            "Narration and source audio are both foreground.",
                            {
                                "narration_volume": narration.volume,
                                "original_volume": original.volume,
                            },
                        )
                    )
                elif narration.volume >= 0.5 and original.volume >= 0.5:
                    issues.append(
                        self._issue(
                            "AUDIO_CONFLICT_RISK",
                            "WARNING",
                            item.timeline_id,
                            "Narration and source audio may compete.",
                        )
                    )

            if (
                item.match.selection_status == "LOCKED"
                and item.match.similarity_score < self.minimum_similarity
            ):
                issues.append(
                    self._issue(
                        "SEMANTIC_AV_MISMATCH",
                        "ERROR",
                        item.timeline_id,
                        "Locked scene similarity is below the semantic alignment threshold.",
                        {"similarity_score": item.match.similarity_score},
                    )
                )
            elif item.match.similarity_score < self.minimum_similarity:
                issues.append(
                    self._issue(
                        "LOW_SCENE_MATCH",
                        "WARNING",
                        item.timeline_id,
                        "Narration-to-scene similarity is below the review threshold.",
                        {"similarity_score": item.match.similarity_score},
                    )
                )
            if item.match.selection_status != "LOCKED":
                unknowns.add("SEMANTIC_AV_ALIGNMENT_REQUIRES_REVIEW")
            expected_start = item.end

        if abs(timeline.duration - expected_start) > _EPSILON:
            issues.append(
                self._issue(
                    "TIMELINE_DURATION_MISMATCH",
                    "ERROR",
                    None,
                    "Timeline duration does not equal the end of the final item.",
                    {"declared": timeline.duration, "computed": expected_start},
                )
            )

        has_error = any(issue.severity == "ERROR" for issue in issues)
        status = "FAIL" if has_error else "PASS_WITH_UNKNOWN" if unknowns else "PASS"
        return QualityReport(
            status=status,
            issues=issues,
            unknowns=sorted(unknowns),
        )

    @staticmethod
    def _dialogue_overlaps_narration(item, cue) -> bool:
        if not item.audio.narration.enabled:
            return False
        narration_start = item.subtitle.start if item.subtitle else item.start
        narration_end = item.subtitle.end if item.subtitle else item.end
        cue_start = item.start + max(0.0, cue.start_time - item.video.source_start)
        cue_end = item.start + min(
            item.end - item.start,
            cue.end_time - item.video.source_start,
        )
        return cue_end > narration_start + _EPSILON and cue_start < narration_end - _EPSILON

    def validate_or_raise(self, timeline: TimelineDocument) -> QualityReport:
        report = self.validate(timeline)
        if report.status == "FAIL":
            raise TimelineValidationError(report)
        return report

    @staticmethod
    def write(
        report: QualityReport,
        output_path: str | Path,
    ) -> Path:
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        content = json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n"
        target.write_text(content, encoding="utf-8")
        return target

    @staticmethod
    def _issue(
        check_id: str,
        severity: str,
        timeline_id: str | None,
        message: str,
        evidence: dict | None = None,
    ) -> QualityIssue:
        return QualityIssue(
            check_id=check_id,
            severity=severity,
            timeline_id=timeline_id,
            message=message,
            evidence=evidence or {},
        )
