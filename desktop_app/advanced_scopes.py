"""Lightweight luma waveform, RGB parade and vectorscope calculations."""
from __future__ import annotations

from typing import Sequence

from color_scopes import SCOPE_HEIGHT, SCOPE_WIDTH

ScopeMatrix = tuple[tuple[int, ...], ...]
VECTOR_SIZE = 128


def _validate_rgb24(rgb24: bytes) -> None:
    expected = SCOPE_WIDTH * SCOPE_HEIGHT * 3
    if len(rgb24) != expected:
        raise ValueError(f"Expected {expected} RGB bytes, received {len(rgb24)}")


def calculate_luma_waveform(rgb24: bytes) -> ScopeMatrix:
    """Return [luma_bin][horizontal_pixel] counts for a 256x144 frame."""
    _validate_rgb24(rgb24)
    matrix = [[0] * SCOPE_WIDTH for _ in range(256)]
    for y in range(SCOPE_HEIGHT):
        row_offset = y * SCOPE_WIDTH * 3
        for x in range(SCOPE_WIDTH):
            offset = row_offset + x * 3
            red, green, blue = rgb24[offset:offset + 3]
            luma = (77 * red + 150 * green + 29 * blue) >> 8
            matrix[luma][x] += 1
    return tuple(tuple(row) for row in matrix)


def calculate_rgb_parade(rgb24: bytes) -> tuple[ScopeMatrix, ScopeMatrix, ScopeMatrix]:
    """Return three [value_bin][horizontal_pixel] matrices."""
    _validate_rgb24(rgb24)
    channels = [[[0] * SCOPE_WIDTH for _ in range(256)] for _ in range(3)]
    for y in range(SCOPE_HEIGHT):
        row_offset = y * SCOPE_WIDTH * 3
        for x in range(SCOPE_WIDTH):
            offset = row_offset + x * 3
            channels[0][rgb24[offset]][x] += 1
            channels[1][rgb24[offset + 1]][x] += 1
            channels[2][rgb24[offset + 2]][x] += 1
    return tuple(tuple(tuple(row) for row in channel) for channel in channels)  # type: ignore[return-value]


def calculate_vectorscope(rgb24: bytes) -> ScopeMatrix:
    """Accumulate Rec.601-style Cb/Cr chroma into a compact 128x128 plot."""
    _validate_rgb24(rgb24)
    matrix = [[0] * VECTOR_SIZE for _ in range(VECTOR_SIZE)]
    for offset in range(0, len(rgb24), 3):
        red, green, blue = rgb24[offset], rgb24[offset + 1], rgb24[offset + 2]
        # Cb/Cr are centered at zero; map the useful chroma range into the plot.
        cb = (-0.168736 * red - 0.331264 * green + 0.5 * blue) / 255.0
        cr = (0.5 * red - 0.418688 * green - 0.081312 * blue) / 255.0
        x = max(0, min(VECTOR_SIZE - 1, round(63.5 + cb * 127.0)))
        y = max(0, min(VECTOR_SIZE - 1, round(63.5 - cr * 127.0)))
        matrix[y][x] += 1
    return tuple(tuple(row) for row in matrix)


def validate_scope_matrix(matrix: Sequence[Sequence[int]]) -> None:
    if len(matrix) != 256 or any(len(row) != SCOPE_WIDTH for row in matrix):
        raise ValueError("Scope matrix must be 256x256")
    if any(value < 0 for row in matrix for value in row):
        raise ValueError("Scope counts cannot be negative")


def validate_vectorscope_matrix(matrix: Sequence[Sequence[int]]) -> None:
    if len(matrix) != VECTOR_SIZE or any(len(row) != VECTOR_SIZE for row in matrix):
        raise ValueError("Vectorscope matrix must be 128x128")
    if any(value < 0 for row in matrix for value in row):
        raise ValueError("Vectorscope counts cannot be negative")
