"""Dependency-free vector validation and cosine similarity shared with offline evaluation."""

import math


def normalized_vector(value):
    if (
        not isinstance(value, (list, tuple))
        or not 1 <= len(value) <= 4096
        or any(type(x) not in {int, float} or not math.isfinite(x) for x in value)
    ):
        raise ValueError("INVALID_EMBEDDING")
    norm = math.sqrt(sum(x * x for x in value))
    if not math.isfinite(norm) or norm <= 0:
        raise ValueError("INVALID_EMBEDDING_NORM")
    return [float(x / norm) for x in value]


def cosine(left, right):
    left, right = normalized_vector(left), normalized_vector(right)
    if len(left) != len(right):
        raise ValueError("EMBEDDING_DIMENSION_MISMATCH")
    return sum(a * b for a, b in zip(left, right))
