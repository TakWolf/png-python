"""Models for the six fully described public PNG extension chunks."""

from __future__ import annotations

from fractions import Fraction
import re
from struct import pack, unpack

from png._metadata import PngMetadata, _data, _decode, _keyword, _split_keyword, _string
from png._validation import check_integer
from png.chunk import PngChunk
from png.error import PngValidationError
from png.format import PngCalibrationEquation, PngOffsetUnit, PngScaleUnit, PngStereoMode


def _number(value: str, *, positive: bool = False) -> bytes:
    encoded = _string(value, 'ascii')
    if re.fullmatch(rb'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?', encoded) is None:
        raise PngValidationError('invalid extension decimal number')
    # Checking the significand avoids float underflow and arbitrary exponent limits.
    significand = re.split(rb'[eE]', encoded)[0]
    if positive and (encoded.startswith(b'-') or not any(49 <= digit <= 57 for digit in significand)):
        raise PngValidationError('physical scale must be greater than zero')
    return encoded


class PngOffset(PngMetadata):
    type = b'oFFs'
    x: int
    y: int
    unit: PngOffsetUnit

    def __init__(self, position: tuple[int, int] = (0, 0), unit: PngOffsetUnit = PngOffsetUnit.PIXEL) -> None:
        self.x, self.y = position
        self.unit = unit

    @property
    def position(self) -> tuple[int, int]:
        return self.x, self.y

    @position.setter
    def position(self, value: tuple[int, int]) -> None:
        self.x, self.y = value

    @staticmethod
    def from_chunk(chunk: PngChunk) -> PngOffset:
        x, y, unit = unpack('>iiB', _data(chunk, PngOffset.type, 9))
        result = PngOffset((x, y), unit)
        result.validate()
        result.unit = PngOffsetUnit(unit)
        return result

    def to_chunk(self) -> PngChunk:
        check_integer('x offset', self.x, -(1 << 31), (1 << 31) - 1)
        check_integer('y offset', self.y, -(1 << 31), (1 << 31) - 1)
        check_integer('offset unit', self.unit, 0, 1)
        return PngChunk(self.type, pack('>iiB', self.x, self.y, self.unit))


class PngCalibration(PngMetadata):
    type = b'pCAL'
    name: str
    original_zero: int
    original_max: int
    equation_type: PngCalibrationEquation
    unit_name: str
    parameters: list[str]

    def __init__(
            self, name: str, original_zero: int, original_max: int,
            equation_type: PngCalibrationEquation = PngCalibrationEquation.LINEAR,
            unit_name: str = '', parameters: list[str] | None = None,
    ) -> None:
        self.name = name
        self.original_zero = original_zero
        self.original_max = original_max
        self.equation_type = equation_type
        self.unit_name = unit_name
        self.parameters = parameters if parameters is not None else []

    @property
    def num_parameters(self) -> int:
        return len(self.parameters)

    @staticmethod
    def from_chunk(chunk: PngChunk) -> PngCalibration:
        name, tail = _split_keyword(_data(chunk, PngCalibration.type))
        if len(tail) < 10:
            raise PngValidationError('truncated pCAL fields')
        zero, maximum, equation, count = unpack('>iiBB', tail[:10])
        fields = tail[10:].split(b'\0')
        if len(fields) != count + 1:
            raise PngValidationError('pCAL parameter count does not match its payload')
        result = PngCalibration(name, zero, maximum, equation, _decode(fields[0], 'latin-1'),
                                [_decode(value, 'ascii') for value in fields[1:]])
        result.validate()
        result.equation_type = PngCalibrationEquation(equation)
        return result

    def to_chunk(self) -> PngChunk:
        name = _keyword(self.name)
        check_integer('original zero', self.original_zero, -(1 << 31), (1 << 31) - 1)
        check_integer('original max', self.original_max, -(1 << 31), (1 << 31) - 1)
        if self.original_zero == self.original_max:
            raise PngValidationError('pCAL original endpoints must differ')
        check_integer('calibration equation', self.equation_type, 0, 3)
        if self.num_parameters != (2, 3, 3, 4)[self.equation_type]:
            raise PngValidationError('pCAL parameter count does not match its equation')
        unit = _string(self.unit_name, 'latin-1')
        if any(not (32 <= item <= 126 or 161 <= item <= 255) for item in unit):
            raise PngValidationError('pCAL unit name must contain printable Latin-1 characters')
        fields = [unit, *(_number(value) for value in self.parameters)]
        return PngChunk(self.type, name + b'\0' + pack('>iiBB', self.original_zero, self.original_max,
                                                      self.equation_type, self.num_parameters) + b'\0'.join(fields))


