from __future__ import annotations

from io import BytesIO
from collections.abc import Iterator
from os import PathLike
from struct import iter_unpack, pack
from typing import BinaryIO

from png._apng import frame_header, scan_animation
from png._limits import ReadBudget
from png._pixels import decode_pixels, encode_pixels
from png._structure import _BEFORE_PALETTE, _BEFORE_DATA
from png._validation import check_integer
from png.animation import PngAnimation, PngFrame, PngRenderedFrame
from png.chunk import PngChunk
from png.document import PngDocument
from png.error import PngParseError, PngValidationError
from png.format import PngColorType, PngFilterType
from png.header import PngHeader
from png.limits import PngReadLimits
from png.metadata import (
    METADATA_TYPES, PngMetadata, PngBackground, PngHistogram, parse_metadata, validate_metadata_chunks,
)


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
    metadata: list[PngMetadata]
    _source_ancillary: tuple[tuple[PngChunk | PngMetadata, bytes, bytes, bool], ...] | None

    def __init__(
            self,
            header: PngHeader,
            bitmap: list[list[int]] | None = None,
            palette: list[tuple[int, int, int]] | None = None,
            transparent_color: tuple[int, ...] | None = None,
            palette_alpha: list[int] | None = None,
            animation: PngAnimation | None = None,
            ancillary_chunks: list[PngChunk] | None = None,
            metadata: list[PngMetadata] | None = None,
    ) -> None:
        self.header = header
        self.bitmap = bitmap if bitmap is not None else []
        self.palette = palette if palette is not None else []
        self.transparent_color = transparent_color
        self.palette_alpha = palette_alpha if palette_alpha is not None else []
        self.animation = animation
        self.ancillary_chunks = ancillary_chunks if ancillary_chunks is not None else []
        self.metadata = metadata if metadata is not None else []
        self._source_ancillary = None

    @staticmethod
    def from_document(document: PngDocument, *, limits: PngReadLimits | None = None) -> PngImage:
        """Decode an independent image, preserving original sample depth."""
        document.validate(limits=limits)
        header = PngHeader.from_chunk(document.chunks[0])
        image = PngImage(header, decode_pixels(header, (chunk.data for chunk in document.find_chunks(b'IDAT'))))
        animation = scan_animation(document.chunks, header)
        if animation is not None:
            plays, frames = animation
            image.animation = PngAnimation(num_plays=plays)
            for control, blocks, is_default in frames:
                if is_default:
                    image.animation.default_image_control = control
                else:
                    bitmap = decode_pixels(frame_header(header, control.dimensions), (chunk.data[4:] for chunk in blocks))
                    image.animation.frames.append(PngFrame(control, bitmap))
        before_data = True
        original = []
        budget = ReadBudget(limits)
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
            elif chunk.type not in (b'acTL', b'fcTL', b'fdAT') and not chunk.is_critical:
                typed = parse_metadata(chunk, budget=budget)
                if typed is not None:
                    if isinstance(typed, PngBackground) and typed.color is not None:
                        typed.color = tuple(sample & ((1 << header.bit_depth) - 1) for sample in typed.color)
                    image.metadata.append(typed)
                    original.append((typed, chunk.type, chunk.data, not before_data))
                else:
                    copied = PngChunk(chunk.type, chunk.data)
                    image.ancillary_chunks.append(copied)
                    original.append((copied, copied.type, copied.data, not before_data))
        image._source_ancillary = tuple(original)
        if header.color_type == PngColorType.INDEXED_COLOR:
            bitmaps = [image.bitmap] + ([frame.bitmap for frame in image.animation.frames] if image.animation else [])
            largest_index = max(max(row) for bitmap in bitmaps for row in bitmap)
            if largest_index >= len(image.palette):
                # Third Edition 13.1: out-of-range palette indices display as
                # opaque black. Extend the palette so the sample model remains
                # indexed and a subsequent save produces a valid PNG.
                image.palette.extend([(0, 0, 0)] * (largest_index + 1 - len(image.palette)))
                if image.palette_alpha:
                    image.palette_alpha.extend([255] * (len(image.palette) - len(image.palette_alpha)))
                if image.find_metadata(b'hIST'):
                    image.recalculate_histogram()
        image.validate()
        return image

    @staticmethod
    def parse(stream: bytes | BinaryIO, *, limits: PngReadLimits | None = None) -> PngImage:
        ReadBudget(limits)  # Invalid application policy is not corrupt PNG input.
        try:
            return PngImage.from_document(PngDocument.parse(stream, limits=limits), limits=limits)
        except PngValidationError as error:
            raise PngParseError(str(error)) from error

    @staticmethod
    def load(file_path: str | PathLike[str], *, limits: PngReadLimits | None = None) -> PngImage:
        """Read a whole PNG file, checking its boundary before decoding pixels."""
        document = PngDocument.load(file_path, limits=limits)
        try:
            return PngImage.from_document(document, limits=limits)
        except PngValidationError as error:
            raise PngParseError(str(error)) from error

    def to_document(
            self,
            *,
            filter_type: PngFilterType | None = None,
            compression_level: int = 6,
            idat_chunk_size: int = 65536,
    ) -> PngDocument:
        """Encode an image. None selects adaptive scanline filtering."""
        self.validate()
        check_integer('IDAT chunk size', idat_chunk_size, 1, 0x7FFFFFFF)
        encoded = encode_pixels(self.header, self.bitmap, filter_type, compression_level)
        before, after = [], []
        entries = [(item, item.to_chunk()) for item in self.metadata] + [(chunk, chunk) for chunk in self.ancillary_chunks]
        for entry, chunk in entries:
            after_data = False
            if self._source_ancillary is not None:
                # Re-encoding changes critical chunks. Until a metadata type
                # has semantic support, apply the same conservative editor
                # policy as PngDocument and omit unknown unsafe chunks.
                if chunk.type not in METADATA_TYPES and not chunk.safe_to_copy:
                    continue
                origins = [origin for origin in self._source_ancillary if origin[0] is entry]
                if not origins:
                    origins = [origin for origin in self._source_ancillary if origin[1:3] == (chunk.type, chunk.data)]
                if origins:
                    after_data = origins[0][3]
                if chunk.type in _BEFORE_DATA:
                    after_data = False
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
        sequence = 0
        if self.animation is not None:
            chunks.append(PngChunk(b'acTL', pack('>II', self.animation.num_frames, self.animation.num_plays)))
            if self.animation.default_image_control is not None:
                chunks.append(self.animation.default_image_control.to_chunk(sequence))
                sequence += 1
        chunks.extend(PngChunk(b'IDAT', encoded[offset:offset + idat_chunk_size])
                      for offset in range(0, len(encoded), idat_chunk_size))
        if self.animation is not None:
            for frame in self.animation.frames:
                chunks.append(frame.control.to_chunk(sequence))
                sequence += 1
                payload = encode_pixels(frame_header(self.header, frame.control.dimensions), frame.bitmap,
                                        filter_type, compression_level)
                frame_chunk_size = min(idat_chunk_size, 0x7FFFFFFF - 4)
                for offset in range(0, len(payload), frame_chunk_size):
                    check_integer('sequence number', sequence, 0, 0x7FFFFFFF)
                    chunks.append(PngChunk(b'fdAT', pack('>I', sequence) + payload[offset:offset + frame_chunk_size]))
                    sequence += 1
        chunks.extend(after)
        chunks.append(PngChunk(b'IEND'))
        document = PngDocument(chunks)
        document.validate()
        return document

    def render_frames(self) -> Iterator[PngRenderedFrame]:
        """Yield independent RGBA canvas snapshots for one animation play.

        Samples are composited in their stored color space. Color management,
        display transfer functions and HDR tone mapping are separate operations.
        """
        from png._composite import render_frames
        self.validate()
        yield from render_frames(self)

    def find_metadata(self, chunk_type: bytes) -> list[PngMetadata]:
        """Return references to supported metadata entries in list order."""
        return [item for item in self.metadata if item.type == chunk_type]

    def recalculate_histogram(self) -> PngHistogram:
        """Update/create hIST for indexed samples, including APNG local frames.

        Counts up to 65535 are exact. Larger counts are scaled, preserving a
        nonzero frequency for every used index. No color quantization is done.
        """
        self.header.validate()
        if self.header.color_type != PngColorType.INDEXED_COLOR:
            raise PngValidationError('histogram recalculation requires an indexed-color image')
        if not 1 <= len(self.palette) <= 1 << self.header.bit_depth:
            raise PngValidationError('histogram recalculation requires PLTE fitting the bit depth')
        bitmaps = [self.bitmap]
        self._validate_bitmap(self.bitmap, self.dimensions)
        if self.animation is not None:
            self.animation.validate(self.dimensions)
            for frame in self.animation.frames:
                self._validate_bitmap(frame.bitmap, frame.control.dimensions)
                bitmaps.append(frame.bitmap)
        frequencies = [0] * len(self.palette)
        for bitmap in bitmaps:
            for row in bitmap:
                for index in row:
                    frequencies[index] += 1
        maximum = max(frequencies)
        if maximum > 65535:
            frequencies = [max(1, (value * 65535 + maximum // 2) // maximum) if value else 0
                           for value in frequencies]
        structured = self.find_metadata(b'hIST')
        raw = [chunk for chunk in self.ancillary_chunks if chunk.type == b'hIST']
        if len(structured) + len(raw) > 1:
            raise PngValidationError('duplicate hIST metadata')
        if structured:
            result = structured[0]
            result.frequencies[:] = frequencies
        else:
            result = PngHistogram(frequencies)
            self.metadata.append(result)
            if raw:
                self.ancillary_chunks.remove(raw[0])
        return result

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
        metadata_chunks = [item.to_chunk() for item in self.metadata] + self.ancillary_chunks
        validate_metadata_chunks(metadata_chunks, self.header, len(self.palette), for_encoding=True)
        self._validate_bitmap(self.bitmap, self.dimensions)
        if self.animation is not None:
            self.animation.validate(self.dimensions)
            for frame in self.animation.frames:
                self._validate_bitmap(frame.bitmap, frame.control.dimensions)
        if self.header.color_type == PngColorType.INDEXED_COLOR:
            histograms = [PngHistogram.from_chunk(chunk) for chunk in metadata_chunks if chunk.type == b'hIST']
            if histograms:
                frequencies = histograms[0].frequencies
                bitmaps = [self.bitmap] + ([frame.bitmap for frame in self.animation.frames] if self.animation else [])
                if any(frequencies[index] == 0 for bitmap in bitmaps for row in bitmap for index in row):
                    raise PngValidationError('hIST must have a nonzero frequency for every used palette index')

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
