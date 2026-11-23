"""Per-operation counters; no global policy or mutable counters on models."""

from struct import unpack

from png._scanlines import scan_passes
from png.error import PngLimitError, PngValidationError
from png.format import PngColorType
from png.limits import PngReadLimits


class ReadBudget:
    def __init__(self, limits: PngReadLimits | None) -> None:
        if limits is not None:
            if not isinstance(limits, PngReadLimits):
                raise PngValidationError('limits must be PngReadLimits or None')
            limits.validate()
        self.limits = limits
        self.total_bytes = 0
        self.chunks = 0
        self.total_pixels = 0
        self.frames = 0
        self.metadata_bytes = 0
        self.seen_data = False
        self.pixel_format: tuple[int, int] | None = None
        self.decoded_bytes = 0

    def check(self, name: str, actual: int) -> None:
        maximum = getattr(self.limits, name) if self.limits is not None else None
        if maximum is not None and actual > maximum:
            raise PngLimitError(name, maximum, actual)

    def signature(self) -> None:
        self.check('max_total_bytes', self.total_bytes + 8)
        self.total_bytes += 8

    def start_chunk(self) -> None:
        self.check('max_chunks', self.chunks + 1)
        self.check('max_total_bytes', self.total_bytes + 12)

    def chunk(self, length: int) -> None:
        self.check('max_chunk_bytes', length)
        self.check('max_chunks', self.chunks + 1)
        self.check('max_total_bytes', self.total_bytes + length + 12)
        self.chunks += 1
        self.total_bytes += length + 12

    def pixels(self, count: int) -> None:
        self.check('max_pixels', count)
        self.check('max_total_pixels', self.total_pixels + count)
        self.total_pixels += count

    def inspect(self, kind: bytes, data: bytes) -> None:
        if kind == b'IHDR' and len(data) == 13:
            width, height = unpack('>II', data[:8])
            self.pixel_format = (data[8] * PngColorType(data[9]).channels, data[12])
            self.pixels(width * height)
            self.scanlines(width, height)
        elif kind == b'acTL' and len(data) == 8:
            (declared,) = unpack('>I', data[:4])
            self.check('max_frames', declared)
        elif kind == b'fcTL' and len(data) == 26:
            self.frames += 1
            self.check('max_frames', self.frames)
            # The default image was already counted by IHDR, even if it is a poster.
            if self.seen_data:
                width, height = unpack('>II', data[4:12])
                self.pixels(width * height)
                self.scanlines(width, height)
        elif kind == b'IDAT':
            self.seen_data = True

    def scanlines(self, width: int, height: int) -> None:
        if self.pixel_format is None:
            return
        bits_per_pixel, interlace = self.pixel_format
        size = 0
        for _offset_x, _offset_y, _step_x, _step_y, pass_width, pass_height in scan_passes(width, height, interlace):
            row_bytes = (pass_width * bits_per_pixel + 7) // 8
            self.check('max_row_bytes', row_bytes)
            size += (row_bytes + 1) * pass_height
        self.check('max_decoded_bytes', self.decoded_bytes + size)
        self.decoded_bytes += size

    def metadata(self, count: int) -> None:
        self.check('max_metadata_bytes', self.metadata_bytes + count)
        self.metadata_bytes += count

    def metadata_output_size(self) -> int:
        maximum = self.limits.max_metadata_bytes if self.limits is not None else None
        return 65536 if maximum is None else min(65536, maximum - self.metadata_bytes + 1)
