"""Structured PNG metadata. Integer fields retain the specification's units."""

from __future__ import annotations

from abc import ABC, abstractmethod
from fractions import Fraction
import re
from struct import pack, unpack
from typing import ClassVar
import zlib

from png._validation import check_integer
from png.chunk import PngChunk
from png.error import PngValidationError
from png.format import PngPhysicalUnit, PngRenderingIntent


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
    if (not 1 <= len(encoded) <= 79 or value.startswith(' ') or value.endswith(' ') or '  ' in value or
            any(not (32 <= item <= 126 or 161 <= item <= 255) for item in encoded)):
        raise PngValidationError('keyword must be 1-79 printable Latin-1 bytes without leading, trailing or repeated spaces')
    return encoded


def _split_keyword(data: bytes) -> tuple[str, bytes]:
    keyword, separator, tail = data.partition(b'\0')
    if not separator:
        raise PngValidationError('missing metadata keyword separator')
    value = keyword.decode('latin-1')
    _keyword(value)
    return value, tail


def _inflate(data: bytes) -> bytes:
    inflater = zlib.decompressobj()
    result = bytearray()
    pending = data
    try:
        while pending and not inflater.eof:
            result.extend(inflater.decompress(pending, 65536))
            pending = inflater.unconsumed_tail
    except zlib.error as error:
        raise PngValidationError(f'invalid compressed metadata: {error}') from error
    if not inflater.eof or inflater.unused_data:
        raise PngValidationError('compressed metadata must contain one complete zlib stream')
    return bytes(result)


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


class PngGamma(PngMetadata):
    type = b'gAMA'
    raw_gamma: int

    def __init__(self, raw_gamma: int) -> None:
        self.raw_gamma = raw_gamma

    @property
    def gamma(self) -> Fraction:
        return Fraction(self.raw_gamma, 100000)

    @staticmethod
    def from_chunk(chunk: PngChunk) -> PngGamma:
        result = PngGamma(unpack('>I', _data(chunk, b'gAMA', 4))[0])
        result.validate()
        return result

    def to_chunk(self) -> PngChunk:
        check_integer('gamma', self.raw_gamma, 1, 0x7FFFFFFF)
        return PngChunk(self.type, pack('>I', self.raw_gamma))


class PngChromaticities(PngMetadata):
    type = b'cHRM'
    white_point: tuple[int, int]
    red: tuple[int, int]
    green: tuple[int, int]
    blue: tuple[int, int]

    def __init__(self, white_point: tuple[int, int], red: tuple[int, int],
                 green: tuple[int, int], blue: tuple[int, int]) -> None:
        self.white_point = white_point
        self.red = red
        self.green = green
        self.blue = blue

    @staticmethod
    def from_chunk(chunk: PngChunk) -> PngChromaticities:
        values = unpack('>8I', _data(chunk, b'cHRM', 32))
        result = PngChromaticities(values[:2], values[2:4], values[4:6], values[6:8])
        result.validate()
        return result

    def to_chunk(self) -> PngChunk:
        values = []
        for point in (self.white_point, self.red, self.green, self.blue):
            if len(point) != 2:
                raise PngValidationError('chromaticities require x,y pairs')
            for value in point:
                check_integer('chromaticity times 100000', value, 0, 0x7FFFFFFF)
            values.extend(point)
        return PngChunk(self.type, pack('>8I', *values))


class PngSrgb(PngMetadata):
    type = b'sRGB'
    rendering_intent: PngRenderingIntent

    def __init__(self, rendering_intent: PngRenderingIntent = PngRenderingIntent.PERCEPTUAL) -> None:
        self.rendering_intent = rendering_intent

    @staticmethod
    def from_chunk(chunk: PngChunk) -> PngSrgb:
        result = PngSrgb(_data(chunk, b'sRGB', 1)[0])
        result.validate()
        result.rendering_intent = PngRenderingIntent(result.rendering_intent)
        return result

    def to_chunk(self) -> PngChunk:
        check_integer('sRGB rendering intent', self.rendering_intent, 0, 3)
        return PngChunk(self.type, bytes([self.rendering_intent]))


