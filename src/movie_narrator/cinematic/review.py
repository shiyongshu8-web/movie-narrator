# SPDX-License-Identifier: AGPL-3.0-or-later

"""Human scene-selection lock workflow for cinematic matches."""

from __future__ import annotations

import json
from pathlib import Path

from .models import MatchesDocument, SceneDatabase
from .state import RunStateStore


def lock_matches(
    *,
    matches_path: str | Path,
    selections_path: str | Path,
    scene_database_path: str | Path,
    output_path: str | Path,
    require_all: bool = True,
) -> tuple[Path, Path]:
    matches_source = Path(matches_path)
    selections_source = Path(selections_path)
    scene_source = Path(scene_database_path)
    for path in (matches_source, selections_source, scene_source):
        if not path.is_file():
            raise FileNotFoundError(f"review input not found: {path}")

    document = MatchesDocument.model_validate_json(
        matches_source.read_text(encoding="utf-8")
    )
    database = SceneDatabase.model_validate_json(scene_source.read_text(encoding="utf-8"))
    selections = _load_selections(selections_source)
    match_ids = {item.narration_segment_id for item in document.matches}
    extra = set(selections) - match_ids
    if extra:
        raise ValueError(f"selections reference unknown narration IDs: {sorted(extra)}")
    if require_all and set(selections) != match_ids:
        missing = sorted(match_ids - set(selections))
        raise ValueError(f"selections are incomplete; missing narration IDs: {missing}")

    known_scenes = {scene.scene_id for scene in database.scenes}
    locked = []
    for match in document.matches:
        scene_id = selections.get(match.narration_segment_id)
        if scene_id is None:
            locked.append(match)
            continue
        candidate_ids = {candidate.scene_id for candidate in match.candidates}
        if scene_id not in known_scenes:
            raise ValueError(f"selected scene does not exist: {scene_id}")
        if scene_id not in candidate_ids:
            raise ValueError(
                f"selected scene {scene_id} is not a candidate for "
                f"{match.narration_segment_id}"
            )
        locked.append(
            match.model_copy(
                update={"selected_scene_id": scene_id, "selection_status": "LOCKED"}
            )
        )

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            MatchesDocument(matches=locked).model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    review_manifest = output.with_name(f"{output.stem}.review.json")
    review_manifest.write_text(
        json.dumps(
            {
                "schema_version": "2.0",
                "status": "LOCKED" if all(m.selection_status == "LOCKED" for m in locked) else "PARTIAL",
                "matches_input": str(matches_source.resolve()),
                "matches_input_sha256": RunStateStore.sha256(matches_source),
                "selections_input": str(selections_source.resolve()),
                "selections_input_sha256": RunStateStore.sha256(selections_source),
                "scene_database": str(scene_source.resolve()),
                "scene_database_sha256": RunStateStore.sha256(scene_source),
                "locked_matches": str(output.resolve()),
                "locked_matches_sha256": RunStateStore.sha256(output),
                "locked_count": sum(m.selection_status == "LOCKED" for m in locked),
                "total_count": len(locked),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return output, review_manifest


def _load_selections(path: Path) -> dict[str, str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and isinstance(payload.get("selections"), list):
        result = {}
        for item in payload["selections"]:
            if not isinstance(item, dict):
                raise ValueError("each selection must be an object")
            result[str(item.get("narration_segment_id", ""))] = str(
                item.get("scene_id", "")
            )
    elif isinstance(payload, dict):
        result = {str(key): str(value) for key, value in payload.items()}
    else:
        raise ValueError("selections must be an object or contain a selections list")
    if not result or any(not key or not value for key, value in result.items()):
        raise ValueError("selections contain an empty narration or scene ID")
    return result
