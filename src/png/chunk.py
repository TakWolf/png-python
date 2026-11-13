from __future__ import annotations

from zlib import crc32

from png.error import PngValidationError


class PngChunk:
    """A raw chunk, without its length and CRC fields.

    Length and CRC are derived from the current payload. This model preserves
    unknown chunk types, including a reserved bit set by a future specification.
    It does not decide whether a chunk is valid in a particular document.
    """

    type: bytes
    data: bytes

    def __init__(self, chunk_type: bytes, data: bytes = b'') -> None:
        self.type = chunk_type
        self.data = data

    @property
    def length(self) -> int:
        return len(self.data)

    @property
    def crc(self) -> int:
        return crc32(self.data, crc32(self.type))

    @property
    def is_critical(self) -> bool:
        self.validate()
        return not bool(self.type[0] & 0x20)

    @property
    def is_private(self) -> bool:
        self.validate()
        return bool(self.type[1] & 0x20)

    @property
    def reserved_bit(self) -> bool:
        self.validate()
        return bool(self.type[2] & 0x20)

    @property
    def safe_to_copy(self) -> bool:
        self.validate()
        return bool(self.type[3] & 0x20)

    def validate(self) -> None:
        if (not isinstance(self.type, bytes) or len(self.type) != 4 or
                any(not (65 <= value <= 90 or 97 <= value <= 122) for value in self.type)):
            raise PngValidationError('chunk type must contain four ASCII letters')
        if not isinstance(self.data, bytes):
            raise PngValidationError('chunk data must be bytes')
        if self.length > 0x7FFFFFFF:
            raise PngValidationError('chunk data exceeds the PNG length limit')
