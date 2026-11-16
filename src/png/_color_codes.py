"""Defined CICP code points in PNG's fixed ITU-T H.273 (07/2024) reference."""

from png.error import PngValidationError

PRIMARIES = frozenset((1, 2, 22)) | frozenset(range(4, 13))
TRANSFERS = frozenset((1, 2)) | frozenset(range(4, 19))
MATRICES = frozenset((0, 1, 2)) | frozenset(range(4, 18))


def validate_code_points(primaries: int, transfer: int, matrix: int, full_range: int) -> None:
    if primaries not in PRIMARIES or transfer not in TRANSFERS or matrix not in MATRICES or full_range not in (0, 1):
        raise PngValidationError('CICP uses code points reserved by ITU-T H.273 (07/2024)')
