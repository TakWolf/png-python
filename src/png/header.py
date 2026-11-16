from __future__ import annotations

from struct import pack, unpack

from png._validation import check_integer
from png.chunk import PngChunk
from png.error import PngValidationError
from png.format import PngColorType, PngCompressionMethod, PngFilterMethod, PngInterlaceMethod


class PngHeader:
    """IHDR canvas dimensions and global encoding parameters."""

    width: int
    height: int
    bit_depth: int
    color_type: PngColorType
    compression_method: PngCompressionMethod
    filter_method: PngFilterMethod
    interlace_method: PngInterlaceMethod

    def __init__(
        self,
        dimensions: tuple[int, int],
        bit_depth: int = 8,
        color_type: PngColorType = PngColorType.TRUECOLOR_ALPHA,
        compression_method: PngCompressionMethod = PngCompressionMethod.DEFLATE,
        filter_method: PngFilterMethod = PngFilterMethod.ADAPTIVE,
        interlace_method: PngInterlaceMethod = PngInterlaceMethod.NONE,
    ) -> None:
        self.width, self.height = dimensions
        self.bit_depth = bit_depth
        self.color_type = color_type
        self.compression_method = compression_method
        self.filter_method = filter_method
        self.interlace_method = interlace_method

    @property
    def dimensions(self) -> tuple[int, int]:
        return self.width, self.height

    @dimensions.setter
    def dimensions(self, value: tuple[int, int]) -> None:
        self.width, self.height = value

    @property
    def channels(self) -> int:
        return PngColorType(self.color_type).channels

    @property
    def bits_per_pixel(self) -> int:
        return self.channels * self.bit_depth

    @property
    def scanline_size(self) -> int:
        """Packed bytes per non-interlaced row, excluding the filter byte."""
        return (self.width * self.bits_per_pixel + 7) // 8

    def validate(self) -> None:
        check_integer('width', self.width, 1, 0x7FFFFFFF)
        check_integer('height', self.height, 1, 0x7FFFFFFF)
        check_integer('bit depth', self.bit_depth, 1, 16)
        check_integer('color type', self.color_type, 0, 255)
        try:
            color_type = PngColorType(self.color_type)
        except ValueError as error:
            raise PngValidationError(f'unsupported color type: {self.color_type}') from error
        if self.bit_depth not in color_type.bit_depths:
            raise PngValidationError(f'bit depth {self.bit_depth} is invalid for {color_type.name}')
        for name, value, enum in (
            ('compression method', self.compression_method, PngCompressionMethod),
            ('filter method', self.filter_method, PngFilterMethod),
            ('interlace method', self.interlace_method, PngInterlaceMethod),
        ):
            check_integer(name, value, 0, 255)
            try:
                enum(value)
            except ValueError as error:
                raise PngValidationError(f'unsupported {name}: {value}') from error

    @staticmethod
    def from_chunk(chunk: PngChunk) -> PngHeader:
        chunk.validate()
        if chunk.type != b'IHDR' or chunk.length != 13:
            raise PngValidationError('IHDR must have exactly 13 bytes of data')
        width, height, depth, color, compression, filtering, interlace = unpack('>IIBBBBB', chunk.data)
        header = PngHeader((width, height), depth, color, compression, filtering, interlace)
        header.validate()
        header.color_type = PngColorType(color)
        header.compression_method = PngCompressionMethod(compression)
        header.filter_method = PngFilterMethod(filtering)
        header.interlace_method = PngInterlaceMethod(interlace)
        return header

    def to_chunk(self) -> PngChunk:
        self.validate()
        return PngChunk(
            b'IHDR',
            pack(
                '>IIBBBBB',
                self.width,
                self.height,
                self.bit_depth,
                self.color_type,
                self.compression_method,
                self.filter_method,
                self.interlace_method,
            ),
        )
