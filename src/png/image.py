from __future__ import annotations

from png._validation import check_integer
from png.animation import PngAnimation
from png.chunk import PngChunk
from png.error import PngValidationError
from png.format import PngColorType
from png.header import PngHeader


class PngImage:
    """Decoded PNG samples, without compressed IDAT/fdAT data.

    Rows run top to bottom, with samples interleaved left to right. For RGB,
    one row is [r, g, b, r, g, b, ...]. Grayscale and palette indices use one
    integer per pixel. Samples retain their original depth and straight alpha;
    they are never silently converted to RGBA8.
    """

    header: PngHeader
    bitmap: list[list[int]]
    palette: list[tuple[int, int, int]]
    transparent_color: tuple[int, ...] | None
    palette_alpha: list[int]
    animation: PngAnimation | None
    ancillary_chunks: list[PngChunk]

    def __init__(
            self,
            header: PngHeader,
            bitmap: list[list[int]] | None = None,
            palette: list[tuple[int, int, int]] | None = None,
            transparent_color: tuple[int, ...] | None = None,
            palette_alpha: list[int] | None = None,
            animation: PngAnimation | None = None,
            ancillary_chunks: list[PngChunk] | None = None,
    ) -> None:
        self.header = header
        self.bitmap = bitmap if bitmap is not None else []
        self.palette = palette if palette is not None else []
        self.transparent_color = transparent_color
        self.palette_alpha = palette_alpha if palette_alpha is not None else []
        self.animation = animation
        self.ancillary_chunks = ancillary_chunks if ancillary_chunks is not None else []

    @property
    def dimensions(self) -> tuple[int, int]:
        return self.header.dimensions

    def validate(self) -> None:
        """Validate the currently implemented pixel and animation model.

        Construction and field mutation allow incomplete intermediate state.
        Chunk ordering, metadata semantics and compressed data are not checked.
        """
        self.header.validate()
        for chunk in self.ancillary_chunks:
            chunk.validate()
            if chunk.is_critical or chunk.type in (b'tRNS', b'acTL', b'fcTL', b'fdAT'):
                raise PngValidationError('image structure must use its dedicated fields, not ancillary_chunks')
        color_type = PngColorType(self.header.color_type)
        if self.palette:
            if color_type in (PngColorType.GRAYSCALE, PngColorType.GRAYSCALE_ALPHA):
                raise PngValidationError('grayscale images cannot contain a palette')
            if len(self.palette) > 256:
                raise PngValidationError('a palette can contain at most 256 entries')
            for color in self.palette:
                if len(color) != 3:
                    raise PngValidationError('palette entries must contain three samples')
                for sample in color:
                    check_integer('palette sample', sample, 0, 255)
        if color_type == PngColorType.INDEXED_COLOR:
            if not 1 <= len(self.palette) <= 1 << self.header.bit_depth:
                raise PngValidationError('indexed images require a palette fitting the bit depth')
        if self.transparent_color is not None:
            if color_type not in (PngColorType.GRAYSCALE, PngColorType.TRUECOLOR):
                raise PngValidationError('a transparent color requires grayscale or truecolor without alpha')
            if len(self.transparent_color) != self.header.channels:
                raise PngValidationError('transparent color has the wrong number of samples')
            for sample in self.transparent_color:
                check_integer('transparent sample', sample, 0, (1 << self.header.bit_depth) - 1)
        if self.palette_alpha:
            if color_type != PngColorType.INDEXED_COLOR or len(self.palette_alpha) > len(self.palette):
                raise PngValidationError('palette alpha requires matching indexed palette entries')
            for alpha in self.palette_alpha:
                check_integer('palette alpha', alpha, 0, 255)
        self._validate_bitmap(self.bitmap, self.dimensions)
        if self.animation is not None:
            self.animation.validate(self.dimensions)
            for frame in self.animation.frames:
                self._validate_bitmap(frame.bitmap, frame.control.dimensions)

    def _validate_bitmap(self, bitmap: list[list[int]], dimensions: tuple[int, int]) -> None:
        width, height = dimensions
        if len(bitmap) != height:
            raise PngValidationError(f'expected {height} bitmap rows, got {len(bitmap)}')
        samples_per_row = width * self.header.channels
        max_sample = (len(self.palette) - 1 if self.header.color_type == PngColorType.INDEXED_COLOR
                      else (1 << self.header.bit_depth) - 1)
        for row in bitmap:
            if len(row) != samples_per_row:
                raise PngValidationError(f'expected {samples_per_row} samples per row, got {len(row)}')
            for sample in row:
                check_integer('pixel sample', sample, 0, max_sample)
