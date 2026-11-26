"""Pure helpers for Bezier graph pointer interaction."""


def nearest_handle_index(x: float, y: float, first_x: float, first_y: float,
                         second_x: float, second_y: float) -> int:
    """Return 0 for the first handle and 1 for the second (ties choose first)."""
    first_distance = (float(x) - float(first_x)) ** 2 + (float(y) - float(first_y)) ** 2
    second_distance = (float(x) - float(second_x)) ** 2 + (float(y) - float(second_y)) ** 2
    return 0 if first_distance <= second_distance else 1
