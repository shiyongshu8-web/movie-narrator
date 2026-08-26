# SPDX-License-Identifier: AGPL-3.0-or-later

"""Quality state machine for event-bound editable cuts."""

from __future__ import annotations

from enum import Enum


class QualityState(str, Enum):
    DISCOVERED = "DISCOVERED"
    ANALYZED = "ANALYZED"
    EVENT_INDEXED = "EVENT_INDEXED"
    SCRIPTED = "SCRIPTED"
    TTS_READY = "TTS_READY"
    SYNC_MAPPED = "SYNC_MAPPED"
    CHATCUT_TIMELINE_CREATED = "CHATCUT_TIMELINE_CREATED"
    SYNC_QC = "SYNC_QC"
    AUTO_REPAIR = "AUTO_REPAIR"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    FINAL_APPROVED = "FINAL_APPROVED"
    EXPORTED = "EXPORTED"


_ORDER = list(QualityState)


def advance_state(current: QualityState, target: QualityState) -> QualityState:
    """Allow only forward transitions, except QC -> AUTO_REPAIR -> QC."""

    if current == target:
        return current
    if current is QualityState.SYNC_QC and target is QualityState.AUTO_REPAIR:
        return target
    if current is QualityState.SYNC_QC and target is QualityState.READY_FOR_REVIEW:
        return target
    if current is QualityState.AUTO_REPAIR and target is QualityState.SYNC_QC:
        return target
    if _ORDER.index(target) != _ORDER.index(current) + 1:
        raise ValueError(f"illegal quality transition: {current.value} -> {target.value}")
    return target