class PngPhysicalScale(PngMetadata):
    type = b'sCAL'
    pixel_width: str
    pixel_height: str
    unit: PngScaleUnit

    def __init__(self, pixel_width: str, pixel_height: str, unit: PngScaleUnit = PngScaleUnit.METRE) -> None:
        self.pixel_width = pixel_width
        self.pixel_height = pixel_height
        self.unit = unit

    @staticmethod
    def from_chunk(chunk: PngChunk) -> PngPhysicalScale:
        data = _data(chunk, PngPhysicalScale.type)
        fields = data[1:].split(b'\0')
        if not data or len(fields) != 2:
            raise PngValidationError('sCAL requires a unit and two decimal numbers')
        result = PngPhysicalScale(_decode(fields[0], 'ascii'), _decode(fields[1], 'ascii'), data[0])
        result.validate()
        result.unit = PngScaleUnit(data[0])
        return result

    def to_chunk(self) -> PngChunk:
        check_integer('scale unit', self.unit, 1, 2)
        return PngChunk(self.type, bytes([self.unit]) + _number(self.pixel_width, positive=True) + b'\0' +
                        _number(self.pixel_height, positive=True))


class PngGifGraphicControl(PngMetadata):
    type = b'gIFg'
    disposal_method: int
    user_input_flag: int
    delay_time: int

    def __init__(self, disposal_method: int = 0, user_input_flag: int = 0, delay_time: int = 0) -> None:
        self.disposal_method = disposal_method
        self.user_input_flag = user_input_flag
        self.delay_time = delay_time

    @property
    def delay(self) -> Fraction:
        return Fraction(self.delay_time, 100)

    @staticmethod
    def from_chunk(chunk: PngChunk) -> PngGifGraphicControl:
        result = PngGifGraphicControl(*unpack('>BBH', _data(chunk, PngGifGraphicControl.type, 4)))
        result.validate()
        return result

    def to_chunk(self) -> PngChunk:
        # GIF's three-bit disposal field includes reserved values 4-7; preserve them.
        check_integer('GIF disposal method', self.disposal_method, 0, 7)
        check_integer('GIF user input flag', self.user_input_flag, 0, 1)
        check_integer('GIF delay time', self.delay_time, 0, 65535)
        return PngChunk(self.type, pack('>BBH', self.disposal_method, self.user_input_flag, self.delay_time))


class PngGifApplication(PngMetadata):
    type = b'gIFx'
    identifier: str
    authentication_code: bytes
    data: bytes

    def __init__(self, identifier: str, authentication_code: bytes, data: bytes = b'') -> None:
        self.identifier = identifier
        self.authentication_code = authentication_code
        self.data = data

    @staticmethod
    def from_chunk(chunk: PngChunk) -> PngGifApplication:
        data = _data(chunk, PngGifApplication.type)
        if len(data) < 11:
            raise PngValidationError('truncated gIFx application fields')
        result = PngGifApplication(_decode(data[:8], 'ascii'), data[8:11], data[11:])
        result.validate()
        return result

    def to_chunk(self) -> PngChunk:
        identifier = _string(self.identifier, 'ascii')
        if len(identifier) != 8 or any(not 32 <= item <= 126 for item in identifier):
            raise PngValidationError('GIF application identifier must be eight printable ASCII bytes')
        if not isinstance(self.authentication_code, bytes) or len(self.authentication_code) != 3:
            raise PngValidationError('GIF authentication code must be three bytes')
        if not isinstance(self.data, bytes):
            raise PngValidationError('GIF application data must be bytes')
        return PngChunk(self.type, identifier + self.authentication_code + self.data)


class PngStereo(PngMetadata):
    type = b'sTER'
    mode: PngStereoMode

    def __init__(self, mode: PngStereoMode = PngStereoMode.CROSS_FUSE) -> None:
        self.mode = mode

    def layout(self, width: int) -> tuple[int, int]:
        """Return (subimage width, padding columns) for a full PNG width."""
        check_integer('stereo image width', width, 1, (1 << 31) - 1)
        padding = 15 - ((width - 1) % 16)
        if padding > 7:
            raise PngValidationError('sTER image width cannot contain two aligned equal subimages')
        return (width - padding) // 2, padding

    @staticmethod
    def from_chunk(chunk: PngChunk) -> PngStereo:
        mode, = _data(chunk, PngStereo.type, 1)
        result = PngStereo(mode)
        result.validate()
        result.mode = PngStereoMode(mode)
        return result

    def to_chunk(self) -> PngChunk:
        check_integer('stereo mode', self.mode, 0, 1)
        return PngChunk(self.type, bytes([self.mode]))


EXTENSION_CLASSES = (PngOffset, PngCalibration, PngPhysicalScale, PngGifGraphicControl,
                     PngGifApplication, PngStereo)
