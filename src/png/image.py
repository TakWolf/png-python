from __future__ import annotations

from io import BytesIO
from os import PathLike
from struct import iter_unpack, pack
from typing import BinaryIO

from png._pixels import decode_pixels, encode_pixels
from png._structure import _BEFORE_PALETTE
from png._validation import check_integer
from png.animation import PngAnimation
from png.chunk import PngChunk
from png.document import PngDocument
from png.error import PngUnsupportedError, PngValidationError
from png.format import PngColorType, PngFilterType
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
    _source_ancillary: tuple[tuple[PngChunk, bytes, bytes, bool], ...] | None

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
        self._source_ancillary = None

    @staticmethod
    def from_document(document: PngDocument) -> PngImage:
        """Decode an independent static image, preserving original sample depth."""
        document.validate()
        if any(chunk.type in (b'acTL', b'fcTL', b'fdAT') for chunk in document.chunks):
            raise PngUnsupportedError('APNG pixel decoding is not implemented yet; use PngDocument for raw chunks')
        header = PngHeader.from_chunk(document.chunks[0])
        image = PngImage(header, decode_pixels(header, (chunk.data for chunk in document.find_chunks(b'IDAT'))))
        before_data = True
        original = []
        for chunk in document.chunks:
            if chunk.type == b'PLTE':
                image.palette = list(iter_unpack('BBB', chunk.data))
            elif chunk.type == b'tRNS':
                if header.color_type == PngColorType.INDEXED_COLOR:
                    image.palette_alpha = list(chunk.data)
                else:
                    mask = (1 << header.bit_depth) - 1
                    image.transparent_color = tuple(sample & mask for sample, in iter_unpack('>H', chunk.data))
            elif chunk.type == b'IDAT':
                before_data = False
            elif not chunk.is_critical:
                copied = PngChunk(chunk.type, chunk.data)
                image.ancillary_chunks.append(copied)
                original.append((copied, copied.type, copied.data, not before_data))
        image._source_ancillary = tuple(original)
        if header.color_type == PngColorType.INDEXED_COLOR:
            largest_index = max(max(row) for row in image.bitmap)
            if largest_index >= len(image.palette):
                # Third Edition 13.1: out-of-range palette indices display as
                # opaque black. Extend the palette so the sample model remains
                # indexed and a subsequent save produces a valid PNG.
                image.palette.extend([(0, 0, 0)] * (largest_index + 1 - len(image.palette)))
                if image.palette_alpha:
                    image.palette_alpha.extend([255] * (len(image.palette) - len(image.palette_alpha)))
        image.validate()
        return image

    @staticmethod
    def parse(stream: bytes | BinaryIO) -> PngImage:
        return PngImage.from_document(PngDocument.parse(stream))

    @staticmethod
    def load(file_path: str | PathLike[str]) -> PngImage:
        with open(file_path, 'rb') as file:
            return PngImage.parse(file)

    def to_document(
            self,
            *,
            filter_type: PngFilterType | None = None,
            compression_level: int = 6,
            idat_chunk_size: int = 65536,
    ) -> PngDocument:
        """Encode a static image. None selects adaptive scanline filtering."""
        if self.animation is not None:
            raise PngUnsupportedError('APNG pixel encoding is not implemented yet')
        self.validate()
        check_integer('IDAT chunk size', idat_chunk_size, 1, 0x7FFFFFFF)
        encoded = encode_pixels(self.header, self.bitmap, filter_type, compression_level)
        before, after = [], []
        for chunk in self.ancillary_chunks:
            after_data = False
            if self._source_ancillary is not None:
                # Re-encoding changes critical chunks. Until a metadata type
                # has semantic support, apply the same conservative editor
                # policy as PngDocument and omit unknown unsafe chunks.
                if not chunk.safe_to_copy:
                    continue
                origins = [origin for origin in self._source_ancillary if origin[0] is chunk]
                if not origins:
                    origins = [origin for origin in self._source_ancillary if origin[1:3] == (chunk.type, chunk.data)]
                if origins:
                    after_data = origins[0][3]
            (after if after_data else before).append(PngChunk(chunk.type, chunk.data))
        chunks = [self.header.to_chunk()]
        chunks.extend(chunk for chunk in before if chunk.type in _BEFORE_PALETTE)
        if self.palette:
            chunks.append(PngChunk(b'PLTE', bytes(sample for color in self.palette for sample in color)))
        chunks.extend(chunk for chunk in before if chunk.type not in _BEFORE_PALETTE)
        if self.transparent_color is not None:
            chunks.append(PngChunk(b'tRNS', pack(f'>{len(self.transparent_color)}H', *self.transparent_color)))
        elif self.palette_alpha:
            chunks.append(PngChunk(b'tRNS', bytes(self.palette_alpha)))
        chunks.extend(PngChunk(b'IDAT', encoded[offset:offset + idat_chunk_size])
                      for offset in range(0, len(encoded), idat_chunk_size))
        chunks.extend(after)
        chunks.append(PngChunk(b'IEND'))
        document = PngDocument(chunks)
        document.validate()
        return document

    def dump(
            self,
            stream: BinaryIO,
            *,
            filter_type: PngFilterType | None = None,
            compression_level: int = 6,
            idat_chunk_size: int = 65536,
    ) -> None:
        self.to_document(filter_type=filter_type, compression_level=compression_level,
                         idat_chunk_size=idat_chunk_size).dump(stream)

    def dump_to_bytes(
            self,
            *,
            filter_type: PngFilterType | None = None,
            compression_level: int = 6,
            idat_chunk_size: int = 65536,
    ) -> bytes:
        stream = BytesIO()
        self.dump(stream, filter_type=filter_type, compression_level=compression_level,
                  idat_chunk_size=idat_chunk_size)
        return stream.getvalue()

    def save(
            self,
            file_path: str | PathLike[str],
            *,
            filter_type: PngFilterType | None = None,
            compression_level: int = 6,
            idat_chunk_size: int = 65536,
    ) -> None:
        self.to_document(filter_type=filter_type, compression_level=compression_level,
                         idat_chunk_size=idat_chunk_size).save(file_path)

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
