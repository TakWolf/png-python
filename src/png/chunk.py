from __future__ import annotations

from collections.abc import Callable
from io import BytesIO
from struct import pack, unpack
from typing import BinaryIO
from zlib import crc32

from png._limits import ReadBudget
from png._stream import read_exact, write_all
from png.error import PngCrcError, PngParseError, PngValidationError
from png.limits import PngReadLimits


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

    @staticmethod
    def parse(stream: bytes | BinaryIO, *, limits: PngReadLimits | None = None) -> PngChunk:
        """Read one chunk envelope, checking its name, length and CRC."""
        budget = ReadBudget(limits)
        if isinstance(stream, bytes):
            stream = BytesIO(stream)
        return PngChunk._parse(stream, budget)

    @staticmethod
    def _parse(
        stream: BinaryIO,
        budget: ReadBudget,
        *,
        check_header: Callable[[bytes, int], None] | None = None,
    ) -> PngChunk:
        budget.start_chunk()
        length, chunk_type = unpack('>I4s', read_exact(stream, 8))
        if length > 0x7FFFFFFF:
            raise PngParseError(f'chunk {chunk_type!r} exceeds the PNG length limit')
        chunk = PngChunk(chunk_type)
        try:
            chunk.validate()
        except PngValidationError as error:
            raise PngParseError(str(error)) from error
        if check_header is not None:
            check_header(chunk_type, length)
        budget.chunk(length)
        chunk.data = read_exact(stream, length)
        (expected,) = unpack('>I', read_exact(stream, 4))
        actual = chunk.crc
        if actual != expected:
            raise PngCrcError(chunk.type, expected, actual)
        return chunk

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
        if (
            not isinstance(self.type, bytes)
            or len(self.type) != 4
            or any(not (65 <= value <= 90 or 97 <= value <= 122) for value in self.type)
        ):
            raise PngValidationError('chunk type must contain four ASCII letters')
        if not isinstance(self.data, bytes):
            raise PngValidationError('chunk data must be bytes')
        if self.length > 0x7FFFFFFF:
            raise PngValidationError('chunk data exceeds the PNG length limit')

    def dump(self, stream: BinaryIO) -> None:
        """Write one envelope, deriving length and CRC from the current data."""
        self.validate()
        write_all(stream, pack('>I4s', self.length, self.type))
        write_all(stream, self.data)
        write_all(stream, pack('>I', self.crc))

    def dump_to_bytes(self) -> bytes:
        stream = BytesIO()
        self.dump(stream)
        return stream.getvalue()
