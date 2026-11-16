"""ICC dictionary and response-curve collections, without executing transforms."""

from struct import unpack_from

from png._icc_text import multilingual_end
from png.error import PngValidationError


def validate_dictionary(data: bytes) -> None:
    if len(data) < 16:
        raise PngValidationError('ICC dictionary header is truncated')
    count, stride = unpack_from('>II', data, 8)
    table_end = 16 + count * stride
    if stride not in (16, 24, 32) or table_end > len(data):
        raise PngValidationError('ICC dictionary record table is invalid')
    view = memoryview(data)
    names = set()
    checked = {}
    for index in range(count):
        for field in range(stride // 8):
            offset, size = unpack_from('>II', data, 16 + stride * index + 8 * field)
            if offset == 0:
                if field == 0:
                    raise PngValidationError('ICC dictionary name is required')
                continue  # Optional absent fields have an undefined size, not a mandatory zero size.
            end = offset + size
            if offset < table_end or offset % 4 or end > len(data):
                raise PngValidationError('ICC dictionary item offset or size is invalid')
            if any(view[end : min((end + 3) & ~3, len(data))]):
                raise PngValidationError('ICC dictionary item padding must be zero')
            extent = (offset, size, field < 2)
            if extent not in checked:
                if field < 2:
                    if size % 2:
                        raise PngValidationError('ICC dictionary string has an odd size')
                    try:
                        text = view[offset:end].tobytes().decode('utf-16-be')
                    except UnicodeDecodeError as error:
                        raise PngValidationError('ICC dictionary string is not UTF-16BE') from error
                    if text.endswith('\0'):
                        raise PngValidationError('ICC dictionary strings must not be null terminated')
                    checked[extent] = text
                else:
                    if size:
                        item = view[offset:end]
                        if item[:4] != b'mluc':
                            raise PngValidationError('ICC dictionary display text requires mluc')
                        multilingual_end(item)
                    checked[extent] = None  # A defined zero-size display item suppresses display.
            if field == 0:
                name = checked[extent]
                if not name or name in names:
                    raise PngValidationError('ICC dictionary names must be nonempty and unique')
                names.add(name)


def validate_response_curves(data: bytes) -> None:
    if len(data) < 12:
        raise PngValidationError('ICC response curve set header is truncated')
    channels, count = unpack_from('>HH', data, 8)
    table_end = 12 + count * 4
    if table_end > len(data):
        raise PngValidationError('ICC response curve offset table exceeds its tag')
    checked = set()
    for index in range(count):
        (offset,) = unpack_from('>I', data, 12 + index * 4)
        if offset in checked:
            continue
        arrays = offset + 4 + channels * 16
        if offset < table_end or arrays > len(data):
            raise PngValidationError('ICC response curve header exceeds its tag')
        counts = [unpack_from('>I', data, offset + 4 + channel * 4)[0] for channel in range(channels)]
        if arrays + 8 * sum(counts) > len(data):
            raise PngValidationError('ICC response measurements exceed their tag')
        cursor = arrays
        for number in counts:
            previous = -1
            for _ in range(number):
                code, reserved = unpack_from('>HH', data, cursor)
                if reserved or code <= previous:
                    raise PngValidationError('ICC response codes must increase and reserved bytes must be zero')
                previous = code
                cursor += 8
        checked.add(offset)