class PngCicp(PngMetadata):
    type = b'cICP'
    color_primaries: int
    transfer_function: int
    matrix_coefficients: int
    video_full_range_flag: int

    def __init__(self, color_primaries: int, transfer_function: int,
                 matrix_coefficients: int = 0, video_full_range_flag: int = 1) -> None:
        self.color_primaries = color_primaries
        self.transfer_function = transfer_function
        self.matrix_coefficients = matrix_coefficients
        self.video_full_range_flag = video_full_range_flag

    @staticmethod
    def from_chunk(chunk: PngChunk) -> PngCicp:
        result = PngCicp(*_data(chunk, b'cICP', 4))
        result.validate()
        return result

    def to_chunk(self) -> PngChunk:
        check_integer('color primaries', self.color_primaries, 0, 255)
        check_integer('transfer function', self.transfer_function, 0, 255)
        check_integer('matrix coefficients', self.matrix_coefficients, 0, 0)
        check_integer('full range flag', self.video_full_range_flag, 0, 1)
        return PngChunk(self.type, bytes((self.color_primaries, self.transfer_function,
                                         self.matrix_coefficients, self.video_full_range_flag)))


class PngMasteringDisplayColorVolume(PngMetadata):
    type = b'mDCV'
    red: tuple[int, int]
    green: tuple[int, int]
    blue: tuple[int, int]
    white_point: tuple[int, int]
    maximum_luminance: int
    minimum_luminance: int

    def __init__(self, red: tuple[int, int], green: tuple[int, int], blue: tuple[int, int],
                 white_point: tuple[int, int], maximum_luminance: int, minimum_luminance: int) -> None:
        self.red = red
        self.green = green
        self.blue = blue
        self.white_point = white_point
        self.maximum_luminance = maximum_luminance
        self.minimum_luminance = minimum_luminance

    @staticmethod
    def from_chunk(chunk: PngChunk) -> PngMasteringDisplayColorVolume:
        values = unpack('>8H2I', _data(chunk, b'mDCV', 24))
        result = PngMasteringDisplayColorVolume(values[:2], values[2:4], values[4:6], values[6:8], values[8], values[9])
        result.validate()
        return result

    def to_chunk(self) -> PngChunk:
        coordinates = []
        for point in (self.red, self.green, self.blue, self.white_point):
            if len(point) != 2:
                raise PngValidationError('mastering display chromaticities require x,y pairs')
            for value in point:
                check_integer('mastering chromaticity times 50000', value, 0, 65535)
            coordinates.extend(point)
        check_integer('maximum luminance times 10000', self.maximum_luminance, 0, 0x7FFFFFFF)
        check_integer('minimum luminance times 10000', self.minimum_luminance, 0, 0x7FFFFFFF)
        return PngChunk(self.type, pack('>8H2I', *coordinates, self.maximum_luminance, self.minimum_luminance))


class PngContentLightLevel(PngMetadata):
    type = b'cLLI'
    maximum_content_light_level: int
    maximum_frame_average_light_level: int

    def __init__(self, maximum_content_light_level: int, maximum_frame_average_light_level: int) -> None:
        self.maximum_content_light_level = maximum_content_light_level
        self.maximum_frame_average_light_level = maximum_frame_average_light_level

    @staticmethod
    def from_chunk(chunk: PngChunk) -> PngContentLightLevel:
        result = PngContentLightLevel(*unpack('>2I', _data(chunk, b'cLLI', 8)))
        result.validate()
        return result

    def to_chunk(self) -> PngChunk:
        check_integer('MaxCLL times 10000', self.maximum_content_light_level, 0, 0x7FFFFFFF)
        check_integer('MaxFALL times 10000', self.maximum_frame_average_light_level, 0, 0x7FFFFFFF)
        return PngChunk(self.type, pack('>2I', self.maximum_content_light_level, self.maximum_frame_average_light_level))


class PngIccProfile(PngMetadata):
    type = b'iCCP'
    name: str
    profile: bytes

    def __init__(self, name: str, profile: bytes) -> None:
        self.name = name
        self.profile = profile

    @staticmethod
    def from_chunk(chunk: PngChunk) -> PngIccProfile:
        name, tail = _split_keyword(_data(chunk, b'iCCP'))
        if not tail or tail[0] != 0:
            raise PngValidationError('iCCP requires compression method 0')
        result = PngIccProfile(name, _inflate(tail[1:]))
        result.validate()
        return result

    def to_chunk(self) -> PngChunk:
        name = _keyword(self.name)
        if not isinstance(self.profile, bytes) or not self.profile:
            raise PngValidationError('ICC profile must be nonempty bytes')
        return PngChunk(self.type, name + b'\0\0' + zlib.compress(self.profile))


