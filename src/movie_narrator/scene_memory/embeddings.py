# SPDX-License-Identifier: AGPL-3.0-or-later

"""Embedding adapters with a deterministic offline fallback."""

from __future__ import annotations

import hashlib
import math
import re
from typing import Protocol, Sequence


Vector = list[float]


class TextEmbedder(Protocol):
    name: str

    def encode(self, texts: Sequence[str]) -> list[Vector]: ...


class VisualEmbedder(Protocol):
    name: str

    def encode_images(self, image_paths: Sequence[str]) -> list[Vector]: ...

    def encode_texts(self, texts: Sequence[str]) -> list[Vector]: ...


def normalize(vector: Vector) -> Vector:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]


def cosine(left: Vector, right: Vector) -> float:
    if len(left) != len(right):
        raise ValueError("embedding dimensions do not match")
    return sum(a * b for a, b in zip(left, right))


class HashingTextEmbedder:
    """Local lexical embeddings for deterministic degraded retrieval."""

    name = "hashing-text-v1"

    def __init__(self, dimensions: int = 512) -> None:
        if dimensions < 32:
            raise ValueError("dimensions must be at least 32")
        self.dimensions = dimensions

    def encode(self, texts: Sequence[str]) -> list[Vector]:
        return [self._encode_one(text) for text in texts]

    def _encode_one(self, text: str) -> Vector:
        normalized_text = re.sub(r"\s+", "", text.lower())
        tokens = list(normalized_text)
        tokens.extend(
            normalized_text[index : index + 2]
            for index in range(len(normalized_text) - 1)
        )
        vector = [0.0] * self.dimensions
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign
        return normalize(vector)


class SentenceTransformerTextEmbedder:
    name = "sentence-transformers"

    def __init__(self, model_name: str = "paraphrase-multilingual-MiniLM-L12-v2") -> None:
        self.model_name = model_name
        self._model = None

    def encode(self, texts: Sequence[str]) -> list[Vector]:
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name)
        vectors = self._model.encode(list(texts), normalize_embeddings=True)
        return [[float(value) for value in row] for row in vectors]


class SentenceTransformerVisualEmbedder:
    """CLIP-compatible text/image embeddings loaded only when explicitly selected."""

    name = "sentence-transformers-clip"

    def __init__(self, model_name: str = "clip-ViT-B-32") -> None:
        self.model_name = model_name
        self._model = None

    def _load(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name)
        return self._model

    def encode_images(self, image_paths: Sequence[str]) -> list[Vector]:
        from PIL import Image

        images = []
        try:
            for path in image_paths:
                images.append(Image.open(path).convert("RGB"))
            vectors = self._load().encode(images, normalize_embeddings=True)
            return [[float(value) for value in row] for row in vectors]
        finally:
            for image in images:
                image.close()

    def encode_texts(self, texts: Sequence[str]) -> list[Vector]:
        vectors = self._load().encode(list(texts), normalize_embeddings=True)
        return [[float(value) for value in row] for row in vectors]
