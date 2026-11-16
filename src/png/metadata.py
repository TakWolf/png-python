"""Structured PNG metadata. Integer fields retain the specification's units."""

from __future__ import annotations

from fractions import Fraction
from struct import iter_unpack, pack, unpack
from typing import TYPE_CHECKING
import zlib

from png._metadata import PngMetadata, _data, _string, _decode, _keyword, _split_keyword
from png._icc_header import validate_png_embedding
from png._limits import ReadBudget
from png._language import validate_language_tag
from png._profiles import validate_icc_structure, validate_icc_tags, validate_exif_structure
from png._validation import check_integer
from png.chunk import PngChunk
from png.error import PngValidationError
from png.extensions import EXTENSION_CLASSES
from png.format import PngColorType, PngPhysicalUnit, PngRenderingIntent

if TYPE_CHECKING:
    from png.header import PngHeader


def _inflate(data: bytes, budget: ReadBudget) -> bytes:
    inflater = zlib.decompressobj()
    result = bytearray()
    pending = data
    try:
        while pending and not inflater.eof:
            part = inflater.decompress(pending, budget.metadata_output_size())
            budget.metadata(len(part))
            result.extend(part)
            pending = inflater.unconsumed_tail
    except zlib.error as error:
        raise PngValidationError(f'invalid compressed metadata: {error}') from error
    if not inflater.eof or inflater.unused_data:
        raise PngValidationError('compressed metadata must contain one complete zlib stream')
    return bytes(result)


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

    def validate_code_points(self) -> None:
        """Reject reserved H.273 (07/2024) code points without changing fields."""
        from png._color_codes import validate_code_points
        self.validate()
        validate_code_points(self.color_primaries, self.transfer_function,
                             self.matrix_coefficients, self.video_full_range_flag)


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

    def _validate_header(self) -> None:
        if not isinstance(self.profile, bytes) or len(self.profile) < 128:
            raise PngValidationError('ICC profile requires a complete 128-byte header')
        if self.profile[36:40] != b'acsp':
            raise PngValidationError('ICC profile requires the acsp header signature')

    @property
    def color_space(self) -> bytes:
        """ICC data color-space signature, derived from the current profile."""
        self._validate_header()
        return self.profile[16:20]

    @property
    def declared_size(self) -> int:
        """ICC header size declaration; not a guarantee of internal validity."""
        self._validate_header()
        return unpack('>I', self.profile[:4])[0]

    def validate_profile_structure(self) -> None:
        """Check the ICC header/table extents, not color transforms or all tags."""
        self._validate_header()
        validate_icc_structure(self.profile)

    def validate_profile_tags(self) -> None:
        """Check structure, header fields/ID and selected v2/v4 tag contents.

        Includes v2/v4 class-specific required tags and the four table-based LUT
        layouts, known multi-process elements, named-color and sequence records.
        Does not evaluate colorimetric transforms. Readers retain original bytes.
        """
        self._validate_header()
        validate_icc_tags(self.profile)

    @staticmethod
    def from_chunk(chunk: PngChunk) -> PngIccProfile:
        return PngIccProfile._from_chunk(chunk, ReadBudget(None))

    @staticmethod
    def _from_chunk(chunk: PngChunk, budget: ReadBudget) -> PngIccProfile:
        name, tail = _split_keyword(_data(chunk, b'iCCP'))
        if not tail or tail[0] != 0:
            raise PngValidationError('iCCP requires compression method 0')
        budget.metadata(chunk.length - len(tail[1:]))
        result = PngIccProfile(name, _inflate(tail[1:], budget))
        result.validate()
        return result

    def to_chunk(self) -> PngChunk:
        name = _keyword(self.name)
        if self.color_space not in (b'RGB ', b'GRAY'):
            raise PngValidationError('PNG ICC profiles must describe RGB or grayscale data')
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
        return PngCompressedText._from_chunk(chunk, ReadBudget(None))

    @staticmethod
    def _from_chunk(chunk: PngChunk, budget: ReadBudget) -> PngCompressedText:
        keyword, tail = _split_keyword(_data(chunk, b'zTXt'))
        if not tail or tail[0] != 0:
            raise PngValidationError('zTXt requires compression method 0')
        budget.metadata(chunk.length - len(tail[1:]))
        return PngCompressedText(keyword, _decode(_inflate(tail[1:], budget), 'latin-1'))

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
        return PngInternationalText._from_chunk(chunk, ReadBudget(None))

    @staticmethod
    def _from_chunk(chunk: PngChunk, budget: ReadBudget) -> PngInternationalText:
        keyword, tail = _split_keyword(_data(chunk, b'iTXt'))
        if len(tail) < 2 or tail[0] not in (0, 1) or (tail[0] == 1 and tail[1] != 0):
            raise PngValidationError('invalid iTXt compression flag or method')
        compressed = bool(tail[0])
        parts = tail[2:].split(b'\0', 2)
        if len(parts) != 3:
            raise PngValidationError('iTXt is missing language or translated-keyword separators')
        language, translated, text = parts
        budget.metadata(chunk.length - len(text) if compressed else chunk.length)
        result = PngInternationalText(keyword, _decode(_inflate(text, budget) if compressed else text, 'utf-8'),
                                      _decode(language, 'ascii'), _decode(translated, 'utf-8'), compressed)
        result.validate()
        return result

    def to_chunk(self) -> PngChunk:
        language = _string(self.language_tag, 'ascii')
        validate_language_tag(language)
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

    def validate_profile_structure(self) -> None:
        """Check TIFF directory/value bounds without interpreting all Exif tags."""
        validate_exif_structure(self.profile)

    def validate_profile_tags(self) -> None:
        """Check storage and selected present Exif fields, without rewriting history."""
        self.validate()
        validate_exif_structure(self.profile, check_fields=True)

    @staticmethod
    def from_chunk(chunk: PngChunk) -> PngExif:
        result = PngExif(_data(chunk, b'eXIf'))
        result.validate()
        return result

    def to_chunk(self) -> PngChunk:
        if not isinstance(self.profile, bytes) or self.profile[:4] not in (b'II*\0', b'MM\0*'):
            raise PngValidationError('Exif profile requires an II or MM TIFF header without a JPEG prefix')
        return PngChunk(self.type, self.profile)


