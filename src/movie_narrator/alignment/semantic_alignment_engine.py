# SPDX-License-Identifier: AGPL-3.0-or-later

"""Named semantic-alignment engine facade for host integrations."""

from __future__ import annotations

from dataclasses import dataclass

from .models import AlignmentReport, SyncMapDocument
from .qc import AlignmentConfig, evaluate_alignment


@dataclass(frozen=True)
class SemanticAlignmentEngine:
    config: AlignmentConfig = AlignmentConfig()

    def evaluate(self, sync_map: SyncMapDocument) -> AlignmentReport:
        return evaluate_alignment(sync_map, config=self.config)


__all__ = ["SemanticAlignmentEngine"]
