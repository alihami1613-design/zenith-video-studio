"""Low-cost luma waveform and RGB parade sampling."""
from __future__ import annotations

from typing import Sequence

from color_scopes import SCOPE_HEIGHT, SCOPE_WIDTH


ScopeMatrix = tuple[tuple[int, ...], ...]


def _validate_rgb24(rgb24: bytes) -> None:
    expected = SCOPE_WIDTH * SCOPE_HEIGHT * 3
    if len(rgb24) != expected:
        raise ValueError(f"Expected {expected} RGB bytes, received {len(rgb24)}")


def calculate_luma_waveform(rgb24: bytes) -> ScopeMatrix:
    """Return [luma_bin][horizontal_pixel] counts for a 256x144 frame."""
    _validate_rgb24(rgb24)
    matrix = [[0] * SCOPE_WIDTH for _ in range(256)]
    pixel = 0
    for y in range(SCOPE_HEIGHT):
        row_offset = y * SCOPE_WIDTH * 3
        for x in range(SCOPE_WIDTH):
            offset = row_offset + x * 3
            red, green, blue = rgb24[offset:offset + 3]
            luma = (77 * red + 150 * green + 29 * blue) >> 8
            matrix[luma][x] += 1
            pixel += 1
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


def validate_scope_matrix(matrix: Sequence[Sequence[int]]) -> None:
    if len(matrix) != 256 or any(len(row) != SCOPE_WIDTH for row in matrix):
        raise ValueError("Scope matrix must be 256x256")
    if any(value < 0 for row in matrix for value in row):
        raise ValueError("Scope counts cannot be negative")