class PngBackground(PngMetadata):
    type = b'bKGD'
    color: tuple[int, ...] | None
    palette_index: int | None

    def __init__(self, color: tuple[int, ...] | None = None, palette_index: int | None = None) -> None:
        self.color = color
        self.palette_index = palette_index

    @staticmethod
    def from_chunk(chunk: PngChunk) -> PngBackground:
        data = _data(chunk, b'bKGD')
        if len(data) == 1:
            return PngBackground(palette_index=data[0])
        if len(data) not in (2, 6):
            raise PngValidationError('bKGD must contain a palette index, grayscale sample or RGB samples')
        return PngBackground(tuple(value for value, in iter_unpack('>H', data)))

    def to_chunk(self) -> PngChunk:
        if (self.color is None) == (self.palette_index is None):
            raise PngValidationError('bKGD requires exactly one of color or palette_index')
        if self.palette_index is not None:
            check_integer('bKGD palette index', self.palette_index, 0, 255)
            return PngChunk(self.type, bytes([self.palette_index]))
        if len(self.color) not in (1, 3):
            raise PngValidationError('bKGD color requires one grayscale or three RGB samples')
        for sample in self.color:
            check_integer('bKGD sample', sample, 0, 65535)
        return PngChunk(self.type, pack(f'>{len(self.color)}H', *self.color))


class PngHistogram(PngMetadata):
    type = b'hIST'
    frequencies: list[int]

    def __init__(self, frequencies: list[int] | None = None) -> None:
        self.frequencies = frequencies if frequencies is not None else []

    @staticmethod
    def from_chunk(chunk: PngChunk) -> PngHistogram:
        data = _data(chunk, b'hIST')
        if not 2 <= len(data) <= 512 or len(data) % 2:
            raise PngValidationError('hIST requires 1-256 two-byte frequencies')
        return PngHistogram([value for value, in iter_unpack('>H', data)])

    def to_chunk(self) -> PngChunk:
        if not 1 <= len(self.frequencies) <= 256:
            raise PngValidationError('hIST requires 1-256 frequencies')
        for frequency in self.frequencies:
            check_integer('hIST frequency', frequency, 0, 65535)
        return PngChunk(self.type, pack(f'>{len(self.frequencies)}H', *self.frequencies))


