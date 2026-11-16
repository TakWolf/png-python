"""ICC.1 multi-process element storage checks, without evaluating transforms."""

from math import prod
from struct import iter_unpack, unpack_from

from png._icc_lut import _channels
from png.error import PngUnsupportedError, PngValidationError

MPET_TAGS = frozenset(b'D2B' + bytes((intent,)) for intent in b'0123') | frozenset(
    b'B2D' + bytes((intent,)) for intent in b'0123'
)


def validate_mpet(data: bytes) -> None:
    if len(data) < 16 or any(data[4:8]):
        raise PngValidationError('ICC mpet header is truncated or has nonzero reserved bytes')
    inputs, outputs, count = unpack_from('>HHI', data, 8)
    if not count:
        raise PngValidationError('ICC mpet requires at least one element')
    positions = _positions(memoryview(data), 16, count, 12)
    checked: dict[tuple[int, int], tuple[int, int]] = {}
    checked_curves: set[tuple[int, int]] = set()
    previous = inputs
    view = memoryview(data)
    for offset, size in positions:
        extent = (offset, size)
        channels = checked.get(extent)
        if channels is None:
            element = view[offset : offset + size]
            channels = _validate_element(element, offset, checked_curves)
            checked[extent] = channels
        if channels[0] != previous:
            raise PngValidationError('ICC mpet processing element input channels do not match the preceding output')
        previous = channels[1]
    if previous != outputs:
        raise PngValidationError('ICC mpet final element output channels do not match its header')


def _positions(data: memoryview, start: int, count: int, minimum: int) -> list[tuple[int, int]]:
    table_end = start + 8 * count
    if table_end > len(data):
        raise PngValidationError('ICC mpet position table exceeds its containing data')
    positions = []
    for index in range(count):
        offset, size = unpack_from('>II', data, start + 8 * index)
        end = offset + size
        if offset < table_end or offset % 4 or size < minimum or end > len(data):
            raise PngValidationError('ICC mpet position offset or size is invalid')
        if any(data[end : min((end + 3) & ~3, len(data))]):
            raise PngValidationError('ICC mpet alignment padding must be zero')
        positions.append((offset, size))
    if positions and min(offset for offset, _ in positions) != table_end:
        raise PngValidationError('ICC mpet first stored item must immediately follow its position table')
    return positions


def _validate_element(data: memoryview, origin: int, checked_curves: set[tuple[int, int]]) -> tuple[int, int]:
    if any(data[4:8]):
        raise PngValidationError('ICC mpet element reserved bytes must be zero')
    inputs, outputs = unpack_from('>HH', data, 8)
    kind = bytes(data[:4])
    if kind == b'matf':
        if len(data) != 12 + 4 * outputs * (inputs + 1):
            raise PngValidationError('ICC mpet matrix coefficient count does not match its size')
        _floats(data, 12, len(data))
    elif kind == b'clut':
        if inputs > 16 or len(data) < 28:
            raise PngValidationError('ICC mpet CLUT dimensions or header are invalid')
        grid = data[12 : 12 + inputs]
        if any(value < 2 for value in grid) or any(data[12 + inputs : 28]):
            raise PngValidationError('ICC mpet CLUT grid or unused dimensions are invalid')
        if len(data) != 28 + 4 * prod(grid) * outputs:
            raise PngValidationError('ICC mpet CLUT sample count does not match its size')
        _floats(data, 28, len(data))
    elif kind == b'cvst':
        if inputs != outputs:
            raise PngValidationError('ICC mpet curve set input and output channels must match')
        positions = _positions(data, 12, inputs, 12)
        for offset, size in positions:
            extent = (origin + offset, size)
            if extent not in checked_curves:
                _segmented_curve(data[offset : offset + size])
                checked_curves.add(extent)
    elif kind in (b'bACS', b'eACS'):
        if inputs != outputs or len(data) != 16:
            raise PngValidationError('ICC mpet expansion element requires equal channels and a signature')
    # Undefined element signatures remain opaque. ICC requires the colour
    # processor to fall back instead of interpreting an unknown element.
    return inputs, outputs


def _segmented_curve(data: memoryview) -> None:
    if data[:4] != b'curf' or any(data[4:8]) or any(data[10:12]):
        raise PngValidationError('ICC mpet segmented curve header is invalid')
    (count,) = unpack_from('>H', data, 8)
    start = 12 + 4 * (count - 1)
    if not count or start > len(data):
        raise PngValidationError('ICC mpet curve segment count or breakpoint table is invalid')
    _floats(data, 12, start)
    previous = None
    for (breakpoint,) in iter_unpack('>f', data[12:start]):
        if previous is not None and breakpoint < previous:
            raise PngValidationError('ICC mpet curve breakpoints must not decrease')
        previous = breakpoint
    for index in range(count):
        if start + 12 > len(data) or any(data[start + 4 : start + 8]):
            raise PngValidationError('ICC mpet curve segment header is invalid')
        kind = bytes(data[start : start + 4])
        if index in (0, count - 1) and kind != b'parf':
            raise PngValidationError('ICC mpet first and last curve segments must use a formula')
        if kind == b'parf':
            function, reserved = unpack_from('>HH', data, start + 8)
            if function > 2 or reserved:
                raise PngValidationError('ICC mpet curve formula function or reserved bytes are invalid')
            end = start + 12 + (16 if function == 0 else 20)
        elif kind == b'samf':
            (samples,) = unpack_from('>I', data, start + 8)
            if not samples:
                raise PngValidationError('ICC mpet sampled curve requires at least one sample')
            end = start + 12 + 4 * samples
        else:
            raise PngUnsupportedError(f'ICC mpet curve segment encoding {kind!r} cannot be checked')
        if end > len(data):
            raise PngValidationError('ICC mpet curve segment parameters or samples exceed its size')
        _floats(data, start + 12, end)
        start = end
    if start != len(data):
        raise PngValidationError('ICC mpet curve segment sizes do not consume the curve')


def _floats(data: memoryview, start: int, end: int) -> None:
    for (bits,) in iter_unpack('>I', data[start:end]):
        exponent = (bits >> 23) & 255
        if exponent == 255 or (exponent == 0 and bits & 0x7FFFFF):
            raise PngValidationError('ICC float32 values must be normal finite values or signed zero')


def validate_mpet_context(profile: bytes, signature: bytes, data: memoryview) -> None:
    if signature not in MPET_TAGS:
        return
    device, pcs = profile[16:20], profile[20:24]
    expected = (_channels(device), _channels(pcs)) if signature[:3] == b'D2B' else (_channels(pcs), _channels(device))
    if unpack_from('>HH', data, 8) != expected:
        raise PngValidationError(f'ICC {signature!r} mpet channel counts disagree with the profile')
