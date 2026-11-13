from enum import IntEnum, unique


@unique
class PngColorType(IntEnum):
    GRAYSCALE = 0
    TRUECOLOR = 2
    INDEXED_COLOR = 3
    GRAYSCALE_ALPHA = 4
    TRUECOLOR_ALPHA = 6

    @property
    def channels(self) -> int:
        """Stored samples per pixel; an indexed pixel contains one index."""
        return {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[self]

    @property
    def bit_depths(self) -> tuple[int, ...]:
        return {
            0: (1, 2, 4, 8, 16),
            2: (8, 16),
            3: (1, 2, 4, 8),
            4: (8, 16),
            6: (8, 16),
        }[self]


@unique
class PngCompressionMethod(IntEnum):
    DEFLATE = 0


@unique
class PngFilterMethod(IntEnum):
    ADAPTIVE = 0


@unique
class PngInterlaceMethod(IntEnum):
    NONE = 0
    ADAM7 = 1


@unique
class PngFilterType(IntEnum):
    NONE = 0
    SUB = 1
    UP = 2
    AVERAGE = 3
    PAETH = 4


@unique
class PngDisposeOp(IntEnum):
    NONE = 0
    BACKGROUND = 1
    PREVIOUS = 2


@unique
class PngBlendOp(IntEnum):
    SOURCE = 0
    OVER = 1