class PngText(PngMetadata):
    type = b'tEXt'
    keyword: str
    text: str

    def __init__(self, keyword: str, text: str) -> None:
        self.keyword = keyword
        self.text = text

    @staticmethod
    def from_chunk(chunk: PngChunk) -> PngText:
        keyword, tail = _split_keyword(_data(chunk, b'tEXt'))
        return PngText(keyword, _decode(tail, 'latin-1'))

    def to_chunk(self) -> PngChunk:
        return PngChunk(self.type, _keyword(self.keyword) + b'\0' + _string(self.text, 'latin-1'))


class PngCompressedText(PngText):
    type = b'zTXt'

    @staticmethod
    def from_chunk(chunk: PngChunk) -> PngCompressedText:
        keyword, tail = _split_keyword(_data(chunk, b'zTXt'))
        if not tail or tail[0] != 0:
            raise PngValidationError('zTXt requires compression method 0')
        return PngCompressedText(keyword, _decode(_inflate(tail[1:]), 'latin-1'))

    def to_chunk(self) -> PngChunk:
        return PngChunk(self.type, _keyword(self.keyword) + b'\0\0' + zlib.compress(_string(self.text, 'latin-1')))


class PngInternationalText(PngMetadata):
    type = b'iTXt'
    keyword: str
    text: str
    language_tag: str
    translated_keyword: str
    compressed: bool

    def __init__(self, keyword: str, text: str, language_tag: str = '',
                 translated_keyword: str = '', compressed: bool = False) -> None:
        self.keyword = keyword
        self.text = text
        self.language_tag = language_tag
        self.translated_keyword = translated_keyword
        self.compressed = compressed

    @staticmethod
    def from_chunk(chunk: PngChunk) -> PngInternationalText:
        keyword, tail = _split_keyword(_data(chunk, b'iTXt'))
        if len(tail) < 2 or tail[0] not in (0, 1) or (tail[0] == 1 and tail[1] != 0):
            raise PngValidationError('invalid iTXt compression flag or method')
        compressed = bool(tail[0])
        parts = tail[2:].split(b'\0', 2)
        if len(parts) != 3:
            raise PngValidationError('iTXt is missing language or translated-keyword separators')
        language, translated, text = parts
        result = PngInternationalText(keyword, _decode(_inflate(text) if compressed else text, 'utf-8'),
                                      _decode(language, 'ascii'), _decode(translated, 'utf-8'), compressed)
        result.validate()
        return result

    def to_chunk(self) -> PngChunk:
        language = _string(self.language_tag, 'ascii')
        if language and re.fullmatch(rb'[A-Za-z]{1,8}(?:-[A-Za-z0-9]{1,8})*', language) is None:
            raise PngValidationError('invalid language tag syntax')
        if not isinstance(self.compressed, bool):
            raise PngValidationError('iTXt compressed must be bool')
        text = _string(self.text, 'utf-8')
        if self.compressed:
            text = zlib.compress(text)
        data = (_keyword(self.keyword) + b'\0' + bytes((self.compressed, 0)) + language + b'\0' +
                _string(self.translated_keyword, 'utf-8') + b'\0' + text)
        return PngChunk(self.type, data)


class PngPhysicalDimensions(PngMetadata):
    type = b'pHYs'
    pixels_per_unit_x: int
    pixels_per_unit_y: int
    unit: PngPhysicalUnit

    def __init__(self, pixels_per_unit_x: int, pixels_per_unit_y: int,
                 unit: PngPhysicalUnit = PngPhysicalUnit.UNKNOWN) -> None:
        self.pixels_per_unit_x = pixels_per_unit_x
        self.pixels_per_unit_y = pixels_per_unit_y
        self.unit = unit

    @staticmethod
    def from_chunk(chunk: PngChunk) -> PngPhysicalDimensions:
        result = PngPhysicalDimensions(*unpack('>IIB', _data(chunk, b'pHYs', 9)))
        result.validate()
        result.unit = PngPhysicalUnit(result.unit)
        return result

    def to_chunk(self) -> PngChunk:
        check_integer('pixels per unit X', self.pixels_per_unit_x, 0, 0x7FFFFFFF)
        check_integer('pixels per unit Y', self.pixels_per_unit_y, 0, 0x7FFFFFFF)
        check_integer('physical unit', self.unit, 0, 1)
        return PngChunk(self.type, pack('>IIB', self.pixels_per_unit_x, self.pixels_per_unit_y, self.unit))


