from collections.abc import Iterator

_ADAM7 = ((0, 0, 8, 8), (4, 0, 8, 8), (0, 4, 4, 8), (2, 0, 4, 4), (0, 2, 2, 4), (1, 0, 2, 2), (0, 1, 1, 2))


def scan_passes(width: int, height: int, interlace: int) -> Iterator[tuple[int, int, int, int, int, int]]:
    passes = _ADAM7 if interlace == 1 else ((0, 0, 1, 1),)
    for offset_x, offset_y, step_x, step_y in passes:
        pass_width = max(0, (width - offset_x + step_x - 1) // step_x)
        pass_height = max(0, (height - offset_y + step_y - 1) // step_y)
        if pass_width and pass_height:
            yield offset_x, offset_y, step_x, step_y, pass_width, pass_height
