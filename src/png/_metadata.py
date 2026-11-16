"""Shared metadata model and wire-format validation helpers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

from png.chunk import PngChunk
from png.error import PngValidationError


def _data(chunk: PngChunk, kind: bytes, size: int | None = None) -> bytes:
    chunk.validate()
    if chunk.type != kind or (size is not None and chunk.length != size):
        raise PngValidationError(f'invalid {kind!r} metadata chunk')
    return chunk.data


def _string(value: str, encoding: str) -> bytes:
    if not isinstance(value, str) or '\0' in value:
        raise PngValidationError('metadata strings must be str without null characters')
    try:
        return value.encode(encoding)
    except UnicodeError as error:
        raise PngValidationError(f'metadata string is not valid {encoding}') from error


def _decode(data: bytes, encoding: str) -> str:
    try:
        value = data.decode(encoding)
    except UnicodeError as error:
        raise PngValidationError(f'metadata string is not valid {encoding}') from error
    if '\0' in value:
        raise PngValidationError('metadata text must not contain null characters')
    return value


def _keyword(value: str) -> bytes:
    encoded = _string(value, 'latin-1')
    if (
        not 1 <= len(encoded) <= 79
        or value.startswith(' ')
        or value.endswith(' ')
        or '  ' in value
        or any(not (32 <= item <= 126 or 161 <= item <= 255) for item in encoded)
    ):
        raise PngValidationError(
            'keyword must be 1-79 printable Latin-1 bytes without leading, trailing or repeated spaces'
        )
    return encoded


def _split_keyword(data: bytes) -> tuple[str, bytes]:
    keyword, separator, tail = data.partition(b'\0')
    if not separator:
        raise PngValidationError('missing metadata keyword separator')
    value = keyword.decode('latin-1')
    _keyword(value)
    return value, tail


class PngMetadata(ABC):
    type: ClassVar[bytes]

    @staticmethod
    @abstractmethod
    def from_chunk(chunk: PngChunk) -> PngMetadata:
        raise NotImplementedError

    @abstractmethod
    def to_chunk(self) -> PngChunk:
        raise NotImplementedError

    def validate(self) -> None:
        self.to_chunk()
