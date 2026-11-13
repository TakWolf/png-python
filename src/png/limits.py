"""Optional application policies, separate from PNG's format limits."""

from png.error import PngValidationError


class PngReadLimits:
    """Inclusive read limits. None leaves that resource unrestricted.

    Byte counts describe the PNG data, not Python's resident memory usage.
    The policy is reusable; counters belong to each read operation.
    """

    max_chunk_bytes: int | None
    max_total_bytes: int | None
    max_chunks: int | None
    max_pixels: int | None
    max_total_pixels: int | None
    max_frames: int | None
    max_metadata_bytes: int | None

    def __init__(
            self, *, max_chunk_bytes: int | None = None, max_total_bytes: int | None = None,
            max_chunks: int | None = None, max_pixels: int | None = None,
            max_total_pixels: int | None = None, max_frames: int | None = None,
            max_metadata_bytes: int | None = None,
    ) -> None:
        self.max_chunk_bytes = max_chunk_bytes
        self.max_total_bytes = max_total_bytes
        self.max_chunks = max_chunks
        self.max_pixels = max_pixels
        self.max_total_pixels = max_total_pixels
        self.max_frames = max_frames
        self.max_metadata_bytes = max_metadata_bytes

    def validate(self) -> None:
        for name in ('max_chunk_bytes', 'max_total_bytes', 'max_chunks', 'max_pixels',
                     'max_total_pixels', 'max_frames', 'max_metadata_bytes'):
            value = getattr(self, name)
            if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
                raise PngValidationError(f'{name} must be a nonnegative integer or None')
