# SPDX-License-Identifier: AGPL-3.0-or-later

"""Plan and execute evidence-aware alignment repairs.

The executor is intentionally transport-neutral.  A ChatCut implementation
must apply operations through the official MCP tools, then read the timeline
back before a new SYNC_MAP is accepted.
"""

from __future__ import annotations

from typing import Any, Protocol, Sequence

from pydantic import BaseModel, Field

from ..narration.segments import NarrationSegmentsDocument
from ..visual_events.models import VisualEventIndex
from .models import AlignmentReport, SyncMapDocument
from .qc import AlignmentConfig, evaluate_alignment
from .sync_map import build_sync_map


class RepairOperation(BaseModel):
    sync_id: str
    narration_id: str
    action: str
    reason: str
    event_ids: list[str] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)


class TimelineEditGateway(Protocol):
    def apply_operations(self, operations: Sequence[RepairOperation]) -> Any: ...

    def read_timeline(self) -> Any: ...


def plan_repairs(report: AlignmentReport, sync_map: SyncMapDocument) -> list[RepairOperation]:
    rows = {row.sync_id: row for row in sync_map.rows}
    operations: list[RepairOperation] = []
    for issue in report.issues:
        if issue.sync_id is None or issue.sync_id not in rows:
            continue
        row = rows[issue.sync_id]
        if issue.check_id in {"narration_lead", "narration_lead_soft_limit"}:
            action = "TRIM_TARGET_VIDEO" if (row.narration_lead or 0) > 0 else "MOVE_NARRATION"
            operations.append(
                RepairOperation(
                    sync_id=row.sync_id,
                    narration_id=row.narration_id,
                    action=action,
                    reason=issue.message,
                    event_ids=list(row.visual_event_ids),
                    parameters={"prefer": "preserve_anchor", "ripple": False},
                )
            )
        elif issue.check_id == "visual_lead":
            operations.append(
                RepairOperation(
                    sync_id=row.sync_id,
                    narration_id=row.narration_id,
                    action="DELAY_TARGET_VIDEO",
                    reason=issue.message,
                    event_ids=list(row.visual_event_ids),
                    parameters={"prefer": "extend_previous_video", "ripple": False},
                )
            )
        elif issue.check_id == "tts_duration_fit":
            operations.append(
                RepairOperation(
                    sync_id=row.sync_id,
                    narration_id=row.narration_id,
                    action="SHORTEN_OR_SPLIT_NARRATION",
                    reason=issue.message,
                    event_ids=list(row.visual_event_ids),
                    parameters={"max_speed_change": 0.08, "preserve_facts": True},
                )
            )
        elif issue.check_id == "event_match":
            operations.append(
                RepairOperation(
                    sync_id=row.sync_id,
                    narration_id=row.narration_id,
                    action="REMATCH_EVENT",
                    reason=issue.message,
                    event_ids=list(row.visual_event_ids),
                    parameters={"require_visual_evidence": True},
                )
            )
    # Deduplicate the plan while preserving the first action.  One row may
    # produce multiple issues; the backend should not receive duplicate edits.
    unique: dict[tuple[str, str], RepairOperation] = {}
    for operation in operations:
        unique.setdefault((operation.sync_id, operation.action), operation)
    return list(unique.values())


def repair_until_pass(
    *,
    gateway: TimelineEditGateway,
    narration: NarrationSegmentsDocument,
    visual_events: VisualEventIndex,
    sync_map: SyncMapDocument,
    config: AlignmentConfig | None = None,
    max_rounds: int = 3,
) -> tuple[SyncMapDocument, AlignmentReport, list[RepairOperation]]:
    """Apply edits, re-read, rebuild, and re-QC; never reuse old coordinates."""

    all_operations: list[RepairOperation] = []
    current_map = sync_map
    report = evaluate_alignment(current_map, config=config)
    for _ in range(max_rounds):
        if report.status == "PASS":
            break
        operations = plan_repairs(report, current_map)
        if not operations:
            break
        gateway.apply_operations(operations)
        all_operations.extend(operations)
        readback = gateway.read_timeline()
        current_map = build_sync_map(
            narration,
            visual_events,
            timeline=readback,
            previous_timeline_hash=current_map.timeline_readback_hash,
        )
        report = evaluate_alignment(current_map, config=config)
    return current_map, report, all_operations