class PngTime(PngMetadata):
    type = b'tIME'
    year: int
    month: int
    day: int
    hour: int
    minute: int
    second: int

    def __init__(self, year: int, month: int, day: int, hour: int = 0, minute: int = 0, second: int = 0) -> None:
        self.year = year
        self.month = month
        self.day = day
        self.hour = hour
        self.minute = minute
        self.second = second

    @staticmethod
    def from_chunk(chunk: PngChunk) -> PngTime:
        result = PngTime(*unpack('>H5B', _data(chunk, b'tIME', 7)))
        result.validate()
        return result

    def to_chunk(self) -> PngChunk:
        check_integer('year', self.year, 0, 65535)
        check_integer('month', self.month, 1, 12)
        check_integer('day', self.day, 1, 31)
        check_integer('hour', self.hour, 0, 23)
        check_integer('minute', self.minute, 0, 59)
        check_integer('second', self.second, 0, 60)
        return PngChunk(self.type, pack('>H5B', self.year, self.month, self.day, self.hour, self.minute, self.second))


class PngExif(PngMetadata):
    type = b'eXIf'
    profile: bytes

    def __init__(self, profile: bytes) -> None:
        self.profile = profile

    @staticmethod
    def from_chunk(chunk: PngChunk) -> PngExif:
        result = PngExif(_data(chunk, b'eXIf'))
        result.validate()
        return result

    def to_chunk(self) -> PngChunk:
        if not isinstance(self.profile, bytes) or self.profile[:4] not in (b'II*\0', b'MM\0*'):
            raise PngValidationError('Exif profile requires an II or MM TIFF header without a JPEG prefix')
        return PngChunk(self.type, self.profile)


_METADATA_CLASSES = {
    cls.type: cls for cls in (
        PngGamma, PngChromaticities, PngSrgb, PngCicp, PngMasteringDisplayColorVolume,
        PngContentLightLevel, PngIccProfile, PngText, PngCompressedText, PngInternationalText,
        PngPhysicalDimensions, PngTime, PngExif,
    )
}
METADATA_TYPES = frozenset(_METADATA_CLASSES)
COLOR_METADATA_TYPES = frozenset((b'gAMA', b'cHRM', b'sRGB', b'cICP', b'mDCV', b'cLLI', b'iCCP'))


def parse_metadata(chunk: PngChunk) -> PngMetadata | None:
    cls = _METADATA_CLASSES.get(chunk.type)
    return cls.from_chunk(chunk) if cls is not None else None


def validate_metadata_chunks(chunks: list[PngChunk]) -> None:
    parsed: dict[bytes, PngMetadata] = {}
    repeated = {b'tEXt', b'zTXt', b'iTXt'}
    for chunk in chunks:
        metadata = parse_metadata(chunk)
        if metadata is not None:
            if chunk.type in parsed and chunk.type not in repeated:
                raise PngValidationError(f'duplicate {chunk.type!r} metadata')
            parsed[chunk.type] = metadata
    if b'mDCV' in parsed and b'cICP' not in parsed:
        raise PngValidationError('mDCV requires accompanying cICP metadata')
    if b'sRGB' in parsed:
        if b'gAMA' in parsed and parsed[b'gAMA'].raw_gamma != 45455:
            raise PngValidationError('sRGB requires gAMA value 45455 when present')
        if b'cHRM' in parsed:
            expected = PngChromaticities((31270, 32900), (64000, 33000), (30000, 60000), (15000, 6000))
            if parsed[b'cHRM'].to_chunk().data != expected.to_chunk().data:
                raise PngValidationError('sRGB requires standard sRGB chromaticities when cHRM is present')