class PngSignificantBits(PngMetadata):
    type = b'sBIT'
    bits: tuple[int, ...]

    def __init__(self, bits: tuple[int, ...]) -> None:
        self.bits = bits

    @staticmethod
    def from_chunk(chunk: PngChunk) -> PngSignificantBits:
        result = PngSignificantBits(tuple(_data(chunk, b'sBIT')))
        result.validate()
        return result

    def to_chunk(self) -> PngChunk:
        if not 1 <= len(self.bits) <= 4:
            raise PngValidationError('sBIT requires 1-4 sample depths')
        for depth in self.bits:
            check_integer('sBIT sample depth', depth, 1, 16)
        return PngChunk(self.type, bytes(self.bits))


class PngSuggestedPaletteEntry:
    red: int
    green: int
    blue: int
    alpha: int
    frequency: int

    def __init__(self, color: tuple[int, int, int, int], frequency: int = 0) -> None:
        self.red, self.green, self.blue, self.alpha = color
        self.frequency = frequency

    @property
    def color(self) -> tuple[int, int, int, int]:
        return self.red, self.green, self.blue, self.alpha

    @color.setter
    def color(self, value: tuple[int, int, int, int]) -> None:
        self.red, self.green, self.blue, self.alpha = value

    def validate(self, sample_depth: int) -> None:
        check_integer('sPLT sample depth', sample_depth, 8, 16)
        if sample_depth not in (8, 16):
            raise PngValidationError('sPLT sample depth must be 8 or 16')
        for sample in self.color:
            check_integer('sPLT sample', sample, 0, (1 << sample_depth) - 1)
        check_integer('sPLT frequency', self.frequency, 0, 65535)


class PngSuggestedPalette(PngMetadata):
    type = b'sPLT'
    name: str
    sample_depth: int
    entries: list[PngSuggestedPaletteEntry]

    def __init__(self, name: str, sample_depth: int = 8,
                 entries: list[PngSuggestedPaletteEntry] | None = None) -> None:
        self.name = name
        self.sample_depth = sample_depth
        self.entries = entries if entries is not None else []

    @staticmethod
    def from_chunk(chunk: PngChunk) -> PngSuggestedPalette:
        name, tail = _split_keyword(_data(chunk, b'sPLT'))
        if not tail or tail[0] not in (8, 16):
            raise PngValidationError('sPLT sample depth must be 8 or 16')
        depth = tail[0]
        size = 6 if depth == 8 else 10
        if (len(tail) - 1) % size:
            raise PngValidationError('sPLT contains an incomplete palette entry')
        entries = [PngSuggestedPaletteEntry(values[:4], values[4])
                   for values in iter_unpack('>4BH' if depth == 8 else '>5H', tail[1:])]
        result = PngSuggestedPalette(name, depth, entries)
        result.validate()
        return result

    def to_chunk(self) -> PngChunk:
        name = _keyword(self.name)
        check_integer('sPLT sample depth', self.sample_depth, 8, 16)
        if self.sample_depth not in (8, 16):
            raise PngValidationError('sPLT sample depth must be 8 or 16')
        data = bytearray(name + b'\0' + bytes([self.sample_depth]))
        previous_frequency = 65535
        for entry in self.entries:
            entry.validate(self.sample_depth)
            if entry.frequency > previous_frequency:
                raise PngValidationError('sPLT entries must be in nonincreasing frequency order')
            previous_frequency = entry.frequency
            data.extend(pack('>4BH' if self.sample_depth == 8 else '>5H', *entry.color, entry.frequency))
        return PngChunk(self.type, bytes(data))


