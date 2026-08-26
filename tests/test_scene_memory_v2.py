from movie_narrator.cinematic.models import NarrationSegment, SceneDatabase, SceneRecord
from movie_narrator.scene_memory import SceneMemory


class StubEmbedder:
    name = "stub"

    def encode(self, texts):
        vectors = []
        for text in texts:
            vectors.append([1.0, 0.0] if "舞台" in text or "登台" in text else [0.0, 1.0])
        return vectors


def test_scene_memory_returns_top_k_and_keeps_candidate_state(tmp_path):
    database = SceneDatabase(
        source_video="movie.mp4",
        source_sha256="abc",
        scene_detector="stub",
        asr_backend="none",
        visual_backend="stub",
        scenes=[
            SceneRecord(
                scene_id="SCN-0001",
                start_time=0,
                end_time=5,
                location="舞台",
                visual_description="第一次登台",
            ),
            SceneRecord(
                scene_id="SCN-0002",
                start_time=5,
                end_time=10,
                location="医院",
                visual_description="医院走廊",
            ),
        ],
    )
    narration = NarrationSegment(
        id="NAR-0001",
        narration="他终于站到观众面前。",
        target_scene="第一次登台",
        emotion="紧张",
    )
    memory = SceneMemory(database, text_embedder=StubEmbedder())
    match = memory.retrieve(narration, top_k=2)

    assert match.selected_scene_id == "SCN-0001"
    assert match.selection_status == "CANDIDATE"
    assert [candidate.scene_id for candidate in match.candidates] == ["SCN-0001", "SCN-0002"]

    target = memory.write_matches([match], tmp_path / "matches.json")
    assert target.exists()
    assert '"selection_status": "CANDIDATE"' in target.read_text(encoding="utf-8")


def test_hashing_embedder_path_is_available_without_model_download():
    database = SceneDatabase(
        source_video="movie.mp4",
        source_sha256="abc",
        scene_detector="stub",
        asr_backend="none",
        visual_backend="none",
        scenes=[SceneRecord(scene_id="SCN-0001", start_time=0, end_time=5)],
    )
    match = SceneMemory(database).retrieve(
        NarrationSegment(id="NAR-0001", narration="测试", target_scene="测试"),
        top_k=1,
    )
    assert len(match.candidates) == 1


def test_scene_memory_uses_cross_modal_text_to_image_similarity(tmp_path):
    first = tmp_path / "first.jpg"
    second = tmp_path / "second.jpg"
    first.touch()
    second.touch()

    class CrossModalStub:
        name = "cross-modal-stub"

        def encode_images(self, paths):
            return [[1.0, 0.0] if path == str(first) else [0.0, 1.0] for path in paths]

        def encode_texts(self, texts):
            return [[0.0, 1.0] for _ in texts]

    class NeutralText:
        name = "neutral"

        def encode(self, texts):
            return [[1.0, 0.0] for _ in texts]

    database = SceneDatabase(
        source_video="movie.mp4",
        source_sha256="abc",
        scene_detector="stub",
        asr_backend="none",
        visual_backend="stub",
        scenes=[
            SceneRecord(
                scene_id="S1", start_time=0, end_time=2, thumbnail_path=str(first)
            ),
            SceneRecord(
                scene_id="S2", start_time=2, end_time=4, thumbnail_path=str(second)
            ),
        ],
    )
    match = SceneMemory(
        database,
        text_embedder=NeutralText(),
        visual_embedder=CrossModalStub(),
        text_weight=0.25,
        visual_weight=0.75,
    ).retrieve(NarrationSegment(id="N1", narration="目标", target_scene="目标"))

    assert match.selected_scene_id == "S2"
    assert match.candidates[0].visual_score == 1.0
