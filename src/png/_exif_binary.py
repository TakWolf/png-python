"""CIPA DC-008-2024 variable field layouts; no measurement interpretation."""

from struct import unpack_from

from png.error import PngValidationError


def _dimensions(data: bytes, endian: str) -> tuple[int, int]:
    if len(data) < 4:
        raise PngValidationError('Exif variable field dimensions are truncated')
    return unpack_from(endian + 'HH', data)


def _table(data: bytes, endian: str) -> None:
    columns, rows = _dimensions(data, endian)
    cursor = 4
    # Reserve the numeric region before scanning names; a malformed name must
    # not consume rational bytes as if they were part of an ASCII label.
    numeric = len(data) - 8 * columns * rows
    if numeric < cursor:
        raise PngValidationError('Exif measurement table exceeds its field')
    for _ in range(columns):
        end = data.find(b'\0', cursor, numeric)
        if end < 0 or any(value > 127 for value in data[cursor:end]):
            raise PngValidationError('Exif measurement column name requires null-terminated ASCII')
        cursor = end + 1
    if cursor != numeric:
        raise PngValidationError('Exif measurement names and rational values disagree with its dimensions')


def _settings(data: bytes, endian: str) -> None:
    columns, rows = _dimensions(data, endian)
    cursor = 4
    # Display rows/columns describe layout. The specification does not give
    # a product-to-setting-count equation, so consume the actual strings.
    while cursor < len(data):
        signature = data[cursor : cursor + 2]
        if signature not in (b'\xff\xfe', b'\xfe\xff'):
            raise PngValidationError('Exif device setting requires a UTF-16 signature')
        start = cursor + 2
        end = start
        while end + 2 <= len(data) and data[end : end + 2] != bytes(2):
            end += 2
        if end + 2 > len(data):
            raise PngValidationError('Exif device setting is not terminated')
        try:
            data[start:end].decode('utf-16-le' if signature == b'\xff\xfe' else 'utf-16-be')
        except UnicodeDecodeError as error:
            raise PngValidationError('Exif device setting is not UTF-16') from error
        cursor = end + 2
    if cursor != len(data):
        raise PngValidationError('Exif device settings do not consume their field')


def _comment(data: bytes, version: bytes, endian: str) -> None:
    if len(data) < 8:
        raise PngValidationError('Exif multicode field requires an eight-byte character identifier')
    signature, text = data[:8], data[8:]
    if signature == bytes(8):
        return  # Undefined text intentionally has application-defined encoding.
    codec = {b'ASCII\0\0\0': 'ascii', b'JIS\0\0\0\0\0': 'iso2022_jp'}.get(signature)
    if signature == b'UNICODE\0':
        if not version:
            return  # Exif 2.x UTF-16 vs 3.0 UTF-8 cannot be inferred from GPS alone.
        if version >= b'0300':
            codec = 'utf-8'
        elif text.startswith((b'\xff\xfe', b'\xfe\xff')):
            codec = 'utf-16'
        else:
            codec = 'utf-16-le' if endian == '<' else 'utf-16-be'
    if codec is None:
        raise PngValidationError('Exif multicode character identifier is not defined')
    try:
        text.decode(codec)
    except UnicodeDecodeError as error:
        raise PngValidationError('Exif multicode string disagrees with its character identifier') from error


def validate_binary(tag: int, data: bytes, endian: str, version: bytes) -> None:
    if tag in (0x8828, 0xA20C):
        _table(data, endian)
    elif tag == 0xA302:
        columns, rows = _dimensions(data, endian)
        if not columns or not rows or len(data) != 4 + columns * rows or any(value > 6 for value in data[4:]):
            raise PngValidationError('Exif CFA pattern dimensions or color values are invalid')
    elif tag == 0xA40B:
        _settings(data, endian)
    elif tag == 0xA462:
        if len(data) < 58:
            raise PngValidationError('Exif composite exposures require seven rationals and a sequence count')
        (sequences,) = unpack_from(endian + 'H', data, 56)
        expected = 58
        if sequences:
            if len(data) < 60:
                raise PngValidationError('Exif composite exposure image count is truncated')
            (images,) = unpack_from(endian + 'H', data, 58)
            if sequences * images < 2:
                raise PngValidationError('Exif composite exposures require at least two source images')
            expected = 60 + 8 * images
        if len(data) != expected:
            raise PngValidationError('Exif composite exposure list disagrees with its image count')
    elif tag in (0x9286, 0x001B, 0x001C):
        _comment(data, version, endian)