_METADATA_CLASSES = {
    cls.type: cls for cls in (
        PngGamma, PngChromaticities, PngSrgb, PngCicp, PngMasteringDisplayColorVolume,
        PngContentLightLevel, PngIccProfile, PngText, PngCompressedText, PngInternationalText,
        PngPhysicalDimensions, PngTime, PngExif, PngBackground, PngHistogram,
        PngSignificantBits, PngSuggestedPalette, *EXTENSION_CLASSES,
    )
}
METADATA_TYPES = frozenset(_METADATA_CLASSES)
COLOR_METADATA_TYPES = frozenset((b'gAMA', b'cHRM', b'sRGB', b'cICP', b'mDCV', b'cLLI', b'iCCP'))


def parse_metadata(chunk: PngChunk, *, budget: ReadBudget | None = None) -> PngMetadata | None:
    if budget is None:
        budget = ReadBudget(None)
    cls = _METADATA_CLASSES.get(chunk.type)
    if cls in (PngIccProfile, PngCompressedText, PngInternationalText):
        return cls._from_chunk(chunk, budget)
    if chunk.type not in (b'IHDR', b'PLTE', b'IDAT', b'IEND', b'tRNS', b'acTL', b'fcTL', b'fdAT'):
        budget.metadata(chunk.length)
    return cls.from_chunk(chunk) if cls is not None else None


def validate_metadata_chunks(
        chunks: list[PngChunk], header: PngHeader | None = None, palette_size: int = 0,
        *, for_encoding: bool = False, budget: ReadBudget | None = None, check_profile_structure: bool = False,
) -> None:
    if budget is None:
        budget = ReadBudget(None)
    parsed: dict[bytes, PngMetadata] = {}
    repeated = {b'tEXt', b'zTXt', b'iTXt', b'sPLT', b'gIFg', b'gIFx'}
    palette_names = set()
    for chunk in chunks:
        metadata = parse_metadata(chunk, budget=budget)
        if metadata is not None:
            if check_profile_structure:
                if isinstance(metadata, PngIccProfile):
                    validate_png_embedding(metadata.profile)
                    metadata.validate_profile_tags()
                elif isinstance(metadata, PngExif):
                    metadata.validate_profile_tags()
                elif isinstance(metadata, PngCicp):
                    metadata.validate_code_points()
            if chunk.type in parsed and chunk.type not in repeated:
                raise PngValidationError(f'duplicate {chunk.type!r} metadata')
            if isinstance(metadata, PngSuggestedPalette):
                if metadata.name in palette_names:
                    raise PngValidationError(f'duplicate sPLT palette name: {metadata.name!r}')
                palette_names.add(metadata.name)
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
    if header is None:
        return
    if b'iCCP' in parsed:
        expected = b'GRAY' if header.color_type in (PngColorType.GRAYSCALE, PngColorType.GRAYSCALE_ALPHA) else b'RGB '
        if parsed[b'iCCP'].color_space != expected:
            raise PngValidationError('iCCP color space must match the PNG color type')
    if b'sTER' in parsed:
        parsed[b'sTER'].layout(header.width)
    if b'bKGD' in parsed:
        background = parsed[b'bKGD']
        if header.color_type == PngColorType.INDEXED_COLOR:
            if background.palette_index is None or not 0 <= background.palette_index < palette_size:
                raise PngValidationError('bKGD index is outside PLTE or has the wrong color representation')
        else:
            count = 1 if header.color_type in (PngColorType.GRAYSCALE, PngColorType.GRAYSCALE_ALPHA) else 3
            if background.color is None or len(background.color) != count:
                raise PngValidationError('bKGD has the wrong sample count for the color type')
            if for_encoding and any(value >= 1 << header.bit_depth for value in background.color):
                raise PngValidationError('bKGD sample exceeds the image bit depth')
    if b'hIST' in parsed:
        if not palette_size or len(parsed[b'hIST'].frequencies) != palette_size:
            raise PngValidationError('hIST requires one two-byte entry per PLTE entry')
    if b'sBIT' in parsed:
        bits = parsed[b'sBIT'].bits
        channels = 3 if header.color_type == PngColorType.INDEXED_COLOR else header.channels
        maximum = 8 if header.color_type == PngColorType.INDEXED_COLOR else header.bit_depth
        if len(bits) != channels or any(value > maximum for value in bits):
            raise PngValidationError('sBIT sample depths must fit the color type and bit depth')
